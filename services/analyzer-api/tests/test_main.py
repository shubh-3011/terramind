from fastapi.testclient import TestClient

from app.main import app

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
    assert any(item["rule_id"] == "TM-IAM-001" for item in response.json()["findings"])


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


def test_analyze_enforces_workspace_file_limit(tmp_path):
    for index in range(501):
        (tmp_path / f"resource-{index}.tf").touch()

    response = client.post("/v1/analyze", json={"workspace_path": str(tmp_path)})

    assert response.status_code == 413


def test_analyze_rejects_missing_workspace(tmp_path):
    response = client.post("/v1/analyze", json={"workspace_path": str(tmp_path / "missing")})
    assert response.status_code == 400
