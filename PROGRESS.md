# TerraMind progress log

> **Update (2026-10-02, desktop fixed):** the **native Windows app now opens**. Root cause: an earlier local workaround had replaced `node_modules/@vscode/policy-watcher/index.js` with a stub whose `createWatcher` never invokes its callback. `NativePolicyService._updatePolicyDefinitions()` awaits a promise resolved only from that callback, so `configurationService.initialize()` never resolved and `CodeMain.initServices` hung **before** any window (silent, no logs, and `--version` hung too). Fixed by restoring the real loader and adding a **5s `raceTimeout` guard** in `src/vs/platform/policy/node/nativePolicyService.ts` so a missing/broken native policy watcher can never brick startup again. Verified: `VSCode-win32-x64\TerraMind.exe` opens a window with a renderer + workbench (`"Welcome … TerraMind - AI-Native Terraform IDE"`). Committed `6ce298b0`. The browser workbench also remains available.

> **Update (2026-10-02, later):** TerraMind now also runs as a **browser workbench** with the extension integrated, because the **native Electron window does not open on this machine**. `scripts/code-web.bat` (via `scripts/web_live.bat`) serves the real workbench at `http://localhost:8080`; the extension has a **web build** (`extensions/terramind-core/esbuild.browser.mts` + a `browser` entry) and the analyzer gained **localhost-only CORS** so the browser can call it. Added **Check Analyzer Connection** (and an auto health check) plus **Analyze Demo Fixture**, which analyzes a local Terraform fixture **server-side, so it works in any browser including Brave** (Brave blocks the File System Access folder picker). A full Windows x64 package was produced (`VSCode-win32-x64\TerraMind.exe`, 228 MB) and all 13 missing native modules were rebuilt by disabling Spectre mitigation (the VS component id is absent from this 2019 Build Tools graph). **However**, the desktop app still never opens a window: with the Node inspector, `app.isReady()===true` but `BrowserWindow.getAllWindows().length===0`, `TerraMind.exe --version` hangs, no logs are written, and Electron itself (`v43.7.3`) and stock VS Code both work. Ruled out: native modules, policy-watcher, Spectre, proxy, Cloudflare WARP, user-data, GPU flags, dev-vs-packaged. Analyzer suite: **120 passing**.

> **Update (2026-10-02):** TerraMind now **ships its own Terraform model and needs no Ollama**. A LoRA fine-tune of `Qwen2.5-Coder-1.5B-Instruct` (Apache-2.0) was trained on a 72k-row **multi-cloud** corpus (v2 = 2 epochs, `eval_loss` 0.460), merged, and quantized to a **940 MB Q4_K_M GGUF** that the analyzer **auto-discovers** (drop it in `services/analyzer-api/models/`; the `auto` engine prefers `gguf`). Verified with no env vars: generation returns valid HCL from the bundled model. Honest quality on 12 held-out examples: **83% parse / 42% `terraform validate`** (v1: 75% / 50%; the provider gap is within noise at n=12). The model is a **review-required draft assistant**, not a correctness guarantee; the deterministic analyzer and opt-in provider validation still gate every draft. Analyzer/data/training/eval suite: **120 passing**; extension TypeScript check clean. A deterministic post-processor auto-declares undeclared `var.*` references. Everything is committed to `main` and `testing`.

> **Update (2026-10-01, wave 2):** TerraMind is no longer AWS-only. The deterministic registry now holds **66 rules** across provider-agnostic general Terraform hygiene (`TM-GEN-*`: CLI/provider/module pinning, backend state, variable/output documentation), AWS, **Azure** (`azurerm_*`), and **Google Cloud** (`google_*`). Ratings score resources from **any provider** and create entries for services that only have findings. The bundled extension gained a **TerraMind Report** webview (service scores, ranked recommendations, grouped findings) and activity-bar welcome actions wiring the guided wizard and report. The Ollama path is now speed-tunable (`TERRAMIND_OLLAMA_NUM_PREDICT`, `_TEMPERATURE`, `_NUM_CTX`, `_KEEP_ALIVE`) and a new [`docs/MODEL_STRATEGY.md`](docs/MODEL_STRATEGY.md) recommends an existing quantized coder model over the tiny self-trained adapters. Analyzer suite: **72 passing** (from 44); extension TypeScript check clean. Committed to `testing` as `862f4a4e`, `149adc1d`, `cdae8fcc`, `937c8b90`, `2c89f391`, `7e416d2f`. Deterministic static checks only; the Windows native launch and hosted CI billing blockers are unchanged.

> **Update (2026-10-01, wave 1):** the deterministic analyzer exposed an extensible AWS rule registry with **45 rules** across networking, IAM, storage (S3/EBS/EFS), database (RDS/Aurora/DynamoDB/ElastiCache), compute (EC2/ASG/Lambda/ECS/EKS), observability, and secrets hygiene. Per-service ratings moved to `aws-rubric-v2`: **security, reliability, and maintainability are scored from observable evidence**, while scalability and cost stay explicitly `insufficient_information`. `/v1/analyze` and `/v1/generate` also return a **prioritized recommendation list**. A `TERRAMIND_ALLOWED_ROOTS` workspace allowlist guards analyze/generate/repair.

> **Current status (2026-09-29):** local generation is available through Ollama or an explicitly configured local Transformers model; generated HCL receives TerraMind static security checks and evidence-limited service ratings, plus optional preinitialized-cache Terraform provider validation before preview. VS Code Restricted Mode suppresses optional external tools for both analysis and generated-draft validation. The model gets at most one parser/provider-feedback retry. A same-split/seed, 3-example post-retry smoke run parsed 2/3 outputs (one recovered after retry), with one HTTP 422; resource-type micro-F1 was 0.471 across the two parseable cases and mean latency was 99.7 seconds. With the locally cached AWS provider enabled, both parseable outputs still failed provider validation after retry (0/2 schema-valid), while the third remained HTTP 422; mean latency was 107.3 seconds. A separate 384-token experiment returned HTTP 422 for both adapters after about 146 seconds; direct inspection confirmed the 0.6B model stopped exactly at token 384 and produced truncated HCL (parse error line 38). The default therefore remains 2,048 tokens; lower values are configurable but risk truncating Terraform. The 1.7B model exceeded the evaluator's 180-second timeout at higher limits. These are pipeline/performance observations, not quality claims. The 44-test API/data/training/evaluation suite passes. The full official `npm run compile-client` build succeeds with zero errors, including the TerraMind extension. Interactive desktop startup remains blocked by the missing native Windows `@vscode/policy-watcher` binary and Spectre libraries. Visual Studio Installer confirmed that adding the matching component requires UAC elevation; no system components were changed. GitHub Actions jobs are currently blocked before startup by an account payment/spending-limit restriction. Current scope estimate: about 65% by milestone coverage. Native launch, desktop packaging, and hosted checks remain blockers.
> **Status update (2026-09-29):** the local suite now has 44 passing tests. A repair endpoint and **Propose Terraform Repair** command produce a full-file proposal from one local `.tf` document and TerraMind diagnostics, validate its HCL/static findings (and optional cached-provider result), show a diff, and only apply after modal approval. The extension refuses to apply if the source document changes while the proposal is being reviewed; approved edits trigger workspace re-analysis. See the entry below. This feature is a review workflow, not evidence that model repairs are correct.

> **Latest hosted check snapshot (feature commit `fd8a59a7`, 2026-09-29):** PR #6 remains open and unmerged; the current testing branch also contains docs-only commit `c215490e`. GitHub reported failures for TerraMind ML validation, Windows/Linux packaging, CodeQL, and several upstream Code OSS workflows; no package artifact is verified. The latest detailed runner-start annotation available in the Actions UI says jobs were not started because recent account payments failed or the Actions spending limit needs to increase. The Code OSS workflow also remained queued at the latest snapshot. Do not treat these as source-level test results or merge until the account restriction is cleared and required checks actually run and pass.

This file records real work, decisions, tests, and blockers and is included in the private GitHub repository by owner decision. Add an entry for each meaningful work session; do not claim unrun tests or unimplemented features.

## Status snapshot

**Current phase:** M1/M3/M6 - Analyzer breadth and rating quality work (broadened rules and evidence-scored dimensions), plus model quality and the Windows/Linux alpha packaging pipeline (CI artifacts still need a successful hosted run)

**Next build targets:** unblock GitHub Actions billing, then rerun required checks; improve and benchmark generation against a curated, independent provider-valid Terraform suite; verify desktop packages. Do not merge to `main` until required checks pass.

**Overall estimate:** roughly 68-70% of the agreed MVP scope is implemented, based on milestone coverage—not a schedule or quality estimate. The deterministic analyzer and rating breadth advanced materially on 2026-10-01 (45 rules, scored security/reliability/maintainability, prioritized recommendations). This still includes a reproducible data/training path and optional local Transformers generation whose smoke outputs fail correctness gates; this estimate is not a claim that the model is useful or ready. Independent generation/repair evaluation and verified desktop packaging remain.

| Milestone | Status | Evidence / remaining work |
| --- | --- | --- |
| M0 - Fork foundation | Partial | TerraMind identity and bundled contribution exist; Windows/Linux preview package workflows are configured, but no successful package output or launch is verified. |
| M1 - Deterministic analyzer | Partial | HCL parsing and a 66-rule extensible registry: provider-agnostic general hygiene plus AWS, Azure, and GCP rules across networking/IAM/storage/database/compute/observability/secrets; opt-in CLI/scanner adapters suppressed in VS Code Restricted Mode; `TERRAMIND_ALLOWED_ROOTS` workspace allowlist; API tests and Problems diagnostics. Live installed-tool tests and authenticated (non-caller-asserted) authorization remain. |
| M2 - Dataset pipeline | Partial | Pinned 46-row AWS risk dataset plus a license-aware SFT preparation pipeline; locally prepared 43,561 train / 2,229 validation rows; larger independent risk labels remain. |
| M3 - ML baseline | Partial | Grouped OOF logistic baseline, pair-group bootstrap intervals, and portable inference; tiny sample, no external holdout. |
| M4 - Native workbench UX | Partial | Analyze/Generate/Propose Repair commands, a guided Generate **webview form**, a **TerraMind Report** webview (scores, recommendations, findings), activity-bar welcome actions, Problems integration, generated-draft and repair diff preview, explicit approvals, `aws-rubric-v2` security/reliability/maintainability scores, prioritized recommendations, trust signal, optional provider validation, and post-approval re-analysis; runtime UI tests remain. |
| M5 - Local AI workflow | Partial | Ollama and optional Transformers-backed generation; one bounded parser/provider-feedback retry; repair proposal validated and shown as a reviewable diff; optional schema checks against preinitialized providers; two short CUDA LoRA runs completed. Post-retry smoke: 2/3 parseable, one recovered; provider-enabled: 0/2 parsed outputs schema-valid after retry. Tiny sample only; repair correctness and useful-scale quality remain unmeasured. |
| M6 - Demo hardening | Partial | 44 API/data/training/evaluation-script tests; pinned risk evaluation and short SFT smoke metrics. Clean desktop demo, screenshots, package execution, and bundled analyzer lifecycle remain. |

### 2026-09-29 - Bound local Transformers generation and measure adapter latency

- Added `TERRAMIND_HF_MAX_NEW_TOKENS`, bounded to 128–2,048 with a default of 2,048 that preserves prior behavior. Invalid values fall back safely; lowering the cap can truncate a Terraform draft before it parses.
- Enabled the Transformers tokenizer's recommended `fix_mistral_regex` correction after the pinned Qwen tokenizer emitted a warning that its default regex could tokenize incorrectly.
- Added unit coverage for the token-limit default, lower/upper bounds, and invalid configuration. Full analyzer/data/training/evaluation suite: 44 passed.
- Reproduced the same repository-disjoint validation example (hashed ID `2e4fe917ca7c4558`, seed 29) with both merged Qwen3 adapters at an explicit 384-token cap. Each returned HTTP 422 after about 146 seconds. An in-memory inspection of the 0.6B model's first response showed exactly 384 generated tokens and an HCL parse failure at line 38, confirming output truncation; no source or output text was printed or saved. The 1.7B adapter at the earlier 768 and 2,048-token settings exceeded the evaluator's 180-second request timeout. These are single-example pipeline/latency observations, not model-quality comparisons.
- No dataset, prompt, generated code, adapter weights, or local evaluation JSON was added to Git. The Transformers backend remains opt-in and is not ready for interactive generation on this hardware; Ollama remains the default. The next useful model step is a bounded, user-intent benchmark with valid-provider targets and per-example error categories, not claiming success from training loss.
- The PR checks inspected during this session were not started because GitHub reports an account payment/spending-limit restriction. The desktop native-module prerequisite also remains blocked until the matching Visual Studio component is installed in an elevated session.

### 2026-09-29 - Reviewable Terraform repair proposal

- Added `POST /v1/repair` for one bounded Terraform file, up to 50 findings, optional instructions, and the configured local model. The repair prompt treats file content and findings as untrusted data; the endpoint returns only an HCL-parsed proposal with TerraMind static findings and evidence-limited ratings. Optional provider validation uses the same trusted-workspace/preinitialized-cache guard and never initializes, plans, or applies.
- Added the built-in **Propose Terraform Repair** command and editor-title affordance for local `.tf` files. It submits only the active file and its TerraMind diagnostics, opens a VS Code diff, requires explicit modal approval, checks the document version/content has not changed, applies/saves a single workspace edit, and reruns workspace analysis. Existing unsaved changes require an explicit save before the proposal is requested.
- Added tests that verify original code/findings/instructions reach the local model, reject unparsable output, and confirm the endpoint does not write files. Analyzer/data/training/evaluation suite: 43 passed. Extension TypeScript project check passed with no diagnostics; command/package JSON parsed successfully.
- This provides a review/approval path but does not guarantee semantics or provider compatibility, and there are not yet interactive VS Code integration tests for the diff/apply race guard.

### 2026-09-29 - Desktop launch verification attempt

- First launch failed because the VS Code output tree was incomplete. Restored dependencies from the committed lockfiles and ran the official `npm run compile-client` build; it completed successfully with zero source/extension errors after about 7 minutes, producing `out/vs/base/parts/ipc/common/ipc.js` and compiling `extensions/terramind-core`.
- A second isolated launch passed the missing-module failure but the workbench main process exited while loading `@vscode/policy-watcher`: no native `.node` binary was available. Running dependency installs with lifecycle scripts disabled avoided the machine's native-build error, but the binary is required on Windows. An attempted native install reports MSBuild `MSB8040` because the installed VS 2019 toolchain lacks Spectre-mitigated libraries. The repair command therefore remains unverified interactively.
- The launch created untracked `data/argv.json` and `data/user-data/` artifacts in the repository. They are local launch state, not project inputs, and must not be committed.
- GitHub PR #6 is still open. Its last retrieved feature-code check snapshot failed ML, Windows/Linux package, and several upstream checks; the prior Actions UI diagnostic attributes runner-start failures to account payment/spending-limit restrictions. No merge or package publication was performed.
- **Resume plan:** install the matching Spectre-mitigated C++ libraries with Visual Studio Installer, rebuild the native policy watcher, relaunch the already-compiled app, then run an interactive repair-command check against a disposable Terraform fixture and local analyzer. Re-fetch PR checks and resolve the account Actions-spending/payment restriction before any merge. Keep weights and non-redistributable/raw source data out of Git; continue licensing/provenance checks for any added training corpus.

### 2026-09-29 - Structured infrastructure generation inputs

- Expanded Generate Infrastructure with separate optional fields for resource types/counts and connectivity/traffic flow, in addition to the original requirements and constraints prompts.
- The extension sends each field independently; the analyzer labels each section in the local model prompt and supplies explicit fallback text when optional inventory/topology are omitted. API defaults preserve compatibility with existing callers.
- Added an API test proving inventory, topology, and constraints reach the model prompt. Analyzer/data/training/evaluation tests: 41 passed; extension TypeScript project check: passed with no diagnostics.
- This improves prompt structure and input fidelity, but does not establish that a model will produce correct counts, topology, or provider-valid infrastructure. User review and validation remain required.

### 2026-09-29 - Validate generated HCL against a local provider cache

**Implemented and verified locally**

- Added an opt-in generated-draft `terraform validate` path tied to the existing `terramind.analysis.runExternalTools` setting. It requires an existing `.terraform.lock.hcl` and `.terraform/providers` cache; if either is absent, it reports a clear not-run state.
- Validation runs in a disposable scratch directory using hardlinked/copied provider files and the lockfile. It does not run `terraform init`, `plan`, or `apply`; it invokes no shell, has a 45-second timeout, isolates Terraform's data/home directories, and removes cloud, `TF_*`, Vault, and related credential variables before launching Terraform/provider plugins.
- The Generate command reports the check status and line-specific validation findings before the save prompt. Saving still requires explicit in-workspace confirmation.
- Verified with Terraform 1.16.4 and the locally initialized HashiCorp AWS provider 6.66.0: an intentionally incompatible generated draft produced three schema errors on exact lines. No network initialization or cloud call was made.
- Added validator/API opt-in tests, including default-off behavior, missing-cache behavior, credential scrubbing, and scratch-directory cleanup. Analyzer suite at that commit: 34 passing. The Code-OSS Gulp extension command is unavailable in this checkout because `build/gulpfile.extensions.mjs` and `extensions/terramind-core/node_modules/vscode/bin/compile` are absent; a later direct native TypeScript project check is recorded below.
- Pushed commit `8aa8b253` to `testing`; PR #6 updated. Hosted ML validation run #21 and Windows/Linux packaging run #19 both failed before jobs started with GitHub's recent-payments/spending-limit annotation. The PR's Code OSS workflow has the same account-block annotation on attempted jobs and additional jobs queued. These are not source-level failures; no hosted artifact was produced. The PR remains open and `main` remains unchanged.

### 2026-09-29 - Respect VS Code workspace trust before external checks

**Implemented and verified locally**

- The built-in extension now sends VS Code's `workspace.isTrusted` state with analysis and generation requests. The API skips Terraform, TFLint, and Checkov execution when the workspace is in Restricted Mode, even if the user setting is enabled, and reports the reason in each check status.
- Added tests proving the analyze and generate paths do not invoke external processes for an untrusted workspace. Analyzer suite: 36 passing.
- Verified the extension sources with the bundled native TypeScript compiler: `node_modules/.bin/tsc --noEmit -p extensions/terramind-core/tsconfig.json` completed with exit code 0 and no diagnostics. This is a typecheck, not the full Code-OSS extension packaging build.
- Pushed commit `1e775d18` to `testing`; PR #6 is still open. GitHub run #24 for the ML validation failed before starting due to the account payment/spending-limit block. The next pushed evaluator commit `ce4d57b3` has a queued ML job at the latest inspection; no new passing hosted build/artifact is available yet.

### 2026-09-29 - Measure provider compatibility in local generation evaluations

**Implemented and verified locally**

- Extended the repository-disjoint generation evaluator with optional provider-schema acceptance counts using `--provider-workspace`. Before sending any prompts, the evaluator verifies the supplied workspace exists and has both `.terraform.lock.hcl` and `.terraform/providers`.
- When selected, each generation request explicitly opts into `terraform validate` against the installed local cache; no provider workspace path, prompt, or Terraform source is written to the aggregate report. No `init`, `plan`, or `apply` is run. The CLI help warns that Terraform provider plugins execute.
- Added tests for accepted schema metric reporting, provider-path privacy, and preflight refusal of missing caches. Analyzer/data/training/evaluation suite: 38 passing. Extension TypeScript project check: exit code 0, no diagnostics.
- This compatibility metric still does not prove semantic correctness, security, runtime behavior, cost, availability, or model quality. The 3-example smoke result remains far too small for quality conclusions.
- Pushed commit `ce4d57b3` to `testing`. At inspection, its ML validation run #26 failed before job start with the same GitHub payment/spending-limit notice; related PR checks were queued. Six pull requests remain open (#6 and Dependabot #1-#5). Inspection of old-base PR #1 and #2 checks found a concrete Linux CI defect: Electron unit tests invoke `./scripts/test.sh` directly and fail with “Permission denied” (exit 126). The fix (`bash ./scripts/test.sh`) exists on `testing`, but these PRs have not tested against that fix. Keep them open and unmerged until the base workflow is fixed and their required checks pass.
- This is a Restricted Mode guard in the first-party extension workflow, not API authentication: callers can forge the JSON trust flag. The service must remain bound to loopback; a stronger authenticated workspace authorization mechanism remains open.

### 2026-09-29 - Retry generated Terraform once from validation feedback

**Implemented and verified locally**

- Added a single bounded retry for generated HCL. If the first output fails parsing, the local model receives the parser diagnostic and original draft. If trusted opt-in `terraform validate` finds line-specific provider-schema errors, those diagnostics are fed into one repair prompt and the revised draft is parsed and validated again.
- Repair prompts explicitly treat the original request, HCL, and diagnostics as untrusted data. No generated code is written automatically; the editor previews the final attempt and still requires explicit save approval. No `terraform init`, `plan`, or `apply` was added.
- The API now exposes a `generation_repair` check, and the evaluation report version 2 records retry-status counts and parseable outputs recovered after retry without retaining prompt/code/path data.
- Added tests for parse-error retry, provider-error retry followed by successful revalidation, and evaluator retry metrics. Analyzer/data/training/evaluation suite: 40 passed. The extension's existing TypeScript project check remains clean; its UI behavior is unchanged.
- Ran the updated evaluator on the same three-case held-out split/seed as the historical pre-retry smoke. Parse-only: 2/3 HCL parseable, with one output recovered after retry; one case remained HTTP 422. Resource-type micro-F1 was 0.471 across two parseable cases; mean latency 99.7 seconds. This is not a statistically useful model-quality estimate.
- Repeated with the locally cached AWS provider and explicit Terraform binary. Both parseable drafts still failed provider validation after their single retry (0/2 provider-valid); the third case remained HTTP 422. Mean latency was 107.3 seconds. Reports are local ignored `.build` artifacts and contain aggregate metrics only; no dataset, generated code, or workspace paths were added to Git.
- This is one auto-correction attempt, not the planned reviewable diff/repair workflow. No full local-model benchmark has been rerun, so no model quality improvement is claimed.

### 2026-09-29 - Analyze generated Terraform before preview

**Implemented and verified locally**

- The generation API now parses the generated configuration once, runs TerraMind's existing deterministic AWS security checks in memory, and returns findings plus evidence-limited service ratings alongside the HCL. It does not write files or initialize Terraform providers.
- The built-in Generate command records those findings and service dimensions in the TerraMind output channel and reports error/warning counts in the pre-save review prompt. Provider schema/reference compatibility, external scanners, cost, uptime, scalability, and deployment behavior remain explicitly unverified.
- Added a test using an insecure generated public-SSH security group; the response includes `TM-NET-001`, a limited networking security rating, and syntax-vs-provider validation limits. Analyzer suite: 27 passing. TerraMind extension compile: 0 TypeScript errors.
- The API creates only preview content; the existing explicit in-workspace save/overwrite confirmation remains required.

### 2026-09-29 - Add reproducible local generation evaluation

**Implemented and verified locally**

- Added a deterministic held-out evaluation CLI that calls only a loopback analyzer endpoint and reports HCL parse rate, resource-type micro precision/recall/F1, latency, backend name, dataset/manifest hashes, and hashed example identifiers.
- The report intentionally excludes prompts, reference/generated Terraform source, and source repository paths. It documents that the corpus uses back-translated prompts and that resource overlap is not semantic/provider correctness.
- Ran the merged Qwen3-0.6B smoke model over 3 repository-disjoint validation examples (seed 29): 1/3 outputs parsed; 2/3 returned HTTP 422; resource-type micro-F1 0.286; mean request latency 83.5 seconds. This small result is evidence of current weakness and that the evaluator works, not a quality estimate.
- Added 4 evaluator tests (loopback enforcement, metric aggregation/no raw code in report, parse-failure accounting, and unknown F1 when no resources were generated); analyzer suite now passes 31 tests. Extension compile remains 0 TypeScript errors.

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

**Historical GitHub check snapshot (2026-09-29, after push `3701b1cc`; superseded by later pushes)**

- PR #6 tracks `testing` at `3701b1cc`. New `TerraMind ML validation` run #19 failed after 4 seconds; its annotation again states the job was not started because recent account payments failed or the spending limit needs to be increased. Code OSS run #27 was queued at inspection, while several other PR checks showed quick failures. This repeated annotation confirms the account blocker; queued or quick-failing checks should not be treated as source-level failures until their jobs actually start.
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

### 2026-10-01 - Broadened AWS rules, scored dimensions, recommendations, and guided generation

**Implemented and verified locally**

- Added an extensible deterministic rule registry under `services/analyzer-api/app/rules/` with a shared `Rule`/`RuleHit`/`RuleHelpers` contract (`base.py`) and a defensive `evaluate_rules` aggregator that skips a failing rule rather than failing an analysis request. The registry now holds **45 rules** across networking, IAM, storage (S3/EBS/EFS), database (RDS/Aurora/DynamoDB/ElastiCache), compute (EC2/launch/ASG/Lambda/ECS/EKS), observability, and secrets hygiene. The registry is invoked from `_static_security_findings`, so both Analyze and Generate receive the expanded checks with line locations and remediation guidance.
- Upgraded per-service ratings to `aws-rubric-v2`. Security keeps the existing evidence-weighted penalty scheme and now attributes findings through the registry; **reliability** (multi-AZ, backups, deletion protection, ASG health checks, load-balancer spread, versioning) and **maintainability** (tags, hardcoded-vs-referenced values, module usage, pinned provider versions) are scored from attributes actually present in the parsed HCL. `scalability` and `cost` remain explicit `insufficient_information`. Every scored dimension carries `criteria_version`, `evidence`, `evidence_finding_ids`, `assumptions`, and `limitations`.
- Added `app/recommendations.py` and surfaced a prioritized recommendation list from `/v1/analyze` and `/v1/generate`: findings are grouped by rule, ordered by severity then occurrence count, and annotated with the rule's remediation text.
- Added `app/workspace_guard.py`: `TERRAMIND_ALLOWED_ROOTS` (path-separator list) now constrains analyze/generate/repair to approved roots; the guard resolves paths before comparison so symlinks/junctions cannot escape. When the variable is unset, behavior is unchanged.
- Bundled extension: added a **guided generation webview form** (`terramind.generateInfrastructureWizard`) with region, repeatable resource-inventory rows, connectivity, and constraints inputs, strict CSP, and no external resources. Extracted `presentGeneratedDraft` so both generation entry points share the preview/approval/save/re-analysis flow. The dashboard and output channel now show security/reliability/maintainability scores and the ranked recommendations.
- Documented rule ownership, severity, and dimension per module so future contributors can extend the registry without editing request handlers.

**Validation performed**

- Analyzer/data/training/evaluation suite: **60 passed** (from a 44-test baseline), including new tests for recommendations and the workspace allowlist.
- `node_modules/.bin/tsc --noEmit -p extensions/terramind-core/tsconfig.json`: exit 0, no diagnostics; `package.json` and `package.nls.json` parse.
- End-to-end in-process `/v1/analyze` run against a deliberately flawed workspace reported 10 findings across networking, storage, database, and secrets; produced per-service security/reliability/maintainability scores (database security 50, reliability 55) and a severity-ranked recommendation list.
- Committed to `testing`: `862f4a4e` (analyzer) and `149adc1d` (extension), pushed to `origin/testing`.

**Not completed / risks**

- These are static heuristics over parsed HCL, not provider-schema validation, runtime, cost, or availability evidence. Module internals, resolved variables, `jsonencode(...)` policy bodies, and provider defaults are not expanded; a clean rating is not a certification.
- Reliability/maintainability scoring is a transparent rubric, not a calibrated measurement.
- Interactive workbench tests (webview form and diagnostic flow) and hosted CI remain unverified; the GitHub Actions billing restriction and the Windows native-launch prerequisite are unchanged.

### 2026-10-01 - Terraform-in-general coverage, report panel, and model strategy

**Implemented and verified locally**

- Added `app/rules/general.py` (9 provider-agnostic rules, service `general`): required CLI version present and constrained, provider version pinning, registry module version pinning, remote-state/backend presence, variable `type`/`description`, output `description`, and literal provider region/location values that should be variables. These apply to any Terraform project, not just AWS.
- Added `app/rules/multicloud.py` (12 rules): Azure storage-account public/TLS/HTTPS exposure, key-vault purge protection, public NSG admin ports, and publicly reachable MSSQL; Google Cloud Storage public access/uniform access, VPC firewall admin-port exposure, public Cloud SQL, and GKE public/authorized-network gaps.
- Generalized `app/ratings.py` so ratings score resources from **any** provider (Azure, Google, Kubernetes-aware `other`) and also create a rating entry for services that have relevant findings but no matching resources, so project-level `general`/`secrets` findings surface as points.
- Registry now holds **66 unique rules**; the integration test asserts registry invariants (uniqueness, `TM-` prefix, valid severity/dimension) with a lower bound instead of a hardcoded count.
- Bundled extension: added `src/reportView.ts` — a CSP-restricted **TerraMind Report** webview showing service scores with bars, ranked recommendations, and grouped findings; `terramind.openReport` command; Analyze now populates the report; activity-bar `viewsWelcome` actions link Analyze, the guided wizard, and the report.
- Made the Ollama generation path speed-tunable with bounded env settings (`TERRAMIND_OLLAMA_NUM_PREDICT` 256-8192, `_TEMPERATURE` 0.0-1.0, `_NUM_CTX` 2048-32768, `_KEEP_ALIVE` duration) and added unit tests for defaults, clamping, and payload shape.
- Added [`docs/MODEL_STRATEGY.md`](docs/MODEL_STRATEGY.md): a decision document recommending an existing quantized coder model over the tiny self-trained adapters, with an 8 GB-VRAM model matrix, speed levers, licensing, and the conditions under which fine-tuning would be justified.

**Validation performed**

- Analyzer suite: **72 passed** (from 66). Extension TypeScript check: exit 0, no diagnostics; extension JSON parses.
- End-to-end `/v1/analyze` on a mixed workspace (`azurerm_storage_account`, `azurerm_key_vault`, `google_storage_bucket`, `google_compute_firewall`, untyped variable, unpinned provider, unversioned registry module) reported the expected general/Azure/GCP findings, scored `storage` security 20 and `networking` security 65, and returned a ranked recommendation list.
- Committed to `testing`: `2c89f391` (analyzer), `7e416d2f` (extension).

**Not completed / risks**

- The general rules are deliberately scoped per parsed document; there is no cross-file module expansion, so some project-wide absence checks (for example a backend defined in a separate file) can still be reported per file.
- Azure/GCP reliability and maintainability are not yet rubric-scored (only their security findings are attributed); their ratings show those dimensions as `insufficient_information`.
- Self-trained generation remains a research artifact. The product recommendation is an existing pre-trained code model; see `docs/MODEL_STRATEGY.md`.

### 2026-10-01 - Self-hosted model pipeline: multi-cloud corpus and working training loop

**Implemented and verified locally**

- Prepared a **multi-cloud** supervised-fine-tuning corpus from the pinned `SASVAAI/terraform-multicloud` revision (`--provider-family all`): **72,150 train / 3,825 validation rows** across AWS (45,790), GCP (8,680), Azure (8,560), Kubernetes (4,521), OCI, IBM, Alibaba, Cloudflare, DigitalOcean, Docker, GitHub, OpenStack, Vault, vSphere, and Yandex. License allowlisting, HCL-parse filtering, repository-disjoint splits, and per-row attribution are retained; prepared text stays in the git-ignored `.build/`.
- Added a default training preset on **`Qwen/Qwen2.5-Coder-1.5B-Instruct`** (Apache-2.0, pinned revision `2e1fd397ee46e1388853d2af2c993145b0f1098a`) so a redistributable Terraform adapter can be trained and shipped. Presets, checkpoint save/resume, `--dry-run`, and configurable LoRA/hyperparameters are in `train_sft.py`.
- Fixed a **CPU-fallback bug**: the PEFT model was never moved to CUDA, so training ran at ~25 s/step. An explicit `.to("cuda")` restored GPU execution.
- Fixed a **Windows stall**: `dataloader_pin_memory=True` made the Hugging Face `Trainer` run at 16-25 s/step with the GPU starved at ~18 W; the same model computes a step in ~2 s directly. Replaced `Trainer` with an explicit training loop (gradient accumulation, cosine schedule, evaluation, checkpointing, metadata) and added opt-in per-phase timing (`TERRAMIND_TRAIN_DEBUG=1`).
- Bounded memory: sample raw JSONL lines before parsing and store encoded rows as `int32` numpy arrays instead of Python int lists.
- Added a bundled **GGUF (llama.cpp) generation engine** with per-request and env engine selection (`auto`/`ollama`/`transformers`/`gguf`), an export/quantization CLI (`export_gguf.py`) that builds merge → f16 → Q4_K_M commands and writes a model manifest with SHA-256, plus `docs/MODEL_CARD.md` and `docs/OPEN_SOURCE.md` for licensing/attribution and no-Ollama deployment. The extension exposes `terramind.generationEngine` and `terramind.ggufModelPath`.

**Validation performed**

- Analyzer suite: **113 passing**; extension TypeScript check clean.
- Measured on the RTX 4060 (8 GB): forward ~0.7 s and backward ~1.4 s per 512-token example with LoRA (batch 1; batch 4 caused memory-thrash spikes). A 40-example debug run completed a full epoch. A full fine-tune over 10,000 multi-cloud examples was started; results are reported in a later entry.
- Committed to `testing`/`main`: `b8d082fd`, `5bacb7ed`, `91db5256`, `36e55c3f`, `f6491c6d`, `4bc40353`, `098c1c25`.

**Not completed / risks**

- The 8 GB GPU forces batch size 1, so wall-clock training time scales with the number of examples (~2 s each). Larger batches spill VRAM and stall.
- No trained adapter is claimed yet; loss is not a validity measure, and the shipped model must still be gated by the deterministic analyzer and optional provider validation.
- GGUF conversion requires external `llama.cpp` tools (`convert_hf_to_gguf.py`, `llama-quantize`), supplied via `TERRAMIND_LLAMA_CPP_DIR` or `PATH`.

### 2026-10-01 - Fine-tuned Terraform generator trained and evaluated

**Completed**

- Trained a LoRA adapter on **20,000 multi-cloud Terraform examples** (Qwen2.5-Coder-1.5B-Instruct base, r=16/alpha=32, 512-token context, 1 epoch) on the RTX 4060 in **~2.75 hours**. Measured: `train_loss` **0.475**, `eval_loss` **0.470** over 2,395 optimizer steps.
- Merged the adapter into the base and produced a local 2.9 GB full model at `.build/terramind-qwen2.5-coder-1.5b-terraform-merged`.
- Ran a held-out generation evaluation (`scripts/eval_model.py`): **8/8 (100%) of generated configurations parsed as HCL**, at roughly 16 s/example, versus the earlier Qwen3-0.6B/1.7B adapters that were largely unparsable or provider-invalid.
- Added visible-console launchers with live progress counters and logs: `scripts/train_model_live.bat`, `scripts/eval_model_live.bat`, `scripts/export_gguf_live.bat` (to `.build/*-log.txt`).

**Interpretation / limits**

- 100% **parse** rate is not provider-schema validity, semantic correctness, security, cost, or availability. `terraform validate` (opt-in, pre-initialized cache) and the deterministic analyzer still gate every draft, and the model ignores some constraints (for example it may still emit broad security-group CIDRs).
- The measure is 8 examples; a larger provider-valid benchmark remains necessary before any quality claim.

**Commits:** `af0400f5` (eval tooling) and the GGUF-export launcher added alongside.

**Quantized and running without Ollama (verified)**

- Converted the merged model to GGUF and quantized it with llama.cpp (`convert_hf_to_gguf.py` → f16 → `llama-quantize` **Q4_K_M**). Result: **940 MB** Q4_K_M GGUF and a `model-manifest.json` recording base model, pinned revision, license, quant type, size, and **SHA-256** `6917bf57…c7906`. Tools were pinned to llama.cpp `v0.5.0` (b11146) and its matching `gguf` python package.
- Installed `llama-cpp-python 0.3.36` (CPU wheel) in the analyzer environment and generated through the bundled **`gguf` engine with no Ollama present**: `POST /v1/generate` with `engine: "gguf"` returned HTTP 200, `syntax_valid: true`, and a correct private S3 bucket with SSE + versioning, flagged by the static rules (`TM-STOR-001` AES256-instead-of-KMS information, `TM-STOR-003` missing lifecycle information). This is the first end-to-end proof that TerraMind generates Terraform with its own model and no external LLM service.
- Added reusable visible-console launchers with live progress counters and logs: `scripts/train_model_live.bat`, `scripts/eval_model_live.bat`, `scripts/export_gguf_live.bat`.

**Remaining for distribution**

- Bundle/download the GGUF as a release asset and document `TERRAMIND_GGUF_MODEL` + `TERRAMIND_GENERATION_ENGINE=gguf` for end users; packaging `llama-cpp-python` (or the llama.cpp server binary) with the analyzer remains.
- Provider-schema validity was measured on 12 held-out examples through the shipped GGUF engine against AWS provider 6.66.0: **75% (9/12) valid HCL and 50% (6/12) passing `terraform validate`**, up from 67%/42% after a deterministic post-processor that declares undeclared `var.*` references (`checks.auto_declared_variables`). Remaining failures are unparsable output after the single repair attempt and residual provider-schema errors. Intent fidelity is still only partially met (the model can ignore a stated constraint such as "no public SSH"). These are honest draft-quality numbers; the model is a review-required draft assistant, not a correctness guarantee.

### 2026-10-02 - Model v2 (2 epochs) and built-in auto-discovery

- Trained a second adapter with **2 epochs** over the same 20,000 multi-cloud examples (4790 steps, `train_loss` 0.424, `eval_loss` 0.460, ~6.3 h), merged it, and exported a **940 MB Q4_K_M GGUF** (SHA-256 `1ecf85fe…ba492`). `scripts/build_model_v2_live.bat` runs train -> merge -> export in one visible window with a live log.
- Made the model **built in**: the analyzer now auto-discovers a bundled GGUF (explicit `TERRAMIND_GGUF_MODEL`, then `TERRAMIND_MODELS_DIR`, `models/` next to the analyzer, repository `models/`, `~/.terramind/models`) and the `auto` engine prefers `gguf` when one is found. Verified with no environment variables: generation returned HTTP 200 and valid HCL from the discovered model. Suite: 120 passing.
- Re-measured v2 on the same 12 held-out examples: **parse 10/12 (83%, up from 75%) but provider-valid 5/12 (42%, from 50%)**. With 12 examples the provider figures are within noise, so v2 is not demonstrably better on schema validity; the marginal gains confirm that the bottleneck is training-data quality and base-model size, not epochs.

### 2026-10-02 - Browser workbench integration and native-launch investigation

**Implemented and verified**

- Added a **web (browser) build** for the TerraMind extension: `extensions/terramind-core/esbuild.browser.mts` + a `browser` entry in `package.json` + `tsconfig.browser.json`; removed the Node-only `crypto` nonce in favour of `globalThis.crypto` so the same sources run in the browser and in Electron.
- Added **localhost-only CORS** to the analyzer (`allow_origin_regex` for `localhost`/`127.0.0.1`/`::1`) so the browser workbench can call it. Verified an `OPTIONS /v1/analyze` preflight returns `Access-Control-Allow-Origin: http://localhost:8080`.
- Added extension UX: an automatic **health check** on activation plus **Check Analyzer Connection**, and **Analyze Demo Fixture** which runs `/v1/analyze` against a local fixture folder server-side (no browser folder picker, so it works in Brave).
- Served the workbench with `scripts/code-web.bat` (wrapped by `scripts/web_live.bat`) at `http://localhost:8080`, and the analyzer with `scripts/analyzer_live.bat` at `http://127.0.0.1:8000`. Verified the TerraMind browser bundle is served (HTTP 200) and the analyzer health endpoint responds.
- Produced a full **Windows x64 package**: `VSCode-win32-x64\TerraMind.exe` (228 MB) via `npm run gulp vscode-win32-x64-min` (0 source errors). Rebuilt all 13 missing native modules by disabling Spectre mitigation in the gyp files (the documented VS component id `...VC.14.29.16.11.x86.x64.Spectre` is **not present** in this 2019 Build Tools product graph, so the component route could not be used).

**Native launch remains blocked (evidence)**

- The desktop app never creates a window. Via the Node inspector: `process.type === 'browser'`, `app.isReady() === true`, `BrowserWindow.getAllWindows().length === 0`, and the main process is idle (`_getActiveHandles()` = `WriteStream,FSWatcher`).
- `TerraMind.exe --version` **hangs** (stock `Code.exe --version` exits; the raw Electron runtime prints `v43.7.3`). No files are written under `%APPDATA%\TerraMind\logs\`; no Application-error/hang event.
- Ruled out: native modules, `@vscode/policy-watcher`, Spectre libs, system proxy, **Cloudflare WARP** (disconnected — no change), a clean profile, `--disable-gpu`, `CalculateNativeWinOcclusion`, and dev-vs-packaged. A background investigation into the main-process startup (`openFirstWindow` / shared process / the fork's Agent Host additions) is in flight.

**Where the project stands**

- Working end-to-end today: analyzer API (66 rules, ratings, recommendations), bundled v2 model with no Ollama, extension UI (wizard, report, dashboard), and the **browser workbench** with the extension integrated. Analyzer suite: **120 passing**; extension TypeScript check clean.
- **RESOLVED (same day): the native Electron window now opens.** Precise chain: `src/vs/code/electron-main/main.ts:118` → `configurationService.initialize()` → `configurations.ts:122` `PolicyConfiguration.initialize()` → `nativePolicyService.ts:25` `_updatePolicyDefinitions()` awaits a promise resolved only from the `@vscode/policy-watcher` `createWatcher` callback. A local debugging stub of `node_modules/@vscode/policy-watcher/index.js` (added earlier to work around the then-missing native binding, and never removed after the binding was rebuilt) returned `{ dispose() {} }` and **never called the callback**, so `initServices` hung before any window was created — with no error and no log, and `--version` hung on the same path. Fixes: restore the real loader (`require('bindings')('vscode-policy-watcher')`) and add a **5s `raceTimeout`** in `nativePolicyService.ts` that degrades to "no policies" instead of hanging (defense-in-depth, committed `6ce298b0`). Verified on the packaged app: renderer + workbench window opens (`"Welcome … TerraMind - AI-Native Terraform IDE"`). This was **not** the Agent Host/sessions/shared-process code.

## Cross-cutting context

- Two run targets now work: the **native desktop app** (`npm run gulp vscode-win32-x64-min` → `VSCode-win32-x64\TerraMind.exe`) and the **browser workbench** (`scripts\web_live.bat` → http://localhost:8080). The analyzer (`scripts\analyzer_live.bat`) is shared.
- Generation runs on the **GPU** (`n_gpu_layers=-1` with a CUDA `llama-cpp-python` build; ~100 tok/s vs ~15 on CPU) and reports **progress 0-100%** through the job API + workbench notification.
- Truncated output is handled deterministically: `_trim_incomplete_hcl` drops an incomplete trailing block (tracking `{}`, `[]`, `()` and ignoring strings/comments) before parsing and before the repair prompt, and the analyzer's GGUF limit is 4096. This removed the "could not generate a draft" failures caused by the model running to the token limit (3/3 sample generations succeed).
