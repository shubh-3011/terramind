"""Local, deterministic first-pass analysis for Terraform workspaces.

This module deliberately does not invoke Terraform providers or initialize a
workspace. HCL parsing and the small rule set are static checks only.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Literal

import hcl2
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from terramind_ml.features import expand_dynamic_ingress, extract_features
from terramind_ml.predictor import predict_risk

app = FastAPI(title="TerraMind Analyzer", version="0.1.0")

MAX_TERRAFORM_FILES = 500
MAX_FILE_BYTES = 1_000_000


class AnalyzeRequest(BaseModel):
    """A request to statically inspect one local Terraform workspace."""

    workspace_path: str = Field(min_length=1, max_length=4096)


class Finding(BaseModel):
    """A stable, navigable finding; scanner/model results use distinct sources."""

    id: str
    source: Literal["hcl-parser", "terramind-rules"]
    rule_id: str
    severity: Literal["error", "warning", "information"]
    message: str
    file: str
    line: int | None = None
    recommendation: str | None = None


class AnalyzeResponse(BaseModel):
    status: Literal["completed"]
    terraform_file_count: int
    parsed_file_count: int
    findings: list[Finding]
    risk_prediction: dict[str, Any] | None
    risk_prediction_reason: str | None
    checks: dict[str, str]


@app.get("/health")
def health() -> dict[str, str]:
    """Return service availability without touching a workspace."""
    return {"status": "ok"}


@app.post("/v1/analyze", response_model=AnalyzeResponse)
def analyze_workspace(request: AnalyzeRequest) -> AnalyzeResponse:
    """Parse Terraform HCL and report a deliberately small first set of rules."""
    workspace = Path(request.workspace_path).expanduser().resolve()
    if not workspace.is_dir():
        raise HTTPException(status_code=400, detail="workspace_path must be an existing directory")

    terraform_files = _discover_terraform_files(workspace)

    findings: list[Finding] = []
    parsed_documents: list[dict[str, Any]] = []
    parsed_sources: list[str] = []
    parsed_file_count = 0
    for file_path in terraform_files:
        relative_path = file_path.relative_to(workspace).as_posix()
        try:
            if file_path.stat().st_size > MAX_FILE_BYTES:
                findings.append(_finding(
                    relative_path,
                    "TM-HCL-002",
                    "warning",
                    f"File exceeds the {MAX_FILE_BYTES // 1_000_000} MB analysis limit and was skipped.",
                    source="hcl-parser",
                ))
                continue
            source = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            findings.append(_finding(
                relative_path,
                "TM-HCL-003",
                "error",
                f"Could not read Terraform file: {error}",
                source="hcl-parser",
            ))
            continue

        try:
            document = hcl2.loads(source)
        except Exception as error:  # parser exceptions vary by python-hcl2 version
            findings.append(_finding(
                relative_path,
                "TM-HCL-001",
                "error",
                _parse_error_message(error),
                source="hcl-parser",
                line=_parse_error_line(error),
            ))
            continue

        parsed_file_count += 1
        parsed_documents.append(document)
        parsed_sources.append(source)
        findings.extend(_static_security_findings(document, source, relative_path))

    risk_prediction: dict[str, Any] | None = None
    if not terraform_files:
        risk_prediction_reason = "No Terraform files were found."
    elif parsed_file_count != len(terraform_files):
        risk_prediction_reason = "Risk estimate unavailable because one or more Terraform files could not be parsed or read."
    else:
        risk_prediction = predict_risk(extract_features(parsed_documents, parsed_sources))
        risk_prediction_reason = None if risk_prediction else "No compatible trained risk model is available."

    return AnalyzeResponse(
        status="completed",
        terraform_file_count=len(terraform_files),
        parsed_file_count=parsed_file_count,
        findings=findings,
        risk_prediction=risk_prediction,
        risk_prediction_reason=risk_prediction_reason,
        checks={
            "hcl_parse": "completed",
            "terraform_validate": "not_run: provider initialization and execution are not enabled",
            "tflint": "not_run: integration pending",
            "checkov": "not_run: integration pending",
            "ml_risk": f"experimental: {risk_prediction['model_version']}" if risk_prediction else "not_available: " + str(risk_prediction_reason),
        },
    )


def _discover_terraform_files(workspace: Path) -> list[Path]:
    """Discover .tf files without following symlinks outside the workspace."""
    files: list[Path] = []
    for current, directories, names in os.walk(workspace, topdown=True, followlinks=False):
        directories[:] = [
            name for name in directories
            if name not in {".terraform", ".git", "node_modules"}
            and not (Path(current) / name).is_symlink()
        ]
        for name in names:
            if not name.endswith(".tf"):
                continue
            path = Path(current) / name
            try:
                resolved = path.resolve(strict=True)
                if not resolved.is_relative_to(workspace) or not resolved.is_file():
                    continue
            except (OSError, ValueError):
                continue
            files.append(resolved)
            if len(files) > MAX_TERRAFORM_FILES:
                raise HTTPException(
                    status_code=413,
                    detail=f"Workspace has more than the supported limit of {MAX_TERRAFORM_FILES} Terraform files",
                )
    return sorted(set(files), key=lambda item: item.as_posix().casefold())


def _static_security_findings(document: dict[str, Any], source: str, file: str) -> list[Finding]:
    findings: list[Finding] = []
    for resource_type, attributes, label in _resources(document):
        if resource_type == "aws_security_group":
            dynamic_ingress, unresolved_dynamic = expand_dynamic_ingress(document, attributes)
            for ingress in [*_as_block_list(attributes.get("ingress")), *dynamic_ingress]:
                _check_public_ssh(ingress, file, source, findings, label)
            if unresolved_dynamic:
                findings.append(_finding(
                    file,
                    "TM-NET-003",
                    "information",
                    f"Security group '{label}' uses dynamic ingress that could not be fully resolved statically.",
                    line=_line_containing(source, re.compile(r"\bdynamic\s+\"ingress\"|\bfor_each\b")),
                    recommendation="Review every expanded ingress rule and its variable/local inputs; static analysis cannot determine their effective CIDRs.",
                ))
        elif resource_type == "aws_security_group_rule":
            if str(attributes.get("type", "")).strip('"') == "ingress":
                _check_public_ssh(attributes, file, source, findings, label)
        elif resource_type == "aws_s3_bucket_public_access_block":
            protection_flags = (
                "block_public_acls", "block_public_policy", "ignore_public_acls", "restrict_public_buckets",
            )
            disabled_flags = [flag for flag in protection_flags if _is_disabled(attributes.get(flag))]
            if disabled_flags:
                findings.append(_finding(
                    file,
                    "TM-S3-001",
                    "warning",
                    f"S3 public-access protections are disabled: {', '.join(disabled_flags)}.",
                    line=_line_containing(source, re.compile(r"\b(?:block_public|ignore_public|restrict_public)")),
                    recommendation="Enable all four S3 public-access-block protections unless an approved exception requires otherwise.",
                ))
        elif resource_type in {"aws_s3_bucket", "aws_s3_bucket_acl"}:
            acl = str(attributes.get("acl", "")).strip('"').lower()
            if acl in {"public-read", "public-read-write", "authenticated-read"}:
                findings.append(_finding(
                    file,
                    "TM-S3-002",
                    "error",
                    f"S3 resource '{label}' uses the public ACL '{acl}'.",
                    line=_line_containing(source, re.compile(r"\bacl\s*=")),
                    recommendation="Avoid public ACLs; use a reviewed bucket policy and keep S3 Block Public Access enabled.",
                ))
        elif resource_type == "aws_ecr_repository":
            mutability = str(attributes.get("image_tag_mutability", "")).strip('"').upper()
            if mutability == "MUTABLE":
                findings.append(_finding(
                    file,
                    "TM-ECR-001",
                    "warning",
                    f"ECR repository '{label}' allows mutable image tags.",
                    line=_line_containing(source, re.compile(r"\bimage_tag_mutability\s*=")),
                    recommendation="Consider immutable tags to reduce the risk of replacing an image behind an existing tag.",
                ))
        elif resource_type in {"aws_instance", "aws_launch_template"}:
            for metadata_options in _as_block_list(attributes.get("metadata_options")):
                if str(metadata_options.get("http_tokens", "")).strip('"').lower() == "optional":
                    findings.append(_finding(
                        file,
                        "TM-EC2-001",
                        "warning",
                        f"Compute resource '{label}' does not require IMDSv2 tokens.",
                        line=_line_containing(source, re.compile(r"\bhttp_tokens\s*=")),
                        recommendation="Set metadata_options.http_tokens to required when compatible with the workload.",
                    ))
        if resource_type in {"aws_ebs_volume", "aws_instance", "aws_launch_configuration", "aws_launch_template"}:
            if attributes.get("encrypted") is False:
                findings.append(_finding(
                    file,
                    "TM-EBS-001",
                    "warning",
                    f"Storage attached to '{label}' explicitly disables encryption.",
                    line=_line_containing(source, re.compile(r"\bencrypted\s*=\s*false\b")),
                    recommendation="Enable EBS encryption and confirm the selected KMS key and account defaults.",
                ))

    # IAM document blocks commonly use plural HCL attributes; JSON-encoded
    # policies are inspected only when they are literal strings.
    wildcard_actions = False
    wildcard_resources = False
    for key, value in _walk(document):
        if key in {"action", "actions", "not_action", "not_actions"}:
            wildcard_actions |= _contains_wildcard(value)
        if key in {"resource", "resources"}:
            wildcard_resources |= _contains_wildcard(value)
        if key == "policy" and isinstance(value, str):
            try:
                policy = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                continue
            statements = policy.get("Statement", []) if isinstance(policy, dict) else []
            if isinstance(statements, dict):
                statements = [statements]
            wildcard_actions |= any(
                _contains_wildcard(statement.get("Action"))
                for statement in statements if isinstance(statement, dict)
            )
            wildcard_resources |= any(
                _contains_wildcard(statement.get("Resource"))
                for statement in statements if isinstance(statement, dict)
            )
    if wildcard_actions:
        findings.append(_finding(
            file,
            "TM-IAM-001",
            "warning",
            "IAM policy contains a wildcard action. Confirm the permissions are intentionally broad.",
            line=_line_containing(source, re.compile(r"\b(?:actions?|not_actions?)\b")),
            recommendation="Prefer the smallest action set required by the workload.",
        ))
    if wildcard_resources:
        findings.append(_finding(
            file,
            "TM-IAM-002",
            "warning",
            "IAM policy contains a wildcard resource target. Confirm the policy scope is intentionally broad.",
            line=_line_containing(source, re.compile(r"\bresources?\b")),
            recommendation="Restrict Resource to the smallest set of ARNs required by the workload.",
        ))
    return findings


def _resources(document: dict[str, Any]):
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
                    yield str(resource_type), attributes, str(label)


def _as_block_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _check_public_ssh(
    ingress: dict[str, Any], file: str, source: str,
    findings: list[Finding], label: str,
) -> None:
    try:
        from_port = int(str(ingress.get("from_port", "")).strip('"'))
        to_port = int(str(ingress.get("to_port", "")).strip('"'))
    except (TypeError, ValueError):
        return
    if from_port > 22 or to_port < 22:
        return
    ranges = ingress.get("cidr_blocks", [])
    ipv6_ranges = ingress.get("ipv6_cidr_blocks", [])
    if not isinstance(ranges, list):
        ranges = [ranges]
    if not isinstance(ipv6_ranges, list):
        ipv6_ranges = [ipv6_ranges]
    if not any(str(value).strip('"') == "0.0.0.0/0" for value in ranges) and not any(
        str(value).strip('"') == "::/0" for value in ipv6_ranges
    ):
        return
    findings.append(_finding(
        file,
        "TM-NET-001",
        "error",
        f"Ingress rule '{label}' exposes SSH (port 22) to the public internet.",
        line=_line_containing(source, re.compile(r"\b(?:from_port|22)\b")),
        recommendation="Restrict SSH to a trusted CIDR or use a managed access path such as Systems Manager.",
    ))


def _walk(value: Any):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key).lower(), child
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _contains_wildcard(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip('"') == "*"
    if isinstance(value, list):
        return any(_contains_wildcard(item) for item in value)
    return False


def _is_disabled(value: Any) -> bool:
    return value is False or value == 0 or value == "false"


def _finding(
    file: str,
    rule_id: str,
    severity: Literal["error", "warning", "information"],
    message: str,
    *,
    source: Literal["hcl-parser", "terramind-rules"] = "terramind-rules",
    line: int | None = None,
    recommendation: str | None = None,
) -> Finding:
    return Finding(
        id=f"{file}:{rule_id}:{line or 0}", source=source, rule_id=rule_id,
        severity=severity, message=message, file=file, line=line,
        recommendation=recommendation,
    )


def _parse_error_line(error: Exception) -> int | None:
    match = re.search(r"line\s+(\d+)", str(error), re.IGNORECASE)
    return int(match.group(1)) if match else None


def _parse_error_message(error: Exception) -> str:
    message = str(error).splitlines()[0].strip()
    return f"Terraform HCL syntax could not be parsed: {message[:300]}"


def _line_containing(source: str, pattern: re.Pattern[str]) -> int | None:
    for line_number, line in enumerate(source.splitlines(), start=1):
        if pattern.search(line):
            return line_number
    return None
