"""Build TerraMind's compact feature dataset from a pinned IaCSecBench checkout."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

import hcl2

from .features import FEATURE_NAMES, FEATURE_VERSION, extract_features

EXPECTED_SOURCE_COMMIT = "6e359ac29dcde1974d792f454e1a48dfd9deeaa6"
SOURCE_URL = "https://github.com/mchittineni/iacsecbench.git"


def build_dataset(source_root: Path) -> list[dict[str, Any]]:
    """Extract only generated, labelled AWS pairs; do not retain source text."""
    source_root = source_root.resolve()
    commit = _git_commit(source_root)
    if commit != EXPECTED_SOURCE_COMMIT:
        raise ValueError(f"Expected IaCSecBench {EXPECTED_SOURCE_COMMIT}, got {commit}")

    rows: list[dict[str, Any]] = []
    cases_root = source_root / "benchmark" / "internal" / "cases"
    for case_dir in sorted(path for path in cases_root.iterdir() if path.is_dir()):
        metadata_path = case_dir / "metadata.json"
        if not metadata_path.is_file():
            continue
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("generated_by") != "benchmark/generate_corpus.py":
            continue
        if metadata.get("provider") != "aws":
            continue

        terraform_files = sorted(case_dir.rglob("*.tf"))
        if not terraform_files:
            continue
        documents: list[dict[str, Any]] = []
        sources: list[str] = []
        for terraform_file in terraform_files:
            source = terraform_file.read_text(encoding="utf-8")
            sources.append(source)
            documents.append(hcl2.loads(source))

        expected_result = metadata.get("expected_result")
        if expected_result not in {"PASS", "FAIL"}:
            raise ValueError(f"Unexpected expected_result for {case_dir.name}: {expected_result}")
        label = int(expected_result == "FAIL")
        pair_id = metadata.get("pair_id")
        if not isinstance(pair_id, str) or not pair_id:
            raise ValueError(f"Missing pair_id for {case_dir.name}")

        features = extract_features(documents, sources)
        rows.append({
            "sample_id": str(metadata.get("case_id", metadata.get("id", case_dir.name))),
            "group_id": pair_id,
            "label": label,
            "source_commit": commit,
            **features,
        })

    _validate_pairs(rows)
    return rows


def write_dataset(rows: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["sample_id", "group_id", "label", "source_commit", *FEATURE_NAMES]
    with output_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _validate_pairs(rows: list[dict[str, Any]]) -> None:
    groups: dict[str, list[int]] = {}
    for row in rows:
        groups.setdefault(str(row["group_id"]), []).append(int(row["label"]))
    invalid = [group for group, labels in groups.items() if sorted(labels) != [0, 1]]
    if not rows or invalid:
        raise ValueError(f"Dataset must contain complete vulnerable/compliant pairs; invalid groups: {invalid[:5]}")


def _git_commit(source_root: Path) -> str:
    import subprocess

    result = subprocess.run(
        ["git", "-C", str(source_root), "rev-parse", "HEAD"],
        capture_output=True,
        check=True,
        text=True,
        timeout=10,
    )
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="IaCSecBench clone at the pinned source commit")
    parser.add_argument("--output", type=Path, required=True, help="Path for the derived CSV feature dataset")
    args = parser.parse_args()
    try:
        rows = build_dataset(args.source)
        write_dataset(rows, args.output)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Dataset build failed: {error}", file=sys.stderr)
        return 1
    print(f"Wrote {len(rows)} AWS examples from {len({row['group_id'] for row in rows})} control pairs to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
