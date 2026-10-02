from fastapi.testclient import TestClient
from unittest.mock import patch
import json
import time

import pytest

from app.main import _transformers_max_new_tokens, app
from terramind_ml.features import extract_features
import hcl2

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolate_bundled_model(monkeypatch):
    """Keep tests deterministic: do not let a locally installed GGUF change the
    default engine. Tests that exercise GGUF set TERRAMIND_GGUF_MODEL explicitly."""
    monkeypatch.setenv("TERRAMIND_DISABLE_BUNDLED_MODEL", "1")
    monkeypatch.delenv("TERRAMIND_GGUF_MODEL", raising=False)


def test_transformers_generation_token_limit_is_bounded_and_configurable():
    with patch.dict("os.environ", {}, clear=True):
        assert _transformers_max_new_tokens() == 2048
    with patch.dict("os.environ", {"TERRAMIND_HF_MAX_NEW_TOKENS": "4096"}):
        assert _transformers_max_new_tokens() == 2048
    with patch.dict("os.environ", {"TERRAMIND_HF_MAX_NEW_TOKENS": "8"}):
        assert _transformers_max_new_tokens() == 128
    with patch.dict("os.environ", {"TERRAMIND_HF_MAX_NEW_TOKENS": "invalid"}):
        assert _transformers_max_new_tokens() == 2048


def test_analyze_parses_hcl_and_reports_public_ssh(tmp_path):
    (tmp_path / "main.tf").write_text(
        '''resource "aws_security_group" "web" {
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
''',
        encoding="utf-8",
    )

    response = client.post("/v1/analyze", json={"workspace_path": str(tmp_path)})

    assert response.status_code == 200
    report = response.json()
    assert report["status"] == "completed"
    assert report["terraform_file_count"] == 1
    assert report["parsed_file_count"] == 1
    assert report["findings"][0]["rule_id"] == "TM-NET-001"
    assert report["findings"][0]["severity"] == "error"
    assert report["checks"]["terraform_validate"].startswith("not_run:")
    assert report["risk_prediction"]["source"] == "experimental-ml"
    assert report["risk_prediction"]["calibrated"] is False


def test_analyze_reports_hcl_syntax_error_and_continues(tmp_path):
    (tmp_path / "broken.tf").write_text('resource "aws_instance" {\n', encoding="utf-8")
    (tmp_path / "valid.tf").write_text('terraform {\n  required_version = ">= 1.5"\n}\n', encoding="utf-8")

    response = client.post("/v1/analyze", json={"workspace_path": str(tmp_path)})

    assert response.status_code == 200
    report = response.json()
    assert report["terraform_file_count"] == 2
    assert report["parsed_file_count"] == 1
    assert any(item["rule_id"] == "TM-HCL-001" for item in report["findings"])


def test_analyze_reports_wildcard_iam_action(tmp_path):
    (tmp_path / "iam.tf").write_text(
        '''data "aws_iam_policy_document" "broad" {
  statement {
    actions   = ["*"]
    resources = ["*"]
  }
}
''',
        encoding="utf-8",
    )

    response = client.post("/v1/analyze", json={"workspace_path": str(tmp_path)})

    assert response.status_code == 200
    rule_ids = {item["rule_id"] for item in response.json()["findings"]}
    assert {"TM-IAM-001", "TM-IAM-002"}.issubset(rule_ids)


def test_analyze_does_not_flag_public_https_as_public_ssh(tmp_path):
    (tmp_path / "network.tf").write_text(
        '''resource "aws_security_group" "web" {
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
''',
        encoding="utf-8",
    )

    response = client.post("/v1/analyze", json={"workspace_path": str(tmp_path)})

    assert response.status_code == 200
    assert response.json()["findings"] == []


def test_analyze_flags_weak_aws_defaults(tmp_path):
    (tmp_path / "aws.tf").write_text(
        '''resource "aws_s3_bucket_public_access_block" "example" {
  bucket                  = "example"
  block_public_acls       = false
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_ecr_repository" "images" {
  name                 = "images"
  image_tag_mutability = "MUTABLE"
}

resource "aws_instance" "web" {
  ami           = "ami-12345678"
  instance_type = "t3.micro"

  metadata_options {
    http_tokens = "optional"
  }
}
''',
        encoding="utf-8",
    )

    response = client.post("/v1/analyze", json={"workspace_path": str(tmp_path)})

    assert response.status_code == 200
    rule_ids = {finding["rule_id"] for finding in response.json()["findings"]}
    assert {"TM-S3-001", "TM-ECR-001", "TM-EC2-001"}.issubset(rule_ids)


def test_analyze_resolves_dynamic_public_ssh_from_literal_local(tmp_path):
    (tmp_path / "network.tf").write_text(
        '''locals {
  ingress_cidrs = ["0.0.0.0/0"]
}

resource "aws_security_group" "web" {
  dynamic "ingress" {
    for_each = local.ingress_cidrs
    content {
      from_port   = 22
      to_port     = 22
      protocol    = "tcp"
      cidr_blocks = [ingress.value]
    }
  }
}
''',
        encoding="utf-8",
    )

    response = client.post("/v1/analyze", json={"workspace_path": str(tmp_path)})

    assert response.status_code == 200
    report = response.json()
    assert any(item["rule_id"] == "TM-NET-001" for item in report["findings"])
    document = hcl2.loads((tmp_path / "network.tf").read_text(encoding="utf-8"))
    assert extract_features([document], [(tmp_path / "network.tf").read_text(encoding="utf-8")])["public_ssh_ingress_count"] == 1


def test_analyze_marks_unresolved_dynamic_ingress_for_review(tmp_path):
    (tmp_path / "network.tf").write_text(
        '''resource "aws_security_group" "web" {
  dynamic "ingress" {
    for_each = var.ingress_rules
    content {
      from_port = 22
      to_port = 22
    }
  }
}
''',
        encoding="utf-8",
    )

    response = client.post("/v1/analyze", json={"workspace_path": str(tmp_path)})

    assert response.status_code == 200
    assert any(item["rule_id"] == "TM-NET-003" for item in response.json()["findings"])


def test_analyze_enforces_workspace_file_limit(tmp_path):
    for index in range(501):
        (tmp_path / f"resource-{index}.tf").touch()

    response = client.post("/v1/analyze", json={"workspace_path": str(tmp_path)})

    assert response.status_code == 413


def test_analyze_rejects_missing_workspace(tmp_path):
    response = client.post("/v1/analyze", json={"workspace_path": str(tmp_path / "missing")})
    assert response.status_code == 400


def test_generate_returns_parseable_hcl_without_writing_files(tmp_path):
    class OllamaResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return json.dumps({
                "model": "qwen2.5-coder:3b",
                "response": 'terraform { required_version = ">= 1.5" }',
            }).encode("utf-8")

    class OllamaOpener:
        def open(self, *_args, **_kwargs):
            return OllamaResponse()

    with patch("app.main.urllib.request.build_opener", return_value=OllamaOpener()):
        response = client.post("/v1/generate", json={"description": "Create a private S3 bucket"})

    assert response.status_code == 200
    assert response.json()["syntax_valid"] is True
    assert response.json()["model"] == "qwen2.5-coder:3b"
    assert "does not verify" in response.json()["validation_scope"]
    assert list(tmp_path.iterdir()) == []


def test_generate_runs_static_security_checks_before_preview():
    generated_hcl = '''resource "aws_security_group" "web" {
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
'''

    class OllamaResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return json.dumps({"model": "test-model", "response": generated_hcl}).encode("utf-8")

    class OllamaOpener:
        def open(self, *_args, **_kwargs):
            return OllamaResponse()

    with patch("app.main.urllib.request.build_opener", return_value=OllamaOpener()):
        response = client.post("/v1/generate", json={"description": "Create a web server"})

    assert response.status_code == 200
    generated = response.json()
    assert any(finding["rule_id"] == "TM-NET-001" for finding in generated["findings"])
    networking = next(rating for rating in generated["service_ratings"] if rating["service"] == "networking")
    assert networking["dimensions"]["security"]["score"] == 65
    assert "static security heuristics only" in generated["validation_scope"]


def test_generate_includes_structured_inventory_and_topology_in_model_prompt():
    with patch("app.main._generate_with_ollama", return_value=("test-model", 'resource "aws_s3_bucket" "data" {}')) as generate:
        response = client.post("/v1/generate", json={
            "description": "Build a small application environment",
            "resource_inventory": "2 EC2 instances, 1 VPC, 1 S3 bucket",
            "connectivity": "Instances stay in private subnets and read from the bucket",
            "constraints": "ap-south-1; no public SSH",
            "engine": "ollama",
        })

    assert response.status_code == 200
    prompt = generate.call_args.args[2]
    assert "Requested resources and counts:\n2 EC2 instances, 1 VPC, 1 S3 bucket" in prompt
    assert "Requested connections and traffic flow:\nInstances stay in private subnets and read from the bucket" in prompt
    assert "Other constraints:\nap-south-1; no public SSH" in prompt


def test_auto_prefers_the_scaffolder_when_an_inventory_is_provided():
    # With a structured inventory and no forced engine, TerraMind scaffolds
    # deterministically instead of calling the language model.
    with patch("app.main._generate_with_ollama") as generate:
        response = client.post("/v1/generate", json={
            "description": "A private S3 bucket with encryption",
            "resource_inventory": "1 S3 bucket",
        })

    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "scaffold"
    assert body["checks"]["generation_engine"] == "scaffold"
    assert 'resource "aws_s3_bucket"' in body["terraform"]
    assert "aws_s3_bucket_server_side_encryption_configuration" in body["terraform"]
    generate.assert_not_called()


def test_explicit_scaffold_engine_rejects_unrecognised_request():
    response = client.post("/v1/generate", json={
        "description": "a small production environment",
        "engine": "scaffold",
    })
    assert response.status_code == 422


def test_repair_returns_validated_proposal_without_writing_workspace(tmp_path):
    original = 'resource "aws_security_group" "web" { ingress { cidr_blocks = ["0.0.0.0/0"] } }'
    proposed = 'resource "aws_security_group" "web" { ingress { cidr_blocks = ["192.0.2.0/24"] } }'
    with patch("app.main._generate_with_ollama", return_value=("test-model", proposed)) as generate:
        response = client.post("/v1/repair", json={
            "terraform": original,
            "findings": ["TM-NET-001: ingress is open to the public"],
            "instructions": "Restrict to the approved office range",
            "workspace_path": str(tmp_path),
        })

    assert response.status_code == 200
    assert response.json()["terraform"] == proposed
    assert response.json()["syntax_valid"] is True
    prompt = generate.call_args.args[2]
    assert "TM-NET-001: ingress is open to the public" in prompt
    assert json.dumps(original) in prompt
    assert "Restrict to the approved office range" in prompt
    assert list(tmp_path.iterdir()) == []


def test_repair_rejects_unparseable_proposal():
    with patch("app.main._generate_with_ollama", return_value=("test-model", "resource { broken")):
        response = client.post("/v1/repair", json={
            "terraform": 'resource "aws_s3_bucket" "data" {}',
            "findings": ["Fix the missing configuration"],
        })

    assert response.status_code == 422
    assert "not parseable HCL" in response.json()["detail"]


def test_generate_can_opt_into_cached_provider_validation(tmp_path):
    from app.main import Finding

    validation_finding = Finding(
        id="main.tf:TF-VALIDATE:4:0", source="terraform-cli", rule_id="TF-VALIDATE",
        severity="error", message="Unsupported argument", file="main.tf", line=4,
    )
    class OllamaResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return json.dumps({
                "model": "test-model",
                "response": 'resource "aws_s3_bucket" "example" { invalid_argument = true }',
            }).encode("utf-8")

    class OllamaOpener:
        def open(self, *_args, **_kwargs):
            return OllamaResponse()

    with patch("app.main.urllib.request.build_opener", return_value=OllamaOpener()), patch(
        "app.generated_validator.run_generated_terraform_validation",
        return_value=("failed: 1 error(s), 0 warning(s)", [validation_finding]),
    ) as validate:
        response = client.post("/v1/generate", json={
            "description": "Create a private S3 bucket",
            "workspace_path": str(tmp_path),
            "run_external_tools": True,
            "workspace_trusted": True,
        })

    assert response.status_code == 200
    generated = response.json()
    assert generated["checks"]["terraform_validate"] == "failed: 1 error(s), 0 warning(s)"
    assert any(finding["rule_id"] == "TF-VALIDATE" for finding in generated["findings"])
    assert validate.call_count == 2
    assert validate.call_args.args[1] == str(tmp_path)


def test_generate_skips_provider_plugins_for_untrusted_workspace(tmp_path):
    class OllamaResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return json.dumps({
                "model": "test-model",
                "response": 'resource "aws_s3_bucket" "example" {}',
            }).encode("utf-8")

    class OllamaOpener:
        def open(self, *_args, **_kwargs):
            return OllamaResponse()

    with patch("app.main.urllib.request.build_opener", return_value=OllamaOpener()), patch(
        "app.generated_validator.run_generated_terraform_validation",
        side_effect=AssertionError("provider plugins must not run in Restricted Mode"),
    ):
        response = client.post("/v1/generate", json={
            "description": "Create a private S3 bucket",
            "workspace_path": str(tmp_path),
            "run_external_tools": True,
            "workspace_trusted": False,
        })

    assert response.status_code == 200
    assert response.json()["checks"]["terraform_validate"] == "not_run: workspace is untrusted (Restricted Mode)"


def test_generate_retries_once_with_hcl_parser_feedback():
    with patch(
        "app.main._generate_with_ollama",
        side_effect=[
            ("test-model", "resource { invalid"),
            ("test-model", 'resource "aws_s3_bucket" "example" {}'),
        ],
    ) as generate:
        response = client.post("/v1/generate", json={
            "description": "Create a private S3 bucket",
        })

    assert response.status_code == 200
    result = response.json()
    assert result["syntax_valid"] is True
    assert result["checks"]["generation_repair"] == "attempted once; review the returned validation findings"
    assert generate.call_count == 2
    repair_prompt = generate.call_args_list[1].args[2]
    assert "<validation_feedback>" in repair_prompt
    assert "not parseable HCL" in repair_prompt


def test_generate_repairs_provider_errors_and_revalidates():
    from app.main import Finding

    invalid_draft = 'resource "aws_s3_bucket" "example" { invalid_argument = true }'
    corrected_draft = 'resource "aws_s3_bucket" "example" {}'
    provider_finding = Finding(
        id="main.tf:TF-VALIDATE:1:0", source="terraform-cli", rule_id="TF-VALIDATE",
        severity="error", message="Unsupported argument: invalid_argument", file="main.tf", line=1,
    )

    with patch(
        "app.main._generate_with_ollama",
        side_effect=[("test-model", invalid_draft), ("test-model", corrected_draft)],
    ) as generate, patch(
        "app.generated_validator.run_generated_terraform_validation",
        side_effect=[
            ("failed: 1 error(s), 0 warning(s)", [provider_finding]),
            ("passed", []),
        ],
    ) as validate:
        response = client.post("/v1/generate", json={
            "description": "Create a private S3 bucket",
            "workspace_path": "C:/trusted/workspace",
            "run_external_tools": True,
            "workspace_trusted": True,
        })

    assert response.status_code == 200
    result = response.json()
    assert result["checks"]["terraform_validate"] == "passed"
    assert result["checks"]["generation_repair"] == "attempted once; review the returned validation findings"
    assert validate.call_count == 2
    repair_prompt = generate.call_args_list[1].args[2]
    assert "Unsupported argument: invalid_argument" in repair_prompt


def test_generate_rejects_unparseable_model_output():
    class OllamaResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return json.dumps({"response": "resource { invalid"}).encode("utf-8")

    class OllamaOpener:
        def open(self, *_args, **_kwargs):
            return OllamaResponse()

    with patch("app.main.urllib.request.build_opener", return_value=OllamaOpener()):
        response = client.post("/v1/generate", json={"description": "Create a private S3 bucket"})

    assert response.status_code == 422
    assert "nothing was written" in response.json()["detail"]


def test_generate_rejects_non_loopback_ollama_url(monkeypatch):
    monkeypatch.setenv("TERRAMIND_OLLAMA_URL", "http://192.0.2.5:11434")

    response = client.post("/v1/generate", json={"description": "Create a private S3 bucket"})

    assert response.status_code == 503


def test_generate_rejects_url_credentials_that_could_escape_loopback(monkeypatch):
    monkeypatch.setenv("TERRAMIND_OLLAMA_URL", "http://127.0.0.1:11434@attacker.example")

    response = client.post("/v1/generate", json={"description": "Create a private S3 bucket"})

    assert response.status_code == 503


def test_generate_can_use_an_explicit_local_transformers_model(monkeypatch):
    monkeypatch.setenv("TERRAMIND_HF_MODEL_PATH", "C:/local/terramind-merged-model")
    with patch("app.main._generate_with_transformers", return_value=(
        "transformers:terramind-merged-model", 'terraform { required_version = ">= 1.5" }',
    )) as generate:
        response = client.post("/v1/generate", json={"description": "Create a private S3 bucket"})

    assert response.status_code == 200
    assert response.json()["model"] == "transformers:terramind-merged-model"
    assert response.json()["syntax_valid"] is True
    generate.assert_called_once()
    assert generate.call_args.args[0] == "C:/local/terramind-merged-model"


def test_external_checks_are_explicitly_opt_in(tmp_path):
    (tmp_path / "main.tf").write_text('terraform { required_version = ">= 1.5" }', encoding="utf-8")

    response = client.post("/v1/analyze", json={"workspace_path": str(tmp_path)})

    assert response.status_code == 200
    assert response.json()["checks"]["tflint"].startswith("not_run: external tools disabled")


def test_external_tools_map_json_findings_and_hide_cloud_credentials(tmp_path, monkeypatch):
    import subprocess

    (tmp_path / "main.tf").write_text('terraform { required_version = ">= 1.5" }', encoding="utf-8")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "must-not-reach-a-tool")

    def fake_which(name):
        return {"tflint": "C:/tools/tflint.exe", "checkov": "C:/tools/checkov.exe"}.get(name)

    def fake_run(command, **kwargs):
        assert kwargs["shell"] is False
        assert "AWS_ACCESS_KEY_ID" not in kwargs["env"]
        if command[0].endswith("tflint.exe"):
            output = json.dumps({
                "issues": [{
                    "rule": {"name": "terraform_required_version"},
                    "message": "Set a required version",
                    "severity": "WARNING",
                    "range": {"filename": "main.tf", "start": {"line": 1}},
                }],
            })
        else:
            output = json.dumps({"results": {"failed_checks": [{
                "check_id": "CKV_AWS_18",
                "check_name": "Ensure access logging is enabled",
                "severity": "MEDIUM",
                "file_path": "main.tf",
                "file_line_range": [1, 1],
            }]}})
        return subprocess.CompletedProcess(command, 1, output, "")

    with patch("app.tool_runner.shutil.which", side_effect=fake_which), patch(
        "app.tool_runner.subprocess.run", side_effect=fake_run
    ):
        response = client.post("/v1/analyze", json={
            "workspace_path": str(tmp_path), "run_external_tools": True,
            "workspace_trusted": True,
        })

    assert response.status_code == 200
    report = response.json()
    assert report["checks"]["tflint"] == "completed: 1 issue(s)"
    assert report["checks"]["checkov"] == "completed: 1 failed check(s)"
    assert {finding["source"] for finding in report["findings"]} == {"tflint", "checkov"}


def test_analysis_skips_external_tools_for_untrusted_workspace(tmp_path):
    with patch(
        "app.tool_runner.run_static_tools",
        side_effect=AssertionError("external tools must not run in Restricted Mode"),
    ):
        response = client.post("/v1/analyze", json={
            "workspace_path": str(tmp_path),
            "run_external_tools": True,
            "workspace_trusted": False,
        })

    assert response.status_code == 200
    assert response.json()["checks"]["terraform_validate"] == "not_run: workspace is untrusted (Restricted Mode)"


def test_service_rating_cites_static_evidence_and_does_not_invent_unknown_scores(tmp_path):
    (tmp_path / "storage.tf").write_text(
        '''resource "aws_s3_bucket_acl" "public" {
  bucket = "example"
  acl    = "public-read"
}
''',
        encoding="utf-8",
    )

    response = client.post("/v1/analyze", json={"workspace_path": str(tmp_path)})

    assert response.status_code == 200
    s3 = next(item for item in response.json()["service_ratings"] if item["service"] == "s3")
    assert s3["dimensions"]["security"]["score"] == 65
    assert s3["dimensions"]["security"]["status"] == "limited"
    assert s3["dimensions"]["security"]["evidence_finding_ids"]
    assert s3["dimensions"]["cost"]["score"] is None
    assert s3["dimensions"]["cost"]["status"] == "insufficient_information"


def test_service_rating_does_not_treat_no_findings_as_perfect_security(tmp_path):
    (tmp_path / "storage.tf").write_text('resource "aws_s3_bucket" "example" {}', encoding="utf-8")

    response = client.post("/v1/analyze", json={"workspace_path": str(tmp_path)})

    s3 = next(item for item in response.json()["service_ratings"] if item["service"] == "s3")
    assert s3["dimensions"]["security"]["score"] is None
    assert s3["dimensions"]["security"]["status"] == "insufficient_information"


def test_ollama_generation_options_use_safe_defaults_when_unset():
    from app.main import (
        _ollama_keep_alive,
        _ollama_num_ctx,
        _ollama_num_predict,
        _ollama_options,
        _ollama_temperature,
    )

    with patch.dict("os.environ", {}, clear=True):
        assert _ollama_num_predict() == 4096
        assert _ollama_temperature() == 0.1
        assert _ollama_num_ctx() == 8192
        assert _ollama_keep_alive() == "10m"
        assert _ollama_options() == {"temperature": 0.1, "num_predict": 4096, "num_ctx": 8192}


def test_ollama_num_predict_is_clamped_and_configurable():
    from app.main import _ollama_num_predict

    with patch.dict("os.environ", {"TERRAMIND_OLLAMA_NUM_PREDICT": "8192"}):
        assert _ollama_num_predict() == 8192
    with patch.dict("os.environ", {"TERRAMIND_OLLAMA_NUM_PREDICT": "100000"}):
        assert _ollama_num_predict() == 8192
    with patch.dict("os.environ", {"TERRAMIND_OLLAMA_NUM_PREDICT": "5"}):
        assert _ollama_num_predict() == 256
    with patch.dict("os.environ", {"TERRAMIND_OLLAMA_NUM_PREDICT": "invalid"}):
        assert _ollama_num_predict() == 4096


def test_ollama_temperature_is_clamped_and_configurable():
    from app.main import _ollama_temperature

    with patch.dict("os.environ", {"TERRAMIND_OLLAMA_TEMPERATURE": "0.7"}):
        assert _ollama_temperature() == 0.7
    with patch.dict("os.environ", {"TERRAMIND_OLLAMA_TEMPERATURE": "2"}):
        assert _ollama_temperature() == 1.0
    with patch.dict("os.environ", {"TERRAMIND_OLLAMA_TEMPERATURE": "-1"}):
        assert _ollama_temperature() == 0.0
    with patch.dict("os.environ", {"TERRAMIND_OLLAMA_TEMPERATURE": "invalid"}):
        assert _ollama_temperature() == 0.1
    with patch.dict("os.environ", {"TERRAMIND_OLLAMA_TEMPERATURE": "nan"}):
        assert _ollama_temperature() == 0.1


def test_ollama_num_ctx_is_clamped_and_configurable():
    from app.main import _ollama_num_ctx

    with patch.dict("os.environ", {"TERRAMIND_OLLAMA_NUM_CTX": "32768"}):
        assert _ollama_num_ctx() == 32768
    with patch.dict("os.environ", {"TERRAMIND_OLLAMA_NUM_CTX": "100000"}):
        assert _ollama_num_ctx() == 32768
    with patch.dict("os.environ", {"TERRAMIND_OLLAMA_NUM_CTX": "100"}):
        assert _ollama_num_ctx() == 2048
    with patch.dict("os.environ", {"TERRAMIND_OLLAMA_NUM_CTX": "invalid"}):
        assert _ollama_num_ctx() == 8192


def test_ollama_keep_alive_is_validated_and_configurable():
    from app.main import _ollama_keep_alive

    with patch.dict("os.environ", {"TERRAMIND_OLLAMA_KEEP_ALIVE": "30m"}):
        assert _ollama_keep_alive() == "30m"
    with patch.dict("os.environ", {"TERRAMIND_OLLAMA_KEEP_ALIVE": "-1"}):
        assert _ollama_keep_alive() == "-1"
    with patch.dict("os.environ", {"TERRAMIND_OLLAMA_KEEP_ALIVE": "1h30m"}):
        assert _ollama_keep_alive() == "1h30m"
    with patch.dict("os.environ", {"TERRAMIND_OLLAMA_KEEP_ALIVE": ""}):
        assert _ollama_keep_alive() == "10m"
    with patch.dict("os.environ", {"TERRAMIND_OLLAMA_KEEP_ALIVE": "   "}):
        assert _ollama_keep_alive() == "10m"
    with patch.dict("os.environ", {"TERRAMIND_OLLAMA_KEEP_ALIVE": "not-a-duration"}):
        assert _ollama_keep_alive() == "10m"


def test_generate_with_ollama_sends_bounded_options_and_keep_alive(monkeypatch):
    from app.main import _generate_with_ollama

    captured: dict[str, dict] = {}

    class OllamaResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return json.dumps({
                "model": "qwen2.5-coder:3b",
                "response": 'resource "aws_s3_bucket" "example" {}',
            }).encode("utf-8")

    class OllamaOpener:
        def open(self, request, *_args, **_kwargs):
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return OllamaResponse()

    monkeypatch.setenv("TERRAMIND_OLLAMA_NUM_PREDICT", "2048")
    monkeypatch.setenv("TERRAMIND_OLLAMA_TEMPERATURE", "0.25")
    monkeypatch.setenv("TERRAMIND_OLLAMA_NUM_CTX", "4096")
    monkeypatch.setenv("TERRAMIND_OLLAMA_KEEP_ALIVE", "5m")
    with patch("app.main.urllib.request.build_opener", return_value=OllamaOpener()):
        model, terraform = _generate_with_ollama("http://127.0.0.1:11434", "qwen2.5-coder:3b", "draft this")

    assert model == "qwen2.5-coder:3b"
    assert terraform == 'resource "aws_s3_bucket" "example" {}'
    payload = captured["payload"]
    assert payload["stream"] is False
    assert payload["keep_alive"] == "5m"
    assert payload["options"] == {"temperature": 0.25, "num_predict": 2048, "num_ctx": 4096}


# --- generation Job API -----------------------------------------------------


def test_generate_job_reaches_completed_with_result():
    with patch(
        "app.main._generate_with_ollama",
        return_value=("test-model", 'resource "aws_s3_bucket" "job" {}'),
    ):
        accepted = client.post("/v1/generate/job", json={"description": "Create a private S3 bucket"})
        assert accepted.status_code == 200
        job_id = accepted.json()["job_id"]

        deadline = time.time() + 10
        status: dict = {}
        while time.time() < deadline:
            response = client.get(f"/v1/generate/job/{job_id}")
            assert response.status_code == 200
            status = response.json()
            if status["status"] in {"completed", "failed"}:
                break
            time.sleep(0.02)

    assert status["status"] == "completed"
    assert status["progress"] == 100
    assert status["phase"] == "completed"
    assert status["result"] is not None
    assert status["result"]["status"] == "completed"
    assert status["result"]["terraform"] == 'resource "aws_s3_bucket" "job" {}'


def test_generate_job_reports_failure_detail():
    from fastapi import HTTPException

    def explode(*_args, **_kwargs):
        raise HTTPException(status_code=503, detail="Local Ollama is unavailable")

    with patch("app.main._generate_with_ollama", side_effect=explode):
        accepted = client.post("/v1/generate/job", json={"description": "Create a private S3 bucket"})
        job_id = accepted.json()["job_id"]

        deadline = time.time() + 10
        status: dict = {}
        while time.time() < deadline:
            status = client.get(f"/v1/generate/job/{job_id}").json()
            if status["status"] != "running":
                break
            time.sleep(0.02)

    assert status["status"] == "failed"
    assert status["result"] is None
    assert status["detail"] == "Local Ollama is unavailable"


def test_generate_job_unknown_id_returns_404():
    response = client.get("/v1/generate/job/does-not-exist")
    assert response.status_code == 404


def test_generate_job_registry_is_bounded():
    from app.main import MAX_GENERATION_JOBS, _GENERATION_JOBS, _create_generation_job

    for index in range(MAX_GENERATION_JOBS + 5):
        _create_generation_job(f"unit-test-job-{index}")

    assert len(_GENERATION_JOBS) <= MAX_GENERATION_JOBS
    # The oldest entries were evicted.
    assert "unit-test-job-0" not in _GENERATION_JOBS

