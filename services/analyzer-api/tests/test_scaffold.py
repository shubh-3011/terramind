"""Tests for the deterministic (model-free) Terraform scaffolder."""

import ipaddress
import re

import hcl2
import pytest

from app.scaffold import scaffold_terraform


def _scaffold(inventory: str, *, description: str = "", connectivity: str = "", constraints: str = ""):
    result = scaffold_terraform(
        description=description,
        resource_inventory=inventory,
        connectivity=connectivity,
        constraints=constraints,
    )
    assert result is not None, f"expected a scaffold for {inventory!r}"
    hcl, notes = result
    return hcl, notes, hcl2.loads(hcl)


def _resource_types(document: dict) -> list[str]:
    types: list[str] = []
    for block in document.get("resource", []):
        types.extend(block.keys())
    return types


def _resources(document: dict, resource_type: str) -> list[dict]:
    matches: list[dict] = []
    for block in document.get("resource", []):
        if resource_type in block:
            matches.append(block[resource_type])
    return matches


def _declared_variables(document: dict) -> set[str]:
    declared: set[str] = set()
    for block in document.get("variable", []):
        declared.update(block.keys())
    return declared


def test_unsupported_inventory_returns_none():
    assert scaffold_terraform(
        description="",
        resource_inventory="a big pile of unrelated nouns",
        connectivity="",
        constraints="",
    ) is None
    assert scaffold_terraform(
        description="",
        resource_inventory="",
        connectivity="",
        constraints="",
    ) is None


def test_two_ec2_and_one_s3_is_valid_hcl_with_secure_defaults():
    hcl, _notes, document = _scaffold("2 EC2 + 1 S3")

    # (a) parses (implicitly, by hcl2.loads in the helper)
    # (b) two EC2 instances and the S3 encryption configuration
    assert hcl.count('resource "aws_instance"') == 2
    assert "aws_s3_bucket_server_side_encryption_configuration" in _resource_types(document)

    # (c) secure defaults on every instance
    assert hcl.count('http_tokens   = "required"') == 2
    assert hcl.count("encrypted   = true") == 2
    assert "aws_s3_bucket_versioning" in _resource_types(document)
    assert "aws_s3_bucket_public_access_block" in _resource_types(document)

    # (d) every var.* reference is declared
    referenced = set(re.findall(r"\bvar\.([A-Za-z_][A-Za-z0-9_]*)", hcl))
    declared = _declared_variables(document)
    assert referenced <= declared, f"undeclared variables: {sorted(referenced - declared)}"
    assert referenced  # the scaffold should always reference at least aws_region


def test_five_vpcs_and_transit_gateway_attaches_every_vpc_with_unique_cidrs():
    hcl, _notes, document = _scaffold("5 VPC + 1 Transit Gateway")

    assert len(_resources(document, "aws_vpc")) == 5
    attachments = _resources(document, "aws_ec2_transit_gateway_vpc_attachment")
    assert len(attachments) == 5
    # exactly one attachment per VPC label vpc_1 .. vpc_5
    attached_vpcs = {
        attributes["vpc_id"]
        for instances in attachments
        for attributes in instances.values()
    }
    assert attached_vpcs == {
        f"${{aws_vpc.vpc_{index}.id}}" for index in range(1, 6)
    } or attached_vpcs == {f"aws_vpc.vpc_{index}.id" for index in range(1, 6)}
    assert len(_resources(document, "aws_ec2_transit_gateway_route_table_association")) == 5
    assert len(_resources(document, "aws_ec2_transit_gateway_route_table_propagation")) == 5

    vpc_cidrs = [
        attributes["cidr_block"]
        for attributes in _resources(document, "aws_vpc")
        for attributes in attributes.values()
    ]
    networks = [ipaddress.ip_network(str(cidr)) for cidr in vpc_cidrs]
    assert len(networks) == 5
    for index, network in enumerate(networks):
        for other in networks[index + 1:]:
            assert not network.overlaps(other), f"{network} overlaps {other}"
    assert hcl.count('resource "aws_ec2_transit_gateway_vpc_attachment"') == 5


def test_no_public_ssh_ingress_in_any_generated_security_group():
    for inventory in ("2 EC2 + 1 S3", "3 public subnet and 3 private subnet", "2 EC2 and 1 sg"):
        hcl, _notes, document = _scaffold(inventory)
        for instances in _resources(document, "aws_security_group"):
            for label, attributes in instances.items():
                for ingress in attributes.get("ingress", []):
                    from_port = int(str(ingress.get("from_port", "")).strip('"'))
                    to_port = int(str(ingress.get("to_port", "")).strip('"'))
                    if from_port <= 22 <= to_port:
                        cidrs = ingress.get("cidr_blocks", [])
                        assert "0.0.0.0/0" not in cidrs, f"{label} exposes SSH publicly"
                        assert "::/0" not in ingress.get("ipv6_cidr_blocks", [])
        # A literal check as well, so a new code path cannot slip through.
        assert not re.search(r'from_port\s*=\s*22[\s\S]{0,200}?0\.0\.0\.0/0', hcl)


@pytest.mark.parametrize(
    "inventory",
    [
        "5 VPC",
        "VPC 5",
        "5 VPCs",
        "vpc: 5",
        "5x vpc",
        "transit gateway: 1",
        "1x igw",
        "nat gateway 2",
        "4 buckets",
        "2 ALB",
        "10 SG",
    ],
)
def test_supported_alias_forms_produce_parsable_hcl(inventory):
    hcl, _notes, document = _scaffold(inventory)
    assert _resource_types(document)
    referenced = set(re.findall(r"\bvar\.([A-Za-z_][A-Za-z0-9_]*)", hcl))
    assert referenced <= _declared_variables(document)


def test_region_is_detected_from_constraints_and_description():
    _hcl, _notes, document = _scaffold(
        "1 VPC", constraints="Deploy everything in ap-south-1 only"
    )
    assert document["variable"][0]["aws_region"]["default"] == "ap-south-1"

    _hcl2, _notes2, document2 = _scaffold(
        "1 VPC", description="Create the network in eu-west-2 for EU data residency"
    )
    assert document2["variable"][0]["aws_region"]["default"] == "eu-west-2"

    _hcl3, _notes3, document3 = _scaffold("1 VPC")
    assert document3["variable"][0]["aws_region"]["default"] == "us-east-1"


def test_ec2_instances_are_private_by_default():
    hcl, _notes, document = _scaffold("2 EC2")
    for instances in _resources(document, "aws_instance"):
        for attributes in instances.values():
            assert attributes["associate_public_ip_address"] is False
            assert "private_subnet" in str(attributes["subnet_id"])
    assert "aws_subnet" in _resource_types(document)


def test_iam_instance_profile_uses_ssm_managed_policy_when_requested():
    hcl, _notes, _document = _scaffold("2 EC2 with an instance profile and SSM access")
    assert "aws_iam_role" in hcl
    assert "aws_iam_instance_profile" in hcl
    assert "AmazonSSMManagedInstanceCore" in hcl


def test_s3_bucket_hardening_is_emitted():
    hcl, _notes, document = _scaffold("1 S3 bucket")
    assert "aws_s3_bucket_server_side_encryption_configuration" in _resource_types(document)
    assert 'sse_algorithm = "aws:kms"' in hcl
    assert "aws_s3_bucket_versioning" in _resource_types(document)
    assert _resources(document, "aws_s3_bucket_public_access_block")
    for instances in _resources(document, "aws_s3_bucket_public_access_block"):
        for attributes in instances.values():
            for flag in (
                "block_public_acls",
                "block_public_policy",
                "ignore_public_acls",
                "restrict_public_buckets",
            ):
                assert attributes[flag] is True


def test_alb_uses_https_listener_on_443():
    hcl, _notes, document = _scaffold("1 ALB with 2 public subnet")
    assert "aws_lb" in _resource_types(document)
    assert "aws_lb_target_group" in _resource_types(document)
    listeners = _resources(document, "aws_lb_listener")
    assert listeners
    for instances in listeners:
        for attributes in instances.values():
            assert int(attributes["port"]) == 443
            assert attributes["protocol"] == "HTTPS"


def test_generation_never_emits_credentials_or_shell_commands():
    hcl, _notes, _document = _scaffold("5 VPC, 2 EC2, 1 S3 bucket, 1 Transit Gateway")
    lowered = hcl.lower()
    assert "terraform init" not in lowered
    assert "terraform plan" not in lowered
    assert "terraform apply" not in lowered
    assert "aws_access_key" not in lowered
    assert "aws_secret" not in lowered
    assert "password" not in lowered


def test_notes_describe_assumptions():
    _hcl, notes, _document = _scaffold("2 EC2 + 1 S3")
    assert notes
    assert any("VPC" in note for note in notes)
