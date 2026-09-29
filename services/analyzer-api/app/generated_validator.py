"""Run provider-schema validation on generated Terraform in an isolated scratch tree."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

TIMEOUT_SECONDS = 45
OUTPUT_LIMIT = 2_000_000
_CLOUD_PREFIXES = ("AWS_", "AZURE_", "ARM_", "GOOGLE_", "GCP_", "CLOUDSDK_", "VAULT_")
_SECRET_ENV_NAMES = {"GITHUB_TOKEN", "GH_TOKEN", "VAULT_TOKEN"}


def run_generated_terraform_validation(
    terraform_source: str,
    workspace_path: str | None,
) -> tuple[str, list[Any]]:
    """Validate against an existing provider cache without init, planning, or apply.

    Provider plugins execute during `terraform validate`; callers must make this
    opt-in and restrict it to workspaces they trust.
    """
    from app.main import Finding

    if not workspace_path:
        return "not_run: no workspace supplied", []
    workspace = Path(workspace_path).expanduser().resolve()
    if not workspace.is_dir():
        return "not_run: workspace is unavailable", []
    lockfile = workspace / ".terraform.lock.hcl"
    provider_cache = workspace / ".terraform" / "providers"
    if not lockfile.is_file() or not provider_cache.is_dir():
        return "not_run: pre-initialized provider cache not found", []
    terraform = os.environ.get("TERRAMIND_TERRAFORM_PATH") or shutil.which("terraform")
    if not terraform or not Path(terraform).expanduser().is_file():
        return "not_available: Terraform CLI is not installed", []

    command = [str(Path(terraform).resolve()), "validate", "-json"]
    findings: list[Finding] = []
    try:
        with tempfile.TemporaryDirectory(prefix="terramind-generated-validate-") as raw_sandbox:
            sandbox = Path(raw_sandbox)
            data_dir = sandbox / ".terraform"
            data_dir.mkdir()
            shutil.copy2(lockfile, sandbox / ".terraform.lock.hcl")
            shutil.copytree(provider_cache, data_dir / "providers", copy_function=_link_or_copy)
            (sandbox / "main.tf").write_text(terraform_source, encoding="utf-8", newline="\n")
            isolated_home = sandbox / "home"
            isolated_home.mkdir()
            env = _isolated_environment(isolated_home, data_dir)
            result = subprocess.run(
                [command[0], f"-chdir={sandbox}", *command[1:]],
                cwd=sandbox,
                env=env,
                shell=False,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=TIMEOUT_SECONDS,
            )
            parsed = _decode_json(result.stdout[:OUTPUT_LIMIT])
            if parsed is None:
                return "failed: Terraform returned invalid JSON", []
            diagnostics = parsed.get("diagnostics", [])
            diagnostics = diagnostics if isinstance(diagnostics, list) else []
            valid = bool(parsed.get("valid", result.returncode == 0))
            for index, diagnostic in enumerate(diagnostics):
                if not isinstance(diagnostic, dict):
                    continue
                source_range = diagnostic.get("range") or {}
                start = source_range.get("start") or {}
                line = start.get("line") if isinstance(start, dict) else None
                line = line if isinstance(line, int) and line > 0 else None
                summary = str(diagnostic.get("summary") or "Terraform validation diagnostic")
                detail = str(diagnostic.get("detail") or "")
                message = f"{summary}: {detail}" if detail else summary
                severity = "error" if diagnostic.get("severity") == "error" else "warning"
                findings.append(Finding(
                    id=f"main.tf:TF-VALIDATE:{line or 0}:{index}",
                    source="terraform-cli",
                    rule_id="TF-VALIDATE",
                    severity=severity,
                    message=message[:500],
                    file="main.tf",
                    line=line,
                    recommendation="Review this diagnostic against the selected workspace's installed Terraform provider versions.",
                ))
            error_count = sum(finding.severity == "error" for finding in findings)
            warning_count = len(findings) - error_count
            status = "passed" if valid else f"failed: {error_count} error(s), {warning_count} warning(s)"
            return status, findings
    except subprocess.TimeoutExpired:
        return f"failed: Terraform validate timed out after {TIMEOUT_SECONDS}s", []
    except (OSError, shutil.Error) as error:
        return f"not_run: could not prepare isolated validation workspace ({type(error).__name__})", []


def _link_or_copy(source: str, destination: str) -> str:
    """Avoid duplicating large provider binaries when scratch data shares a volume."""
    try:
        os.link(source, destination)
        return destination
    except OSError:
        return shutil.copy2(source, destination)


def _isolated_environment(home: Path, data_dir: Path) -> dict[str, str]:
    env = {
        key: value for key, value in os.environ.items()
        if not key.upper().startswith(("TF_", *_CLOUD_PREFIXES))
        and key.upper() not in _SECRET_ENV_NAMES
    }
    env["TF_DATA_DIR"] = str(data_dir)
    env["TF_IN_AUTOMATION"] = "1"
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["APPDATA"] = str(home)
    return env


def _decode_json(output: str) -> dict[str, Any] | None:
    try:
        value = json.loads(output)
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None
