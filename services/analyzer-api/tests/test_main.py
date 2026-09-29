from fastapi.testclient import TestClient
from unittest.mock import patch
import json

from app.main import app
from terramind_ml.features import extract_features
import hcl2

client = TestClient(app)


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
    assert "not verified" in response.json()["validation_scope"]
    assert list(tmp_path.iterdir()) == []


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
        })

    assert response.status_code == 200
    report = response.json()
    assert report["checks"]["tflint"] == "completed: 1 issue(s)"
    assert report["checks"]["checkov"] == "completed: 1 failed check(s)"
    assert {finding["source"] for finding in report["findings"]} == {"tflint", "checkov"}


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
