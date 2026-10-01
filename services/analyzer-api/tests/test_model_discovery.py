from app.main import _discover_gguf_model


def test_explicit_env_wins(monkeypatch):
    monkeypatch.setenv("TERRAMIND_GGUF_MODEL", r"C:\somewhere\my-model.gguf")
    assert _discover_gguf_model() == r"C:\somewhere\my-model.gguf"


def test_models_dir_is_discovered(monkeypatch, tmp_path):
    monkeypatch.delenv("TERRAMIND_GGUF_MODEL", raising=False)
    model = tmp_path / "terramind-terraform-Q4_K_M.gguf"
    model.write_bytes(b"not a real model")
    monkeypatch.setenv("TERRAMIND_MODELS_DIR", str(tmp_path))

    assert _discover_gguf_model() == str(model)


def test_models_dir_without_gguf_falls_through(monkeypatch, tmp_path):
    monkeypatch.delenv("TERRAMIND_GGUF_MODEL", raising=False)
    monkeypatch.setenv("TERRAMIND_MODELS_DIR", str(tmp_path))
    # No .gguf here; discovery must not raise even if nothing is found.
    result = _discover_gguf_model()
    assert result is None or result.lower().endswith(".gguf")
