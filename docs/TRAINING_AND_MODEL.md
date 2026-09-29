# TerraMind risk-model prototype

## What this model does—and does not do

TerraMind now has a small, reproducible traditional-ML baseline. It is a standardized logistic-regression classifier trained to estimate whether a Terraform configuration violates a named security control represented in a controlled benchmark. It is **not** a foundation model, a Terraform code generator, a deployment-failure predictor, or a guarantee about AWS security, uptime, scalability, or cost.

The analyzer exposes the estimate separately from deterministic findings and marks it `experimental-ml`. The exported model is uncalibrated; its probability must not be treated as a production probability.

## Source data and provenance

The training source is [IaCSecBench](https://github.com/mchittineni/iacsecbench), pinned at commit `6e359ac29dcde1974d792f454e1a48dfd9deeaa6`. Its repository identifies the benchmark as MIT licensed and describes a controlled generated vulnerable/compliant corpus. TerraMind selects only generated AWS-provider cases with `pair_id` metadata. It excludes Kubernetes cases and examples whose source provenance is unclear, resulting in 46 samples across 23 AWS control pairs (23 compliant, 23 violations).

TerraMind does not copy the benchmark's Terraform files into this repository. It commits only numeric features and case/control identifiers, plus this source manifest: [data/manifests/terraform-risk-v1.json](../data/manifests/terraform-risk-v1.json). The model input explicitly excludes `sample_id`, `group_id`, comments, case names, control names, and labels.

## Feature pipeline

`terramind_ml.features` parses `.tf` files with `python-hcl2` and emits the versioned numeric schema `terraform-risk-features-v1`. Features cover file/resource structure and a few generic security-sensitive indicators (public CIDRs, SSH exposure, wildcard IAM values, disabled encryption/public controls, sensitive false flags, and weak mode/protocol literals). This is a deliberately simple feature baseline, not full Terraform semantic analysis.

Benchmark HCL is parsed into structured values; expected-label comments are not passed to the model. Training validates that each group has exactly one compliant and one violation member. Five-fold `GroupKFold` keeps both variants of every control pair in the same fold. `sample_id` and `group_id` are used only for provenance and splitting, never as model features.

## Reproduce the pinned dataset and model

From the repository root in PowerShell, clone the pinned benchmark into a temporary source directory and install the optional development dependencies:

```powershell
$sourcePath = Join-Path $env:TEMP "terramind-iacsecbench"
git clone https://github.com/mchittineni/iacsecbench.git $sourcePath
git -C $sourcePath checkout --detach 6e359ac29dcde1974d792f454e1a48dfd9deeaa6

Push-Location services/analyzer-api
python -m pip install -e ".[dev]"
Pop-Location
python -m terramind_ml.dataset --source $sourcePath --output data/processed/terraform-risk-v1.csv
python -m terramind_ml.train `
  --dataset data/processed/terraform-risk-v1.csv `
  --model-output models/terraform-risk-v1.json `
  --metrics-output reports/terraform-risk-v1-metrics.json
```

If installing the analyzer package in editable mode, run the install command from `services/analyzer-api` and use that package's directory as the current path. The Python runtime needs the base dependencies plus `scikit-learn` for training; inference uses the exported JSON coefficients and the Python standard library only.

## Initial evaluation (exploratory only)

On the pinned 46-sample AWS subset, five-fold grouped out-of-fold evaluation produced:

- Logistic regression: balanced accuracy **0.674**, ROC-AUC **0.709**, PR-AUC **0.764**, precision **0.700**, recall **0.609**, F1 **0.651**, Brier score **0.209**.
- Dummy-prior baseline: balanced accuracy **0.500**, ROC-AUC **0.500**, PR-AUC **0.500**.
- Logistic confusion matrix (true rows 0/1, predicted columns 0/1): `[[17, 6], [9, 14]]`.

The exact generated evaluation is [reports/terraform-risk-v1-metrics.json](../reports/terraform-risk-v1-metrics.json); the exported artifact records the dataset SHA-256 and grouped-evaluation method. The score is a prototype result on a very small, controlled/generated sample. It has not been calibrated, externally validated on labeled repositories, or evaluated against real deployment outcomes. Do not use it for production decisions or claim that the score generalizes.

## Next research work

1. Add independently authored and human-reviewed labeled AWS examples; record license and provenance per source.
2. Add repository-level held-out evaluation with no generated variants crossing partitions, plus confidence intervals and a pre-registered test set.
3. Compare richer deterministic baselines and feature ablations before adding model complexity.
4. Calibrate probabilities only if the dataset size and validation design support it.
5. Keep code generation/explanation in a separate local LLM adapter; never merge LLM output into ground-truth labels.
