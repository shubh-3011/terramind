"""Bundled local GGUF generation engine backed by llama-cpp-python.

This module is imported eagerly by the analyzer service but only imports the
heavy ``llama_cpp`` package lazily, the first time a GGUF model is actually
generated. That keeps the default Ollama and Transformers paths working even
when ``llama-cpp-python`` is not installed.
"""

from __future__ import annotations

import math
import os
import threading
from pathlib import Path
from typing import Any

from fastapi import HTTPException

DEFAULT_GGUF_N_CTX = 8192
MIN_GGUF_N_CTX = 2048
MAX_GGUF_N_CTX = 32768

DEFAULT_GGUF_TEMPERATURE = 0.1
MIN_GGUF_TEMPERATURE = 0.0
MAX_GGUF_TEMPERATURE = 1.0

DEFAULT_GGUF_MAX_TOKENS = 1024
MIN_GGUF_MAX_TOKENS = 128
MAX_GGUF_MAX_TOKENS = 4096

_MISSING_PACKAGE_DETAIL = (
    "llama-cpp-python is not installed. Install llama-cpp-python or use another engine."
)
_SYSTEM_INSTRUCTION = (
    "You are TerraMind, a Terraform HCL drafting assistant. "
    "Return only Terraform HCL. Do not include analysis, Markdown fences, or prose."
)

# One loaded model per resolved path; loading is expensive, so cache and reuse it.
_LLAMA_CACHE: dict[str, Any] = {}
_LLAMA_CACHE_LOCK = threading.Lock()


def _clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    """Return ``value`` coerced to int and clamped to ``[minimum, maximum]``."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return min(maximum, max(minimum, parsed))


def _clamp_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    """Return ``value`` coerced to a finite float and clamped to ``[minimum, maximum]``."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    return min(maximum, max(minimum, parsed))


def gguf_n_ctx() -> int:
    """Return a bounded GGUF context window, defaulting on invalid input."""
    return _clamp_int(
        os.environ.get("TERRAMIND_GGUF_N_CTX", str(DEFAULT_GGUF_N_CTX)),
        DEFAULT_GGUF_N_CTX,
        MIN_GGUF_N_CTX,
        MAX_GGUF_N_CTX,
    )


def gguf_temperature() -> float:
    """Return a bounded GGUF sampling temperature, defaulting on invalid input."""
    return _clamp_float(
        os.environ.get("TERRAMIND_GGUF_TEMPERATURE", str(DEFAULT_GGUF_TEMPERATURE)),
        DEFAULT_GGUF_TEMPERATURE,
        MIN_GGUF_TEMPERATURE,
        MAX_GGUF_TEMPERATURE,
    )


def gguf_max_tokens() -> int:
    """Return a bounded GGUF output-token limit suitable for interactive use."""
    return _clamp_int(
        os.environ.get("TERRAMIND_GGUF_MAX_TOKENS", str(DEFAULT_GGUF_MAX_TOKENS)),
        DEFAULT_GGUF_MAX_TOKENS,
        MIN_GGUF_MAX_TOKENS,
        MAX_GGUF_MAX_TOKENS,
    )


def gguf_n_threads() -> int | None:
    """Return an optional positive GGUF thread count, or None to let llama.cpp decide."""
    configured_value = os.environ.get("TERRAMIND_GGUF_N_THREADS", "").strip()
    if not configured_value:
        return None
    try:
        threads = int(configured_value)
    except (TypeError, ValueError):
        return None
    return threads if threads > 0 else None


def _import_llama_cpp():
    """Import llama-cpp-python lazily and surface a clear 503 when it is missing."""
    try:
        import llama_cpp
    except ImportError as error:
        raise HTTPException(status_code=503, detail=_MISSING_PACKAGE_DETAIL) from error
    return llama_cpp


def _load_llama(resolved_path: str):
    """Load and cache one ``Llama`` instance keyed by its resolved model path."""
    with _LLAMA_CACHE_LOCK:
        cached = _LLAMA_CACHE.get(resolved_path)
        if cached is not None:
            return cached
        llama_cpp = _import_llama_cpp()
        options: dict[str, Any] = {
            "model_path": resolved_path,
            "n_ctx": gguf_n_ctx(),
            "verbose": False,
        }
        n_threads = gguf_n_threads()
        if n_threads is not None:
            options["n_threads"] = n_threads
        try:
            llama = llama_cpp.Llama(**options)
        except HTTPException:
            raise
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail=f"Configured GGUF model could not be loaded: {error}",
            ) from error
        _LLAMA_CACHE[resolved_path] = llama
        return llama


def _has_chat_handler(llama: Any) -> bool:
    """Return True when the loaded model exposes a usable chat completion path."""
    if not callable(getattr(llama, "create_chat_completion", None)):
        return False
    if getattr(llama, "chat_format", None):
        return True
    metadata = getattr(llama, "metadata", None)
    return isinstance(metadata, dict) and bool(metadata.get("tokenizer.chat_template"))


def _first_choice(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    choices = result.get("choices")
    if not isinstance(choices, list) or not choices:
        return {}
    first = choices[0]
    return first if isinstance(first, dict) else {}


def _extract_chat_content(result: Any) -> str | None:
    message = _first_choice(result).get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
    return None


def _extract_completion_text(result: Any) -> str | None:
    text = _first_choice(result).get("text")
    return text if isinstance(text, str) else None


def generate_with_gguf(
    model_path: str,
    prompt: str,
    *,
    max_tokens: int | None = None,
) -> tuple[str, str]:
    """Generate a Terraform draft with a bundled local GGUF model.

    Returns ``(f"gguf:{filename}", text)`` to match the other generators.
    """
    resolved_path = str(Path(model_path).expanduser().resolve())
    if not Path(resolved_path).is_file():
        raise HTTPException(
            status_code=503,
            detail="Configured GGUF model file does not exist. Set TERRAMIND_GGUF_MODEL to a local .gguf file.",
        )

    llama = _load_llama(resolved_path)
    limit = (
        gguf_max_tokens()
        if max_tokens is None
        else _clamp_int(max_tokens, DEFAULT_GGUF_MAX_TOKENS, MIN_GGUF_MAX_TOKENS, MAX_GGUF_MAX_TOKENS)
    )
    temperature = gguf_temperature()

    try:
        if _has_chat_handler(llama):
            result = llama.create_chat_completion(
                messages=[
                    {"role": "system", "content": _SYSTEM_INSTRUCTION},
                    {"role": "user", "content": prompt},
                ],
                temperature=temperature,
                max_tokens=limit,
            )
            terraform = _extract_chat_content(result)
        else:
            result = llama.create_completion(
                prompt=f"{_SYSTEM_INSTRUCTION}\n\n{prompt}",
                temperature=temperature,
                max_tokens=limit,
            )
            terraform = _extract_completion_text(result)
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail="Local GGUF model failed during generation",
        ) from error

    if not isinstance(terraform, str) or not terraform.strip():
        raise HTTPException(status_code=502, detail="The configured local GGUF model returned no Terraform draft")
    return f"gguf:{Path(resolved_path).name}", terraform
