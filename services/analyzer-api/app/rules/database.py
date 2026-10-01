"""Database rules (RDS, Aurora, DynamoDB, ElastiCache).

Owner: database subagent.  Export ``RULES: list[Rule]``.

Every check is a pure function of the parsed document and its source text and
only fires on attributes that are explicitly written in HCL.  Where a provider
default matters (DynamoDB always encrypts at rest with an AWS-owned key unless a
``server_side_encryption`` block supplies a customer-managed key) the comment
says so and the rule reports the unstated configuration rather than a false
"unencrypted" claim.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from app.rules.base import Rule, RuleHelpers, RuleHit


def _resource_line(helpers: RuleHelpers, resource_type: str, label: str) -> int | None:
    pattern = rf'resource\s+"{re.escape(resource_type)}"\s+"{re.escape(label)}"'
    return helpers.line_matching(pattern) or helpers.line_of(f'"{label}"')


def _attribute_line(helpers: RuleHelpers, attribute: str) -> int | None:
    return helpers.line_matching(rf"\b{re.escape(attribute)}\b")


def _as_int(value: Any) -> int | None:
    """Coerce a literal retention count; ``bool`` is not a valid count."""
    if isinstance(value, bool):
        return None
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


def _check_rds_publicly_accessible(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers,
) -> list[RuleHit]:
    """TM-DB-001: an RDS instance reachable from the public internet."""
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of("aws_db_instance"):
        if helpers.is_enabled(attributes.get("publicly_accessible")):
            hits.append(RuleHit(
                message=f"RDS instance '{label}' sets publicly_accessible = true.",
                line=_attribute_line(helpers, "publicly_accessible"),
                recommendation="Place the instance in private subnets and reach it through a bastion, VPN, or private link.",
                severity="error",
            ))
    return hits


def _check_rds_storage_encryption(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers,
) -> list[RuleHit]:
    """TM-DB-002: an RDS instance that explicitly disables storage encryption."""
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of("aws_db_instance"):
        if "storage_encrypted" not in attributes:
            continue
        if helpers.is_disabled(attributes.get("storage_encrypted")):
            hits.append(RuleHit(
                message=f"RDS instance '{label}' sets storage_encrypted = false.",
                line=_attribute_line(helpers, "storage_encrypted"),
                recommendation="Set storage_encrypted = true (with kms_key_id where a customer-managed key is required).",
            ))
    return hits


def _check_rds_backup_retention(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers,
) -> list[RuleHit]:
    """TM-DB-003: an RDS instance that disables automated backups."""
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of("aws_db_instance"):
        retention = _as_int(attributes.get("backup_retention_period"))
        if retention is not None and retention <= 0:
            hits.append(RuleHit(
                message=f"RDS instance '{label}' sets backup_retention_period = {retention}, disabling automated backups.",
                line=_attribute_line(helpers, "backup_retention_period"),
                recommendation="Set backup_retention_period to at least 7 days (or the value required by your recovery objective).",
            ))
    return hits


def _check_rds_deletion_protection(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers,
) -> list[RuleHit]:
    """TM-DB-004: an RDS instance that disables deletion protection."""
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of("aws_db_instance"):
        if helpers.is_disabled(attributes.get("deletion_protection")):
            hits.append(RuleHit(
                message=f"RDS instance '{label}' sets deletion_protection = false.",
                line=_attribute_line(helpers, "deletion_protection"),
                recommendation="Set deletion_protection = true on stateful databases to guard against accidental destroy.",
            ))
    return hits


def _check_rds_multi_az(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers,
) -> list[RuleHit]:
    """TM-DB-005: an RDS instance explicitly left in a single Availability Zone."""
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of("aws_db_instance"):
        if helpers.is_disabled(attributes.get("multi_az")):
            hits.append(RuleHit(
                message=f"RDS instance '{label}' sets multi_az = false, leaving no standby for failover.",
                line=_attribute_line(helpers, "multi_az"),
                recommendation="Set multi_az = true for production databases that require automated failover.",
            ))
    return hits


def _check_rds_cluster_storage_encryption(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers,
) -> list[RuleHit]:
    """TM-DB-006: an Aurora/RDS cluster that explicitly disables storage encryption."""
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of("aws_rds_cluster"):
        if "storage_encrypted" not in attributes:
            continue
        if helpers.is_disabled(attributes.get("storage_encrypted")):
            hits.append(RuleHit(
                message=f"RDS cluster '{label}' sets storage_encrypted = false.",
                line=_attribute_line(helpers, "storage_encrypted"),
                recommendation="Set storage_encrypted = true so the cluster's underlying storage is encrypted at rest.",
            ))
    return hits


def _check_dynamodb_encryption(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers,
) -> list[RuleHit]:
    """TM-DB-007: a DynamoDB table without a server-side encryption block.

    DynamoDB always encrypts at rest, but without a ``server_side_encryption``
    block it uses an AWS-owned key; this rule reports the missing
    customer-managed-key configuration rather than claiming data is unencrypted.
    """
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of("aws_dynamodb_table"):
        if helpers.blocks(attributes, "server_side_encryption"):
            continue
        hits.append(RuleHit(
            message=f"DynamoDB table '{label}' has no server_side_encryption block for a customer-managed key.",
            line=_resource_line(helpers, "aws_dynamodb_table", label),
            recommendation="Add server_side_encryption { enabled = true; kms_key_arn = ... } to control table encryption.",
        ))
    return hits


def _check_elasticache_transit_encryption(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers,
) -> list[RuleHit]:
    """TM-DB-008: an ElastiCache replication group with transport encryption off."""
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of("aws_elasticache_replication_group"):
        if helpers.is_disabled(attributes.get("transit_encryption_enabled")):
            hits.append(RuleHit(
                message=f"ElastiCache replication group '{label}' sets transit_encryption_enabled = false.",
                line=_attribute_line(helpers, "transit_encryption_enabled"),
                recommendation="Set transit_encryption_enabled = true and require TLS from clients to protect cache traffic.",
            ))
    return hits


RULES: list[Rule] = [
    Rule(
        rule_id="TM-DB-001",
        title="RDS instance is publicly accessible",
        severity="error",
        service="database",
        dimension="security",
        recommendation="Place the instance in private subnets and expose it only through controlled network paths.",
        check=_check_rds_publicly_accessible,
    ),
    Rule(
        rule_id="TM-DB-002",
        title="RDS storage encryption disabled",
        severity="warning",
        service="database",
        dimension="security",
        recommendation="Set storage_encrypted = true, using a customer-managed KMS key where required.",
        check=_check_rds_storage_encryption,
    ),
    Rule(
        rule_id="TM-DB-003",
        title="RDS automated backups disabled",
        severity="warning",
        service="database",
        dimension="reliability",
        recommendation="Set a non-zero backup_retention_period that meets the recovery objective.",
        check=_check_rds_backup_retention,
    ),
    Rule(
        rule_id="TM-DB-004",
        title="RDS deletion protection disabled",
        severity="warning",
        service="database",
        dimension="reliability",
        recommendation="Enable deletion_protection on stateful databases to prevent accidental destroy.",
        check=_check_rds_deletion_protection,
    ),
    Rule(
        rule_id="TM-DB-005",
        title="RDS instance is single-AZ",
        severity="information",
        service="database",
        dimension="reliability",
        recommendation="Set multi_az = true for production databases that need automated failover.",
        check=_check_rds_multi_az,
    ),
    Rule(
        rule_id="TM-DB-006",
        title="RDS cluster storage encryption disabled",
        severity="warning",
        service="database",
        dimension="security",
        recommendation="Set storage_encrypted = true so the cluster's underlying storage is encrypted at rest.",
        check=_check_rds_cluster_storage_encryption,
    ),
    Rule(
        rule_id="TM-DB-007",
        title="DynamoDB table lacks a customer-managed encryption key",
        severity="information",
        service="database",
        dimension="security",
        recommendation="Add a server_side_encryption block with a customer-managed KMS key to control table encryption.",
        check=_check_dynamodb_encryption,
    ),
    Rule(
        rule_id="TM-DB-008",
        title="ElastiCache transit encryption disabled",
        severity="warning",
        service="database",
        dimension="security",
        recommendation="Enable transit_encryption_enabled and require TLS from clients.",
        check=_check_elasticache_transit_encryption,
    ),
]
