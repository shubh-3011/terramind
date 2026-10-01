"""Tests for the merged-model -> GGUF export pipeline.

These tests never invoke llama.cpp or a GPU: command construction is pure, and
the CLI is exercised with ``subprocess.run`` mocked out.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from terramind_ml.export_gguf import (
    LlamaCppTools,
    LlamaCppToolsNotFound,
    build_convert_command,
    build_quantize_command,
    find_llama_cpp_tools,
    main,
    write_model_manifest,
)

TOOLS = LlamaCppTools(
    convert_script=Path("/opt/llama.cpp/convert_hf_to_gguf.py"),
    quantize_exe=Path("/opt/llama.cpp/llama-quantize"),
)


# --- command construction ---------------------------------------------------


def test_build_convert_command_argument_shape():
    merged = Path("C:/models/terramind-merged")
    out_f16 = Path("C:/dist/model-f16.gguf")

    command = build_convert_command(merged, out_f16, TOOLS)

    assert command == [
        sys.executable,
        str(TOOLS.convert_script),
        str(merged),
        "--outfile",
        str(out_f16),
        "--outtype",
        "f16",
    ]


def test_build_convert_command_requires_convert_script():
    tools = LlamaCppTools(convert_script=None, quantize_exe=Path("llama-quantize"))
    with pytest.raises(ValueError, match="convert_script"):
        build_convert_command(Path("merged"), Path("out-f16.gguf"), tools)


def test_build_quantize_command_argument_shape():
    in_f16 = Path("C:/dist/model-f16.gguf")
    out_q4 = Path("C:/dist/model-Q4_K_M.gguf")

    command = build_quantize_command(in_f16, out_q4, "Q4_K_M", TOOLS)

    assert command == [
        str(TOOLS.quantize_exe),
        str(in_f16),
        str(out_q4),
        "Q4_K_M",
    ]


# --- manifest ---------------------------------------------------------------


def test_write_model_manifest_records_fields_and_sha256(tmp_path):
    gguf = tmp_path / "terramind-merged-Q4_K_M.gguf"
    payload = b"GGUF" + bytes(range(256)) * 8
    gguf.write_bytes(payload)
    manifest_path = tmp_path / "model-manifest.json"

    manifest = write_model_manifest(
        tmp_path / "terramind-merged",
        gguf,
        manifest_path,
        base_model="Qwen/Qwen2.5-Coder-1.5B-Instruct",
        base_revision="0123456789abcdef",
        license="Apache-2.0",
        quant_type="Q4_K_M",
    )

    on_disk = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert on_disk == manifest
    assert manifest["model"] == "Qwen/Qwen2.5-Coder-1.5B-Instruct"
    assert manifest["base_model"] == "Qwen/Qwen2.5-Coder-1.5B-Instruct"
    assert manifest["base_revision"] == "0123456789abcdef"
    assert manifest["license"] == "Apache-2.0"
    assert manifest["quant_type"] == "Q4_K_M"
    assert manifest["gguf_file"] == gguf.name
    assert manifest["sha256"] == hashlib.sha256(payload).hexdigest()
    assert manifest["size_bytes"] == len(payload)
    assert manifest["size_mib"] == round(len(payload) / (1024 * 1024), 2)
    assert manifest["suggested_asset_filename"] == "terramind-merged-Q4_K_M.gguf"


def test_manifest_without_gguf_leaves_hash_and_size_unset(tmp_path):
    manifest = write_model_manifest(
        tmp_path / "terramind-merged",
        tmp_path / "not-created.gguf",
        tmp_path / "model-manifest.json",
        base_model="base",
        base_revision="rev",
        license="Apache-2.0",
        quant_type="Q4_K_M",
    )
    assert manifest["sha256"] is None
    assert manifest["size_bytes"] is None


# --- tool discovery ---------------------------------------------------------


def test_find_llama_cpp_tools_uses_env_directory(tmp_path):
    (tmp_path / "convert_hf_to_gguf.py").write_text("# stub\n", encoding="utf-8")
    quantize = tmp_path / "llama-quantize.exe"
    quantize.write_text("", encoding="utf-8")

    tools = find_llama_cpp_tools(
        env={"TERRAMIND_LLAMA_CPP_DIR": str(tmp_path)},
        which=lambda _name: None,
    )

    assert tools.convert_script == tmp_path / "convert_hf_to_gguf.py"
    assert tools.quantize_exe == quantize


def test_find_llama_cpp_tools_finds_built_executable(tmp_path):
    (tmp_path / "convert_hf_to_gguf.py").write_text("# stub\n", encoding="utf-8")
    built_bin = tmp_path / "build" / "bin"
    built_bin.mkdir(parents=True)
    quantize = built_bin / "llama-quantize"
    quantize.write_text("", encoding="utf-8")

    tools = find_llama_cpp_tools(
        env={"TERRAMIND_LLAMA_CPP_DIR": str(tmp_path)},
        which=lambda _name: None,
    )

    assert tools.quantize_exe == quantize


def test_find_llama_cpp_tools_quantize_only_does_not_require_convert(tmp_path):
    quantize = tmp_path / "llama-quantize"
    quantize.write_text("", encoding="utf-8")

    tools = find_llama_cpp_tools(
        require_convert=False,
        env={"TERRAMIND_LLAMA_CPP_DIR": str(tmp_path)},
        which=lambda _name: None,
    )

    assert tools.convert_script is None
    assert tools.quantize_exe == quantize


def test_find_llama_cpp_tools_raises_with_actionable_message():
    with pytest.raises(LlamaCppToolsNotFound, match="TERRAMIND_LLAMA_CPP_DIR"):
        find_llama_cpp_tools(env={}, which=lambda _name: None)


# --- CLI --------------------------------------------------------------------


def _tools_dir(tmp_path: Path, *, convert: bool = True, quantize: bool = True) -> Path:
    tools_dir = tmp_path / "llama.cpp"
    tools_dir.mkdir()
    if convert:
        (tools_dir / "convert_hf_to_gguf.py").write_text("# stub\n", encoding="utf-8")
    if quantize:
        (tools_dir / "llama-quantize").write_text("", encoding="utf-8")
    return tools_dir


def test_dry_run_prints_commands_without_executing(tmp_path, capsys, monkeypatch):
    merged = tmp_path / "terramind-merged"
    merged.mkdir()
    out_dir = tmp_path / "dist"

    monkeypatch.delenv("TERRAMIND_LLAMA_CPP_DIR", raising=False)
    with patch("terramind_ml.export_gguf.subprocess.run") as run:
        exit_code = main(
            ["--merged", str(merged), "--out-dir", str(out_dir), "--quant", "Q4_K_M", "--dry-run"]
        )

    assert exit_code == 0
    run.assert_not_called()
    output = capsys.readouterr().out
    assert "dry run" in output
    assert "convert_hf_to_gguf.py" in output
    assert "llama-quantize" in output
    assert "--outtype f16" in output
    assert '"quant_type": "Q4_K_M"' in output
    assert "model-manifest.json" in output
    assert not (out_dir / "model-manifest.json").exists()


def test_export_runs_convert_then_quantize_and_writes_manifest(tmp_path, monkeypatch):
    merged = tmp_path / "terramind-merged"
    merged.mkdir()
    out_dir = tmp_path / "dist"
    tools_dir = _tools_dir(tmp_path)
    monkeypatch.setenv("TERRAMIND_LLAMA_CPP_DIR", str(tools_dir))

    calls: list[list[str]] = []

    def fake_run(command, check):
        assert check is True
        calls.append(list(command))
        if command[0] == str(tools_dir / "llama-quantize"):
            Path(command[2]).write_bytes(b"GGUF" + b"q" * 64)
        return subprocess.CompletedProcess(command, 0)

    with patch("terramind_ml.export_gguf.subprocess.run", side_effect=fake_run):
        exit_code = main(["--merged", str(merged), "--out-dir", str(out_dir), "--quant", "Q4_K_M"])

    assert exit_code == 0
    assert len(calls) == 2
    assert calls[0][1] == str(tools_dir / "convert_hf_to_gguf.py")
    assert calls[0][3] == "--outfile"
    assert calls[1][0] == str(tools_dir / "llama-quantize")
    assert calls[1][-1] == "Q4_K_M"

    manifest = json.loads((out_dir / "model-manifest.json").read_text(encoding="utf-8"))
    assert manifest["sha256"] == hashlib.sha256(b"GGUF" + b"q" * 64).hexdigest()
    assert manifest["size_bytes"] == 68
    assert manifest["quant_type"] == "Q4_K_M"


def test_skip_convert_only_runs_quantize(tmp_path, monkeypatch):
    out_dir = tmp_path / "dist"
    tools_dir = _tools_dir(tmp_path, convert=False)
    monkeypatch.setenv("TERRAMIND_LLAMA_CPP_DIR", str(tools_dir))
    existing_f16 = tmp_path / "terramind-merged-f16.gguf"
    existing_f16.write_bytes(b"GGUF" + b"\x00" * 16)

    calls: list[list[str]] = []

    def fake_run(command, check):
        calls.append(list(command))
        Path(command[2]).write_bytes(b"GGUF" + b"z" * 32)
        return subprocess.CompletedProcess(command, 0)

    with patch("terramind_ml.export_gguf.subprocess.run", side_effect=fake_run):
        exit_code = main(
            [
                "--skip-convert",
                "--f16",
                str(existing_f16),
                "--out-dir",
                str(out_dir),
                "--quant",
                "Q5_K_M",
            ]
        )

    assert exit_code == 0
    assert len(calls) == 1
    assert calls[0][0] == str(tools_dir / "llama-quantize")
    assert calls[0][1] == str(existing_f16)
    assert calls[0][-1] == "Q5_K_M"
    assert (out_dir / "model-manifest.json").is_file()


def test_skip_convert_without_f16_is_a_cli_error(tmp_path):
    with pytest.raises(SystemExit) as error:
        main(["--skip-convert", "--out-dir", str(tmp_path / "dist")])
    assert error.value.code == 2
