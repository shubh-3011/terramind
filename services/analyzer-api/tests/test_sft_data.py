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


def test_sft_prep_all_includes_non_aws_and_aws_excludes_them(tmp_path):
    rows = [
        _row("owner/train-aws"),
        _row("owner/train-azure", provider="azure"),
        _row("owner/train-gcp", provider="gcp"),
        _row("owner/train-google", provider="google"),
    ]

    multicloud = prepare_sft_splits(rows, [_row("owner/val-aws")], tmp_path, provider_family="all")
    assert multicloud["filtered_to_provider_family"] == "all"
    assert multicloud["train_rows"] == 4
    assert "non_aws" not in multicloud["skipped"]["train"]

    aws_only = prepare_sft_splits(rows, [_row("owner/val-aws")], tmp_path, provider_family="aws")
    assert aws_only["filtered_to_provider_family"] == "aws"
    assert aws_only["train_rows"] == 1
    assert aws_only["skipped"]["train"] == {"non_aws": 3}


def test_sft_prep_all_still_applies_license_hcl_and_field_filters(tmp_path):
    missing_field = _row("owner/all-missing", provider="gcp")
    missing_field["input"] = ""
    manifest = prepare_sft_splits(
        [
            _row("owner/all-valid", provider="azure"),
            _row("owner/all-bad-license", provider="gcp", license_name="NOASSERTION"),
            _row("owner/all-bad-hcl", provider="google", output="resource {"),
            missing_field,
        ],
        [_row("owner/all-val", provider="azure")],
        tmp_path,
        provider_family="all",
    )

    assert manifest["train_rows"] == 1
    assert manifest["skipped"]["train"] == {
        "hcl_parse_error": 1,
        "license_not_allowlisted": 1,
        "missing_required_field": 1,
    }


def test_sft_prep_manifest_records_provider_family_counts(tmp_path):
    manifest = prepare_sft_splits(
        [_row("owner/t-aws"), _row("owner/t-azure", provider="azure")],
        [_row("owner/v-gcp", provider="gcp")],
        tmp_path,
        provider_family="all",
    )
    assert manifest["filtered_to_provider_family"] == "all"
    assert manifest["provider_family_counts"] == {"aws": 1, "azure": 1, "gcp": 1}

    default_manifest = prepare_sft_splits([_row("owner/a")], [_row("owner/b")], tmp_path)
    assert default_manifest["filtered_to_provider_family"] == "aws"
    assert default_manifest["provider_family_counts"] == {"aws": 2}


def test_sft_prep_rejects_unknown_provider_family(tmp_path):
    with pytest.raises(ValueError, match="provider_family must be one of"):
        prepare_sft_splits([_row("owner/a")], [_row("owner/b")], tmp_path, provider_family="azure")
