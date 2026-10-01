"""Observability and secrets-hygiene rules (logging, tracing, CloudTrail).

Owner: observability subagent.  Export ``RULES: list[Rule]``.

Observability checks are relational where possible (a VPC only raises a flow-log
gap when no ``aws_flow_log`` exists in the same file).  Secrets checks inspect
the raw HCL source for *literal* credential material only; variable, data, and
module references are never flagged, and reported messages never contain the
matched value.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from app.rules.base import Rule, RuleHelpers, RuleHit


def _location(helpers: RuleHelpers, attribute: str, label: str) -> int | None:
    """Best-effort line: the attribute name if present, else the resource label."""
    return helpers.line_matching(rf"\b{re.escape(attribute)}\b") or helpers.line_of(f'"{label}"')


def _check_cloudtrail_configuration(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers,
) -> list[RuleHit]:
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of("aws_cloudtrail"):
        # enable_logging defaults to true, so only an explicit false is a gap.
        if helpers.is_disabled(attributes.get("enable_logging")):
            hits.append(RuleHit(
                message=f"CloudTrail '{label}' explicitly disables logging.",
                line=_location(helpers, "enable_logging", label),
                recommendation="Set enable_logging = true so account API activity is recorded.",
                severity="error",
            ))
        # AWS defaults is_multi_region_trail to false.
        if not helpers.is_enabled(attributes.get("is_multi_region_trail")):
            hits.append(RuleHit(
                message=f"CloudTrail '{label}' is not configured as a multi-region trail.",
                line=_location(helpers, "is_multi_region_trail", label),
                recommendation="Set is_multi_region_trail = true to capture activity across all enabled regions.",
            ))
        # AWS defaults enable_log_file_validation to false.
        if not helpers.is_enabled(attributes.get("enable_log_file_validation")):
            hits.append(RuleHit(
                message=f"CloudTrail '{label}' does not enable log file integrity validation.",
                line=_location(helpers, "enable_log_file_validation", label),
                recommendation="Set enable_log_file_validation = true to detect tampering with delivered log files.",
            ))
    return hits


def _check_cloudtrail_kms(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers,
) -> list[RuleHit]:
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of("aws_cloudtrail"):
        if helpers.attribute(attributes, "kms_key_id") is None:
            hits.append(RuleHit(
                message=f"CloudTrail '{label}' does not encrypt logs with a customer-managed KMS key.",
                line=_location(helpers, "kms_key_id", label),
                recommendation="Set kms_key_id so trail logs are encrypted with a key you control and can audit.",
            ))
    return hits


def _check_flow_logs(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers,
) -> list[RuleHit]:
    vpcs = list(helpers.resources_of("aws_vpc"))
    if not vpcs:
        return []
    if any(True for _ in helpers.resources_of("aws_flow_log")):
        return []
    hits: list[RuleHit] = []
    for _type, attributes, label in vpcs:
        hits.append(RuleHit(
            message=f"VPC '{label}' has no VPC flow log in this file.",
            line=_location(helpers, "aws_vpc", label),
            recommendation="Add an aws_flow_log (to CloudWatch Logs or S3) to capture accepted and rejected traffic.",
        ))
    return hits


def _check_log_group_retention(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers,
) -> list[RuleHit]:
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of("aws_cloudwatch_log_group"):
        retention = helpers.attribute(attributes, "retention_in_days")
        # AWS default (and 0) means logs are retained forever.
        if retention is None or retention in (0, "0"):
            hits.append(RuleHit(
                message=f"CloudWatch log group '{label}' has no retention limit and keeps logs indefinitely.",
                line=_location(helpers, "retention_in_days", label),
                recommendation="Set retention_in_days to a value allowed by your compliance and cost policy.",
            ))
    return hits


#: AWS access key IDs always begin with AKIA and are uppercase.
_AWS_ACCESS_KEY_ID = re.compile(r"\bAKIA[0-9A-Z]{16}\b")

#: Credential-like assignments whose value is a quoted literal.  The optional
#: prefix catches names such as ``db_password`` or ``aws_access_key_id``.
_SECRET_ASSIGNMENT = re.compile(
    r"""^\s*["']?(?P<key>[a-z0-9_]*(?:password|passwd|secret_access_key|secret_key"""
    r"""|access_key_id|access_key|private_key|api_key|apikey|auth_token|token|secret))"""
    r"""["']?\s*[:=]\s*"""
    r'''"(?P<value>[^"]*)"''',
    re.IGNORECASE,
)


def _check_literal_access_key(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers,
) -> list[RuleHit]:
    line = helpers.line_matching(_AWS_ACCESS_KEY_ID)
    if line is None:
        return []
    return [RuleHit(
        message="A literal AWS access key ID appears in the file.",
        line=line,
        recommendation="Remove and rotate the key; load credentials from IAM roles, environment variables, or a secrets manager.",
    )]


def _check_literal_credentials(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers,
) -> list[RuleHit]:
    hits: list[RuleHit] = []
    for number, text in enumerate(helpers.source.splitlines(), start=1):
        match = _SECRET_ASSIGNMENT.match(text)
        if match is None:
            continue
        value = (match.group("value") or "").strip()
        if not value:
            continue
        if "${" in value:
            continue
        if value.lower().startswith(("var.", "data.", "local.", "module.", "path.", "file.", "env.")):
            continue
        # Dedicated AKIA rule already reports this exact evidence.
        if _AWS_ACCESS_KEY_ID.search(value):
            continue
        key = match.group("key")
        hits.append(RuleHit(
            message=f"Literal credential-like value assigned to '{key}'.",
            line=number,
            recommendation="Remove the literal secret, rotate it, and inject it via variables or a secrets manager.",
        ))
    return hits


RULES: list[Rule] = [
    Rule(
        rule_id="TM-OBS-001",
        title="CloudTrail logging, multi-region, or validation disabled",
        severity="warning",
        service="observability",
        dimension="security",
        recommendation="Enable CloudTrail logging, multi-region coverage, and log file validation.",
        check=_check_cloudtrail_configuration,
    ),
    Rule(
        rule_id="TM-OBS-002",
        title="CloudTrail logs not encrypted with a customer-managed key",
        severity="information",
        service="observability",
        dimension="security",
        recommendation="Set kms_key_id on aws_cloudtrail to control and audit trail encryption.",
        check=_check_cloudtrail_kms,
    ),
    Rule(
        rule_id="TM-OBS-003",
        title="VPC missing a flow log",
        severity="information",
        service="observability",
        dimension="security",
        recommendation="Add an aws_flow_log for each VPC to capture network-level audit evidence.",
        check=_check_flow_logs,
    ),
    Rule(
        rule_id="TM-OBS-004",
        title="CloudWatch log group has no retention limit",
        severity="information",
        service="observability",
        dimension="cost",
        recommendation="Set retention_in_days on log groups to bound storage cost and data lifetime.",
        check=_check_log_group_retention,
    ),
    Rule(
        rule_id="TM-SECRET-001",
        title="Literal AWS access key ID in source",
        severity="error",
        service="secrets",
        dimension="security",
        recommendation="Remove and rotate the key; use IAM roles or a secrets manager instead of literals.",
        check=_check_literal_access_key,
    ),
    Rule(
        rule_id="TM-SECRET-002",
        title="Literal credential-like value in source",
        severity="error",
        service="secrets",
        dimension="security",
        recommendation="Remove the literal secret, rotate it, and inject it via variables or a secrets manager.",
        check=_check_literal_credentials,
    ),
]
