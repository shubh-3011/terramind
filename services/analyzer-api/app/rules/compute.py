"""Compute rules (EC2, launch templates, ASG, Lambda, ECS/EKS).

Owner: compute subagent.  Export ``RULES: list[Rule]``.

Every check is a pure function over an already-parsed HCL document.  Checks
only fire on explicit attribute evidence; where AWS supplies an unsafe default
(disabled monitoring, ``EC2`` health checks, PassThrough tracing, no CMK) the
comment says so and the message is phrased as a posture observation, not an
explicit misconfiguration.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from app.rules.base import Rule, RuleHelpers, RuleHit


def _location(helpers: RuleHelpers, attribute: str, label: str) -> int | None:
    """Best-effort line: the attribute name if present, else the resource label."""
    return helpers.line_matching(rf"\b{re.escape(attribute)}\b") or helpers.line_of(f'"{label}"')


def _check_public_ip(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers,
) -> list[RuleHit]:
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of("aws_instance"):
        if helpers.is_enabled(helpers.attribute(attributes, "associate_public_ip_address")):
            hits.append(RuleHit(
                message=f"EC2 instance '{label}' is assigned a public IP address.",
                line=_location(helpers, "associate_public_ip_address", label),
                recommendation="Run the instance in a private subnet and reach it through a load balancer, NAT, or SSM.",
            ))
    return hits


def _check_block_device_encryption(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers,
) -> list[RuleHit]:
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of("aws_instance", "aws_launch_template"):
        unencrypted = False
        for key in ("root_block_device", "ebs_block_device"):
            for block in helpers.blocks(attributes, key):
                if helpers.is_disabled(block.get("encrypted")):
                    unencrypted = True
        for mapping in helpers.blocks(attributes, "block_device_mappings"):
            for ebs in helpers.blocks(mapping, "ebs"):
                if helpers.is_disabled(ebs.get("encrypted")):
                    unencrypted = True
        if unencrypted:
            hits.append(RuleHit(
                message=f"Compute resource '{label}' defines an explicitly unencrypted EBS block device.",
                line=_location(helpers, "encrypted", label),
                recommendation="Set encrypted = true on every root_block_device, ebs_block_device, and launch-template ebs mapping.",
            ))
    return hits


def _check_detailed_monitoring(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers,
) -> list[RuleHit]:
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of("aws_instance"):
        # AWS defaults monitoring to false, so an absent value is also a gap.
        if not helpers.is_enabled(attributes.get("monitoring")):
            hits.append(RuleHit(
                message=f"EC2 instance '{label}' does not enable detailed CloudWatch monitoring.",
                line=_location(helpers, "monitoring", label),
                recommendation="Set monitoring = true for 1-minute metrics when operational visibility matters.",
            ))
    return hits


def _check_asg_health_check(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers,
) -> list[RuleHit]:
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of("aws_autoscaling_group"):
        health = str(helpers.attribute(attributes, "health_check_type") or "").strip('"').upper()
        min_elb_capacity = helpers.attribute(attributes, "min_elb_capacity")
        # AWS defaults: health_check_type = "EC2" and min_elb_capacity = 0, which
        # replace instances without first confirming they pass ELB health checks.
        if health != "ELB" and min_elb_capacity in (None, 0, "0"):
            hits.append(RuleHit(
                message=f"Autoscaling group '{label}' does not use ELB health checks or min_elb_capacity.",
                line=_location(helpers, "health_check_type", label),
                recommendation='Set health_check_type = "ELB" (with a target group) and a non-zero min_elb_capacity where availability matters.',
            ))
    return hits


def _check_asg_force_delete(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers,
) -> list[RuleHit]:
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of("aws_autoscaling_group"):
        if helpers.is_enabled(attributes.get("force_delete")):
            hits.append(RuleHit(
                message=f"Autoscaling group '{label}' sets force_delete = true.",
                line=_location(helpers, "force_delete", label),
                recommendation="Set force_delete = false so instances are drained before the group is destroyed.",
            ))
    return hits


def _check_launch_configuration(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers,
) -> list[RuleHit]:
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of("aws_launch_configuration"):
        hits.append(RuleHit(
            message="A launch configuration is used instead of a launch template.",
            line=_location(helpers, "aws_launch_configuration", label),
            recommendation="Migrate to aws_launch_template, which supports versioning, mixed instances, and newer EC2 features.",
        ))
    return hits


def _check_lambda_hardening(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers,
) -> list[RuleHit]:
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of("aws_lambda_function"):
        tracing_blocks = helpers.blocks(attributes, "tracing_config")
        mode = ""
        if tracing_blocks:
            mode = str(helpers.attribute(tracing_blocks[0], "mode") or "").strip('"').lower()
        # AWS defaults tracing mode to PassThrough, so an absent block is a gap.
        if mode != "active":
            hits.append(RuleHit(
                message=f"Lambda function '{label}' does not enable active X-Ray tracing.",
                line=_location(helpers, "tracing_config", label),
                recommendation='Set tracing_config { mode = "Active" } to capture request traces.',
            ))
        # AWS encrypts environment variables with an AWS-managed key unless a
        # customer-managed key is supplied.
        if helpers.attribute(attributes, "kms_key_arn") is None:
            hits.append(RuleHit(
                message=f"Lambda function '{label}' does not use a customer-managed KMS key for environment encryption.",
                line=_location(helpers, "kms_key_arn", label),
                recommendation="Set kms_key_arn to a customer-managed KMS key when environment variables hold sensitive data.",
            ))
    return hits


def _check_eks_public_endpoint(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers,
) -> list[RuleHit]:
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of("aws_eks_cluster"):
        for vpc_config in helpers.blocks(attributes, "vpc_config"):
            if not helpers.is_enabled(vpc_config.get("endpoint_public_access")):
                continue
            cidrs = vpc_config.get("public_access_cidrs")
            # AWS defaults public_access_cidrs to 0.0.0.0/0 when omitted.
            if not cidrs or helpers.contains_public_cidr(cidrs):
                hits.append(RuleHit(
                    message=f"EKS cluster '{label}' exposes a public API endpoint without a restricted CIDR.",
                    line=_location(helpers, "endpoint_public_access", label),
                    recommendation="Restrict public_access_cidrs to approved networks or set endpoint_public_access = false.",
                    severity="error",
                ))
    return hits


def _check_ecs_privileged_container(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers,
) -> list[RuleHit]:
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of("aws_ecs_task_definition"):
        container_blocks = helpers.blocks(attributes, "container_definitions")
        privileged = any(helpers.is_enabled(block.get("privileged")) for block in container_blocks)
        # container_definitions is usually a jsonencode() string, so also scan
        # the literal text for a privileged container definition.
        definition = " ".join(helpers.strings(attributes.get("container_definitions")))
        if not privileged and re.search(r'"privileged"\s*:\s*true|privileged\s*[:=]\s*true', definition):
            privileged = True
        if privileged:
            hits.append(RuleHit(
                message=f"ECS task definition '{label}' runs a privileged container.",
                line=_location(helpers, "privileged", label),
                recommendation="Remove privileged = true and grant only the specific Linux capabilities or device access the task needs.",
                severity="error",
            ))
    return hits


RULES: list[Rule] = [
    Rule(
        rule_id="TM-COMPUTE-001",
        title="EC2 instance assigned a public IP address",
        severity="warning",
        service="compute",
        dimension="security",
        recommendation="Disable associate_public_ip_address and reach the instance through a load balancer, NAT, or SSM.",
        check=_check_public_ip,
    ),
    Rule(
        rule_id="TM-COMPUTE-002",
        title="Compute block device explicitly not encrypted",
        severity="warning",
        service="compute",
        dimension="security",
        recommendation="Enable EBS encryption on every root, attached, and launch-template block device.",
        check=_check_block_device_encryption,
    ),
    Rule(
        rule_id="TM-COMPUTE-003",
        title="EC2 detailed monitoring not enabled",
        severity="information",
        service="compute",
        dimension="reliability",
        recommendation="Enable detailed monitoring where 1-minute metrics are needed for alerting or capacity decisions.",
        check=_check_detailed_monitoring,
    ),
    Rule(
        rule_id="TM-COMPUTE-004",
        title="Autoscaling group lacks ELB health gating",
        severity="warning",
        service="compute",
        dimension="reliability",
        recommendation='Use health_check_type = "ELB" with a target group and a non-zero min_elb_capacity.',
        check=_check_asg_health_check,
    ),
    Rule(
        rule_id="TM-COMPUTE-005",
        title="Autoscaling group force deletion enabled",
        severity="warning",
        service="compute",
        dimension="reliability",
        recommendation="Disable force_delete so instances terminate gracefully before the group is removed.",
        check=_check_asg_force_delete,
    ),
    Rule(
        rule_id="TM-COMPUTE-006",
        title="Launch configuration used instead of launch template",
        severity="information",
        service="compute",
        dimension="maintainability",
        recommendation="Migrate to launch templates, which are versioned and support newer EC2 capabilities.",
        check=_check_launch_configuration,
    ),
    Rule(
        rule_id="TM-COMPUTE-007",
        title="Lambda tracing or customer-managed key missing",
        severity="information",
        service="compute",
        dimension="security",
        recommendation="Enable active X-Ray tracing and a customer-managed KMS key for sensitive environment variables.",
        check=_check_lambda_hardening,
    ),
    Rule(
        rule_id="TM-COMPUTE-008",
        title="EKS public API endpoint unrestricted",
        severity="error",
        service="compute",
        dimension="security",
        recommendation="Restrict public_access_cidrs to approved networks or disable the public endpoint.",
        check=_check_eks_public_endpoint,
    ),
    Rule(
        rule_id="TM-COMPUTE-009",
        title="ECS task definition runs a privileged container",
        severity="error",
        service="compute",
        dimension="security",
        recommendation="Drop privileged mode and grant only the specific capabilities the task requires.",
        check=_check_ecs_privileged_container,
    ),
]
