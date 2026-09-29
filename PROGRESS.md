# TerraMind progress log

This file records real work, decisions, tests, and blockers and is included in the private GitHub repository by owner decision. Add an entry for each meaningful work session; do not claim unrun tests or unimplemented features.

## Status snapshot

**Current phase:** M1/M3/M6 - Analyzer and model quality work, plus Windows/Linux alpha packaging pipeline (CI artifacts still need a successful hosted run)

**Next build targets:** run the new model reproducibility and Windows/Linux packaging workflows on `testing`; fix actionable failures; verify the packaged editor and then wire in a bundled analyzer service. Expand analyzer integrations (workspace authorization, Terraform/TFLint/Checkov) before treating packages as end-user ready. Do not merge to `main` until the PR's required checks pass; macOS billing and Microsoft-only runner configuration remain external blockers for upstream CI.

**Overall estimate:** roughly 35–40% of the agreed MVP scope is implemented, based on the milestones below—not a schedule forecast. The analyzer/model foundation exists, while Terraform tool integrations, complete workbench UX, generation/repair, and desktop packaging/build verification remain major unfinished work.

| Milestone | Status | Evidence / remaining work |
| --- | --- | --- |
| M0 - Fork foundation | Partial | TerraMind identity and bundled contribution exist; Windows/Linux preview package workflows are configured, but no successful package output or launch is verified. |
| M1 - Deterministic analyzer | Partial | HCL parsing, AWS heuristic rules, API tests, and Problems diagnostics; Terraform validate/TFLint/Checkov and workspace authorization remain. |
| M2 - Dataset pipeline | Partial | Reproducible, pinned 46-row AWS derived dataset; broader independently sourced/human-reviewed corpus remains. |
| M3 - ML baseline | Partial | Grouped OOF logistic baseline, pair-group bootstrap intervals, and portable inference; tiny sample, no external holdout. |
| M4 - Native workbench UX | Partial | Analyze command and initial activity-bar/Problems integration; full analysis panel, ratings, and generation dialog remain. |
| M5 - Local AI workflow | Not started | Ollama generation, grounded explanations, repair diff/preview, and approval flow are absent. |
| M6 - Demo hardening | Partial | API fixtures/tests and reproducible model evaluation exist; clean desktop demo, screenshots, package execution, and bundled analyzer lifecycle remain. |

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
