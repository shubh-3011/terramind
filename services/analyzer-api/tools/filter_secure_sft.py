"""Drop supervised-fine-tuning examples whose Terraform violates TerraMind security rules.

Public datasets of real-world Terraform contain insecure samples (public SSH/RDP, public S3
ACLs, wildcard IAM). Training on them teaches the model those patterns. This filter runs
TerraMind's own deterministic rules over each example and removes any with an ``error``
finding, so the model is not trained to reproduce known-unsafe configurations.

Usage:
    python -m tools.filter_secure_sft --input <in.jsonl> --output <out.jsonl> [--keep-warnings]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import hcl2

from app.main import _static_security_findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--drop-warnings",
        action="store_true",
        help="Also drop examples with warning-severity findings (stricter).",
    )
    parser.add_argument(
        "--keep-first",
        type=int,
        default=None,
        help="Only read the first N input rows (useful to bound filtering time).",
    )
    args = parser.parse_args()

    dropped_severities = {"error", "warning"} if args.drop_warnings else {"error"}
    kept = dropped_insecure = unparsable = 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.input.open(encoding="utf-8") as source, args.output.open(
        "w", encoding="utf-8", newline="\n"
    ) as sink:
        for index, line in enumerate(source):
            if args.keep_first is not None and index >= args.keep_first:
                break
            if not line.strip():
                continue
            row = json.loads(line)
            messages = row.get("messages") or []
            if len(messages) != 3:
                unparsable += 1
                continue
            answer = messages[2].get("content", "")
            try:
                document = hcl2.loads(answer)
            except Exception:  # noqa: BLE001 - any parse failure is a skip
                unparsable += 1
                continue
            findings = _static_security_findings(document, answer, "main.tf")
            if any(str(f.severity) in dropped_severities for f in findings):
                dropped_insecure += 1
                continue
            sink.write(json.dumps(row, ensure_ascii=False) + "\n")
            kept += 1

    print(json.dumps({
        "input": str(args.input),
        "kept": kept,
        "dropped_insecure": dropped_insecure,
        "unparsable": unparsable,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
