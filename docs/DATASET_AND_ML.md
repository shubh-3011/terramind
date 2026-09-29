# Dataset and ML protocol

> **Status:** the first reproducible pipeline and experimental risk baseline are implemented in [TRAINING_AND_MODEL.md](TRAINING_AND_MODEL.md): 46 generated AWS cases, 23 paired controls, and grouped out-of-fold metrics. This is a prototype only—not a validated production model. The larger corpus, independently reviewed labels, external validation, calibration, and richer evaluation below remain future work.

## Research question

Can static structural and analyzer-derived features from AWS Terraform configurations estimate the probability that a configuration is risky or will fail a controlled validation/plan workflow, beyond a simple baseline?

This is a risk-estimation study, not a claim that the model predicts real-world outages or replaces security scanners.

## Dataset acquisition

1. Maintain `data/manifests/sources.csv` with source URL, commit SHA, license, retrieval date, AWS relevance, and inclusion/exclusion reason.
2. Accept only public sources whose license permits the intended academic use; retain attribution.
3. Pin each source revision; never train directly from a moving branch.
4. Deduplicate near-identical modules/configurations using normalized content hashes.
5. Store raw sources outside Git or with Git LFS only after explicit approval; commit manifests, scripts, schemas, and small fixtures.

## Sample schema

Each base configuration and mutation receives a stable `sample_id`; variants share a `base_config_id` and `repository_id`.

| Group | Fields |
| --- | --- |
| Provenance | `sample_id`, `base_config_id`, `repository_id`, `source_url`, `source_commit`, `license`, `is_mutation`, `mutation_id` |
| Structure | `resource_count`, `resource_type_counts`, `module_count`, `provider_count`, `variable_count`, `output_count`, `dependency_count`, `dependency_depth`, `cycle_count`, `hcl_file_count`, `loc` |
| Tool signals | `fmt_status`, `validate_status`, `plan_status`, `plan_unavailable_reason`, `tflint_counts`, `checkov_counts`, `tool_versions` |
| AWS/security signals | public ingress count, wildcard IAM count, encryption-related finding count, public storage finding count |
| Labels | `risk_label`, `failure_category`, `label_source`, `label_confidence` |

Keep feature schema version, analyzer configuration hash, and timestamp with every row.

## Labels

For the MVP, define `risk_label=1` if a configuration has a validation failure, a controlled-plan failure attributable to configuration, or a predeclared threshold of severe static findings. Record which condition caused the label; do not silently merge operational/environment failures.

`plan_status=unavailable` (for example, no credentials) is missing evidence, not a negative label. Keep it as a separate category/feature and report the affected sample count.

## Controlled mutations

Create one mutation per copy and record exact before/after diff plus expected class. Start with these deterministic transformations:

| Mutation family | Example | Expected evidence |
| --- | --- | --- |
| Invalid reference | Point an attribute at a nonexistent resource | `terraform validate` error |
| Missing/wrong variable | Remove a required declaration or give incompatible type | validation/plan diagnostic |
| Dependency | Introduce a direct reference cycle where syntax permits | graph/validation diagnostic |
| Provider/version | Use incompatible/deprecated constraint or attribute | init/validate diagnostic |
| IAM | Broaden action/resource to wildcard | Checkov/TFLint/security finding |
| Network | Add public `0.0.0.0/0` SSH ingress | static security finding |
| Storage/database | Remove encryption or make access public | static security finding |

Do not mutate every sample in every way. Choose applicable mutations, cap variants per base, preserve the original, and validate labels by re-running analyzers. Mutations must never invoke a cloud apply.

## Feature engineering

- Build parsing features before reading outcome labels to avoid leakage.
- Encode resource types as counts or a fixed vocabulary; collapse rare types to `other`.
- Include graph metrics such as dependency count and depth only if parser semantics are tested.
- Keep scanner counts/severity by tool and category; do not use free-text errors as a shortcut feature in the first baseline.
- Fit normalizers/encoders solely on the training partition in a pipeline.
- Version the feature list. A production inference request must expose its `feature_version`.

## Splits, evaluation, and selection

1. Split by `repository_id` or `base_config_id` before creating fit transforms. All mutations of a base stay in one partition.
2. Use grouped cross-validation for model selection and a final untouched grouped test set for reporting.
3. Compare a dummy classifier, logistic regression, random forest, and optionally XGBoost.
4. For the positive risk class report precision, recall, F1, PR-AUC, ROC-AUC, confusion matrix, and prevalence. Accuracy alone is insufficient.
5. Calibrate the selected probability model on a validation partition (e.g., Platt or isotonic when data supports it); report Brier score and a calibration curve.
6. Report metrics separately for originals, mutations, and all samples if sample sizes permit.
7. Save seed, source manifest hash, split assignments, hyperparameters, dependency/tool versions, and model artifact hash.

## Failure-category model and quality score

Do not build these until the binary-risk workflow is complete. Failure-category classification needs enough examples per class and macro-F1/confusion-matrix reporting. A numeric quality score needs a defensible human or rubric-derived target; it must not merely relabel the same Checkov count as "AI quality."

## Reproducibility outputs

The eventual pipeline should produce:

```text
data/manifests/sources.csv
data/manifests/split_assignments.csv
data/processed/features-<version>.parquet
models/risk-<version>.joblib
reports/evaluation-<run-id>.md
reports/evaluation-<run-id>.json
```

Large raw data and trained artifacts remain out of Git by default; commit the manifests/configuration that can recreate them.
