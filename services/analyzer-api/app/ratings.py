"""Evidence-limited service ratings; unknown dimensions stay explicitly unknown."""

from __future__ import annotations

from collections import Counter
from typing import Any


_SERVICE_RULES = {
    "networking": ("TM-NET-",),
    "iam": ("TM-IAM-",),
    "s3": ("TM-S3-",),
    "ecr": ("TM-ECR-",),
    "compute": ("TM-EC2-", "TM-EBS-"),
    "storage": ("TM-EBS-",),
}


def build_service_ratings(documents: list[dict[str, Any]], findings: list[Any]) -> list[dict[str, Any]]:
    """Return scoped evidence summaries, never guessed uptime/cost scores."""
    service_counts: Counter[str] = Counter()
    for document in documents:
        for block in document.get("resource", []) if isinstance(document.get("resource", []), list) else []:
            if not isinstance(block, dict):
                continue
            for resource_type, resources in block.items():
                if not str(resource_type).startswith("aws_") or not isinstance(resources, dict):
                    continue
                service_counts[_service_for_resource(str(resource_type))] += len(resources)

    results: list[dict[str, Any]] = []
    for service, count in sorted(service_counts.items()):
        prefixes = _SERVICE_RULES.get(service, ())
        relevant = [
            item for item in findings
            if getattr(item, "source", "") == "terramind-rules"
            and any(str(getattr(item, "rule_id", "")).startswith(prefix) for prefix in prefixes)
        ]
        if relevant:
            penalty = sum(
                {"error": 35, "warning": 15, "information": 5}.get(
                    str(getattr(item, "severity", "information")), 5
                )
                for item in relevant
            )
            security = {
                "score": max(0, 100 - penalty),
                "status": "limited",
                "criteria_version": "observed-static-findings-v1",
                "evidence_finding_ids": [item.id for item in relevant],
                "summary": "Penalty-based summary of observed TerraMind static security findings only.",
                "limitations": [
                    "This is not a security certification; rules cover only a small subset of Terraform/AWS risks.",
                    "No finding means only that the implemented checks did not report one.",
                ],
            }
        else:
            security = {
                "score": None,
                "status": "insufficient_information",
                "criteria_version": "observed-static-findings-v1",
                "evidence_finding_ids": [],
                "summary": "No service-specific evidence from the current static rules is available.",
                "limitations": ["Enable trusted external scanners and expand service coverage before interpreting security posture."],
            }

        results.append({
            "service": service,
            "resource_count": count,
            "dimensions": {
                "security": security,
                "reliability": _unknown("Reliability requires an availability target, deployment topology, and runtime/health evidence."),
                "scalability": _unknown("Scalability requires workload, traffic, and capacity assumptions."),
                "cost": _unknown("Cost requires region, usage, pricing date, and a provider pricing estimator."),
                "maintainability": _unknown("Maintainability scoring needs a reviewed rubric and module/reference analysis."),
            },
        })
    return results


def _unknown(summary: str) -> dict[str, Any]:
    return {
        "score": None,
        "status": "insufficient_information",
        "criteria_version": "not_scored",
        "evidence_finding_ids": [],
        "summary": summary,
        "limitations": [],
    }


def _service_for_resource(resource_type: str) -> str:
    if resource_type.startswith("aws_s3_"):
        return "s3"
    if resource_type.startswith("aws_iam_"):
        return "iam"
    if resource_type.startswith("aws_ecr_"):
        return "ecr"
    if resource_type.startswith(("aws_ebs_", "aws_efs_")):
        return "storage"
    if resource_type.startswith(("aws_security_group", "aws_subnet", "aws_vpc", "aws_route", "aws_network_acl")):
        return "networking"
    if resource_type.startswith(("aws_instance", "aws_launch_", "aws_autoscaling_", "aws_ecs_", "aws_eks_", "aws_lambda_")):
        return "compute"
    if resource_type.startswith(("aws_db_", "aws_rds_")):
        return "database"
    return "other"
