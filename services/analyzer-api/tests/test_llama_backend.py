"""Tests for the bundled GGUF (llama.cpp) generation engine.

These tests never require ``llama-cpp-python`` to be installed: the package is
imported lazily and every code path here is exercised through fakes.
"""

import sys
import types
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import llama_cpp_backend
from app.llama_cpp_backend import (
    generate_with_gguf,
    gguf_max_tokens,
    gguf_n_ctx,
    gguf_n_threads,
    gguf_temperature,
)
from app.main import _resolve_engine, app

client = TestClient(app)


# --- (a) engine resolution precedence -------------------------------------


def test_resolve_engine_auto_prefers_gguf_then_transformers_then_ollama():
    assert _resolve_engine(None, False, False, "auto") == "ollama"
    assert _resolve_engine(None, False, True, "auto") == "transformers"
    assert _resolve_engine(None, True, False, "auto") == "gguf"
    assert _resolve_engine(None, True, True, "auto") == "gguf"


def test_resolve_engine_explicit_request_overrides_env():
    assert _resolve_engine("ollama", True, True, "gguf") == "ollama"
    assert _resolve_engine("transformers", True, True, "gguf") == "transformers"
    assert _resolve_engine("gguf", False, True, "ollama") == "gguf"
    assert _resolve_engine("auto", True, False, "ollama") == "gguf"


def test_resolve_engine_invalid_env_falls_back_to_auto():
    assert _resolve_engine(None, False, False, "banana") == "ollama"
    assert _resolve_engine("", False, True, "not-an-engine") == "transformers"


def test_generate_auto_prefers_gguf_when_both_models_are_configured(monkeypatch):
    monkeypatch.setenv("TERRAMIND_GGUF_MODEL", "C:/models/terramind.gguf")
    monkeypatch.setenv("TERRAMIND_HF_MODEL_PATH", "C:/local/terramind-model")
    with patch(
        "app.main.generate_with_gguf",
        return_value=("gguf:terramind.gguf", 'terraform { required_version = ">= 1.5" }'),
    ) as gguf, patch("app.main._generate_with_transformers") as hf:
        response = client.post("/v1/generate", json={"description": "Create a private S3 bucket"})

    assert response.status_code == 200
    assert response.json()["model"] == "gguf:terramind.gguf"
    gguf.assert_called_once()
    hf.assert_not_called()


# --- (b) missing llama-cpp-python -> 503 -----------------------------------


def test_generate_with_gguf_missing_package_returns_503(tmp_path):
    model_file = tmp_path / "terramind.gguf"
    model_file.write_bytes(b"GGUF")
    llama_cpp_backend._LLAMA_CACHE.pop(str(model_file.resolve()), None)

    with patch.dict(sys.modules, {"llama_cpp": None}):
        with pytest.raises(HTTPException) as error:
            generate_with_gguf(str(model_file), "draft something")

    assert error.value.status_code == 503
    assert "llama-cpp-python" in error.value.detail
    assert "another engine" in error.value.detail


def test_push_request_engine_gguf_without_model_returns_503(monkeypatch):
    monkeypatch.delenv("TERRAMIND_GGUF_MODEL", raising=False)
    response = client.post(
        "/v1/generate",
        json={"description": "Create a private S3 bucket", "engine": "gguf"},
    )
    assert response.status_code == 503
    assert "TERRAMIND_GGUF_MODEL" in response.json()["detail"]


# --- (c) missing model file -> 503 -----------------------------------------


def test_generate_with_gguf_missing_model_file_returns_503(tmp_path):
    with pytest.raises(HTTPException) as error:
        generate_with_gguf(str(tmp_path / "absent.gguf"), "draft something")

    assert error.value.status_code == 503
    assert "does not exist" in error.value.detail


# --- (d) TERRAMIND_GGUF_* clamping helpers ---------------------------------


def test_gguf_bounds_have_safe_defaults_when_unset():
    with patch.dict("os.environ", {}, clear=True):
        assert gguf_n_ctx() == 8192
        assert gguf_temperature() == 0.1
        assert gguf_max_tokens() == 1024
        assert gguf_n_threads() is None


def test_gguf_context_is_clamped_and_configurable():
    with patch.dict("os.environ", {"TERRAMIND_GGUF_N_CTX": "16384"}):
        assert gguf_n_ctx() == 16384
    with patch.dict("os.environ", {"TERRAMIND_GGUF_N_CTX": "100000"}):
        assert gguf_n_ctx() == 32768
    with patch.dict("os.environ", {"TERRAMIND_GGUF_N_CTX": "100"}):
        assert gguf_n_ctx() == 2048
    with patch.dict("os.environ", {"TERRAMIND_GGUF_N_CTX": "invalid"}):
        assert gguf_n_ctx() == 8192


def test_gguf_temperature_is_clamped_and_configurable():
    with patch.dict("os.environ", {"TERRAMIND_GGUF_TEMPERATURE": "0.7"}):
        assert gguf_temperature() == 0.7
    with patch.dict("os.environ", {"TERRAMIND_GGUF_TEMPERATURE": "5"}):
        assert gguf_temperature() == 1.0
    with patch.dict("os.environ", {"TERRAMIND_GGUF_TEMPERATURE": "-2"}):
        assert gguf_temperature() == 0.0
    with patch.dict("os.environ", {"TERRAMIND_GGUF_TEMPERATURE": "nan"}):
        assert gguf_temperature() == 0.1


def test_gguf_max_tokens_is_clamped_and_configurable():
    with patch.dict("os.environ", {"TERRAMIND_GGUF_MAX_TOKENS": "2048"}):
        assert gguf_max_tokens() == 2048
    with patch.dict("os.environ", {"TERRAMIND_GGUF_MAX_TOKENS": "1"}):
        assert gguf_max_tokens() == 128
    with patch.dict("os.environ", {"TERRAMIND_GGUF_MAX_TOKENS": "999999"}):
        assert gguf_max_tokens() == 4096
    with patch.dict("os.environ", {"TERRAMIND_GGUF_MAX_TOKENS": "invalid"}):
        assert gguf_max_tokens() == 1024


def test_gguf_n_threads_is_optional_and_validated():
    with patch.dict("os.environ", {"TERRAMIND_GGUF_N_THREADS": "4"}):
        assert gguf_n_threads() == 4
    with patch.dict("os.environ", {"TERRAMIND_GGUF_N_THREADS": "0"}):
        assert gguf_n_threads() is None
    with patch.dict("os.environ", {"TERRAMIND_GGUF_N_THREADS": "-3"}):
        assert gguf_n_threads() is None
    with patch.dict("os.environ", {"TERRAMIND_GGUF_N_THREADS": "many"}):
        assert gguf_n_threads() is None


# --- (e) request engine routes to the backend ------------------------------


def test_generate_request_engine_gguf_routes_to_gguf_backend(monkeypatch):
    monkeypatch.setenv("TERRAMIND_GGUF_MODEL", "C:/models/terramind.gguf")
    with patch(
        "app.main.generate_with_gguf",
        return_value=("gguf:terramind.gguf", 'terraform { required_version = ">= 1.5" }'),
    ) as generate:
        response = client.post(
            "/v1/generate",
            json={"description": "Create a private S3 bucket", "engine": "gguf"},
        )

    assert response.status_code == 200
    assert response.json()["model"] == "gguf:terramind.gguf"
    assert response.json()["syntax_valid"] is True
    assert generate.call_args.args[0] == "C:/models/terramind.gguf"


def test_repair_request_engine_gguf_routes_to_gguf_backend(monkeypatch):
    monkeypatch.setenv("TERRAMIND_GGUF_MODEL", "C:/models/terramind.gguf")
    with patch(
        "app.main.generate_with_gguf",
        return_value=("gguf:terramind.gguf", 'resource "aws_s3_bucket" "data" {}'),
    ) as generate:
        response = client.post(
            "/v1/repair",
            json={
                "terraform": 'resource "aws_s3_bucket" "data" {}',
                "findings": ["TM-S3-001: enable protections"],
                "engine": "gguf",
            },
        )

    assert response.status_code == 200
    generate.assert_called_once()


def test_invalid_engine_value_returns_422():
    response = client.post(
        "/v1/generate",
        json={"description": "Create a private S3 bucket", "engine": "banana"},
    )
    assert response.status_code == 422


# --- backend chat vs completion routing (with fakes) -----------------------


class _ChatFakeLlama:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.metadata = {"tokenizer.chat_template": "template"}
        self.chat_format = "chatml"

    def create_chat_completion(self, **kwargs):
        return {"choices": [{"message": {"content": 'resource "aws_s3_bucket" "x" {}'}}]}


class _CompletionFakeLlama:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.metadata = {}
        self.chat_format = None

    def create_chat_completion(self, **kwargs):
        raise AssertionError("chat completion must not be used without a chat handler")

    def create_completion(self, **kwargs):
        return {"choices": [{"text": 'resource "aws_s3_bucket" "y" {}'}]}


def _fake_llama_module(fake_llama):
    return types.SimpleNamespace(Llama=fake_llama)


def test_generate_with_gguf_uses_chat_completion_when_available(tmp_path):
    model_file = tmp_path / "terramind.gguf"
    model_file.write_bytes(b"GGUF")
    llama_cpp_backend._LLAMA_CACHE.pop(str(model_file.resolve()), None)

    with patch.dict(sys.modules, {"llama_cpp": _fake_llama_module(_ChatFakeLlama)}):
        label, text = generate_with_gguf(str(model_file), "draft something")

    assert label == "gguf:terramind.gguf"
    assert text == 'resource "aws_s3_bucket" "x" {}'


def test_generate_with_gguf_falls_back_to_completion_without_chat_handler(tmp_path):
    model_file = tmp_path / "terramind.gguf"
    model_file.write_bytes(b"GGUF")
    llama_cpp_backend._LLAMA_CACHE.pop(str(model_file.resolve()), None)

    with patch.dict(sys.modules, {"llama_cpp": _fake_llama_module(_CompletionFakeLlama)}):
        label, text = generate_with_gguf(str(model_file), "draft something")

    assert label == "gguf:terramind.gguf"
    assert text == 'resource "aws_s3_bucket" "y" {}'
