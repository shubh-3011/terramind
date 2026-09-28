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
    if len(terraform_files) > MAX_TERRAFORM_FILES:
        raise HTTPException(
            status_code=413,
            detail=f"Workspace has more than the supported limit of {MAX_TERRAFORM_FILES} Terraform files",
        )

    findings: list[Finding] = []
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
        findings.extend(_static_security_findings(document, source, relative_path))

    return AnalyzeResponse(
        status="completed",
        terraform_file_count=len(terraform_files),
        parsed_file_count=parsed_file_count,
        findings=findings,
        checks={
            "hcl_parse": "completed",
            "terraform_validate": "not_run: provider initialization and execution are not enabled",
            "tflint": "not_run: integration pending",
            "checkov": "not_run: integration pending",
            "ml_risk": "not_available: no trained model",
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
            for ingress in _as_block_list(attributes.get("ingress")):
                _check_public_ssh(ingress, file, source, findings, label)
        elif resource_type == "aws_security_group_rule":
            if str(attributes.get("type", "")).strip('"') == "ingress":
                _check_public_ssh(attributes, file, source, findings, label)

    # IAM document blocks commonly use plural HCL attributes; JSON-encoded
    # policies are inspected only when they are literal strings.
    for key, value in _walk(document):
        if key in {"action", "actions", "not_action", "not_actions"} and _contains_wildcard(value):
            findings.append(_finding(
                file,
                "TM-IAM-001",
                "warning",
                "IAM policy contains a wildcard action. Confirm the permissions are intentionally broad.",
                line=_line_containing(source, re.compile(r"\b(?:actions?|not_actions?)\b")),
                recommendation="Prefer the smallest action set required by the workload.",
            ))
            break
        if key == "policy" and isinstance(value, str):
            try:
                policy = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                continue
            statements = policy.get("Statement", []) if isinstance(policy, dict) else []
            if isinstance(statements, dict):
                statements = [statements]
            if any(_contains_wildcard(statement.get("Action")) for statement in statements if isinstance(statement, dict)):
                findings.append(_finding(
                    file,
                    "TM-IAM-001",
                    "warning",
                    "IAM policy contains a wildcard action. Confirm the permissions are intentionally broad.",
                    line=_line_containing(source, re.compile(r"\bpolicy\b")),
                    recommendation="Prefer the smallest action set required by the workload.",
                ))
                break
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
