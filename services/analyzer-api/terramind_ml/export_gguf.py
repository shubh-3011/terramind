"""Export a merged TerraMind Terraform model to a small, redistributable GGUF.

This module is deliberately thin: it only builds and runs the two upstream
llama.cpp steps that turn a merged Hugging Face directory into a quantized
GGUF, then records a manifest with a content hash so the artifact can be
attached to a GitHub release. It never imports ``torch``/``transformers`` and
never needs a GPU, so it can run on any machine that can run llama.cpp.

Pipeline:

1. ``convert_hf_to_gguf.py`` converts the merged model directory to an f16 GGUF.
2. ``llama-quantize`` compresses the f16 GGUF into the requested low-bit
   quantization (``Q4_K_M`` by default).

TerraMind loads the resulting file through the bundled ``llama-cpp-python``
engine, configured with the ``TERRAMIND_GGUF_MODEL`` environment variable; no
separate Ollama installation is required.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

DEFAULT_BASE_MODEL = "Qwen/Qwen2.5-Coder-1.5B-Instruct"
DEFAULT_BASE_REVISION = "<pin the upstream commit before release>"
DEFAULT_LICENSE = "Apache-2.0"
DEFAULT_QUANT_TYPE = "Q4_K_M"
DEFAULT_MANIFEST_NAME = "model-manifest.json"

TRAINING_METADATA_NAME = "training-metadata.json"

_REDISTRIBUTION_NOTICE = (
    "GGUF is a conversion of the Apache-2.0 base weights plus a Terraform SFT adapter. "
    "Keep docs/MODEL_CARD.md and the prepared corpus ATTRIBUTION.csv with any redistribution; "
    "the training corpus (SASVAAI/terraform-multicloud, CC-BY-4.0) retains per-row source licenses."
)


@dataclass(frozen=True)
class LlamaCppTools:
    """Paths to the two llama.cpp tools the export pipeline shells out to.

    ``convert_script`` is ``None`` only when tools were resolved with
    ``require_convert=False`` (the ``--skip-convert`` quantize-only path).
    """

    convert_script: Path | None
    quantize_exe: Path


class LlamaCppToolsNotFound(RuntimeError):
    """Raised when the llama.cpp conversion/quantization tools cannot be located."""


# --- tool discovery ---------------------------------------------------------


def _first_existing(candidates: list[Path]) -> Path | None:
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _convert_candidates(root: Path) -> list[Path]:
    return [
        root / "convert_hf_to_gguf.py",
        root / "convert-hf-to-gguf.py",
        root / "gguf-py" / "gguf" / "scripts" / "convert_hf_to_gguf.py",
    ]


def _quantize_candidates(root: Path) -> list[Path]:
    names = ["llama-quantize", "llama-quantize.exe"]
    return [root / name for name in names] + [root / "build" / "bin" / name for name in names]


def find_llama_cpp_tools(
    *,
    require_convert: bool = True,
    env: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] | None = None,
) -> LlamaCppTools:
    """Locate ``convert_hf_to_gguf.py`` and the ``llama-quantize`` executable.

    Resolution order:

    1. ``TERRAMIND_LLAMA_CPP_DIR`` (a cloned/built llama.cpp checkout; executables
       may live in the checkout root or ``build/bin``).
    2. Common executable names on ``PATH`` (``convert_hf_to_gguf.py`` and
       ``llama-quantize``/``llama-quantize.exe``).

    Raises ``LlamaCppToolsNotFound`` with actionable guidance when a required
    tool cannot be found. Pass ``require_convert=False`` for the quantize-only
    ``--skip-convert`` path, where the conversion script is not needed.
    """

    resolved_env = os.environ if env is None else env
    resolved_which = shutil.which if which is None else which

    configured_dir = (resolved_env.get("TERRAMIND_LLAMA_CPP_DIR") or "").strip()
    if configured_dir:
        root = Path(configured_dir).expanduser()
        convert_script = _first_existing(_convert_candidates(root))
        quantize_exe = _first_existing(_quantize_candidates(root))
        missing = []
        if require_convert and convert_script is None:
            missing.append("convert_hf_to_gguf.py")
        if quantize_exe is None:
            missing.append("llama-quantize")
        if missing:
            raise LlamaCppToolsNotFound(
                f"TERRAMIND_LLAMA_CPP_DIR ({root}) is missing: {', '.join(missing)}. "
                "Point it at a llama.cpp checkout (with build/bin/llama-quantize) or set it to a PATH entry "
                "that contains both tools."
            )
        return LlamaCppTools(convert_script=convert_script, quantize_exe=quantize_exe)

    convert_on_path = resolved_which("convert_hf_to_gguf.py") if require_convert else None
    quantize_on_path = resolved_which("llama-quantize") or resolved_which("llama-quantize.exe")
    missing = []
    if require_convert and convert_on_path is None:
        missing.append("convert_hf_to_gguf.py")
    if quantize_on_path is None:
        missing.append("llama-quantize")
    if missing:
        raise LlamaCppToolsNotFound(
            f"Could not find {', '.join(missing)} on PATH. Set TERRAMIND_LLAMA_CPP_DIR to a llama.cpp "
            "checkout or place the tools on PATH."
        )
    return LlamaCppTools(
        convert_script=Path(convert_on_path) if convert_on_path else None,
        quantize_exe=Path(quantize_on_path) if quantize_on_path else None,
    )


# --- command construction ---------------------------------------------------


def build_convert_command(
    merged_model_dir: Path,
    out_f16_path: Path,
    tools: LlamaCppTools,
) -> list[str]:
    """Return the ``convert_hf_to_gguf.py`` argument list for an f16 GGUF."""

    if tools.convert_script is None:
        raise ValueError("build_convert_command requires tools.convert_script")
    return [
        sys.executable,
        str(tools.convert_script),
        str(merged_model_dir),
        "--outfile",
        str(out_f16_path),
        "--outtype",
        "f16",
    ]


def build_quantize_command(
    in_f16_path: Path,
    out_q4_path: Path,
    quant_type: str,
    tools: LlamaCppTools,
) -> list[str]:
    """Return the ``llama-quantize`` argument list for the requested quant type."""

    return [
        str(tools.quantize_exe),
        str(in_f16_path),
        str(out_q4_path),
        quant_type,
    ]


# --- manifest ---------------------------------------------------------------


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def build_model_manifest(
    merged_model_dir: Path,
    gguf_path: Path,
    *,
    base_model: str,
    base_revision: str,
    license: str,
    quant_type: str,
) -> dict[str, object]:
    """Build the manifest payload, hashing the GGUF when it exists.

    A missing GGUF (for example during ``--dry-run``) yields ``None`` for the
    hash and size fields rather than failing, so the preview stays printable.
    """

    slug = _slugify(merged_model_dir.name) or "terramind-terraform"
    manifest: dict[str, object] = {
        "model": base_model,
        "base_model": base_model,
        "base_revision": base_revision,
        "license": license,
        "quant_type": quant_type,
        "merged_model_dir": merged_model_dir.name,
        "gguf_file": gguf_path.name,
        "sha256": None,
        "size_bytes": None,
        "size_mib": None,
        "suggested_asset_filename": f"{slug}-{quant_type}.gguf",
        "redistribution_notice": _REDISTRIBUTION_NOTICE,
    }
    if gguf_path.is_file():
        size_bytes = gguf_path.stat().st_size
        manifest["sha256"] = _sha256(gguf_path)
        manifest["size_bytes"] = size_bytes
        manifest["size_mib"] = round(size_bytes / (1024 * 1024), 2)
    return manifest


def write_model_manifest(
    merged_model_dir: Path,
    gguf_path: Path,
    manifest_path: Path,
    *,
    base_model: str,
    base_revision: str,
    license: str,
    quant_type: str,
) -> dict[str, object]:
    """Write the export manifest JSON next to the GGUF and return its payload."""

    manifest = build_model_manifest(
        merged_model_dir,
        gguf_path,
        base_model=base_model,
        base_revision=base_revision,
        license=license,
        quant_type=quant_type,
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


# --- CLI --------------------------------------------------------------------


def _read_merged_metadata(merged_model_dir: Path | None) -> dict[str, object]:
    if merged_model_dir is None:
        return {}
    metadata_path = merged_model_dir / TRAINING_METADATA_NAME
    if not metadata_path.is_file():
        return {}
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return metadata if isinstance(metadata, dict) else {}


def _resolve_base_fields(args: argparse.Namespace) -> tuple[str, str, str]:
    metadata = _read_merged_metadata(args.merged)
    base_model = args.base_model or metadata.get("base_model") or DEFAULT_BASE_MODEL
    base_revision = args.base_revision or metadata.get("base_model_revision") or DEFAULT_BASE_REVISION
    license_name = args.license or metadata.get("base_model_license") or DEFAULT_LICENSE
    return str(base_model), str(base_revision), str(license_name)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--merged",
        type=Path,
        help="Merged Hugging Face model directory (required unless --skip-convert)",
    )
    parser.add_argument("--out-dir", type=Path, required=True, help="Directory for the GGUF and manifest")
    parser.add_argument("--quant", default=DEFAULT_QUANT_TYPE, help=f"llama.cpp quant type (default {DEFAULT_QUANT_TYPE})")
    parser.add_argument(
        "--f16",
        type=Path,
        help="Intermediate f16 GGUF. Output path when converting; required input with --skip-convert",
    )
    parser.add_argument("--output", type=Path, help="Final quantized GGUF path (default: <out-dir>/<name>-<quant>.gguf)")
    parser.add_argument("--manifest", type=Path, help=f"Manifest path (default: <out-dir>/{DEFAULT_MANIFEST_NAME})")
    parser.add_argument("--base-model", help=f"Base model id (default: {DEFAULT_BASE_MODEL})")
    parser.add_argument("--base-revision", help="Pinned base model revision")
    parser.add_argument("--license", help=f"Base model license (default: {DEFAULT_LICENSE})")
    parser.add_argument("--llama-cpp-dir", type=Path, help="Override TERRAMIND_LLAMA_CPP_DIR for this run")
    parser.add_argument("--skip-convert", action="store_true", help="Only quantize an existing --f16 GGUF")
    parser.add_argument("--dry-run", action="store_true", help="Print the commands and manifest without executing them")
    return parser


def _placeholder_tools() -> LlamaCppTools:
    return LlamaCppTools(convert_script=Path("convert_hf_to_gguf.py"), quantize_exe=Path("llama-quantize"))


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.skip_convert:
        if args.f16 is None:
            parser.error("--skip-convert requires --f16 pointing at an existing f16 GGUF")
        merged_model_dir = args.merged or args.f16.parent
    else:
        if args.merged is None:
            parser.error("--merged is required unless --skip-convert is set")
        merged_model_dir = args.merged

    stem = merged_model_dir.name
    f16_path = args.f16 or (args.out_dir / f"{stem}-f16.gguf")
    gguf_path = args.output or (args.out_dir / f"{stem}-{args.quant}.gguf")
    manifest_path = args.manifest or (args.out_dir / DEFAULT_MANIFEST_NAME)

    base_model, base_revision, license_name = _resolve_base_fields(args)

    tool_env = dict(os.environ)
    if args.llama_cpp_dir is not None:
        tool_env["TERRAMIND_LLAMA_CPP_DIR"] = str(args.llama_cpp_dir)

    if args.dry_run:
        try:
            tools = find_llama_cpp_tools(require_convert=not args.skip_convert, env=tool_env)
        except LlamaCppToolsNotFound:
            tools = _placeholder_tools()
        manifest = build_model_manifest(
            merged_model_dir,
            gguf_path,
            base_model=base_model,
            base_revision=base_revision,
            license=license_name,
            quant_type=args.quant,
        )
        print("# TerraMind GGUF export (dry run): no commands were executed.")
        print(f"# tools: {tools}")
        if not args.skip_convert:
            convert_command = build_convert_command(merged_model_dir, f16_path, tools)
            print("convert: " + " ".join(convert_command))
        quantize_command = build_quantize_command(f16_path, gguf_path, args.quant, tools)
        print("quantize: " + " ".join(quantize_command))
        print(f"manifest -> {manifest_path}")
        print(json.dumps(manifest, indent=2))
        return 0

    try:
        tools = find_llama_cpp_tools(require_convert=not args.skip_convert, env=tool_env)
    except LlamaCppToolsNotFound as error:
        parser.error(str(error))

    args.out_dir.mkdir(parents=True, exist_ok=True)
    if not args.skip_convert:
        convert_command = build_convert_command(merged_model_dir, f16_path, tools)
        print("convert: " + " ".join(convert_command))
        subprocess.run(convert_command, check=True)
    quantize_command = build_quantize_command(f16_path, gguf_path, args.quant, tools)
    print("quantize: " + " ".join(quantize_command))
    subprocess.run(quantize_command, check=True)

    manifest = write_model_manifest(
        merged_model_dir,
        gguf_path,
        manifest_path,
        base_model=base_model,
        base_revision=base_revision,
        license=license_name,
        quant_type=args.quant,
    )
    print(f"Wrote {gguf_path} ({manifest['size_bytes']} bytes) and {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
