# TerraMind implementation blueprint

> **Live status (2026-09-29):** TerraMind is a private Code-OSS fork with bundled Analyze/Generate commands, opt-in Terraform/TFLint/Checkov analysis, local Ollama or opt-in Transformers generation, static AWS/HCL findings, evidence-backed/unknown service ratings, an experimental 46-case AWS risk baseline, and a license-filtered 43,561/2,229-row generation corpus. A LoRA training pipeline and short CUDA runs for Apache-2.0 Qwen3-0.6B and Qwen3-1.7B are verified. Generated drafts now receive static AWS security checks and service evidence summaries before preview, but these models still fail end-to-end generation quality gates: the 0.6B sample failed AWS provider validation and the 1.7B smoke output failed HCL parsing. API/data/training-script suite: 27 passing; extension compile: 0 TypeScript errors. PR #6 remains failing/queued on GitHub; do not merge until required checks pass. See [PROGRESS.md](PROGRESS.md), [docs/TRAINING_AND_MODEL.md](docs/TRAINING_AND_MODEL.md), and [docs/GENERATIVE_TRAINING.md](docs/GENERATIVE_TRAINING.md).

## 1. Refined problem statement

Terraform authoring tools help with syntax, but generated or hand-written infrastructure can still contain invalid references, unsafe access controls, incompatible provider settings, poor dependency design, and deployment risks. TerraMind is a branded **Code-OSS fork** specialized for AWS Terraform authors. It keeps independent deterministic tooling as the source of truth, adds a trained ML risk estimate for patterns not reducible to one fixed rule, and uses a local LLM for generation, explanation, and repair suggestions.

## 2. Objectives and success criteria

| Objective | Evidence of completion |
| --- | --- |
| Generate or modify Terraform from a natural-language request | Structured `.tf` files or a reviewable patch are produced by a local LLM. |
| Independently assess configuration quality | `fmt`, `validate`, TFLint, and Checkov results are shown with file/line locations when available. |
| Deliver genuine ML work | A trained, versioned binary risk model is compared to a baseline on repository-grouped holdout data. |
| Keep the system safe | No `terraform apply`; patches require preview and approval. |
| Make the result demonstrable | A repeatable demo runs on known-good and intentionally faulty fixtures. |

## 3. Exact MVP scope

**In (target MVP):** a branded Code-OSS fork named TerraMind, Terraform HCL, AWS-focused projects, built-in TerraMind workbench features, local FastAPI service, local Ollama model, `terraform fmt`/`validate`, guarded `plan`, TFLint, Checkov, deterministic finding aggregation, feature extraction, one binary risk model, explanation and patch proposal, patch preview, re-test. **Current implementation is partial:** HCL parsing/static AWS rules, opt-in `fmt`/TFLint/Checkov and pre-initialized `validate`, bundled Analyze/Generate commands, local Ollama/Transformers drafting, static security analysis of generated drafts, and the small experimental logistic baseline are implemented; reliability/cost/scalability scoring beyond explicit unknowns, repairs, automated service lifecycle, provider-aware generation validation, and production-quality ML validation remain open.

**Out:** automatic cloud deployment, multi-cloud support, cost optimization, Kubernetes, Pulumi, CloudFormation, autonomous multi-file edits without review, failure-category model, quality-score model, graph visualization, and production-scale hosted service.

## 3A. Required user workflows

### Workflow A - Analyze Terraform already written by the user

When a workspace contains `.tf` files, the user selects **TerraMind: Analyze Workspace**. TerraMind must:

1. Locate and parse the Terraform project.
2. Run `terraform fmt -check`, `terraform validate`, TFLint, and Checkov; run `plan` only when explicitly enabled and safely configured.
3. Show errors, compatibility/provider-version problems, security issues, and best-practice findings as VS Code diagnostics linked to file and line where available.
4. Produce a project summary plus clear **service ratings** for detected AWS services. Ratings are not invented AI facts: each includes a score, the criteria used, evidence/finding IDs, and an "insufficient information" state.
5. Show an overall risk prediction from the separately trained ML model.
6. Offer **Explain** and **Generate Repair**. A repair is always a previewable diff, applied only after the user approves it, then re-analyzed.

Initial service-rating dimensions:

| Dimension | What TerraMind can assess from Terraform | Important limit |
| --- | --- | --- |
| Security | public exposure, IAM scope, encryption, known scanner findings | Does not prove runtime security. |
| Reliability / availability | single points of failure, load balancing, Multi-AZ, backups, redundancy settings | Requires a stated availability target. |
| Scalability | autoscaling, load balancer, instance/database configuration, obvious bottlenecks | Requires expected traffic/workload to be meaningful. |
| Cost awareness | resource choices and an external cost-estimator result | Requires region, usage, and pricing assumptions; report an estimate/range. |
| Maintainability | modules, variables, naming, complexity, dependency structure | Uses transparent structural rules. |

### Workflow B - Generate a connected Terraform architecture from a prompt

The extension displays a dedicated TerraMind dialog with a structured prompt. Example:

```text
Region: ap-south-1
Resources: 2 application servers, 1 VPC, 1 S3 bucket
Connection requirements: servers are in private subnets; an ALB is public;
servers access S3 through a least-privilege IAM role; no public SSH.
Constraints: low cost, secure defaults, target availability 99.9%.
```

The local LLM returns a staged Terraform project or a diff with an explicit file plan. TerraMind parses the generated HCL and applies its existing deterministic AWS static rules before presenting the draft; the generated result includes finding IDs and evidence-limited service ratings. This is not provider schema/reference validation or a replacement for Workflow A. The user reviews the generated files/patch and accepts them before they become workspace files, then the saved draft can be sent through the full configured workspace analysis.

The dialog should collect structured fields alongside free text: region, resources/counts, connectivity, public/private exposure, workload/traffic, budget, availability target, and constraints. This reduces ambiguity and improves generation and ratings.

## 4. Feature split

| Deterministic engineering | Traditional ML | Generative AI |
| --- | --- | --- |
| Terraform/TFLint/Checkov runners, HCL parsing, diagnostics, report aggregation, patch application, tests | Feature pipeline, repository-group split, risk classifier, calibration, evaluation report | Prompt-to-Terraform, error explanation grounded in report, unified-diff repair proposal |

The UI must label these sources separately; no prediction may be presented as a scanner finding.

## 5. Architecture and data flow

```text
TerraMind Code-OSS workbench
  | built-in prompt / analyze / repair commands
  v
FastAPI analyzer service
  |-- workspace sandbox + HCL feature extractor
  |-- Terraform fmt -> validate -> guarded plan
  |-- TFLint + Checkov
  |-- report normalizer -> ML inference
  |-- Ollama adapter (generate, explain, patch)
  v
typed AnalysisReport / PatchProposal
  v
VS Code diagnostics + analysis panel + user-approved WorkspaceEdit
```

The planned service runs external tools with timeouts, an explicit workspace allowlist, captured machine-readable output, and no `apply`. The current analyzer is static-only and does not execute Terraform or providers. TerraMind's UI features are shipped inside the fork; they are not installed from the VS Code Marketplace. See [ARCHITECTURE.md](ARCHITECTURE.md) and [docs/FORK_BUILD.md](docs/FORK_BUILD.md) for contracts and build strategy.

## 6. Dataset and ML plan

Build a reproducible AWS Terraform corpus from license-compatible public repositories/modules. For every base configuration, retain immutable source/provenance metadata, parse features, execute analyzers, and create controlled mutations. Most examples should be labeled through safe static/validation/plan evidence rather than real cloud deployment.

The required model predicts binary risk/failure probability. Compare logistic regression, random forest, and XGBoost (only if dependencies/data justify it); select using group-safe validation and calibration, not raw accuracy alone. Details: [docs/DATASET_AND_ML.md](docs/DATASET_AND_ML.md).

## 7. Milestones

**Current estimate:** roughly 65% of agreed MVP scope by milestone coverage (not a schedule or quality estimate). The local training and Transformers inference path now run, but the smoke adapters are not usable-quality models, HCL/provider validation fails on test generations, GitHub checks are failing/queued, and the full desktop build and launch are unverified. The [progress log](PROGRESS.md) has evidence and remaining work for each milestone.

| Milestone | Deliverable | Exit criteria |
| --- | --- | --- |
| M0 - Fork foundation | Clone/pin Code-OSS, TerraMind product branding, build prerequisites, tool preflight | Source snapshot and branding exist; development build still blocked/unverified by Windows native dependencies. |
| M1 - Deterministic analyzer | HCL parse diagnostics, bounded workspace scan, report schema, tested rules, then Terraform/TFLint/Checkov adapters | HCL/static and opt-in CLI/scanner adapters implemented and unit-tested; broader rules, workspace allowlisting, and live installed-tool tests remain. |
| M2 - Dataset pipeline | Acquisition manifest, parser/features, mutations, dataset version | Pinned 46-case AWS risk dataset builds reproducibly; separate pinned, license-aware AWS generation corpus pipeline prepared 43,561 train / 2,229 validation rows locally. |
| M3 - ML baseline | Baseline/model comparison, calibration, evaluation report | Experimental logistic baseline, grouped OOF metrics, pair-group bootstrap intervals, reproducible training workflow, and portable model artifact; no external validation or calibration. |
| M4 - Native workbench UX | Built-in commands, diagnostics, TerraMind panel/dialog | Analyze and Generate commands, Problems diagnostics, prompt capture, preview, and explicit in-workspace save implemented; UX/runtime integration tests remain. |
| M5 - Local AI workflow | Ollama/Transformers adapter, grounded generation/explanation/patch proposal | Base and merged local model inference paths exercised; short BF16 LoRA training runs completed. Smoke generations fail parser/provider tests; quality improvement, independent evaluation, explanations, repairs, and re-test feedback loop remain. |
| M6 - Demo hardening | Demo fixtures, tests, screenshots/video, presentation | Repeatable 5-7 minute demo from a clean setup. |

## 8. Testing strategy

- Unit-test parsers, feature calculations, report normalization, and API validation.
- Use small checked-in Terraform fixtures for valid, invalid-reference, insecure-IAM/network, and version/provider cases.
- Mock external tools in unit tests; run real-tool integration tests only in a controlled environment.
- Test extension commands, diagnostic mapping, patch preview, cancellation, tool timeout, and missing-tool behavior.
- Reproduce dataset build from a pinned manifest; test mutations against expected labels.
- Report ML metrics with confidence intervals where feasible and retain the exact split/model configuration.

## 9. Major risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Missing cloud credentials make `plan` fail | Make `plan` optional; classify unavailable separately from configuration failure. |
| LLM produces unsafe or invalid Terraform | Never trust it; run full analysis and require patch review. |
| Dataset leakage through mutations | Group all base variants by repository/base ID before splitting. |
| Class imbalance / synthetic-only signal | Report prevalence, use appropriate metrics, compare real vs mutated subsets, and avoid overclaiming. |
| Tool version drift | Pin/record versions in dataset metadata and CI. |
| Scope explosion | Enforce the MVP boundary in `AGENTS.md`; defer optional models and graph UI. |

## 10. Work split for 2-3 students

| Person | Primary ownership | Secondary support |
| --- | --- | --- |
| A | FastAPI, Terraform/TFLint/Checkov runner, report schema, fixtures | Extension API integration |
| B | Dataset provenance, mutation engine, feature pipeline, ML experiments/evaluation | Research documentation |
| C | Code-OSS workbench UI, TerraMind panel/dialog, Ollama adapter, demo flow | Integration and tests |

For two people, combine A+C and keep M5 minimal until M1-M3 are complete.

## 11. Definition of done

The mini-project is done when a fresh TerraMind-branded Code-OSS build can analyze at least one valid and several defective AWS Terraform fixtures; surface deterministic results and a model-derived risk probability; generate a reviewable repair proposal; re-run analysis after user approval; and reproduce the documented ML evaluation without data leakage.
