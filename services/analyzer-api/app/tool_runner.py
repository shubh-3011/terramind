"""Opt-in, bounded static tooling integrations for Terraform workspaces."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from app.main import Finding

TIMEOUT_SECONDS = 45
OUTPUT_LIMIT = 2_000_000
_CLOUD_ENV_PREFIXES = ("AWS_", "AZURE_", "ARM_", "GOOGLE_", "GCP_")
_SECRET_ENV_NAMES = {"TF_TOKEN", "GITHUB_TOKEN", "GH_TOKEN", "VAULT_TOKEN"}


def run_static_tools(workspace: Path) -> tuple[list[Finding], dict[str, str]]:
    """Run installed static tools only; never initializes or plans a workspace."""
    findings: list[Finding] = []
    checks: dict[str, str] = {}
    tools = {
        "terraform_fmt": ("terraform", ["fmt", "-check", "-recursive", "-no-color"]),
        "tflint": ("tflint", ["--format=json", "--no-color"]),
        "checkov": ("checkov", ["-d", str(workspace), "--framework", "terraform", "-o", "json", "--quiet"]),
    }

    terraform_path = shutil.which("terraform")
    if terraform_path:
        fmt_result = _run([terraform_path, *tools["terraform_fmt"][1]], workspace)
        checks["terraform_fmt"] = "passed" if fmt_result.returncode == 0 else "failed: formatting changes required"
        if fmt_result.returncode != 0:
            for raw_path in fmt_result.stdout.splitlines():
                candidate = _relative_tool_path(raw_path.strip().lstrip("- "), workspace)
                if candidate:
                    findings.append(_tool_finding(
                        candidate, "TF-FMT-001", "warning",
                        "Terraform file is not formatted according to terraform fmt.", "terraform-cli",
                        "Run terraform fmt after reviewing the diff.",
                    ))

        if (workspace / ".terraform.lock.hcl").is_file() and (workspace / ".terraform" / "providers").is_dir():
            validate_result = _run([terraform_path, "validate", "-json"], workspace)
            parsed = _decode_json(validate_result.stdout)
            if parsed is None:
                checks["terraform_validate"] = "failed: Terraform returned invalid JSON"
            else:
                diagnostics = parsed.get("diagnostics", [])
                valid = bool(parsed.get("valid", validate_result.returncode == 0))
                checks["terraform_validate"] = "passed" if valid else "failed: invalid Terraform configuration"
                for item in diagnostics if isinstance(diagnostics, list) else []:
                    if not isinstance(item, dict):
                        continue
                    severity = "error" if item.get("severity") == "error" else "warning"
                    detail = str(item.get("detail") or item.get("summary") or "Terraform validation diagnostic")
                    source_range = item.get("range") or {}
                    filename = _relative_tool_path(str(source_range.get("filename", "")), workspace)
                    start = source_range.get("start") or {}
                    if filename:
                        findings.append(_tool_finding(
                            filename, "TF-VALIDATE", severity, detail[:500], "terraform-cli",
                            "Review the Terraform diagnostic and the installed provider/module versions.",
                            int(start["line"]) if isinstance(start.get("line"), int) else None,
                        ))
        else:
            checks["terraform_validate"] = "not_run: existing provider initialization not found; TerraMind never runs terraform init automatically"
    else:
        checks["terraform_fmt"] = "not_available: terraform CLI is not installed"
        checks["terraform_validate"] = "not_available: terraform CLI is not installed"

    tflint_path = shutil.which("tflint")
    if tflint_path:
        result = _run([tflint_path, *tools["tflint"][1]], workspace)
        parsed = _decode_json(result.stdout)
        if parsed is None:
            checks["tflint"] = "failed: TFLint returned invalid JSON"
        else:
            issues = parsed.get("issues", [])
            checks["tflint"] = "passed" if not issues and result.returncode == 0 else f"completed: {len(issues)} issue(s)"
            for item in issues if isinstance(issues, list) else []:
                if not isinstance(item, dict):
                    continue
                rule = item.get("rule") or {}
                source_range = item.get("range") or {}
                start = source_range.get("start") or {}
                filename = _relative_tool_path(str(source_range.get("filename", "")), workspace)
                if filename:
                    severity = "error" if str(item.get("severity", "")).upper() == "ERROR" else "warning"
                    findings.append(_tool_finding(
                        filename, f"TFLINT-{str(rule.get('name') or 'ISSUE')[:80]}", severity,
                        str(item.get("message") or "TFLint issue")[:500], "tflint",
                        "Review this TFLint diagnostic and the matching rule documentation.",
                        int(start["line"]) if isinstance(start.get("line"), int) else None,
                    ))
    else:
        checks["tflint"] = "not_available: TFLint is not installed"

    checkov_path = shutil.which("checkov")
    if checkov_path:
        result = _run([checkov_path, *tools["checkov"][1]], workspace)
        parsed = _decode_json(result.stdout)
        if parsed is None:
            checks["checkov"] = "failed: Checkov returned invalid JSON"
        else:
            results = parsed.get("results") or {}
            failed = results.get("failed_checks", []) if isinstance(results, dict) else []
            checks["checkov"] = "passed" if not failed and result.returncode == 0 else f"completed: {len(failed)} failed check(s)"
            for item in failed if isinstance(failed, list) else []:
                if not isinstance(item, dict):
                    continue
                filename = _relative_tool_path(str(item.get("file_path") or ""), workspace)
                if filename:
                    severity_value = str(item.get("severity") or "MEDIUM").upper()
                    severity = "error" if severity_value in {"CRITICAL", "HIGH"} else "warning"
                    line_range = item.get("file_line_range") or []
                    line = line_range[0] if line_range and isinstance(line_range[0], int) else None
                    findings.append(_tool_finding(
                        filename, str(item.get("check_id") or "CHECKOV")[:100], severity,
                        str(item.get("check_name") or item.get("guideline") or "Checkov finding")[:500], "checkov",
                        str(item.get("guideline") or "Review this Checkov finding and its framework guidance.")[:500],
                        line,
                    ))
    else:
        checks["checkov"] = "not_available: Checkov is not installed"

    return findings, checks


def _run(command: list[str], workspace: Path) -> subprocess.CompletedProcess[str]:
    env = {
        key: value for key, value in os.environ.items()
        if key.upper() not in {"TF_CLI_CONFIG_FILE", *_SECRET_ENV_NAMES}
        and not key.upper().startswith(("TF_TOKEN_", "TF_VAR_"))
        and not key.upper().startswith(_CLOUD_ENV_PREFIXES)
    }
    env["TF_IN_AUTOMATION"] = "1"
    env["CHECKOV_DISABLE_TELEMETRY"] = "1"
    env["DO_NOT_TRACK"] = "1"
    with tempfile.TemporaryDirectory(prefix="terramind-tools-") as isolated_home:
        env["HOME"] = isolated_home
        env["USERPROFILE"] = isolated_home
        env["APPDATA"] = isolated_home
        try:
            result = subprocess.run(
                command, cwd=workspace, env=env, shell=False, check=False,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as error:
            return subprocess.CompletedProcess(command, 124, str(error.stdout or "")[:OUTPUT_LIMIT], "Tool timed out")
    return subprocess.CompletedProcess(
        command, result.returncode, result.stdout[:OUTPUT_LIMIT], result.stderr[:OUTPUT_LIMIT]
    )


def _decode_json(output: str) -> dict[str, Any] | None:
    try:
        value = json.loads(output)
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _relative_tool_path(raw_path: str, workspace: Path) -> str | None:
    if not raw_path:
        return None
    normalized = raw_path.strip().strip('"')
    try:
        candidate = Path(normalized)
        if not candidate.is_absolute():
            candidate = workspace / candidate
        resolved = candidate.resolve(strict=False)
        return resolved.relative_to(workspace).as_posix()
    except (OSError, ValueError):
        return None


def _tool_finding(
    file: str, rule_id: str, severity: str, message: str, source: str,
    recommendation: str, line: int | None = None,
) -> Finding:
    return Finding(
        id=f"{file}:{rule_id}:{line or 0}", source=source, rule_id=rule_id,
        severity=severity, message=message, file=file, line=line,
        recommendation=recommendation,
    )
