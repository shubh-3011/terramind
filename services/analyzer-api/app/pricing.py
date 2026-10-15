"""Deterministic, offline monthly cost estimation for Terraform resources.

The analyzer is static: it never calls a cloud API and never initialises a
provider.  This module therefore produces a **list-price estimate, not a
quote**.  It combines published US on-demand prices for the common resource
types TerraMind recognises with documented default assumptions, and it labels
every number with its billing basis and a confidence so a figure is never
presented as exact.

Design rules:

* Every priced line item records ``billing_basis``, ``unit``,
  ``unit_price_usd`` and how the quantity was derived (``assumption``).
* Resource types this module cannot price are reported under ``unpriced`` with
  a reason -- never silently dropped, so the total is never quietly wrong.
* A region only scales list prices by a coarse factor relative to ``us-east-1``.

The numbers are deliberately conservative round numbers sourced from public
on-demand pricing pages; they are good enough to rank and sanity-check a
workspace, which is the point of a static analyzer.
"""

from __future__ import annotations

from typing import Any

from app.ratings import iter_resources, service_for_resource

ASSUMED_HOURS_PER_MONTH = 730
DEFAULT_REGION = "us-east-1"
ESTIMATE_DISCLAIMER = (
    "Static list-price estimate (on-demand, Linux, no discounts, "
    f"{ASSUMED_HOURS_PER_MONTH} h/month). Not a quote and not a billed amount."
)

# Coarse regional multipliers relative to us-east-1 list prices.  These exist to
# give a directional signal, not an exact figure; unknown regions fall back to
# 1.0 and the estimate notes that it assumed the default region.
REGION_MULTIPLIERS: dict[str, float] = {
    "us-east-1": 1.00,
    "us-east-2": 1.00,
    "us-west-1": 1.06,
    "us-west-2": 1.00,
    "ca-central-1": 1.03,
    "sa-east-1": 1.30,
    "eu-west-1": 1.05,
    "eu-west-2": 1.07,
    "eu-west-3": 1.07,
    "eu-central-1": 1.08,
    "eu-north-1": 1.02,
    "ap-south-1": 1.04,
    "ap-southeast-1": 1.09,
    "ap-southeast-2": 1.11,
    "ap-northeast-1": 1.12,
    "ap-northeast-2": 1.11,
}

# us-east-1 on-demand, Linux, per hour.  Kept intentionally small but covering
# the types people actually put in tutorials and coursework.
EC2_HOURLY: dict[str, float] = {
    "t2.nano": 0.0058,
    "t2.micro": 0.0116,
    "t2.small": 0.0230,
    "t2.medium": 0.0464,
    "t3.nano": 0.0052,
    "t3.micro": 0.0104,
    "t3.small": 0.0208,
    "t3.medium": 0.0416,
    "t3.large": 0.0832,
    "t3.xlarge": 0.1664,
    "t3.2xlarge": 0.3328,
    "t4g.nano": 0.0042,
    "t4g.micro": 0.0084,
    "t4g.small": 0.0168,
    "t4g.medium": 0.0336,
    "m5.large": 0.0960,
    "m5.xlarge": 0.1920,
    "m5.2xlarge": 0.3840,
    "m5.4xlarge": 0.7680,
    "m6i.large": 0.0960,
    "m6i.xlarge": 0.1920,
    "m5a.large": 0.0860,
    "c5.large": 0.0850,
    "c5.xlarge": 0.1700,
    "c5.2xlarge": 0.3400,
    "c6i.large": 0.0850,
    "r5.large": 0.1260,
    "r5.xlarge": 0.2520,
    "r6i.large": 0.1260,
    "g4dn.xlarge": 0.5260,
    "g4dn.2xlarge": 0.7520,
    "p3.2xlarge": 3.0600,
}

# RDS instance classes, per hour (single-AZ, MySQL/PostgreSQL).
RDS_HOURLY: dict[str, float] = {
    "db.t3.micro": 0.0170,
    "db.t3.small": 0.0340,
    "db.t3.medium": 0.0680,
    "db.t3.large": 0.1360,
    "db.t4g.micro": 0.0160,
    "db.t4g.small": 0.0320,
    "db.t4g.medium": 0.0640,
    "db.m5.large": 0.1710,
    "db.m5.xlarge": 0.3420,
    "db.m5.2xlarge": 0.6840,
    "db.r5.large": 0.2490,
    "db.r5.xlarge": 0.4980,
}

# Azure Virtual Machines, per hour (Linux, pay-as-you-go, East US).
AZURE_VM_HOURLY: dict[str, float] = {
    "standard_b1s": 0.0104,
    "standard_b1ms": 0.0207,
    "standard_b2s": 0.0416,
    "standard_b2ms": 0.0832,
    "standard_d2s_v3": 0.0960,
    "standard_d4s_v3": 0.1920,
    "standard_d2s_v5": 0.1010,
    "standard_d4s_v5": 0.2020,
    "standard_e2s_v3": 0.1260,
    "standard_f2s_v2": 0.0850,
}

# Google Compute Engine, per hour (us-central1, on-demand).
GCP_MACHINE_HOURLY: dict[str, float] = {
    "e2-micro": 0.0084,
    "e2-small": 0.0168,
    "e2-medium": 0.0336,
    "e2-standard-2": 0.0672,
    "e2-standard-4": 0.1344,
    "n1-standard-1": 0.0475,
    "n1-standard-2": 0.0950,
    "n2-standard-2": 0.0971,
    "n2-standard-4": 0.1942,
    "n2d-standard-2": 0.0849,
    "c2-standard-4": 0.2088,
}

# Resource types that exist but cost nothing on their own.  Listing them as
# explicit zero items is more honest than leaving them unpriced.
ZERO_COST_PREFIXES = (
    "aws_vpc",
    "aws_subnet",
    "aws_internet_gateway",
    "aws_route_table",
    "aws_route",
    "aws_network_acl",
    "aws_security_group",
    "aws_iam_",
    "aws_cloudwatch_log_group_",
    "azurerm_resource_group",
    "azurerm_virtual_network",
    "azurerm_subnet",
    "azurerm_network_security_group",
    "azurerm_network_security_rule",
    "google_compute_network",
    "google_compute_subnetwork",
    "google_compute_firewall",
    "google_project_service",
    "kubernetes_",
    "random_",
    "null_",
    "local_",
    "tls_",
    "aws_s3_bucket_",
)


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return int(text)
    return None


def _as_str(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        if text and "${" not in text:
            return text
    return None


def _blocks(attributes: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = attributes.get(key)
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _count(attributes: dict[str, Any]) -> tuple[int, str | None]:
    """Return a resource multiplier and, if derived, the assumption text."""
    count = _as_int(attributes.get("count"))
    if count is not None and count > 0:
        return count, f"count = {count}"
    return 1, None


def _detect_region(documents: list[dict[str, Any]]) -> str | None:
    for document in documents:
        if not isinstance(document, dict):
            continue
        providers = document.get("provider", [])
        if isinstance(providers, dict):
            providers = [providers]
        for provider in providers if isinstance(providers, list) else []:
            if not isinstance(provider, dict):
                continue
            for _name, config in provider.items():
                if not isinstance(config, dict):
                    continue
                for key in ("region", "location"):
                    literal = _as_str(config.get(key))
                    if literal:
                        return literal
    return None


class _Estimator:
    """Accumulates line items while pricing individual resources."""

    def __init__(self, region: str | None) -> None:
        self.region = region or DEFAULT_REGION
        self.region_known = region is None or region in REGION_MULTIPLIERS
        self.multiplier = REGION_MULTIPLIERS.get(self.region, 1.0)
        self.line_items: list[dict[str, Any]] = []
        self.unpriced: list[dict[str, Any]] = []

    def add(
        self,
        *,
        resource_type: str,
        label: str,
        billing_basis: str,
        quantity: float,
        unit: str,
        unit_price_usd: float,
        confidence: str,
        assumption: str | None = None,
    ) -> None:
        monthly = round(quantity * unit_price_usd * self.multiplier, 2)
        self.line_items.append(
            {
                "resource_type": resource_type,
                "label": label,
                "service": service_for_resource(resource_type),
                "billing_basis": billing_basis,
                "quantity": round(quantity, 4),
                "unit": unit,
                "unit_price_usd": unit_price_usd,
                "monthly_usd": monthly,
                "confidence": confidence,
                "assumption": assumption,
            }
        )

    def skip(self, resource_type: str, label: str, reason: str) -> None:
        self.unpriced.append(
            {"resource_type": resource_type, "label": label, "reason": reason}
        )


def _price_aws_instance(est: _Estimator, rtype: str, label: str, attrs: dict[str, Any]) -> bool:
    instance_type = _as_str(attrs.get("instance_type"))
    count, count_note = _count(attrs)
    if instance_type is None:
        est.skip(rtype, label, "instance_type is not a literal value")
        return True
    hourly = EC2_HOURLY.get(instance_type)
    if hourly is None:
        est.skip(rtype, label, f"no list price for instance_type {instance_type!r}")
        return True
    est.add(
        resource_type=rtype,
        label=label,
        billing_basis="compute hours",
        quantity=ASSUMED_HOURS_PER_MONTH * count,
        unit="hour",
        unit_price_usd=hourly,
        confidence="medium",
        assumption=count_note,
    )
    # Root volume (default 8 GB gp3 when unspecified).
    root = _blocks(attrs, "root_block_device")
    if root:
        size = _as_int(root[0].get("volume_size")) or 8
        est.add(
            resource_type=rtype + ".root_block_device",
            label=label,
            billing_basis="root EBS storage",
            quantity=size * count,
            unit="GB-month",
            unit_price_usd=0.08,
            confidence="low",
            assumption=f"root volume {size} GB",
        )
    for block in _blocks(attrs, "ebs_block_device"):
        size = _as_int(block.get("volume_size")) or 8
        est.add(
            resource_type=rtype + ".ebs_block_device",
            label=label,
            billing_basis="EBS storage",
            quantity=size * count,
            unit="GB-month",
            unit_price_usd=0.08,
            confidence="low",
            assumption=f"EBS volume {size} GB",
        )
    return True


def _price_aws_db(est: _Estimator, rtype: str, label: str, attrs: dict[str, Any]) -> bool:
    instance_class = _as_str(attrs.get("instance_class"))
    count, count_note = _count(attrs)
    priced = False
    if instance_class is not None:
        hourly = RDS_HOURLY.get(instance_class)
        if hourly is not None:
            est.add(
                resource_type=rtype,
                label=label,
                billing_basis="database hours",
                quantity=ASSUMED_HOURS_PER_MONTH * count,
                unit="hour",
                unit_price_usd=hourly,
                confidence="medium",
                assumption=count_note,
            )
            priced = True
        else:
            est.skip(rtype, label, f"no list price for instance_class {instance_class!r}")
            priced = True
    else:
        est.skip(rtype, label, "instance_class is not a literal value")
        priced = True
    storage = _as_int(attrs.get("allocated_storage"))
    if storage:
        est.add(
            resource_type=rtype + ".storage",
            label=label,
            billing_basis="database storage",
            quantity=storage * count,
            unit="GB-month",
            unit_price_usd=0.115,
            confidence="low",
        )
    return priced


def _price_azure_vm(est: _Estimator, rtype: str, label: str, attrs: dict[str, Any]) -> bool:
    size = _as_str(attrs.get("size"))
    count, count_note = _count(attrs)
    key = size.lower() if size else ""
    hourly = AZURE_VM_HOURLY.get(key)
    if hourly is None:
        est.skip(
            rtype,
            label,
            "size is not a literal value" if size is None else f"no list price for size {size!r}",
        )
        return True
    est.add(
        resource_type=rtype,
        label=label,
        billing_basis="compute hours",
        quantity=ASSUMED_HOURS_PER_MONTH * count,
        unit="hour",
        unit_price_usd=hourly,
        confidence="medium",
        assumption=count_note,
    )
    return True


def _price_gcp_instance(est: _Estimator, rtype: str, label: str, attrs: dict[str, Any]) -> bool:
    machine_type = _as_str(attrs.get("machine_type"))
    count, count_note = _count(attrs)
    if machine_type is None:
        est.skip(rtype, label, "machine_type is not a literal value")
        return True
    # machine_type may be "e2-medium" or "zones/us-central1-a/e2-medium".
    key = machine_type.rsplit("/", 1)[-1].lower()
    hourly = GCP_MACHINE_HOURLY.get(key)
    if hourly is None:
        est.skip(rtype, label, f"no list price for machine_type {machine_type!r}")
        return True
    est.add(
        resource_type=rtype,
        label=label,
        billing_basis="compute hours",
        quantity=ASSUMED_HOURS_PER_MONTH * count,
        unit="hour",
        unit_price_usd=hourly,
        confidence="medium",
        assumption=count_note,
    )
    return True


def _price_resource(est: _Estimator, rtype: str, label: str, attrs: dict[str, Any]) -> None:
    """Price one resource, recording either a line item or an unpriced reason."""
    # --- AWS ---------------------------------------------------------------
    if rtype in {"aws_instance", "aws_spot_instance_request"}:
        _price_aws_instance(est, rtype, label, attrs)
        return
    if rtype == "aws_ebs_volume":
        size = _as_int(attrs.get("size")) or 8
        est.add(resource_type=rtype, label=label, billing_basis="EBS storage",
                quantity=size, unit="GB-month", unit_price_usd=0.08,
                confidence="low", assumption=None if _as_int(attrs.get("size")) else "assumed 8 GB")
        return
    if rtype == "aws_efs_file_system":
        est.skip(rtype, label, "usage-based (per GB stored/accessed); size unknown statically")
        return
    if rtype in {"aws_s3_bucket", "aws_s3_bucket_lifecycle_configuration"}:
        if rtype == "aws_s3_bucket":
            est.add(resource_type=rtype, label=label, billing_basis="object storage",
                    quantity=0.0, unit="GB-month", unit_price_usd=0.023,
                    confidence="low", assumption="no object size in configuration")
        return
    if rtype in {"aws_lb", "aws_alb", "aws_elb"}:
        est.add(resource_type=rtype, label=label, billing_basis="load balancer hours",
                quantity=ASSUMED_HOURS_PER_MONTH, unit="hour", unit_price_usd=0.0225,
                confidence="medium")
        return
    if rtype == "aws_nat_gateway":
        est.add(resource_type=rtype, label=label, billing_basis="NAT gateway hours",
                quantity=ASSUMED_HOURS_PER_MONTH, unit="hour", unit_price_usd=0.045,
                confidence="medium", assumption="excludes data processing")
        return
    if rtype == "aws_eip":
        est.add(resource_type=rtype, label=label, billing_basis="elastic IP (attached)",
                quantity=ASSUMED_HOURS_PER_MONTH, unit="hour", unit_price_usd=0.005,
                confidence="low", assumption="priced as in-use; free while attached to a running instance")
        return
    if rtype == "aws_eks_cluster":
        est.add(resource_type=rtype, label=label, billing_basis="EKS control plane",
                quantity=ASSUMED_HOURS_PER_MONTH, unit="hour", unit_price_usd=0.10,
                confidence="high")
        return
    if rtype == "aws_kms_key":
        est.add(resource_type=rtype, label=label, billing_basis="key custody",
                quantity=1, unit="month", unit_price_usd=1.0, confidence="high")
        return
    if rtype in {"aws_secretsmanager_secret", "aws_secretsmanager_secret_version"}:
        if rtype == "aws_secretsmanager_secret":
            est.add(resource_type=rtype, label=label, billing_basis="secret custody",
                    quantity=1, unit="month", unit_price_usd=0.40, confidence="high")
        return
    if rtype in {"aws_db_instance", "aws_rds_cluster", "aws_rds_cluster_instance"}:
        _price_aws_db(est, rtype, label, attrs)
        return
    if rtype == "aws_elasticache_cluster":
        node_type = _as_str(attrs.get("node_type"))
        hourly = {"cache.t3.micro": 0.017, "cache.t3.small": 0.034,
                  "cache.t3.medium": 0.068, "cache.m5.large": 0.156,
                  "cache.r5.large": 0.177}.get(node_type or "")
        if hourly is None:
            est.skip(rtype, label, "node_type is not a literal value or has no list price")
        else:
            nodes = _as_int(attrs.get("num_cache_nodes")) or 1
            est.add(resource_type=rtype, label=label, billing_basis="cache node hours",
                    quantity=ASSUMED_HOURS_PER_MONTH * nodes, unit="hour",
                    unit_price_usd=hourly, confidence="medium")
        return
    if rtype == "aws_ecr_repository":
        est.skip(rtype, label, "storage/charged per GB stored; size unknown statically")
        return
    if rtype == "aws_cloudwatch_log_group":
        est.add(resource_type=rtype, label=label, billing_basis="log ingestion",
                quantity=0.0, unit="GB", unit_price_usd=0.50, confidence="low",
                assumption="usage-based; no volume in configuration")
        return
    if rtype == "aws_sns_topic":
        est.add(resource_type=rtype, label=label, billing_basis="notifications",
                quantity=0.0, unit="million", unit_price_usd=0.50, confidence="low",
                assumption="usage-based; volume unknown")
        return
    if rtype == "aws_lambda_function":
        est.skip(rtype, label, "usage-based (requests + GB-seconds); unknown statically")
        return
    if rtype == "aws_autoscaling_group":
        est.skip(rtype, label, "scales with demand; instance type is in the launch template")
        return
    if rtype.startswith("aws_ecs_"):
        est.skip(rtype, label, "Fargate/EC2 capacity is priced per task, not per resource")
        return

    # --- Azure -------------------------------------------------------------
    if rtype in {"azurerm_linux_virtual_machine", "azurerm_windows_virtual_machine",
                 "azurerm_virtual_machine"}:
        _price_azure_vm(est, rtype, label, attrs)
        return
    if rtype == "azurerm_storage_account":
        est.add(resource_type=rtype, label=label, billing_basis="blob storage (LRS hot)",
                quantity=0.0, unit="GB-month", unit_price_usd=0.0184, confidence="low",
                assumption="no stored volume in configuration")
        return
    if rtype in {"azurerm_managed_disk", "azurerm_snapshot"}:
        size = _as_int(attrs.get("disk_size_gb")) or _as_int(attrs.get("size_gb")) or 32
        est.add(resource_type=rtype, label=label, billing_basis="managed disk",
                quantity=size, unit="GB-month", unit_price_usd=0.13, confidence="low")
        return
    if rtype in {"azurerm_public_ip", "azurerm_lb"}:
        est.add(resource_type=rtype, label=label, billing_basis="address/balancer hours",
                quantity=ASSUMED_HOURS_PER_MONTH, unit="hour", unit_price_usd=0.025,
                confidence="medium")
        return
    if rtype == "azurerm_kubernetes_cluster":
        est.add(resource_type=rtype, label=label, billing_basis="AKS control plane",
                quantity=ASSUMED_HOURS_PER_MONTH, unit="hour", unit_price_usd=0.10,
                confidence="low", assumption="free tier costs 0; nodes priced separately")
        return
    if rtype == "azurerm_key_vault":
        est.skip(rtype, label, "operation-based pricing; volume unknown statically")
        return
    if rtype.startswith("azurerm_mssql_") or rtype.startswith("azurerm_postgresql_") \
            or rtype.startswith("azurerm_mysql_") or rtype.startswith("azurerm_cosmosdb_") \
            or rtype.startswith("azurerm_redis_"):
        est.skip(rtype, label, "SKU/tier is not a recognised literal; priced per SKU")
        return

    # --- Google Cloud ------------------------------------------------------
    if rtype == "google_compute_instance":
        _price_gcp_instance(est, rtype, label, attrs)
        return
    if rtype == "google_storage_bucket":
        est.add(resource_type=rtype, label=label, billing_basis="object storage (standard)",
                quantity=0.0, unit="GB-month", unit_price_usd=0.020, confidence="low",
                assumption="no stored volume in configuration")
        return
    if rtype in {"google_compute_disk", "google_compute_region_disk"}:
        size = _as_int(attrs.get("size")) or 32
        est.add(resource_type=rtype, label=label, billing_basis="persistent disk",
                quantity=size, unit="GB-month", unit_price_usd=0.04, confidence="low")
        return
    if rtype == "google_container_cluster":
        est.add(resource_type=rtype, label=label, billing_basis="GKE cluster management",
                quantity=ASSUMED_HOURS_PER_MONTH, unit="hour", unit_price_usd=0.10,
                confidence="low", assumption="zonal clusters have a free tier")
        return
    if rtype in {"google_compute_address", "google_compute_forwarding_rule"}:
        est.add(resource_type=rtype, label=label, billing_basis="address/forwarding hours",
                quantity=ASSUMED_HOURS_PER_MONTH, unit="hour", unit_price_usd=0.025,
                confidence="medium")
        return
    if rtype.startswith("google_sql_") or rtype.startswith("google_spanner_") \
            or rtype.startswith("google_bigtable_"):
        est.skip(rtype, label, "tier is not a recognised literal; priced per tier")
        return

    # --- Free / provider-agnostic -----------------------------------------
    if rtype.startswith(ZERO_COST_PREFIXES):
        est.add(resource_type=rtype, label=label, billing_basis="no direct charge",
                quantity=0.0, unit="month", unit_price_usd=0.0, confidence="high",
                assumption="free building block")
        return

    est.skip(rtype, label, "no pricing model for this resource type")


def estimate_cost(
    documents: list[dict[str, Any]],
    *,
    region: str | None = None,
) -> dict[str, Any]:
    """Estimate the monthly list cost of the resources in parsed HCL documents.

    ``region`` overrides the region discovered from a provider block.  The
    return value is JSON-serialisable and is embedded in the analyze response.
    """
    detected = region or _detect_region(documents)
    est = _Estimator(detected)
    unpriced_types: dict[str, int] = {}

    for rtype, label, attrs in iter_resources(documents):
        before = len(est.unpriced)
        _price_resource(est, rtype, label, attrs)
        if len(est.unpriced) > before:
            unpriced_types[rtype] = unpriced_types.get(rtype, 0) + 1

    total = round(sum(item["monthly_usd"] for item in est.line_items), 2)
    est.line_items.sort(key=lambda item: (-item["monthly_usd"], item["resource_type"]))

    notes: list[str] = []
    if detected is None:
        notes.append(f"No provider region found; assuming {DEFAULT_REGION} list prices.")
    elif not est.region_known:
        notes.append(
            f"Region {detected!r} is not in the price table; {DEFAULT_REGION} prices were used unscaled."
        )
    if len(unpriced_types) > 0:
        notes.append(
            "Usage-based resources (storage volume, data transfer, requests) cannot be "
            "derived from configuration alone and are listed under 'unpriced'."
        )

    return {
        "currency": "USD",
        "period": "month",
        "region": est.region,
        "assumed_hours_per_month": ASSUMED_HOURS_PER_MONTH,
        "total_monthly_usd": total,
        "line_items": est.line_items,
        "unpriced": est.unpriced,
        "notes": notes,
        "disclaimer": ESTIMATE_DISCLAIMER,
    }
