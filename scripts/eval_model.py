"""Evaluate the fine-tuned Terraform model: HCL parse rate over held-out examples.

Run with the training virtualenv (it has transformers/torch), e.g. via
scripts/eval_model_live.bat. Prints a per-example progress counter.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import hcl2

from app.main import _generate_with_transformers

MODEL = os.environ.get("TERRAMIND_HF_MODEL_PATH", "")
DATA = os.environ.get(
    "TERRAMIND_EVAL_DATA",
    r"C:\Users\shubh\Downloads\terramind\.build\terramind-terraform-sft-all\validation.jsonl",
)
COUNT = int(os.environ.get("TERRAMIND_EVAL_COUNT", "5"))


def _resource_count(document: object) -> int:
    if not isinstance(document, dict):
        return 0
    total = 0
    for block in document.get("resource") or []:
        if isinstance(block, dict):
            total += sum(len(v) for v in block.values() if isinstance(v, dict))
    return total


def main() -> int:
    if not MODEL or not Path(MODEL).is_dir():
        print(f"ERROR: set TERRAMIND_HF_MODEL_PATH to a merged model directory (got {MODEL!r})", flush=True)
        return 2
    lines = [line for line in Path(DATA).read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = [json.loads(line) for line in lines][:COUNT]
    print(f"Model : {MODEL}", flush=True)
    print(f"Data  : {DATA}", flush=True)
    print(f"Examples: {len(rows)}", flush=True)
    print("-" * 60, flush=True)

    ok = 0
    started = time.time()
    for index, row in enumerate(rows, start=1):
        user = row["messages"][1]["content"]
        print(f"[{index}/{len(rows)}] generating...", flush=True)
        try:
            _, text = _generate_with_transformers(MODEL, user)
        except Exception as error:  # noqa: BLE001
            print(f"[{index}/{len(rows)}] generation error: {str(error)[:120]}", flush=True)
            continue
        try:
            document = hcl2.loads(text)
            resources = _resource_count(document)
            status = "OK"
            ok += 1
        except Exception as error:  # noqa: BLE001
            resources = 0
            status = f"FAIL ({str(error)[:60]})"
        print(
            f"[{index}/{len(rows)}] parse={status} resources={resources} chars={len(text)} "
            f"elapsed={time.time() - started:.0f}s",
            flush=True,
        )
    print("-" * 60, flush=True)
    print(f"PARSE RATE: {ok}/{len(rows)} ({ok / max(1, len(rows)) * 100:.0f}%)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
