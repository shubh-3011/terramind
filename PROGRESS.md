# TerraMind progress log

> **Current status (2026-09-29):** local generation is available through Ollama or an explicitly configured local Transformers model; opt-in scanner adapters, evidence-based/unknown ratings, and an attributed AWS SFT pipeline are implemented. The 26-test API/data/training suite and extension compilation (0 TypeScript errors) pass. The filtered corpus has 43,561 train and 2,229 validation rows. Short Qwen3-0.6B and Qwen3-1.7B LoRA runs completed on CUDA. Their smoke outputs failed meaningful correctness gates (provider schema errors and HCL parse failure); no model-quality claim is made. Current scope estimate: about 65% by milestone coverage. Desktop packaging and GitHub checks remain blockers.

This file records real work, decisions, tests, and blockers and is included in the private GitHub repository by owner decision. Add an entry for each meaningful work session; do not claim unrun tests or unimplemented features.

## Status snapshot

**Current phase:** M1/M3/M6 - Analyzer and model quality work, plus Windows/Linux alpha packaging pipeline (CI artifacts still need a successful hosted run)

**Next build targets:** unblock GitHub Actions billing, then rerun required checks; improve and benchmark generation against a curated, independent provider-valid Terraform suite; add approved-workspace boundaries for external tools; verify desktop packages. Do not merge to `main` until required checks pass.

**Overall estimate:** roughly 65% of the agreed MVP scope is implemented, based on milestone coverage—not a schedule or quality estimate. This includes a reproducible data/training path and optional local Transformers generation. Smoke outputs currently fail correctness gates; this estimate is not a claim that the model is useful or ready. Repair, stronger independent evaluation, workspace authorization, and verified desktop packaging remain.

| Milestone | Status | Evidence / remaining work |
| --- | --- | --- |
| M0 - Fork foundation | Partial | TerraMind identity and bundled contribution exist; Windows/Linux preview package workflows are configured, but no successful package output or launch is verified. |
| M1 - Deterministic analyzer | Partial | HCL parsing, AWS heuristic rules, opt-in CLI/scanner adapters, API tests, and Problems diagnostics; workspace authorization and live tool tests remain. |
| M2 - Dataset pipeline | Partial | Pinned 46-row AWS risk dataset plus a license-aware SFT preparation pipeline; locally prepared 43,561 train / 2,229 validation rows; larger independent risk labels remain. |
| M3 - ML baseline | Partial | Grouped OOF logistic baseline, pair-group bootstrap intervals, and portable inference; tiny sample, no external holdout. |
| M4 - Native workbench UX | Partial | Analyze/Generate commands, activity-bar/Problems integration, draft preview and explicit save, per-service evidence ratings; runtime UI tests remain. |
| M5 - Local AI workflow | Partial | Ollama and optional Transformers-backed generation with preview/save; two short CUDA LoRA runs completed. One output passed HCL syntax but failed AWS provider v6.66.0 schema validation (5 errors); another failed HCL parsing. Model quality remains unproven. |
| M6 - Demo hardening | Partial | 26 API/data/training-script tests; pinned risk evaluation and short SFT smoke metrics. Clean desktop demo, screenshots, package execution, and bundled analyzer lifecycle remain. |

### 2026-09-29 - Local generation, evidence ratings, tools, and SFT preparation

**Implemented and verified locally**

- Added a loopback-only Ollama generation route with model selection, prompt/output bounds, HCL parse gate, and no filesystem writes. Extension flow previews output and requires explicit in-workspace save confirmation.
- Confirmed a real request against local `qwen2.5-coder:3b` returned HTTP 200 and parser-accepted HCL. This proves the request path works, not Terraform provider correctness or safe infrastructure design.
- Added per-service security summaries based on concrete rule evidence. Cost, reliability, scalability, and maintainability remain `insufficient_information` instead of fabricated scores.
- Added opt-in `terraform fmt`, preinitialized `terraform validate`, TFLint, and Checkov runner. External tool invocation is disabled by default; no `init`, `plan`, or `apply` is run.
- Prepared the pinned public generation corpus locally: 43,561 AWS training rows and 2,229 validation rows passed license/HCL filters, with repository-disjoint split assertion and attribution manifest. Dataset/model artifacts stay out of Git.
- Added 22 passing analyzer/data tests; the bundled extension compiles with 0 TypeScript errors.
- Fixed Linux and Darwin PR workflows to invoke the non-executable tracked `scripts/test.sh` through `bash`.

**Not completed / risks**

- No TerraMind generative adapter has been fine-tuned. The downloaded Qwen2.5-Coder model is pretrained; review its research/non-commercial license before any commercial use or model redistribution.
- A small sample of generated HCL was syntax-parsed only. Run Terraform schema validation in a trusted, provider-initialized test fixture before treating output as usable.
- Current Python PyTorch is CPU-only; no CUDA training stack has been installed or training run performed.
- Windows/Linux desktop artifacts and new GitHub checks need hosted verification. Do not merge until required checks are green; runner spending limits can block matrix jobs.

**GitHub state after push (initial snapshot; superseded by the current check below)**

- Pushed commit `6ce24288` to the `testing` branch; PR #6 updated automatically. The PR page reports 26 failing checks, 11 queued, and 2 skipped (snapshot at 2026-09-29). The push-triggered TerraMind ML validation and Linux/Windows packaging checks also failed quickly; full logs were not available in the connected page at inspection time, so their root causes are not yet established.
- The open Dependabot PRs likewise have failing and queued upstream Code-OSS checks. No PR was merged or closed, and `main` was not changed. Merging is deferred until failures are understood and required checks pass.
- A root-wide `pytest` invocation was not a valid project test command because it collected unrelated VS Code Copilot fixture tests; the supported analyzer suite from `services/analyzer-api` passed 22 tests.

**Current GitHub check (2026-09-29, after push `8013cea4`)**

- PR #6 tracks `testing` at `8013cea4`. The new `TerraMind ML validation` run #12 failed after 5 seconds; its annotation explicitly says the job was not started because recent account payments failed or the spending limit needs to be increased. The new Code OSS, CodeQL, Monaco, component-fixtures, chat-lib, telemetry, and packaging runs were still failing/queued at inspection; do not treat these as source-level failures until GitHub actually starts their jobs.
- The five Dependabot PRs remain open with incomplete/failing upstream checks (11–13 failures and 12 incomplete per PR in the last full status snapshot); several checks succeeded, but none of those PRs was green in that snapshot.
- Six PRs remain open (#6 plus #1–#5); none was merged or closed, and `main` is unchanged. Required checks cannot be cleared by changing source while GitHub refuses to start jobs. The repo owner needs to resolve the GitHub account payment/spending-limit notice in **Settings → Billing & plans**, then rerun checks. After that, inspect actual code failures and only merge PRs whose required checks pass.

### 2026-09-29 - CUDA LoRA training and local Transformers generation path

**Implemented and verified locally**

- Added a seeded LoRA SFT command that masks system/user tokens from the loss, pins the base-model revision, stores dataset hashes/metrics, and refuses to run without CUDA. Added a merge command that verifies the base/revision match and creates a local full-model directory.
- Added an optional generation backend selected only by `TERRAMIND_HF_MODEL_PATH`; it loads local-only model files, requires CUDA, caches the model, serializes generation calls, and reuses the existing HCL parser gate. Ollama remains the default when the variable is unset.
- Used an ignored Python 3.12/CUDA 12.6 venv and RTX 4060 to train Qwen3-0.6B (Apache-2.0): 256 train / 64 validation examples, 32 update steps, train loss 1.004 and validation loss 0.942. A generated S3 draft parsed as HCL, but Terraform 1.16.4 + AWS provider 6.66.0 rejected it with five schema errors.
- Trained Qwen3-1.7B at pinned revision `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e` (Apache-2.0): 128 train / 32 validation examples, 16 update steps, train loss 0.913 and validation loss 0.626. These losses are not directly comparable to the 0.6B run because sample size/model differ. Its smoke generation returned HTTP 422 due to unparsable HCL.
- Merged the 1.7B adapter successfully. Ollama 0.18.0 rejected importing its Safetensors directory as `unsupported architecture "Qwen3ForCausalLM"`; the optional Transformers backend is the working local inference route for the merged model.
- Added 4 tests for assistant-only masking and local Transformers backend dispatch; final analyzer suite: 26 passed. TerraMind extension compile: 0 TypeScript errors.
- Installed HashiCorp Terraform 1.16.4 into ignored `.build`; verified its archive SHA-256 against HashiCorp's published checksum. On a throwaway generated-output fixture, `terraform validate -json` correctly reported 5 schema/type errors. No plan/apply ran.

**Not completed / risks**

- The adapters are short smoke runs on a generated/back-translated corpus, not production models. Training/validation loss does not demonstrate valid configurations; independent generation evaluation and larger/better-reviewed Terraform data are needed.
- The full Transformers model must stay local; merged weights and data are ignored and were not uploaded. The default Ollama Qwen2.5-Coder model is non-commercial under its upstream research license; the fine-tuning path uses pinned Apache-2.0 Qwen3 base revisions.
- GitHub PR/check state has not been cleared; no merge is authorized by green evidence yet.

## Log

### 2026-09-28 - Project concept converted into an implementation plan

**Completed**

- Reviewed the supplied TerraMind project-concept PDF.
- Chose a native VS Code extension instead of a Code-OSS/VS Code fork.
- Defined two primary workflows: analyze existing Terraform and generate a connected AWS Terraform architecture from a structured prompt.
- Defined separate deterministic, ML, and LLM responsibilities.
- Added service-rating dimensions: security, reliability/availability, scalability, cost awareness, and maintainability.
- Added a safety rule: generated or repaired Terraform is previewed, user-approved, then re-tested; no `terraform apply` in MVP.
- Initialized a local Git repository and created a local-only planning package.

**Decisions**

- Product/repository name: TerraMind / `terramind`.
- Coding assistant: use a pretrained local coding model through Ollama; do not train a foundation model from scratch.
- Project ML contribution: train a separate Terraform risk model from engineered Terraform/analyzer features.
- PDF and Markdown planning files are local-only and excluded from Git publishing.

**Not yet implemented**

- VS Code extension.
- FastAPI analyzer service.
- Terraform/TFLint/Checkov tool runners.
- Dataset pipeline and trained ML model.
- Ollama integration.

**Next actions**

1. Scaffold the VS Code extension and FastAPI service.
2. Implement workspace detection and a tool-preflight report.
3. Create small valid and deliberately flawed Terraform fixtures.

### 2026-09-28 - Product scope changed from extension to Code-OSS fork

**Completed**

- Changed the planned delivery from a separately installed VS Code extension to a TerraMind-branded Code-OSS fork.
- Defined the first fork milestone: upstream pin, unmodified build, unique TerraMind branding/data directory, native activity-bar view, and analyzer health check.
- Documented that bundled internal extension code may be used inside the fork, but no Marketplace installation is required for end users.

**Impact**

- The development environment and repository will be much larger than an extension project.
- The analyzer, ML, and local LLM designs do not change; only their user-interface integration point changes.
- Build, packaging, upstream maintenance, and licensing notices are now required project work.

### 2026-09-28 - TerraMind fork scaffold and private repository

**Completed**

- Imported and pinned the current Code-OSS source snapshot; retained `upstream` as the Microsoft VS Code remote.
- Created the private GitHub repository `shubh-3011/terramind`.
- Updated `product.json` with TerraMind product identity, application name, data directories, protocol, and platform identifiers.
- Added the bundled `terramind-core` contribution with TerraMind activity-bar view, dashboard placeholder, Analyze Workspace command, and prompt capture commands.
- Added a FastAPI service with `/health` and a first `/v1/analyze` endpoint that finds Terraform files.
- Registered the TerraMind contribution in Code-OSS extension compilation and dependency setup.
- Kept the concept PDF and local planning Markdown files ignored by Git.

**Validation performed**

- Product and extension JSON manifests parse successfully.
- Python API module compiles under Python 3.13.
- TerraMind extension compiles with Code-OSS Gulp: 0 TypeScript errors.
- Root dependency install with native install scripts enabled stops at `@vscode/deviceid` because VS 2019 Spectre-mitigated libraries are absent.
- Root and build dependencies were installed with scripts disabled to enable extension compilation.

**Current blockers / next actions**

1. The first Windows app build needs the VS 2019 x86/x64 Spectre-mitigated C++ libraries (Visual Studio component `Microsoft.VisualStudio.Component.VC.14.29.16.11.x86.x64.Spectre`).
2. Complete the Code-OSS development build and launch the TerraMind-branded window. A `compile-client` attempt did not verify the client: root npm dependencies were installed with scripts disabled, leaving Electron/native dependencies unavailable and producing dependency-related TypeScript errors.
3. Replace the API file-count stub with Terraform format/validate and machine-readable TFLint/Checkov reports.
4. Implement prompt-to-Terraform generation with preview and user approval; no generation or model integration exists yet.
5. Design service ratings as transparent, rule-based findings first; cost, uptime, and scalability ratings need explicit cloud assumptions and should not be presented as guarantees.
6. Defer training a project-specific risk model until labeled Terraform/analyzer data and evaluation criteria exist.

### 2026-09-28 - Private Code-OSS source snapshot pushed

**Completed**

- Created `https://github.com/shubh-3011/terramind` with private visibility.
- Pushed the complete Code-OSS source snapshot and TerraMind identity/core panel to `main`.
- Kept this local progress/plan set and the supplied project-concept PDF out of the repository.
- Retained `upstream` as the Microsoft VS Code remote; the GitHub repository starts from a source snapshot rather than full upstream commit history to keep the initial fork transfer manageable.

**Validation performed**

- GitHub CLI confirms the repository visibility is private.
- Local `main` tracks `origin/main`.
- TerraMind built-in extension compile completed with 0 TypeScript errors.

**Current blocker**

- Full Code-OSS `npm ci` invokes native compilation and stops on MSB8040: VS 2019 x86/x64 Spectre-mitigated C++ libraries are missing. Automated Visual Studio Installer modification did not complete, so a full app build/launch is not yet verified.
- To unblock, use Visual Studio Installer -> Build Tools 2019 -> Modify -> Individual components, search for `Spectre v14.2`, and install `MSVC v142 Spectre-mitigated libs (x86/x64)`. Then rerun `npm ci` under the pinned Node 24.18.0 environment.

### 2026-09-28 - Follow-up build verification

**Completed**

- Rechecked the private repository: `main` points to the pushed snapshot commit and the working tree has no tracked changes.
- Confirmed the local planning files (`PLAN.md`, `ARCHITECTURE.md`, and `PROGRESS.md`) are ignored and absent from the GitHub commit tree.
- Confirmed the TerraMind contribution compilation succeeds with 0 TypeScript errors.

**Not verified / still blocked**

- A Code-OSS `compile-client` attempt failed because the root dependency install had been run with scripts disabled; Electron and other runtime typings were therefore missing. This is not evidence of a successful full client build.
- TerraMind does not yet provide semantic Terraform analysis, compatibility checks, cloud-service ratings, prompt-to-Terraform generation, or a trained model. The current API only discovers/counts Terraform files, and the UI generation path is a prompt-capture placeholder.
- The private repository contains a Code-OSS source snapshot, not the full Microsoft upstream Git history.

### 2026-09-28 - First static Terraform analysis feature

**Implemented**

- Replaced file-count-only response with bounded `.tf` discovery and `python-hcl2` syntax parsing.
- Added stable findings for HCL parse errors (`TM-HCL-001`), public SSH ingress (`TM-NET-001`), and literal wildcard IAM actions (`TM-IAM-001`). Findings distinguish source, rule, severity, relative file/line, and remediation guidance where available.
- Added explicit report states showing Terraform validation, TFLint, Checkov, and ML as not run/not available. No providers or external binaries are executed.
- Wired analyzer findings into the editor's Problems diagnostics, with unsafe relative paths ignored.
- Removed the ignore rules for the plan, architecture, progress, project docs, and concept brief per the owner's updated request to include these in the private repository.
- Updated the product README, design/API docs, fork instructions, decisions, demo framing, and GitHub workflow to match the current implementation.

**Validation performed**

- `python -m pytest -q` in `services/analyzer-api`: 6 passed, including safe-HTTPS behavior and the 500-file cap.
- `npm run gulp -- compile-extension:terramind-core`: 0 TypeScript errors.

**Still incomplete / safety follow-up**

- No workspace allowlist/authorization exists yet; run the API loopback-only. Add a configured approved-root boundary before external tool execution.
- No actual Terraform validate/format, TFLint, Checkov, cost/rating engine, LLM generation, repair, or trained ML model is wired in.
- Full Code-OSS app build/launch remains blocked on native Windows prerequisites.

### 2026-09-28 - Expand AWS rules and train a pinned risk baseline

**Implemented**

- Expanded deterministic AWS findings to cover S3 public-access-block flags and public ACLs, mutable ECR tags, optional EC2 IMDSv2 tokens, explicitly unencrypted EBS, and IAM wildcard resource targets, alongside HCL, public SSH, and wildcard IAM actions.
- Added static expansion of dynamic security-group ingress when it is driven by literal lists/locals, plus an informational finding when dynamic inputs cannot be resolved. This avoids treating unknown values as safe.
- Gathered a small, pinned public benchmark source: IaCSecBench at commit `6e359ac29dcde1974d792f454e1a48dfd9deeaa6` (MIT). Used only generated, labeled AWS cases; excluded Kubernetes and cases with unclear provenance. Kept raw HCL out of TerraMind; committed only 46 derived numeric feature rows, source/control identifiers, and provenance.
- Added a versioned feature extractor and a logistic-regression training pipeline. Case IDs/control IDs/comments are excluded from model features; vulnerable/compliant pairs stay together under five-fold GroupKFold.
- Exported a portable JSON model and integrated inference into `/v1/analyze` and the TerraMind panel. The UI labels it experimental and uncalibrated and shows its 46-example training size.
- Recorded exact training metrics and the limitations in `docs/TRAINING_AND_MODEL.md`; the model estimates benchmark-control violations only, not production outages, cost, uptime, or deployment success.

**Validation performed**

- Analyzer and ML tests in the analyzer virtual environment: 11 passed, including resolved and unresolved dynamic ingress.
- Dataset reproduced from the pinned IaCSecBench checkout: 46 AWS examples, 23 complete pairs.
- Grouped out-of-fold balanced accuracy: 0.674; PR-AUC: 0.764. Dummy-prior balanced accuracy: 0.500. These are small-sample exploratory results, not a performance claim.
- Re-trained the portable model from the generated CSV; model training and inference tests pass.
- TerraMind extension compile: 0 TypeScript errors.
- Analyzer package built/installed in an isolated virtual environment and imported successfully.

**Still incomplete / safety follow-up**

- Terraform provider validation, TFLint, Checkov, path allowlisting, prompt generation, and repair remain unimplemented.
- The model is not calibrated and has no independent labeled repository holdout or human-reviewed expanded corpus; do not use it for real cloud decisions.
- Full Code-OSS desktop launch remains unverified due the previously recorded native Windows build prerequisites.

**GitHub delivery**

- Pushed analyzer feature commit `3044361d` and project documentation/brief commit `ef667084` to the private repository's `main` branch.
- Verified `main` includes `PLAN.md`, `ARCHITECTURE.md`, `PROGRESS.md`, all TerraMind `docs/*.md`, and the supplied concept PDF. The repository remains private.

### 2026-09-28 - Dynamic ingress coverage and integration retest

**Implemented and verified**

- Expanded literal `dynamic "ingress"` blocks driven by local lists for both deterministic SSH analysis and numeric ML features. Unresolvable `for_each` inputs now produce informational review finding `TM-NET-003`; unknown values are not treated as safe.
- Rebuilt the pinned 46-row derived dataset and retrained the exported model after the feature logic change. The refreshed dataset checksum is recorded in the manifest; grouped OOF balanced accuracy is 0.674 and PR-AUC is 0.764.
- Analyzer/ML suite: 11 passed; Python compile check passed.
- End-to-end API request against the benchmark's vulnerable dynamic-ingress example parsed both Terraform files, emitted `TM-NET-001`, and returned the separate experimental estimate.
- `npm run gulp -- compile-extension:terramind-core`: 0 TypeScript errors.

**Still incomplete**

- Full Code-OSS desktop build and launch are unverified due native Windows build prerequisites. The model remains small, uncalibrated, and benchmark-control scoped; more independently labeled data and external validation are required.

### 2026-09-29 - Repair private-repository pull request checks

**Implemented**

- Added the missing `extensions/terramind-core/package-lock.json`, required by the repository's npm workspace cache-key generator after TerraMind was added to the npm workspace list.
- Granted read-only `contents` permission to the Monaco and telemetry workflows so their checkout steps can read this private repository.
- Skipped CodeQL upload for Dependabot PR events because Dependabot's workflow token is read-only; CodeQL remains enabled for regular PRs, main-branch pushes, and scheduled scans.

**Validation**

- `node build/azure-pipelines/common/computeNodeModulesCacheKey.ts compile x64` succeeds with the new extension lockfile.
- PR checks must be rerun by GitHub after these changes reach the base branch; CI resolution is not claimed until those runs complete.

### 2026-09-29 - Synchronize Dependabot PRs and refresh project docs

**Implemented**

- Updated all five open Dependabot PR branches with the current `main` commit (`188e18bf`) so GitHub receives fresh synchronize events and can rerun checks against the CI fixes.
- Refreshed every TerraMind-owned project Markdown document (`README.md`, `PLAN.md`, `ARCHITECTURE.md`, and `docs/*.md`) to describe the same current feature set, training scope, build limitations, data-tracking policy, and CI state. Upstream VS Code documentation and test-fixture Markdown were not rewritten as project progress documents.
- Corrected stale data-policy text: raw benchmark Terraform stays outside the repo; the small derived numeric CSV, provenance manifest, exported JSON model, and metrics are intentionally tracked in the private repository.

**Current build status and remaining check**

- Local verified checks remain: 11 analyzer/ML tests pass; the bundled TerraMind extension compiles with 0 TypeScript errors; the npm workspace cache-key script succeeds; workflow YAML parses.
- The CI bootstrap issues found in the earlier GitHub runs were addressed: the TerraMind npm workspace now has a lockfile, Monaco/telemetry can read the private repo, and Dependabot CodeQL uploads are skipped because its token is read-only.
- GitHub Actions inspection identified two actionable workflow defects: `apt-retry.sh` is tracked as mode `100644` but was invoked as an executable in Linux test and Copilot setup workflows; CodeQL checked `github.actor`, which becomes the account that synchronizes a Dependabot PR rather than the PR author.
- Updated both workflows to run the helper explicitly with `bash`, and changed CodeQL's skip condition to check the pull-request author's login while keeping push and scheduled scans enabled.
- Latest Code-OSS run also has external execution blockers: macOS jobs report account billing/spending-limit failure, and Microsoft-specific self-hosted runner jobs remain queued. These are not source-code failures and need GitHub billing/runner configuration; no successful full matrix is claimed.
- Pushed the workflow and documentation fixes to `main` as `23d77fc9` and merged that commit into all five open Dependabot branches to trigger fresh checks.
- Local verification passed: all three edited workflow YAML files parse, `services/analyzer-api` has 11 passing tests, the TerraMind extension compiles with 0 TypeScript errors, and `git diff --check` is clean.
- Initial status on the fresh PR run was queued; follow-up inspection after sign-in confirmed Linux Electron-Unit passed `Setup system services` (including the repaired apt helper) and progressed into dependencies/transpilation. The full test job was still running at last check. macOS remains blocked by account billing, and Microsoft-only self-hosted checks remain unavailable; remote CI is not fully green.
- The complete Code-OSS desktop build/launch is still unverified; earlier local Windows build attempts were blocked by missing Spectre C++ libraries and incomplete Electron/native dependencies.

### 2026-09-29 - Add uncertainty-aware model evaluation and preview build workflows

**Implemented on `testing` (not yet merged)**

- Added reproducible 95% percentile intervals for balanced accuracy and PR-AUC by resampling complete control-pair groups over fixed grouped out-of-fold predictions (2,000 seeded resamples). The report explicitly limits interpretation to the 23 benchmark control pairs.
- Regenerated the tracked model and metrics from the 46-row dataset. Point estimates remain balanced accuracy 0.674 and PR-AUC 0.764; grouped-bootstrap intervals are 0.587–0.783 and 0.656–0.867 respectively. This does not add independent training data or establish generalization.
- Added a GitHub Actions workflow that rechecks the pinned benchmark-derived CSV, runs API/ML tests, retrains the model, and uploads the model/report as a short-lived artifact.
- Added a Windows x64 and Linux x64 Code-OSS preview packaging workflow. Commits to `testing` create downloadable Actions artifacts; a `terramind-v*` tag can produce a **draft** private GitHub release only after both platform builds succeed.
- Kept upstream source intact. No optional features were removed without package-size/dependency evidence; the workflows target downloadable alpha builds, not a production installer.

**Validation and remaining work**

- The benchmark extractor reproduced the committed CSV byte-for-byte from IaCSecBench commit `6e359ac29dcde1974d792f454e1a48dfd9deeaa6`.
- The analyzer/ML suite passes 11 tests; fresh training completed with the expected point estimates and produced the new pair-group intervals.
- GitHub workflow execution and desktop package outputs are pending. The app still requires manually starting the analyzer service; packaging the service lifecycle is a prerequisite for a useful end-user download.
- No main-branch merge is claimed. The feature branch must pass its ML and package workflows and applicable PR checks first.
- The first hosted `testing` run found two fixable workflow issues: the dataset comparison used a repository-root path while running from `services/analyzer-api`, and packaging did not apply Code-OSS's Linux native-build environment before `npm ci` (the install stopped at `native-keymap`). The next run confirmed the rebuilt dataset matched in content but differed in platform line endings; comparison now normalizes CRLF/LF. Linux/Windows dependency setup is aligned with the repo's platform build helpers. Reruns are pending; neither package is claimed successful yet.
- A subsequent hosted Linux build reached Code-OSS's libc++ setup but revealed that setup also depends on build-tool packages (`build/node_modules/debug`). Added the upstream workflow's separate `npm ci` in `build/` before Linux setup; the next hosted run will verify that sequencing.

### 2026-09-29 - Add local generation, opt-in analysis tools, and an attributed SFT data path

**Implemented on `testing` (not yet merged)**

- Added `POST /v1/generate` backed only by a loopback Ollama endpoint. It bounds input/output sizes, parses returned HCL, reports syntax-only validation scope, rejects non-loopback configured URLs, and never writes a file.
- Replaced prompt-capture placeholder with a built-in Generate flow: collect requirement and constraints; open a draft preview; save only when the user explicitly chooses a path inside the open workspace; confirm overwrite separately; then run Analyze. Added configurable local model default `qwen2.5-coder:3b`.
- Added opt-in integrations for Terraform `fmt`, `validate` only when provider initialization already exists, TFLint, and Checkov. They are disabled by default; TerraMind never runs `init`, `plan`, or `apply`. Child processes have bounded runtime/output, run without shell, use an isolated home, and receive no cloud credential variables. Provider plugins may execute during `terraform validate`, so users must trust the workspace before opting in.
- Added pinned SFT corpus preparation for the AWS slice of `SASVAAI/terraform-multicloud` at revision `dced854e79a6aadb89f12b3ba74b31720264ea40`. The script filters unlicensed/unparseable/non-AWS entries, preserves per-row repository/license provenance, checks train/validation repo disjointness, writes data only to the selected folder (documented `.build`), and emits hashes plus `ATTRIBUTION.csv`. This is a generation corpus, not risk labels.
- Updated the TerraMind-owned plan, architecture, data, training, build, demo, decision, and progress documents to keep implementation claims aligned.

**Validation performed**

- Analyzer, model, generation-route, scanner-adapter, and SFT-data tests: 22 passed in the final focused suite.
- `npm run gulp -- compile-extension:terramind-core`: 0 TypeScript errors.
- SFT filtering tests cover AWS-only selection, permissive-license allowlist, HCL parse, repository split leakage, and attribution metadata.
- A real local Ollama inference returned HCL accepted by the HCL parser; this does not establish Terraform provider correctness. Installed system Python is CPU-only despite an RTX 4060 8 GB GPU; no generative fine-tuning run or adapter is claimed.
- Windows/Linux Actions package jobs are failing or queued at latest inspection; no desktop artifact is verified. Main branch has not been updated.

**Current estimate and remaining blockers**

- Updated scope coverage estimate: 60–65%, not yet the requested 65–70%. This is a milestone-coverage estimate, not a quality or schedule claim.
- To reach a credible 65–70% milestone, next verify the desktop build/package path and resolve hosted checks; then train or validate a small license-compatible generator adapter. Cost/reliability/scalability remain explicit unknowns where evidence is missing. A fine-tuned generator needs a compatible CUDA training stack, training time, and an evaluation set separate from the training corpus.
- Six PRs were open at the start of this work: TerraMind #6 and five Dependabot updates. Do not merge any until relevant checks are green; existing GitHub runner/billing limitations may prevent clearing every inherited Code-OSS matrix check.
