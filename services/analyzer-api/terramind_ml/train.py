"""Train an experimental, pair-grouped TerraMind binary risk baseline."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sys
from pathlib import Path
from typing import Any

import sklearn
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import GroupKFold, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .features import FEATURE_NAMES, FEATURE_VERSION

SOURCE_COMMIT = "6e359ac29dcde1974d792f454e1a48dfd9deeaa6"


def train(dataset_path: Path, model_path: Path, metrics_path: Path) -> dict[str, Any]:
    dataset_bytes = dataset_path.read_bytes()
    rows = list(csv.DictReader(dataset_path.read_text(encoding="utf-8").splitlines()))
    if len(rows) < 20:
        raise ValueError("At least 20 labeled samples are required for an exploratory grouped baseline")
    if not set(FEATURE_NAMES).issubset(rows[0]):
        raise ValueError("Feature CSV does not match the declared feature schema")
    source_commits = {row.get("source_commit", "") for row in rows}
    if source_commits != {SOURCE_COMMIT}:
        raise ValueError(f"Expected rows derived from pinned source commit {SOURCE_COMMIT}")

    groups = [row["group_id"] for row in rows]
    labels = [int(row["label"]) for row in rows]
    if any(not group for group in groups) or set(labels) != {0, 1}:
        raise ValueError("Training data needs pair IDs and both classes")
    _validate_complete_groups(groups, labels)
    features = [[float(row[name]) for name in FEATURE_NAMES] for row in rows]

    n_splits = min(5, len(set(groups)))
    if n_splits < 3:
        raise ValueError("At least three distinct control pairs are required for grouped evaluation")
    splitter = GroupKFold(n_splits=n_splits)
    pipeline = make_pipeline(
        StandardScaler(),
        LogisticRegression(class_weight="balanced", max_iter=2000, random_state=42),
    )
    oof_probabilities = cross_val_predict(
        pipeline, features, labels, groups=groups, cv=splitter, method="predict_proba",
    )[:, 1]
    baseline_probabilities = cross_val_predict(
        DummyClassifier(strategy="prior"), features, labels, groups=groups, cv=splitter, method="predict_proba",
    )[:, 1]
    metrics = {
        "logistic_regression_grouped_oof": _metrics(labels, oof_probabilities),
        "dummy_prior_grouped_oof": _metrics(labels, baseline_probabilities),
        "evaluation": f"{n_splits}-fold GroupKFold; both members of each control pair stay in one fold",
        "uncertainty": {
            "method": "95% percentile interval from 2,000 bootstrap resamples of control-pair groups over fixed out-of-fold predictions",
            "balanced_accuracy": _grouped_bootstrap_interval(labels, oof_probabilities, groups, balanced_accuracy_score),
            "pr_auc": _grouped_bootstrap_interval(labels, oof_probabilities, groups, average_precision_score),
            "caveat": "Intervals reflect variation across the 23 benchmark control pairs; they do not establish external or production generalization.",
        },
    }

    pipeline.fit(features, labels)
    scaler = pipeline.named_steps["standardscaler"]
    classifier = pipeline.named_steps["logisticregression"]
    artifact = {
        "model_version": "terraform-risk-iacsecbench-v1",
        "model_type": "standardized-logistic-regression",
        "feature_version": FEATURE_VERSION,
        "feature_names": list(FEATURE_NAMES),
        "standardization": {
            "mean": scaler.mean_.tolist(),
            "scale": scaler.scale_.tolist(),
        },
        "coefficients": classifier.coef_[0].tolist(),
        "intercept": float(classifier.intercept_[0]),
        "threshold": 0.5,
        "calibrated": False,
        "training": {
            "dataset_sha256": hashlib.sha256(dataset_bytes).hexdigest(),
            "source_url": "https://github.com/mchittineni/iacsecbench",
            "source_commit": SOURCE_COMMIT,
            "scikit_learn_version": sklearn.__version__,
            "sample_count": len(rows),
            "control_pair_count": len(set(groups)),
            "class_counts": {"compliant": labels.count(0), "violation": labels.count(1)},
            "label_definition": "benchmark control violation; not deployment failure/outage probability",
            "evaluation": metrics,
        },
        "limitations": [
            "Small controlled benchmark; not evidence of production generalization.",
            "Labels describe a named security control, not deployment failure, uptime, scalability, or cost.",
            "Cross-validation groups vulnerable/compliant variants by control, but the training corpus is still generated and narrow.",
            "Probability is not calibrated and must be displayed as experimental.",
        ],
    }
    _write_json(model_path, artifact)
    _write_json(metrics_path, metrics)
    return artifact


def _metrics(labels: list[int], probabilities) -> dict[str, Any]:
    predictions = [int(value >= 0.5) for value in probabilities]
    return {
        "accuracy": float(accuracy_score(labels, predictions)),
        "balanced_accuracy": float(balanced_accuracy_score(labels, predictions)),
        "precision": float(precision_score(labels, predictions, zero_division=0)),
        "recall": float(recall_score(labels, predictions, zero_division=0)),
        "f1": float(f1_score(labels, predictions, zero_division=0)),
        "pr_auc": float(average_precision_score(labels, probabilities)),
        "roc_auc": float(roc_auc_score(labels, probabilities)),
        "brier_score": float(brier_score_loss(labels, probabilities)),
        "confusion_matrix_labels_0_1": confusion_matrix(labels, predictions, labels=[0, 1]).tolist(),
    }


def _grouped_bootstrap_interval(labels, probabilities, groups, metric) -> list[float]:
    """Estimate metric uncertainty by resampling complete control pairs."""
    group_indices: dict[str, list[int]] = {}
    for index, group in enumerate(groups):
        group_indices.setdefault(group, []).append(index)

    group_ids = sorted(group_indices)
    randomizer = random.Random(42)
    estimates: list[float] = []
    for _ in range(2000):
        sampled_groups = [randomizer.choice(group_ids) for _ in group_ids]
        sampled_indices = [index for group in sampled_groups for index in group_indices[group]]
        sample_labels = [labels[index] for index in sampled_indices]
        sample_probabilities = [probabilities[index] for index in sampled_indices]
        metric_inputs = (
            [int(value >= 0.5) for value in sample_probabilities]
            if metric is balanced_accuracy_score else sample_probabilities
        )
        estimates.append(float(metric(sample_labels, metric_inputs)))

    estimates.sort()
    return [_percentile(estimates, 0.025), _percentile(estimates, 0.975)]


def _percentile(sorted_values: list[float], percentile: float) -> float:
    position = (len(sorted_values) - 1) * percentile
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(sorted_values) - 1)
    fraction = position - lower_index
    return sorted_values[lower_index] * (1 - fraction) + sorted_values[upper_index] * fraction


def _validate_complete_groups(groups: list[str], labels: list[int]) -> None:
    pair_labels: dict[str, list[int]] = {}
    for group, label in zip(groups, labels):
        pair_labels.setdefault(group, []).append(label)
    invalid = [group for group, values in pair_labels.items() if sorted(values) != [0, 1]]
    if invalid:
        raise ValueError(f"Each group must contain one compliant and one violating sample: {invalid[:5]}")


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--model-output", type=Path, required=True)
    parser.add_argument("--metrics-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        artifact = train(args.dataset, args.model_output, args.metrics_output)
    except (OSError, ValueError, csv.Error) as error:
        print(f"Training failed: {error}", file=sys.stderr)
        return 1
    result = artifact["training"]["evaluation"]["logistic_regression_grouped_oof"]
    print(
        f"Trained {artifact['model_version']} on {artifact['training']['sample_count']} samples; "
        f"grouped OOF balanced accuracy={result['balanced_accuracy']:.3f}, PR-AUC={result['pr_auc']:.3f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
