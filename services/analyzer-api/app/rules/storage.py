"""Storage rules (S3, EBS, EFS).

Owner: storage subagent.  Export ``RULES: list[Rule]``.

Every check is a pure function of the parsed document and its source text.  A
rule only fires on attributes that are literally written in HCL, except where a
relational check reasons about the *presence* of a companion resource (an S3
lifecycle configuration, an S3 public-access block, or an EFS lifecycle
policy); those messages are phrased as missing-coverage observations.

S3 rules that are about object storage use the ``s3`` service so they land on
the S3 rating; block/volume rules use ``storage``.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from app.rules.base import Rule, RuleHelpers, RuleHit

#: Companion S3 resources that manipulate an object-access surface.  A bucket
#: that opts into one of these without a matching public-access block is worth
#: reporting; a bare bucket is not (AWS enables Block Public Access for new
#: buckets by default, so absence alone is not evidence of exposure).
_S3_ACCESS_COMPANIONS = (
    "aws_s3_bucket_policy",
    "aws_s3_bucket_acl",
    "aws_s3_bucket_website_configuration",
    "aws_s3_bucket_cors_configuration",
    "aws_s3_bucket_grant",
)

#: Bucket attributes that describe an access surface.
_S3_ACCESS_ATTRIBUTES = ("acl", "policy", "website", "website_configuration", "cors_rule", "grant")


def _resource_line(helpers: RuleHelpers, resource_type: str, label: str) -> int | None:
    """Line of a specific ``resource "<type>" "<label>"`` header, best effort."""
    pattern = rf'resource\s+"{re.escape(resource_type)}"\s+"{re.escape(label)}"'
    return helpers.line_matching(pattern) or helpers.line_of(f'"{label}"')


def _attribute_line(helpers: RuleHelpers, attribute: str) -> int | None:
    return helpers.line_matching(rf"\b{re.escape(attribute)}\b")


def _bucket_identifiers(label: str, attributes: Mapping[str, Any]) -> set[str]:
    """Names that can identify a bucket from a companion resource reference."""
    identifiers = {f"aws_s3_bucket.{label.lower()}."}
    name = attributes.get("bucket")
    if isinstance(name, str) and name.strip().strip('"'):
        identifiers.add(name.strip('"').lower())
    return identifiers


def _check_s3_sse_algorithm(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers,
) -> list[RuleHit]:
    """TM-STOR-001: S3 default encryption uses SSE-S3 (AES256) instead of KMS."""
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of(
        "aws_s3_bucket_server_side_encryption_configuration"
    ):
        for rule_block in helpers.blocks(attributes, "rule"):
            for default in helpers.blocks(rule_block, "apply_server_side_encryption_by_default"):
                algorithm = str(default.get("sse_algorithm", "")).strip('"').lower()
                if algorithm != "aes256":
                    continue
                hits.append(RuleHit(
                    message=f"S3 encryption configuration '{label}' uses AES256 (SSE-S3) instead of aws:kms.",
                    line=_attribute_line(helpers, "sse_algorithm"),
                    recommendation="Use sse_algorithm = \"aws:kms\" with a customer-managed key and bucket_key_enabled = true.",
                ))
    return hits


def _check_s3_versioning(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers,
) -> list[RuleHit]:
    """TM-STOR-002: an S3 versioning resource that does not enable versioning."""
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of("aws_s3_bucket_versioning"):
        statuses = [
            str(block.get("status", "")).strip('"').lower()
            for block in helpers.blocks(attributes, "versioning_configuration")
        ]
        if "enabled" in statuses:
            continue
        hits.append(RuleHit(
            message=f"S3 versioning configuration '{label}' does not set versioning_configuration.status to Enabled.",
            line=_attribute_line(helpers, "versioning_configuration") or _resource_line(
                helpers, "aws_s3_bucket_versioning", label
            ),
            recommendation='Set versioning_configuration { status = "Enabled" } to protect objects from overwrite and deletion.',
        ))
    return hits


def _check_s3_lifecycle(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers,
) -> list[RuleHit]:
    """TM-STOR-003: an S3 bucket without any lifecycle configuration in the file."""
    buckets = list(helpers.resources_of("aws_s3_bucket"))
    if not buckets or any(True for _ in helpers.resources_of("aws_s3_bucket_lifecycle_configuration")):
        return []
    hits: list[RuleHit] = []
    for _type, attributes, label in buckets:
        hits.append(RuleHit(
            message=f"S3 bucket '{label}' has no lifecycle configuration to expire or transition objects.",
            line=_resource_line(helpers, "aws_s3_bucket", label),
            recommendation="Add aws_s3_bucket_lifecycle_configuration to expire noncurrent versions and transition cold data.",
        ))
    return hits


def _check_s3_public_access_block(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers,
) -> list[RuleHit]:
    """TM-STOR-004: an access-controlled S3 bucket without a matching block resource.

    Only fires when the bucket (or a companion resource) actually manipulates an
    access surface, so an internal bucket that relies on account-level Block
    Public Access is not reported.
    """
    buckets = list(helpers.resources_of("aws_s3_bucket"))
    if not buckets:
        return []

    block_refs = [
        str(attributes.get("bucket", "")).strip('"').lower()
        for _type, attributes, _label in helpers.resources_of("aws_s3_bucket_public_access_block")
    ]
    companion_refs = [
        str(attributes.get("bucket", "")).strip('"').lower()
        for resource_type, attributes, _label in helpers.resources()
        if resource_type in _S3_ACCESS_COMPANIONS
    ]

    hits: list[RuleHit] = []
    for _type, attributes, label in buckets:
        identifiers = _bucket_identifiers(label, attributes)
        covered = any(identifier in ref for ref in block_refs for identifier in identifiers)
        if covered:
            continue
        has_access_surface = any(
            key in attributes and attributes[key] is not None for key in _S3_ACCESS_ATTRIBUTES
        )
        if not has_access_surface:
            has_access_surface = any(
                identifier in ref for ref in companion_refs for identifier in identifiers
            )
        if has_access_surface:
            hits.append(RuleHit(
                message=f"S3 bucket '{label}' configures access controls without a matching public-access-block resource.",
                line=_resource_line(helpers, "aws_s3_bucket", label),
                recommendation="Add aws_s3_bucket_public_access_block for this bucket and enable all four protections.",
            ))
    return hits


def _check_s3_force_destroy(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers,
) -> list[RuleHit]:
    """TM-STOR-005: an S3 bucket that deletes its objects when destroyed."""
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of("aws_s3_bucket"):
        if helpers.is_enabled(attributes.get("force_destroy")):
            hits.append(RuleHit(
                message=f"S3 bucket '{label}' sets force_destroy = true, so object data is deleted with the bucket.",
                line=_attribute_line(helpers, "force_destroy"),
                recommendation="Set force_destroy = false and remove objects through a reviewed retention or lifecycle process.",
            ))
    return hits


def _check_efs_encryption(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers,
) -> list[RuleHit]:
    """TM-STOR-006: an EFS file system that explicitly disables encryption.

    EFS encryption can only be set at creation time, so an explicit
    ``encrypted = false`` is unrecoverable without recreating the file system.
    """
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of("aws_efs_file_system"):
        if helpers.is_disabled(attributes.get("encrypted")):
            hits.append(RuleHit(
                message=f"EFS file system '{label}' sets encrypted = false and cannot be encrypted after creation.",
                line=_attribute_line(helpers, "encrypted"),
                recommendation="Recreate the file system with encrypted = true; at-rest encryption is only set at creation.",
            ))
    return hits


def _check_efs_lifecycle(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers,
) -> list[RuleHit]:
    """TM-STOR-007: an EFS file system without a lifecycle policy block."""
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of("aws_efs_file_system"):
        if helpers.blocks(attributes, "lifecycle_policy"):
            continue
        hits.append(RuleHit(
            message=f"EFS file system '{label}' has no lifecycle_policy for infrequent-access or archive transitions.",
            line=_resource_line(helpers, "aws_efs_file_system", label),
            recommendation='Add lifecycle_policy { transition_to_ia = "AFTER_30_DAYS" } to move cold data to cheaper storage.',
        ))
    return hits


def _check_ebs_encryption_provenance(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers,
) -> list[RuleHit]:
    """TM-STOR-008: an EBS volume with no snapshot or encryption attributes.

    This deliberately does not overlap TM-EBS-001, which reports an explicit
    ``encrypted = false``.  A volume that names no snapshot, no encryption flag,
    and no KMS key leaves its encryption provenance unstated in configuration.
    """
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of("aws_ebs_volume"):
        if helpers.attribute(attributes, "snapshot_id", "encrypted", "kms_key_id") is not None:
            continue
        hits.append(RuleHit(
            message=f"EBS volume '{label}' declares no snapshot_id or encryption settings; provenance is unclear.",
            line=_resource_line(helpers, "aws_ebs_volume", label),
            recommendation="Set encrypted = true (and optionally kms_key_id) so the volume's encryption is explicit.",
        ))
    return hits


RULES: list[Rule] = [
    Rule(
        rule_id="TM-STOR-001",
        title="S3 default encryption uses SSE-S3 instead of KMS",
        severity="information",
        service="s3",
        dimension="security",
        recommendation='Use sse_algorithm = "aws:kms" with a customer-managed key and bucket_key_enabled = true.',
        check=_check_s3_sse_algorithm,
    ),
    Rule(
        rule_id="TM-STOR-002",
        title="S3 versioning is not enabled",
        severity="warning",
        service="s3",
        dimension="reliability",
        recommendation='Set versioning_configuration { status = "Enabled" } so objects survive overwrite and deletion.',
        check=_check_s3_versioning,
    ),
    Rule(
        rule_id="TM-STOR-003",
        title="S3 bucket has no lifecycle configuration",
        severity="information",
        service="s3",
        dimension="cost",
        recommendation="Add aws_s3_bucket_lifecycle_configuration to expire and transition objects.",
        check=_check_s3_lifecycle,
    ),
    Rule(
        rule_id="TM-STOR-004",
        title="S3 bucket access controls without a public-access block",
        severity="warning",
        service="s3",
        dimension="security",
        recommendation="Add aws_s3_bucket_public_access_block and enable all four protections for the bucket.",
        check=_check_s3_public_access_block,
    ),
    Rule(
        rule_id="TM-STOR-005",
        title="S3 bucket force_destroy enabled",
        severity="information",
        service="s3",
        dimension="reliability",
        recommendation="Disable force_destroy and delete objects through an explicit, reviewed process.",
        check=_check_s3_force_destroy,
    ),
    Rule(
        rule_id="TM-STOR-006",
        title="EFS file system explicitly not encrypted",
        severity="warning",
        service="storage",
        dimension="security",
        recommendation="Recreate the file system with encrypted = true; EFS encryption is fixed at creation.",
        check=_check_efs_encryption,
    ),
    Rule(
        rule_id="TM-STOR-007",
        title="EFS file system has no lifecycle policy",
        severity="information",
        service="storage",
        dimension="cost",
        recommendation="Add a lifecycle_policy block to transition infrequent-access data to cheaper storage.",
        check=_check_efs_lifecycle,
    ),
    Rule(
        rule_id="TM-STOR-008",
        title="EBS volume encryption provenance unstated",
        severity="information",
        service="storage",
        dimension="security",
        recommendation="Set encrypted = true (and optionally kms_key_id) so the volume's encryption is explicit.",
        check=_check_ebs_encryption_provenance,
    ),
]
