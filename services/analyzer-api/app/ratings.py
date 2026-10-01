"""Evidence-limited service ratings; unknown dimensions stay explicitly unknown.

Rating philosophy
-----------------
TerraMind reports a score only when the parsed Terraform documents (or mapped
static findings) contain observable evidence for that dimension.  When nothing
observable is available the dimension is reported as
``insufficient_information`` instead of guessing.  Every scored dimension
carries a ``criteria_version``, its ``evidence`` (structural facts) and
``evidence_finding_ids`` (findings), a ``summary``, ``assumptions`` and
``limitations``.

Rubric version ``aws-rubric-v2`` covers these dimensions:

* ``security`` - mapped static findings are authoritative and use the review
  weights ``error=35`` / ``warning=15`` / ``information=5`` over a 100 base.
  When no rule or scanner finding maps to a service, a very small, explicitly
  observed structural fallback (for example RDS ``publicly_accessible=true``)
  is used.  With neither findings nor observed unsafe attributes the dimension
  stays ``insufficient_information`` (never a fabricated 100).
* ``reliability`` - starts from 100 and subtracts penalties for observed
  unsafe/missing resilience attributes (multi-AZ, backups, deletion
  protection, ASG health checks, load-balancer subnet spread, S3 versioning).
  Only attributes actually written in HCL are counted.
* ``maintainability`` - starts from 100 and subtracts penalties for observed
  structural deficits (missing tags, hardcoded-over-variable values, no module
  blocks, unpinned provider versions).

``scalability`` and ``cost`` deliberately stay ``insufficient_information``:
they require external workload, traffic and pricing data this static pass does
not have.
"""

from __future__ import annotations

from typing import Any

#: Bump together with ``app.rules.base.CRITERIA_VERSION`` when semantics change.
CRITERIA_VERSION = "aws-rubric-v2"

#: Review weights for mapped security findings.  Preserved from v1.
_SECURITY_FINDING_WEIGHTS = {"error": 35, "warning": 15, "information": 5}

#: Fallback attribution for the inline rules implemented in ``app.main``.
#: Registry rules are resolved through ``app.rules.RULE_SERVICES`` first; this
#: map keeps the original inline-rule attribution working unchanged and also
#: lets scanner findings whose ``rule_id`` embeds one of these prefixes map to
#: a service.
_SERVICE_RULES: dict[str, tuple[str, ...]] = {
    "networking": ("TM-NET-",),
    "iam": ("TM-IAM-",),
    "s3": ("TM-S3-",),
    "ecr": ("TM-ECR-",),
    "compute": ("TM-EC2-", "TM-EBS-"),
    "storage": ("TM-EBS-",),
}


def build_service_ratings(documents: list[dict[str, Any]], findings: list[Any]) -> list[dict[str, Any]]:
    """Return scoped evidence summaries, never guessed uptime/cost scores."""
    # Imported lazily so ``app.ratings`` stays importable without the rules
    # package (and to avoid import cycles during app start-up).
    try:
        from app.rules import RULE_DIMENSIONS, RULE_SERVICES
    except Exception:  # noqa: BLE001 - ratings must never break an analysis request
        RULE_DIMENSIONS, RULE_SERVICES = {}, {}

    resources_by_service: dict[str, list[tuple[str, str, dict[str, Any]]]] = {}
    for resource_type, label, attributes in _iter_resources(documents):
        resources_by_service.setdefault(_service_for_resource(resource_type), []).append(
            (resource_type, label, attributes)
        )

    findings_by_service: dict[str, list[Any]] = {}
    for finding in findings:
        if not _is_security_finding(finding, RULE_DIMENSIONS):
            continue
        service = _service_for_finding(finding, RULE_SERVICES)
        if service is None:
            continue
        findings_by_service.setdefault(service, []).append(finding)

    maintainability_facts = _document_maintainability_facts(documents)

    results: list[dict[str, Any]] = []
    services = sorted(set(resources_by_service) | set(findings_by_service))
    for service in services:
        instances = resources_by_service.get(service, [])
        count = len(instances)
        relevant = findings_by_service.get(service, [])
        reliability = _reliability_dimension(instances)
        maintainability = _maintainability_dimension(instances, maintainability_facts)
        results.append({
            "service": service,
            "resource_count": count,
            "dimensions": {
                "security": _security_dimension(relevant, instances),
                "reliability": reliability,
                "scalability": _unknown(
                    "Scalability requires workload, traffic, and capacity assumptions.",
                    "Not scored: no workload, traffic pattern, or capacity target is available in static HCL.",
                ),
                "cost": _unknown(
                    "Cost requires region, usage, pricing date, and a provider pricing estimator.",
                    "Not scored: no usage profile, region, or dated pricing data is available.",
                ),
                "maintainability": maintainability,
            },
        })
    return results


# -- security ---------------------------------------------------------------


def _security_dimension(
    relevant: list[Any], instances: list[tuple[str, str, dict[str, Any]]],
) -> dict[str, Any]:
    if relevant:
        penalty = sum(
            _SECURITY_FINDING_WEIGHTS.get(
                str(getattr(item, "severity", "information")), 5
            )
            for item in relevant
        )
        return {
            "score": max(0, 100 - penalty),
            "status": "limited",
            "criteria_version": CRITERIA_VERSION,
            "evidence_finding_ids": [
                str(getattr(item, "id", "")) for item in relevant if getattr(item, "id", None)
            ],
            "evidence": [],
            "summary": (
                f"Penalty-based summary of {len(relevant)} mapped static security "
                f"finding(s) across {len(instances)} resource(s); this is not a certification."
            ),
            "assumptions": ["Findings reflect the deterministic checks implemented at analysis time."],
            "limitations": [
                "This is not a security certification; rules cover only a small subset of Terraform/AWS risks.",
                "No finding means only that the implemented checks did not report one.",
            ],
        }

    # Rules are authoritative.  Only when nothing maps to the service do we fall
    # back to a tiny, explicitly observed attribute checklist so an uncovered
    # service is not silently treated as unknown when a clearly unsafe value is
    # written out in HCL.
    structural_penalty = 0
    structural_evidence: list[str] = []
    for resource_type, label, attributes in instances:
        for weight, fact in _structural_security_evidence(resource_type, label, attributes):
            structural_penalty += weight
            structural_evidence.append(fact)

    if structural_evidence:
        return {
            "score": max(0, 100 - structural_penalty),
            "status": "limited",
            "criteria_version": CRITERIA_VERSION,
            "evidence_finding_ids": [],
            "evidence": structural_evidence,
            "summary": (
                "No static rule or scanner finding covers this service; scored from observed "
                "unsafe attributes only."
            ),
            "assumptions": ["Only attributes written literally in the parsed HCL are evaluated."],
            "limitations": [
                "Structural fallback checks are a small subset of AWS security guidance.",
                "Resolved variables, modules and provider defaults are not expanded.",
            ],
        }

    return {
        "score": None,
        "status": "insufficient_information",
        "criteria_version": "not_scored",
        "evidence_finding_ids": [],
        "evidence": [],
        "summary": "No service-specific security evidence (rule finding or observed unsafe attribute) is available.",
        "assumptions": [],
        "limitations": [
            "Enable trusted external scanners and expand service coverage before interpreting security posture.",
        ],
    }


def _structural_security_evidence(
    resource_type: str, label: str, attributes: dict[str, Any],
) -> list[tuple[int, str]]:
    """Observed unsafe attributes for services no rule currently covers.

    Kept intentionally small and conservative; each entry is a literal value
    visible in the parsed HCL, never an inferred default.
    """
    evidence: list[tuple[int, str]] = []
    if resource_type in {"aws_db_instance", "aws_rds_cluster"}:
        if _as_bool(attributes.get("publicly_accessible")) is True:
            evidence.append((35, f"{resource_type}.{label}: publicly_accessible=true"))
        if _as_bool(attributes.get("storage_encrypted")) is False:
            evidence.append((15, f"{resource_type}.{label}: storage_encrypted=false"))
    if resource_type == "azurerm_storage_account":
        if _as_bool(attributes.get("allow_nested_items_to_be_public")) is True:
            evidence.append((
                35,
                f"{resource_type}.{label}: allow_nested_items_to_be_public=true",
            ))
    return evidence


# -- reliability ------------------------------------------------------------


def _reliability_dimension(
    instances: list[tuple[str, str, dict[str, Any]]],
) -> dict[str, Any]:
    """Score observable resilience attributes; start at 100, subtract penalties.

    Only attributes explicitly written in the parsed HCL count as evidence, so
    a resource that does not expose any resilience attribute is not scored.
    """
    penalty = 0
    evidence: list[str] = []

    for resource_type, label, attributes in instances:
        if resource_type in {"aws_db_instance", "aws_rds_cluster"}:
            if "multi_az" in attributes:
                value = _as_bool(attributes.get("multi_az"))
                evidence.append(f"{resource_type}.{label}: multi_az={_display(value)}")
                if value is False:
                    penalty += 20
            if "backup_retention_period" in attributes:
                value = _as_int(attributes.get("backup_retention_period"))
                evidence.append(
                    f"{resource_type}.{label}: backup_retention_period={_display(value)}"
                )
                if value is not None and value <= 0:
                    penalty += 15
            if "deletion_protection" in attributes:
                value = _as_bool(attributes.get("deletion_protection"))
                evidence.append(f"{resource_type}.{label}: deletion_protection={_display(value)}")
                if value is False:
                    penalty += 10
        elif resource_type == "aws_elasticache_replication_group":
            if "automatic_failover_enabled" in attributes:
                value = _as_bool(attributes.get("automatic_failover_enabled"))
                evidence.append(
                    f"{resource_type}.{label}: automatic_failover_enabled={_display(value)}"
                )
                if value is False:
                    penalty += 20
            if "multi_az_enabled" in attributes:
                value = _as_bool(attributes.get("multi_az_enabled"))
                evidence.append(f"{resource_type}.{label}: multi_az_enabled={_display(value)}")
                if value is False:
                    penalty += 15
            if "snapshot_retention_limit" in attributes:
                value = _as_int(attributes.get("snapshot_retention_limit"))
                evidence.append(
                    f"{resource_type}.{label}: snapshot_retention_limit={_display(value)}"
                )
                if value is not None and value <= 0:
                    penalty += 10
        elif resource_type == "aws_autoscaling_group":
            if "min_size" in attributes:
                value = _as_int(attributes.get("min_size"))
                evidence.append(f"{resource_type}.{label}: min_size={_display(value)}")
                if value is not None and value <= 1:
                    penalty += 10
            if "health_check_type" in attributes:
                value = _scalar(attributes.get("health_check_type"))
                evidence.append(f"{resource_type}.{label}: health_check_type={_display(value)}")
                if value is not None and value.lower() != "elb":
                    penalty += 10
        elif resource_type in {"aws_lb", "aws_alb", "aws_elb"}:
            subnet_count = _sequence_length(attributes.get("subnets"))
            zone_count = _sequence_length(attributes.get("availability_zones"))
            if subnet_count is not None:
                evidence.append(f"{resource_type}.{label}: subnets={subnet_count}")
                if subnet_count < 2:
                    penalty += 20
            elif zone_count is not None:
                evidence.append(f"{resource_type}.{label}: availability_zones={zone_count}")
                if zone_count < 2:
                    penalty += 20
        elif resource_type == "aws_s3_bucket_versioning":
            for block in _blocks(attributes, "versioning_configuration"):
                value = _scalar(block.get("status"))
                evidence.append(f"{resource_type}.{label}: versioning status={_display(value)}")
                if value is not None and value.lower() != "enabled":
                    penalty += 20
        elif resource_type == "aws_s3_bucket":
            for block in _blocks(attributes, "versioning"):
                value = _as_bool(block.get("enabled"))
                evidence.append(f"{resource_type}.{label}: versioning enabled={_display(value)}")
                if value is False:
                    penalty += 20

    if not evidence:
        return _unknown(
            "Reliability requires an availability target, deployment topology, and runtime/health evidence.",
            "Not scored: no observable resilience attribute (multi-AZ, backups, health checks, spread, versioning) is present for these resources.",
        )

    return {
        "score": max(0, 100 - penalty),
        "status": "limited",
        "criteria_version": CRITERIA_VERSION,
        "evidence_finding_ids": [],
        "evidence": evidence,
        "summary": (
            f"Scored from {len(evidence)} observable resilience attribute(s); "
            f"{penalty} penalty point(s) deducted from a 100 base."
        ),
        "assumptions": [
            "The parsed HCL is the effective configuration; provider and module defaults are not expanded.",
            "A value explicitly written in HCL is treated as observed; unset attributes are not inferred.",
        ],
        "limitations": [
            "No runtime failover, latency, or incident evidence is available.",
            "Resources created inside modules are not expanded unless their attributes appear in parsed documents.",
        ],
    }


# -- maintainability --------------------------------------------------------


def _maintainability_dimension(
    instances: list[tuple[str, str, dict[str, Any]]],
    facts: dict[str, int],
) -> dict[str, Any]:
    """Score observable structure; start at 100, subtract documented penalties.

    Penalties (applied once per service):
      - any service resource without a non-empty ``tags`` map: -5
      - service configuration has hardcoded literals and no variable/reference: -10
      - no ``module`` block anywhere in the parsed documents: -5
      - a required provider without a version constraint: -10
    """
    penalty = 0
    evidence: list[str] = []
    has_untagged = False
    literals = 0
    references = 0

    for resource_type, label, attributes in instances:
        tags = attributes.get("tags")
        if isinstance(tags, dict) and tags:
            evidence.append(f"{resource_type}.{label}: tags present ({len(tags)})")
        else:
            has_untagged = True
            evidence.append(f"{resource_type}.{label}: no tags map")
        literal_count, reference_count = _literal_vs_reference_counts(attributes)
        literals += literal_count
        references += reference_count

    if has_untagged:
        penalty += 5
    if literals and not references:
        penalty += 10
        evidence.append(f"values: {literals} hardcoded literal(s), 0 variable/reference value(s)")
    elif literals or references:
        evidence.append(f"values: {literals} hardcoded literal(s), {references} variable/reference value(s)")

    module_count = facts.get("module_count", 0)
    if module_count:
        evidence.append(f"documents: {module_count} module block(s)")
    else:
        penalty += 5
        evidence.append("documents: no module blocks")

    pinned = facts.get("providers_pinned", 0)
    unpinned = facts.get("providers_unpinned", 0)
    if unpinned:
        penalty += 10
        evidence.append(f"providers: {unpinned} required provider(s) without a pinned version")
    elif pinned:
        evidence.append(f"providers: {pinned} required provider(s) with a version constraint")

    return {
        "score": max(0, 100 - penalty),
        "status": "limited",
        "criteria_version": CRITERIA_VERSION,
        "evidence_finding_ids": [],
        "evidence": evidence,
        "summary": (
            f"Scored from {len(evidence)} observable structural signal(s); "
            f"{penalty} penalty point(s) deducted from a 100 base."
        ),
        "assumptions": [
            "HCL structure (tags, variables, modules, provider constraints) is treated as a proxy for maintainability.",
            "Formatting, naming, and comment style are out of scope.",
        ],
        "limitations": [
            "No repository history, review, test coverage, or documentation evidence is available.",
            "Module internals are not expanded; a module reference counts as one structural fact.",
        ],
    }


def _document_maintainability_facts(documents: list[dict[str, Any]]) -> dict[str, int]:
    module_count = 0
    pinned = 0
    unpinned = 0
    for document in documents:
        if not isinstance(document, dict):
            continue
        for module_block in _as_mapping_list(document.get("module")):
            module_count += len(module_block)
        for terraform_block in _as_mapping_list(document.get("terraform")):
            for required in _as_mapping_list(terraform_block.get("required_providers")):
                for _name, config in required.items():
                    version = config.get("version") if isinstance(config, dict) else None
                    if isinstance(version, str) and version.strip().strip('"'):
                        pinned += 1
                    else:
                        unpinned += 1
    return {"module_count": module_count, "providers_pinned": pinned, "providers_unpinned": unpinned}


# -- findings attribution ---------------------------------------------------


def _is_security_finding(finding: Any, rule_dimensions: dict[str, str]) -> bool:
    """Registry findings carry a dimension; only security ones feed security.

    Inline rules (``TM-NET-*`` etc.) and scanner findings (``source`` other than
    ``terramind-rules``) are treated as security evidence because the current
    inline rule set is security-only.
    """
    source = str(getattr(finding, "source", ""))
    rule_id = str(getattr(finding, "rule_id", ""))
    if source == "terramind-rules" and rule_id in rule_dimensions:
        return rule_dimensions[rule_id] == "security"
    return True


def _service_for_finding(finding: Any, rule_services: dict[str, str]) -> str | None:
    """Map one finding to a service.

    Registry rules map through ``RULE_SERVICES``.  Everything else (the inline
    rules and scanner findings) falls back to ``rule_id`` prefix matching,
    which is intentionally simple and documented.
    """
    source = str(getattr(finding, "source", ""))
    rule_id = str(getattr(finding, "rule_id", ""))
    if source == "terramind-rules" and rule_id in rule_services:
        return rule_services[rule_id]
    for service, prefixes in _SERVICE_RULES.items():
        if any(rule_id.startswith(prefix) for prefix in prefixes):
            return service
    return None


# -- traversal + value helpers ---------------------------------------------


def _iter_resources(documents: list[dict[str, Any]]):
    """Yield ``(resource_type, label, attributes)`` for every provider.

    Only ``resource`` blocks are traversed.  ``data`` blocks and other
    non-resource top-level blocks (``provider``, ``module``, ``terraform``,
    ...) are intentionally skipped.  Resource types are no longer restricted
    to the ``aws_`` prefix so Azure, Google Cloud and general Terraform are
    covered by the same traversal.
    """
    for document in documents:
        if not isinstance(document, dict):
            continue
        blocks = document.get("resource", [])
        if isinstance(blocks, dict):
            blocks = [blocks]
        for block in blocks if isinstance(blocks, list) else []:
            if not isinstance(block, dict):
                continue
            for resource_type, instances in block.items():
                if not isinstance(instances, dict):
                    continue
                for label, attributes in instances.items():
                    if isinstance(attributes, dict):
                        yield str(resource_type), str(label), attributes


def _service_for_resource(resource_type: str) -> str:
    # AWS: preserved unchanged from the original AWS-only mapping.
    if resource_type.startswith("aws_s3_"):
        return "s3"
    if resource_type.startswith("aws_iam_"):
        return "iam"
    if resource_type.startswith("aws_ecr_"):
        return "ecr"
    if resource_type.startswith(("aws_ebs_", "aws_efs_")):
        return "storage"
    if resource_type.startswith(("aws_db_", "aws_rds_", "aws_elasticache_")):
        return "database"
    if resource_type.startswith((
        "aws_security_group", "aws_subnet", "aws_vpc", "aws_route", "aws_network_acl",
        "aws_lb", "aws_alb", "aws_elb",
    )):
        return "networking"
    if resource_type.startswith((
        "aws_instance", "aws_launch_", "aws_autoscaling_", "aws_ecs_", "aws_eks_", "aws_lambda_",
    )):
        return "compute"

    # Azure (azurerm provider).
    if resource_type.startswith("azurerm_storage_") or resource_type in {
        "azurerm_managed_disk", "azurerm_snapshot",
    }:
        return "storage"
    if resource_type.startswith((
        "azurerm_mssql_", "azurerm_postgresql_", "azurerm_mysql_",
        "azurerm_cosmosdb_", "azurerm_redis_",
    )):
        return "database"
    if resource_type.startswith((
        "azurerm_virtual_machine", "azurerm_linux_virtual_machine",
        "azurerm_windows_virtual_machine", "azurerm_kubernetes_cluster",
        "azurerm_function_app", "azurerm_linux_web_app", "azurerm_app_service",
    )):
        return "compute"
    if resource_type.startswith((
        "azurerm_network_security_rule", "azurerm_network_security_group",
        "azurerm_subnet", "azurerm_virtual_network", "azurerm_public_ip",
        "azurerm_lb", "azurerm_application_gateway",
    )):
        return "networking"
    if resource_type.startswith("azurerm_key_vault"):
        return "secrets"

    # Google Cloud (google provider).
    if resource_type.startswith("google_storage_bucket"):
        return "storage"
    if resource_type.startswith(("google_sql_", "google_spanner_", "google_bigtable_")):
        return "database"
    if resource_type.startswith((
        "google_compute_instance", "google_container_cluster",
        "google_cloudfunctions", "google_cloud_run",
    )):
        return "compute"
    if resource_type.startswith((
        "google_compute_firewall", "google_compute_network", "google_compute_subnetwork",
        "google_compute_forwarding_rule",
    )):
        return "networking"

    # Provider-agnostic building blocks are explicitly tracked as "other".
    if resource_type.startswith(("kubernetes_", "random_", "null_", "local_", "tls_")):
        return "other"

    return "other"


def _literal_vs_reference_counts(attributes: dict[str, Any]) -> tuple[int, int]:
    literals = 0
    references = 0
    for key, value in attributes.items():
        if key == "tags":
            continue
        for text in _string_values(value):
            if "${" in text:
                references += 1
            elif text:
                literals += 1
    return literals, references


def _string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip().strip('"')]
    if isinstance(value, dict):
        return [item for child in value.values() for item in _string_values(child)]
    if isinstance(value, list):
        return [item for child in value for item in _string_values(child)]
    return []


def _as_mapping_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _blocks(attributes: dict[str, Any], key: str) -> list[dict[str, Any]]:
    return _as_mapping_list(attributes.get(key))


def _sequence_length(value: Any) -> int | None:
    return len(value) if isinstance(value, list) else None


def _scalar(value: Any) -> str | None:
    if value is None or isinstance(value, (bool, int, float, dict, list)):
        return None
    text = str(value).strip().strip('"')
    return text or None


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().strip('"').lower()
        if text in {"true", "1"}:
            return True
        if text in {"false", "0"}:
            return False
    return None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip().strip('"'))
        except ValueError:
            return None
    return None


def _display(value: Any) -> str:
    if value is None:
        return "unresolved"
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def _unknown(summary: str, detail: str | None = None) -> dict[str, Any]:
    return {
        "score": None,
        "status": "insufficient_information",
        "criteria_version": "not_scored",
        "evidence_finding_ids": [],
        "evidence": [],
        "summary": summary,
        "assumptions": [],
        "limitations": [detail] if detail else [],
    }
