from fastapi.testclient import TestClient

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
