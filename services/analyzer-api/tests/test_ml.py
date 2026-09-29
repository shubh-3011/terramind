import csv

import hcl2

from terramind_ml.features import FEATURE_NAMES, FEATURE_VERSION, extract_features
from terramind_ml.predictor import predict_risk
from terramind_ml.train import SOURCE_COMMIT, train


def test_feature_extraction_ignores_generated_label_comments():
    labeled = '# Expected: VIOLATION\nresource "aws_s3_bucket" "example" {\n  force_destroy = true\n}\n'
    uncommented = 'resource "aws_s3_bucket" "example" {\n  force_destroy = true\n}\n'

    labeled_features = extract_features([hcl2.loads(labeled)], [labeled])
    plain_features = extract_features([hcl2.loads(uncommented)], [uncommented])

    assert labeled_features == plain_features


def test_training_groups_pairs_and_exports_runtime_model(tmp_path):
    dataset_path = tmp_path / "features.csv"
    columns = ["sample_id", "group_id", "label", "source_commit", *FEATURE_NAMES]
    with dataset_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for pair in range(12):
            for label in (0, 1):
                row = {
                    "sample_id": f"sample-{pair}-{label}",
                    "group_id": f"control-{pair}",
                    "label": label,
                    "source_commit": SOURCE_COMMIT,
                }
                row.update({feature: 0 for feature in FEATURE_NAMES})
                row["sensitive_boolean_false_count"] = label
                writer.writerow(row)

    artifact = train(dataset_path, tmp_path / "model.json", tmp_path / "metrics.json")
    prediction = predict_risk(
        {feature: int(feature == "sensitive_boolean_false_count") for feature in FEATURE_NAMES},
        tmp_path / "model.json",
    )

    assert artifact["feature_version"] == FEATURE_VERSION
    assert artifact["training"]["sample_count"] == 24
    assert artifact["training"]["control_pair_count"] == 12
    assert artifact["training"]["evaluation"]["evaluation"].startswith("5-fold GroupKFold")
    assert prediction is not None
    assert prediction["source"] == "experimental-ml"
    assert prediction["calibrated"] is False
