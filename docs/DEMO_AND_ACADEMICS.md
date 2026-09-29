# Demo and academic framing

## Current prototype demo (2-3 minutes)

1. Start the FastAPI service on loopback and Ollama with the configured coder model; open a small Terraform workspace in a TerraMind development window (once the Code-OSS app build is verified).
2. Run **TerraMind: Analyze Workspace**.
3. Show HCL parse diagnostics and the current network, IAM, S3, ECR, EC2, and EBS static rules in Problems, including dynamic ingress resolution/review behavior.
4. Show the experimental, uncalibrated model estimate and its training-set limits; distinguish it from deterministic findings.
5. Generate an intentionally unsafe Terraform draft; show static findings and limited ratings before preview/save. If the workspace has a local initialized provider cache, opt into external tools and show the pre-save `terraform validate` findings too.
6. Explain that provider validation may execute installed plugins and is opt-in; no `init`, `plan`, or `apply` is run.
7. Show the analyzer tests and explain the current limits: heuristics and the narrow model do not establish compatibility or operational cloud quality.

The API/ML/data/training/evaluation suite has 34 passing tests, including mocked pre-save provider validation and checks that ensure local provider plugins receive no cloud/`TF_VAR` credentials. A real local AWS-provider run on an isolated generated draft reported three schema errors without running `terraform init`. A 3-example local 0.6B held-out evaluation parsed 1 response and rejected 2 as invalid HCL; this tiny sample does not establish quality. The full fork launch remains unverified. Extension compilation passed in an earlier session but cannot be rerun in the current checkout; even a successful extension compile would not establish a successful full Code-OSS build.

## Planned final demo (5-7 minutes)

1. Open a small valid AWS Terraform fixture in TerraMind and show the panel.
2. Run **Analyze**: show `fmt`/`validate` and scanner results only when configured and available, plus a separately labeled model risk probability with version.
3. Open a fixture with an invalid reference and insecure SSH/IAM rule. Re-run analysis and navigate from findings to exact lines.
4. Generate a Terraform draft using local Ollama, preview it, then explicitly save it and re-run analysis.
5. Ask for a grounded explanation or repair proposal only after those features are implemented; inspect any diff and re-run all checks.
6. Show the evaluation report: grouped split policy, baseline comparison, calibration, test metrics, and limitations.

Use offline, checked-in fixtures and recorded tool/model versions. Do not rely on a live cloud account during the presentation.

## Claims that are defensible after the corresponding milestone is implemented and evaluated

- TerraMind integrates local LLM assistance with independent deterministic Terraform and static-analysis checks.
- The project trained and evaluated a traditional ML risk model on a documented, reproducible dataset protocol.
- The prediction is a model estimate based on declared features and is shown separately from scanner results.
- Repair suggestions are reviewed, then independently re-tested.

## Claims to avoid

- "The system guarantees secure Terraform."
- "The model predicts production deployment success/outages" without a carefully matched real deployment dataset.
- "AI detected" a condition that Checkov/TFLint deterministically reported.
- "The LLM validates its own output."
- "High accuracy proves the model generalizes" when mutations or source repositories leaked across partitions.
- Claims of cloud cost savings, multi-cloud support, autonomous remediation, or production readiness unless separately implemented and evaluated.

## Improvements after MVP

Prioritize only after the primary deliverable is solid:

1. Dependency/infrastructure graph with finding overlays.
2. Failure-category classifier, only with enough balanced labeled data.
3. Explainable model factors with stability checks.
4. Policy profiles for coursework/demo environments.
5. Cost estimation as a separately labeled, clearly scoped module.
6. Multi-provider support through provider-specific adapters and a new data evaluation, not simple branding.

## Presentation evidence checklist

- Architecture diagram and evidence-source separation.
- Source/license manifest and mutation examples.
- Grouped split diagram and evaluation report.
- Screenshots of valid, invalid, and repaired analysis reports.
- Tool/model versions and known limitations.
- Clear statement: TerraMind does not run `terraform apply`.
