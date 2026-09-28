"""Pure-Python inference for the exported, versioned logistic model."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .features import FEATURE_NAMES, FEATURE_VERSION

MODEL_PATH = Path(__file__).resolve().parents[3] / "models" / "terraform-risk-v1.json"


def predict_risk(features: dict[str, int], model_path: Path = MODEL_PATH) -> dict[str, Any] | None:
    """Return an explicitly experimental estimate; never treat it as a finding."""
    try:
        artifact = json.loads(model_path.read_text(encoding="utf-8"))
        if artifact.get("feature_version") != FEATURE_VERSION or artifact.get("feature_names") != list(FEATURE_NAMES):
            return None
        standardization = artifact["standardization"]
        means = standardization["mean"]
        scales = standardization["scale"]
        coefficients = artifact["coefficients"]
        if not all(len(values) == len(FEATURE_NAMES) for values in (means, scales, coefficients)):
            return None
        linear_score = float(artifact["intercept"])
        for index, name in enumerate(FEATURE_NAMES):
            value = (float(features[name]) - float(means[index])) / float(scales[index])
            linear_score += value * float(coefficients[index])
        linear_score = max(-35.0, min(35.0, linear_score))
        probability = 1.0 / (1.0 + math.exp(-linear_score))
        threshold = float(artifact["threshold"])
        return {
            "source": "experimental-ml",
            "model_version": str(artifact["model_version"]),
            "label": "elevated_observed_control_risk" if probability >= threshold else "lower_observed_control_risk",
            "probability": probability,
            "threshold": threshold,
            "calibrated": bool(artifact.get("calibrated", False)),
            "training_samples": int(artifact["training"]["sample_count"]),
            "limitations": artifact.get("limitations", []),
        }
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None
