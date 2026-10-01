import os

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.workspace_guard import allowed_roots, resolve_workspace

client = TestClient(app)


def test_resolve_workspace_returns_resolved_directory_without_allowlist(tmp_path, monkeypatch):
    monkeypatch.delenv("TERRAMIND_ALLOWED_ROOTS", raising=False)

    resolved = resolve_workspace(str(tmp_path))

    assert resolved == tmp_path.resolve()
    assert resolved.is_dir()


def test_resolve_workspace_rejects_missing_directory(tmp_path, monkeypatch):
    monkeypatch.delenv("TERRAMIND_ALLOWED_ROOTS", raising=False)

    with pytest.raises(HTTPException) as error:
        resolve_workspace(str(tmp_path / "missing"))

    assert error.value.status_code == 400
    assert error.value.detail == "workspace_path must be an existing directory"


def test_resolve_workspace_enforces_configured_allowlist(tmp_path, monkeypatch):
    allowed = tmp_path / "trusted"
    inside = allowed / "nested"
    inside.mkdir(parents=True)
    outside = tmp_path / "untrusted"
    outside.mkdir()
    monkeypatch.setenv("TERRAMIND_ALLOWED_ROOTS", str(allowed))

    assert resolve_workspace(str(allowed)) == allowed.resolve()
    assert resolve_workspace(str(inside)) == inside.resolve()

    with pytest.raises(HTTPException) as error:
        resolve_workspace(str(outside))

    assert error.value.status_code == 403
    assert "TERRAMIND_ALLOWED_ROOTS" in error.value.detail


def test_resolve_workspace_require_allowed_root_without_configuration(tmp_path, monkeypatch):
    monkeypatch.delenv("TERRAMIND_ALLOWED_ROOTS", raising=False)

    with pytest.raises(HTTPException) as error:
        resolve_workspace(str(tmp_path), require_allowed_root=True)

    assert error.value.status_code == 403
    assert "TERRAMIND_ALLOWED_ROOTS" in error.value.detail


def test_allowed_roots_ignores_blanks_and_missing_directories(tmp_path, monkeypatch):
    existing = tmp_path / "root"
    existing.mkdir()
    missing = tmp_path / "gone"
    monkeypatch.setenv(
        "TERRAMIND_ALLOWED_ROOTS",
        f"{existing}{os.pathsep}   {os.pathsep}{missing}",
    )

    assert allowed_roots() == [existing.resolve()]


def test_allowed_roots_is_empty_when_unset(monkeypatch):
    monkeypatch.delenv("TERRAMIND_ALLOWED_ROOTS", raising=False)

    assert allowed_roots() == []


def test_analyze_endpoint_enforces_allowlist(tmp_path, monkeypatch):
    allowed = tmp_path / "trusted"
    workspace = allowed / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "main.tf").write_text('terraform { required_version = ">= 1.5" }', encoding="utf-8")
    outside = tmp_path / "untrusted"
    outside.mkdir()
    (outside / "main.tf").write_text('terraform { required_version = ">= 1.5" }', encoding="utf-8")
    monkeypatch.setenv("TERRAMIND_ALLOWED_ROOTS", str(allowed))

    inside_response = client.post("/v1/analyze", json={"workspace_path": str(workspace)})
    outside_response = client.post("/v1/analyze", json={"workspace_path": str(outside)})

    assert inside_response.status_code == 200
    assert outside_response.status_code == 403
    assert "TERRAMIND_ALLOWED_ROOTS" in outside_response.json()["detail"]
