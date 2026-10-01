from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import _declare_missing_variables, app

client = TestClient(app)


def test_declare_missing_variables_appends_only_missing_names():
    document = {"variable": [{"existing": {"type": "${string}"}}]}
    source = 'resource "x" "y" {\n  a = var.existing\n  b = var.new_one\n}\n'

    result, missing = _declare_missing_variables(source, document)

    assert missing == ["new_one"]
    assert 'variable "new_one"' in result
    assert 'variable "existing"' not in result


def test_declare_missing_variables_is_a_noop_when_all_declared():
    document = {"variable": [{"foo": {}}]}
    source = "a = var.foo\n"

    result, missing = _declare_missing_variables(source, document)

    assert missing == []
    assert result == source


def test_declare_missing_variables_ignores_non_variable_attributes():
    # `var.` only; locals/data references must not be auto-declared.
    document: dict = {}
    source = "a = local.foo\nb = data.aws_ami.x.id\nc = var.real\n"

    result, missing = _declare_missing_variables(source, document)

    assert missing == ["real"]
    assert "local.foo" in result


def test_generate_returns_draft_with_auto_declared_variables():
    generated = 'resource "aws_s3_bucket" "b" {\n  bucket = var.bucket_name\n}\n'
    with patch("app.main._generate_with_ollama", return_value=("test-model", generated)):
        response = client.post("/v1/generate", json={
            "description": "a private bucket whose name comes from a variable",
        })

    assert response.status_code == 200
    body = response.json()
    assert 'variable "bucket_name"' in body["terraform"]
    assert "bucket_name" in body["checks"]["auto_declared_variables"]
