"""Prepare license-attributed Terraform examples for an optional SFT run."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

DATASET_ID = "SASVAAI/terraform-multicloud"
DATASET_REVISION = "dced854e79a6aadb89f12b3ba74b31720264ea40"
DATASET_LICENSE = "CC-BY-4.0"
ALLOWED_SOURCE_LICENSES = {
    "MIT", "Apache-2.0", "UPL-1.0", "Unlicense", "MIT-0", "BSD-3-Clause",
    "CC0-1.0", "BSD-2-Clause", "WTFPL", "ISC", "0BSD", "BSD-3-Clause-Clear",
}
SYSTEM_PROMPT = (
    "You write reviewable Terraform HCL. Produce only the requested HCL; do not claim that it has been "
    "deployed, validated against a provider, or costed. Prefer secure defaults and parameterize environment-specific values."
)
PROVIDER_FAMILIES = ("aws", "all")


def prepare_sft_splits(
    train_rows: Iterable[dict[str, Any]],
    validation_rows: Iterable[dict[str, Any]],
    output_dir: Path,
    provider_family: str = "aws",
) -> dict[str, Any]:
    """Filter to parseable licensed HCL, retaining per-example source attribution.

    ``provider_family`` is ``"aws"`` (default) to keep only AWS examples or ``"all"``
    to retain every provider family.
    """
    import hcl2

    if provider_family not in PROVIDER_FAMILIES:
        raise ValueError(f"provider_family must be one of {PROVIDER_FAMILIES}, got {provider_family!r}")

    output_dir.mkdir(parents=True, exist_ok=True)
    train, train_skipped = _prepare_rows(train_rows, hcl2, provider_family)
    validation, validation_skipped = _prepare_rows(validation_rows, hcl2, provider_family)
    train_repos = {row["provenance"]["repo"] for row in train}
    validation_repos = {row["provenance"]["repo"] for row in validation}
    overlap = sorted(train_repos & validation_repos)
    if overlap:
        raise ValueError(f"SFT train/validation repositories overlap ({len(overlap)} repos)")
    if not train or not validation:
        raise ValueError("Both Terraform train and validation splits must contain parseable licensed examples")

    for filename, rows in (("train.jsonl", train), ("validation.jsonl", validation)):
        with (output_dir / filename).open("w", encoding="utf-8", newline="\n") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    attribution_counts: Counter[tuple[str, str]] = Counter()
    provider_family_counts: Counter[str] = Counter()
    for row in [*train, *validation]:
        provenance = row["provenance"]
        attribution_counts[(provenance["repo"], provenance["license"])] += 1
        provider_family_counts[provenance["provider_family"]] += 1
    with (output_dir / "ATTRIBUTION.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["repository", "source_license", "included_rows"])
        for (repo, license_name), count in sorted(attribution_counts.items()):
            writer.writerow([repo, license_name, count])

    manifest = {
        "dataset": DATASET_ID,
        "revision": DATASET_REVISION,
        "dataset_license": DATASET_LICENSE,
        "dataset_card": "https://huggingface.co/datasets/SASVAAI/terraform-multicloud",
        "purpose": (
            "Optional AWS Terraform supervised fine-tuning; not a security, reliability, cost, or deployment label set."
            if provider_family == "aws"
            else "Optional multi-cloud Terraform supervised fine-tuning; not a security, reliability, cost, or deployment label set."
        ),
        "train_rows": len(train),
        "train_repositories": len(train_repos),
        "validation_rows": len(validation),
        "validation_repositories": len(validation_repos),
        "repository_overlap": 0,
        "filtered_to_provider_family": provider_family,
        "provider_family_counts": dict(sorted(provider_family_counts.items())),
        "allowed_source_licenses": sorted(ALLOWED_SOURCE_LICENSES),
        "source_license_counts": dict(sorted(Counter(
            row["provenance"]["license"] for row in [*train, *validation]
        ).items())),
        "skipped": {"train": train_skipped, "validation": validation_skipped},
        "files_sha256": {
            name: hashlib.sha256((output_dir / name).read_bytes()).hexdigest()
            for name in ("train.jsonl", "validation.jsonl", "ATTRIBUTION.csv")
        },
        "notice": (
            "Keep ATTRIBUTION.csv with any redistributed prepared corpus. Source repositories retain their own licenses; "
            "review Apache NOTICE files and upstream dataset terms before redistributing a trained adapter."
        ),
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def _prepare_rows(
    rows: Iterable[dict[str, Any]],
    hcl2: Any,
    provider_family: str = "aws",
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    prepared: list[dict[str, Any]] = []
    skipped: Counter[str] = Counter()
    for row in rows:
        row_provider = str(row.get("provider_family") or "unknown")
        if provider_family == "aws" and row_provider != "aws":
            skipped["non_aws"] += 1
            continue
        license_name = str(row.get("license", ""))
        if license_name not in ALLOWED_SOURCE_LICENSES:
            skipped["license_not_allowlisted"] += 1
            continue
        instruction = row.get("instruction")
        request = row.get("input")
        answer = row.get("output")
        repo = row.get("repo")
        file_path = row.get("file_path")
        if not all(isinstance(value, str) and value.strip() for value in (instruction, request, answer, repo, file_path)):
            skipped["missing_required_field"] += 1
            continue
        try:
            hcl2.loads(answer)
        except Exception:
            skipped["hcl_parse_error"] += 1
            continue
        prepared.append({
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"{instruction.strip()}\n\n{request.strip()}"},
                {"role": "assistant", "content": answer},
            ],
            "provenance": {
                "repo": repo,
                "license": license_name,
                "file_path": file_path,
                "signature": str(row.get("signature", "")),
                "provider_family": row_provider,
                "dataset": DATASET_ID,
                "dataset_revision": DATASET_REVISION,
            },
        })
    return prepared, dict(sorted(skipped.items()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Output directory (use ignored .build/)")
    parser.add_argument("--revision", default=DATASET_REVISION, help="Pinned Hugging Face dataset commit")
    parser.add_argument(
        "--provider-family",
        choices=PROVIDER_FAMILIES,
        default="aws",
        help='Keep only AWS examples ("aws") or every provider family ("all")',
    )
    args = parser.parse_args()
    if args.revision != DATASET_REVISION:
        parser.error(f"Only the reviewed dataset revision is supported: {DATASET_REVISION}")

    try:
        from datasets import load_dataset
    except ImportError as error:
        parser.error('Install optional preparation dependencies with `pip install -e ".[sft-data]"`')
        raise error

    dataset = load_dataset(DATASET_ID, revision=args.revision)
    if not {"train", "validation"}.issubset(dataset):
        parser.error("Pinned source dataset is missing the expected train/validation splits")
    manifest = prepare_sft_splits(dataset["train"], dataset["validation"], args.output, args.provider_family)
    print(json.dumps({key: manifest[key] for key in (
        "train_rows", "train_repositories", "validation_rows", "validation_repositories",
        "filtered_to_provider_family", "provider_family_counts", "skipped",
    )}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
