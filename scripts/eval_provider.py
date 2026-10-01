"""Measure held-out generation quality: HCL parse rate AND Terraform provider validity.

Generates through the bundled GGUF engine (no Ollama) and validates each draft with
the installed Terraform + a pre-initialized provider cache. Prints a per-example
progress counter and a final summary.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

DATA = os.environ.get(
    "TERRAMIND_EVAL_DATA",
    r"C:\Users\shubh\Downloads\terramind\.build\terramind-terraform-sft-all\validation.jsonl",
)
WORKSPACE = os.environ.get(
    "TERRAMIND_EVAL_WORKSPACE",
    r"C:\Users\shubh\Downloads\terramind\.build\generated-validation",
)
COUNT = int(os.environ.get("TERRAMIND_EVAL_COUNT", "12"))


def main() -> int:
    lines = [line for line in Path(DATA).read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = [json.loads(line) for line in lines][:COUNT]
    client = TestClient(app)
    print(f"Engine    : {os.environ.get('TERRAMIND_GENERATION_ENGINE', 'auto')} / {os.environ.get('TERRAMIND_GGUF_MODEL', '')}", flush=True)
    print(f"Workspace : {WORKSPACE}", flush=True)
    print(f"Examples  : {len(rows)}", flush=True)
    print("-" * 70, flush=True)

    parsed = 0
    provider_valid = 0
    started = time.time()
    for index, row in enumerate(rows, start=1):
        user = row["messages"][1]["content"][:8000]
        print(f"[{index}/{len(rows)}] generating (this can take a minute)...", flush=True)
        try:
            response = client.post("/v1/generate", json={
                "description": user,
                "engine": "gguf",
                "workspace_path": WORKSPACE,
                "run_external_tools": True,
                "workspace_trusted": True,
            })
        except Exception as error:  # noqa: BLE001
            print(f"[{index}/{len(rows)}] request error: {str(error)[:140]}", flush=True)
            continue
        if response.status_code == 200:
            payload = response.json()
            parsed += 1
            provider_status = str(payload.get("checks", {}).get("terraform_validate", "?"))
            valid = provider_status.startswith("passed")
            provider_valid += 1 if valid else 0
            repair = payload.get("checks", {}).get("generation_repair", "?")
            print(
                f"[{index}/{len(rows)}] parse=OK provider={provider_status} repair={repair} "
                f"elapsed={time.time() - started:.0f}s",
                flush=True,
            )
        else:
            detail = ""
            try:
                detail = str(response.json().get("detail", ""))[:100]
            except Exception:  # noqa: BLE001
                pass
            print(f"[{index}/{len(rows)}] parse=FAIL http={response.status_code} {detail}", flush=True)

    print("-" * 70, flush=True)
    print(f"PARSE RATE      : {parsed}/{len(rows)} ({parsed / max(1, len(rows)) * 100:.0f}%)", flush=True)
    print(f"PROVIDER-VALID  : {provider_valid}/{len(rows)} ({provider_valid / max(1, len(rows)) * 100:.0f}%)", flush=True)
    print(f"Elapsed         : {time.time() - started:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
