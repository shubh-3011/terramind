import csv
import json

import pytest

from terramind_ml.sft_data import prepare_sft_splits


def _row(repo, *, provider="aws", license_name="MIT", output='resource "aws_s3_bucket" "example" {}'):
    return {
        "instruction": "Write Terraform HCL.",
        "input": "Create a private S3 bucket.",
        "output": output,
        "repo": repo,
        "license": license_name,
        "file_path": "main.tf",
        "provider_family": provider,
        "signature": "abc123",
    }


def test_sft_prep_keeps_provenance_and_repo_disjoint_splits(tmp_path):
    manifest = prepare_sft_splits(
        [_row("owner/train-one"), _row("owner/ignore", provider="gcp"), _row("owner/no-license", license_name="NOASSERTION")],
        [_row("owner/valid-one", license_name="Apache-2.0")],
        tmp_path,
    )

    assert manifest["train_rows"] == 1
    assert manifest["validation_rows"] == 1
    assert manifest["repository_overlap"] == 0
    train = json.loads((tmp_path / "train.jsonl").read_text(encoding="utf-8"))
    assert train["provenance"]["repo"] == "owner/train-one"
    assert train["messages"][-1]["content"].startswith("resource")
    with (tmp_path / "ATTRIBUTION.csv").open(encoding="utf-8", newline="") as stream:
        license_names = {row["source_license"] for row in csv.DictReader(stream)}
    assert license_names == {"MIT", "Apache-2.0"}


def test_sft_prep_rejects_train_validation_repository_overlap(tmp_path):
    with pytest.raises(ValueError, match="repositories overlap"):
        prepare_sft_splits([_row("owner/reused")], [_row("owner/reused")], tmp_path)


def test_sft_prep_skips_unparseable_hcl(tmp_path):
    with pytest.raises(ValueError, match="parseable licensed examples"):
        prepare_sft_splits([_row("owner/bad", output="resource {")], [_row("owner/valid")], tmp_path)
