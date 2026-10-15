"""Tests for the deterministic, offline cost estimator (app.pricing)."""

from __future__ import annotations

import hcl2
import pytest

from app.pricing import (
    ASSUMED_HOURS_PER_MONTH,
    DEFAULT_REGION,
    estimate_cost,
)


def _estimate(source: str, **kwargs):
    return estimate_cost([hcl2.loads(source)], **kwargs)


def test_empty_documents_cost_nothing():
    result = estimate_cost([])
    assert result["total_monthly_usd"] == 0.0
    assert result["line_items"] == []
    assert result["region"] == DEFAULT_REGION


def test_prices_a_known_instance_type():
    result = _estimate('resource "aws_instance" "web" { instance_type = "t3.micro" }')
    items = [i for i in result["line_items"] if i["resource_type"] == "aws_instance"]
    assert len(items) == 1
    assert items[0]["unit_price_usd"] == pytest.approx(0.0104)
    assert items[0]["quantity"] == ASSUMED_HOURS_PER_MONTH
    assert result["total_monthly_usd"] > 0


def test_count_multiplies_the_hourly_charge():
    one = _estimate('resource "aws_instance" "a" { instance_type = "t3.micro" }')
    three = _estimate('resource "aws_instance" "a" { instance_type = "t3.micro"  count = 3 }')
    assert three["total_monthly_usd"] == pytest.approx(one["total_monthly_usd"] * 3, abs=0.02)


def test_unknown_instance_type_is_reported_not_dropped():
    result = _estimate('resource "aws_instance" "x" { instance_type = "z1.mega" }')
    assert result["total_monthly_usd"] == 0.0
    assert any("z1.mega" in u["reason"] for u in result["unpriced"])


def test_variable_reference_is_unpriced_not_guessed():
    result = _estimate('resource "aws_instance" "x" { instance_type = var.size }')
    assert result["total_monthly_usd"] == 0.0
    assert any("literal" in u["reason"] for u in result["unpriced"])


def test_provider_region_is_detected_and_scales_prices():
    source = """
    provider "aws" { region = "us-east-2" }
    resource "aws_instance" "web" { instance_type = "t3.micro" }
    """
    result = _estimate(source)
    assert result["region"] == "us-east-2"
    # us-east-2 multiplier is 1.0, so this matches the base price.
    assert result["total_monthly_usd"] == pytest.approx(0.0104 * ASSUMED_HOURS_PER_MONTH, abs=0.01)


def test_eu_region_costs_more_than_us_east():
    us = _estimate("""
        provider "aws" { region = "us-east-1" }
        resource "aws_instance" "web" { instance_type = "t3.micro" }
    """)
    eu = _estimate("""
        provider "aws" { region = "eu-central-1" }
        resource "aws_instance" "web" { instance_type = "t3.micro" }
    """)
    assert eu["total_monthly_usd"] > us["total_monthly_usd"]


def test_unknown_region_falls_back_with_a_note():
    result = _estimate("""
        provider "aws" { region = "mars-north-1" }
        resource "aws_instance" "web" { instance_type = "t3.micro" }
    """)
    assert result["region"] == "mars-north-1"
    assert any("not in the price table" in n for n in result["notes"])


def test_free_building_blocks_are_zero_cost_items():
    result = _estimate("""
        resource "aws_vpc" "v" { cidr_block = "10.0.0.0/16" }
        resource "aws_subnet" "s" { cidr_block = "10.0.1.0/24" }
        resource "aws_security_group" "g" { name = "g" }
    """)
    assert result["total_monthly_usd"] == 0.0
    assert {i["resource_type"] for i in result["line_items"]} == {
        "aws_vpc", "aws_subnet", "aws_security_group",
    }
    assert result["unpriced"] == []


def test_rds_instance_and_storage_are_priced():
    result = _estimate("""
        resource "aws_db_instance" "db" {
          instance_class    = "db.t3.micro"
          allocated_storage = 20
        }
    """)
    types = {i["resource_type"] for i in result["line_items"]}
    assert "aws_db_instance" in types
    assert "aws_db_instance.storage" in types
    assert result["total_monthly_usd"] > 0


def test_multi_cloud_resources_are_priced():
    result = _estimate("""
        resource "azurerm_linux_virtual_machine" "vm" { size = "Standard_B2s" }
        resource "google_compute_instance" "gce" { machine_type = "e2-medium" }
    """)
    types = {i["resource_type"] for i in result["line_items"]}
    assert types == {"azurerm_linux_virtual_machine", "google_compute_instance"}
    assert result["total_monthly_usd"] > 0


def test_line_items_are_sorted_by_descending_cost():
    result = _estimate("""
        resource "aws_instance" "web" { instance_type = "m5.4xlarge" }
        resource "aws_kms_key" "k" {}
    """)
    costs = [i["monthly_usd"] for i in result["line_items"]]
    assert costs == sorted(costs, reverse=True)


def test_response_is_json_serialisable():
    import json

    result = _estimate('resource "aws_instance" "web" { instance_type = "t3.micro" }')
    json.dumps(result)  # must not raise


def test_every_priced_item_has_provenance_fields():
    result = _estimate("""
        resource "aws_instance" "web" { instance_type = "t3.small" }
        resource "aws_lb" "lb" {}
        resource "aws_s3_bucket" "b" {}
    """)
    assert result["line_items"]
    for item in result["line_items"]:
        assert item["billing_basis"]
        assert item["unit"]
        assert isinstance(item["unit_price_usd"], float)
        assert item["confidence"] in {"high", "medium", "low"}
