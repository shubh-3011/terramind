import json
import subprocess

from app.generated_validator import run_generated_terraform_validation


def test_generated_validation_uses_cached_providers_without_init(tmp_path, monkeypatch):
    workspace = tmp_path / "trusted-workspace"
    provider = workspace / ".terraform" / "providers" / "registry.terraform.io" / "hashicorp" / "aws" / "6.66.0" / "windows_amd64"
    provider.mkdir(parents=True)
    (workspace / ".terraform.lock.hcl").write_text("provider lock", encoding="utf-8")
    (provider / "terraform-provider-aws.exe").write_bytes(b"provider fixture")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "must-not-reach-provider")
    monkeypatch.setenv("TF_VAR_password", "must-not-reach-provider")
    calls = []
    sandbox_was_prepared = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        sandbox_was_prepared.append(
            (kwargs["cwd"] / ".terraform.lock.hcl").is_file()
            and (kwargs["cwd"] / "main.tf").is_file()
            and (kwargs["cwd"] / ".terraform" / "providers").is_dir()
        )
        output = json.dumps({
            "valid": False,
            "diagnostics": [{
                "severity": "error",
                "summary": "Unsupported argument",
                "detail": "The provider schema rejects this argument.",
                "range": {"filename": "main.tf", "start": {"line": 7}},
            }],
        })
        return subprocess.CompletedProcess(command, 1, output, "")

    terraform_executable = tmp_path / "terraform.exe"
    terraform_executable.write_bytes(b"terraform fixture")
    monkeypatch.setattr("app.generated_validator.shutil.which", lambda _name: str(terraform_executable))
    monkeypatch.setattr("app.generated_validator.subprocess.run", fake_run)

    status, findings = run_generated_terraform_validation(
        'resource "aws_s3_bucket" "example" { invalid_argument = true }', str(workspace),
    )

    assert status == "failed: 1 error(s), 0 warning(s)"
    assert findings[0].rule_id == "TF-VALIDATE"
    assert findings[0].line == 7
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert "validate" in command
    assert "init" not in command and "plan" not in command and "apply" not in command
    assert kwargs["shell"] is False
    assert kwargs["env"]["TF_DATA_DIR"].endswith(".terraform")
    assert "AWS_ACCESS_KEY_ID" not in kwargs["env"]
    assert "TF_VAR_password" not in kwargs["env"]
    assert sandbox_was_prepared == [True]
    assert not kwargs["cwd"].exists()


def test_generated_validation_is_not_run_without_lock_and_provider_cache(tmp_path, monkeypatch):
    monkeypatch.setattr("app.generated_validator.shutil.which", lambda _name: "C:/tools/terraform.exe")
    monkeypatch.setattr(
        "app.generated_validator.subprocess.run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Terraform must not run without an initialized cache")),
    )

    status, findings = run_generated_terraform_validation("terraform {}", str(tmp_path))

    assert status == "not_run: pre-initialized provider cache not found"
    assert findings == []
