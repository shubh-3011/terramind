# TerraMind

TerraMind is an experimental, private **Code-OSS fork** for Terraform authors. Terraform intelligence is bundled into the editor; it is not intended to be installed separately from the VS Code Marketplace.

## Project status

This is an early prototype, not a finished editor or production security product.

**Rough completion estimate: 70-75% of the agreed MVP scope.** This is a milestone-coverage estimate, not a model-quality or readiness claim: a 66-rule deterministic analyzer covering general Terraform plus AWS, Azure, and GCP, evidence-scored security/reliability/maintainability ratings, prioritized recommendations, a guided generation webview form and results report, a workspace allowlist, local generation, optional scanners, license-filtered data preparation, trained LoRA smoke adapters, and a local Transformers generation path are implemented. Smoke-model generations still fail provider-schema checks or HCL parsing; Windows/Linux desktop packages remain unverified. PR #6 and five Dependabot PRs are not green: GitHub reports workflow jobs were not started because of an account payment/spending-limit issue. No PR has been merged and `main` is unchanged. Evidence and blockers are in [PROGRESS.md](PROGRESS.md).

- Bundled model (2026-10-01): a Terraform LoRA fine-tune of `Qwen2.5-Coder-1.5B-Instruct` (Apache-2.0) was trained on 20,000 multi-cloud examples and exported to a **940 MB Q4_K_M GGUF**. It generates Terraform locally through the bundled `llama.cpp` engine with **no Ollama** (`TERRAMIND_GGUF_MODEL` + `TERRAMIND_GENERATION_ENGINE=gguf`); a held-out smoke run parsed 8/8 outputs.
- Implemented: TerraMind product identity, bundled activity-bar contribution, Analyze/Generate/Propose Repair commands plus a guided Generate webview form and a results report panel, local FastAPI API, HCL parsing, a 66-rule extensible registry spanning **provider-agnostic general Terraform hygiene plus AWS, Azure, and GCP** (networking, IAM, storage, database, compute, observability, secrets hygiene), `aws-rubric-v2` evidence-scored security/reliability/maintainability ratings, prioritized `/v1/analyze` recommendations, a `TERRAMIND_ALLOWED_ROOTS` workspace allowlist, opt-in `terraform fmt`/pre-initialized `terraform validate`/TFLint/Checkov integrations, generated-draft provider-schema validation against an existing local cache, Problems diagnostics, local Ollama or explicitly configured local Transformers generation with preview and explicit save, an experimental grouped-evaluation risk model, and a pinned, license-attributed SFT-data preparation/training/merge pipeline.
- Still incomplete: reliable provider-valid generation, evidence-backed cost/reliability/scalability scoring, representative independent generation and repair evaluation, authenticated workspace authorization for external tools, automated analyzer lifecycle, interactive repair-workflow tests, and verified distributable desktop builds. Single-file repair proposals now have a diff/approval/re-analysis path, but the UI has not been interactively exercised. Generation accepts separate requirements, resource/count inventory, topology, and constraints, and permits one retry from parser/provider diagnostics. These are workflow capabilities, not evidence of model quality. The risk classifier uses only 46 controlled AWS cases and is not suitable for production decisions.
- Validation status: analyzer/ML/data-preparation/training/evaluation suite passes 72 tests; the extension TypeScript project check passes with no diagnostics. The official full `npm run compile-client` succeeds with zero errors and compiles TerraMind alongside built-in extensions. A real isolated workbench launch still exits because this Windows setup lacks the native `@vscode/policy-watcher` binary; Visual Studio Installer requires UAC elevation to add its matching Spectre-mitigated libraries. Generated drafts receive static security rules and evidence-limited service summaries before preview; when `terramind.analysis.runExternalTools` is enabled, VS Code reports a trusted workspace, and an existing provider cache is present, the editor also runs schema validation in an isolated scratch directory without `terraform init`. One bounded retry may feed parser/provider diagnostics back to the configured local model. The Generate dialog accepts separate resource/count and connectivity inputs. Post-retry smoke evaluation on three held-out examples parsed 2/3 (one recovered after retry), with one HTTP 422; resource-type micro-F1 was 0.471 over the two parseable cases. With the cached AWS provider enabled, neither parsed result passed provider validation (0/2) after retry. A separate 384-token experiment returned HTTP 422 for both merged Qwen3 adapters after about 146 seconds; the 0.6B output stopped at exactly 384 tokens and was truncated before HCL parsed. The default remains 2,048 tokens; `TERRAMIND_HF_MAX_NEW_TOKENS` is configurable from 128–2,048, but lowering it risks incomplete Terraform. The 1.7B model exceeded 180 seconds at higher limits. These small results show the optional Transformers path is not ready for interactive generation on this hardware, not that either model is useful. The larger CUDA LoRA run used 256/64 examples; a second run used 128/32 for Qwen3-1.7B. The data pipeline yielded 43,561 train and 2,229 validation rows locally; datasets and weights remain uncommitted. GitHub hosted jobs were prevented from starting by an account payment/spending-limit restriction. The single-file repair command is implemented but has not received an interactive workbench test.

See [PLAN.md](PLAN.md), [ARCHITECTURE.md](ARCHITECTURE.md), and [PROGRESS.md](PROGRESS.md) for the roadmap, design contracts, and verified progress.

Current local validation after the 2026-10-01 analyzer/rules/ratings update is 72 analyzer/data/training/evaluation tests plus a clean TerraMind extension TypeScript check. The proposal diff is explicit and local; multi-file repair, semantic correctness, repair-quality evaluation, interactive UI testing, and successful hosted desktop packaging remain unverified.

## Running TerraMind

Two ways to run the workbench:

1. **Browser workbench (works reliably today).** Start the analyzer and the web workbench:
   ```powershell
   scripts\analyzer_live.bat      # http://127.0.0.1:8000
   scripts\web_live.bat           # http://localhost:8080
   ```
   Open `http://localhost:8080` (use Edge or Chrome for `File > Open Folder`; Brave blocks the File System Access API). In any browser, run **TerraMind: Analyze Demo Fixture** from the Command Palette to analyze a local fixture without a folder picker.
2. **Desktop app (native Windows).** Build with `npm run gulp vscode-win32-x64-min` (produces `VSCode-win32-x64\TerraMind.exe`), or run the development build with `scripts\code.bat .`. The window opens with the TerraMind workbench, activity-bar panel, diagnostics, and webviews.

Generation runs locally on the GPU when a CUDA `llama-cpp-python` build is installed (`n_gpu_layers` defaults to -1) and reports a live progress percentage.

The analyzer auto-discovers a bundled GGUF under `services/analyzer-api/models/` and needs no Ollama; see [docs/RUNNING_LOCAL_MODEL.md](docs/RUNNING_LOCAL_MODEL.md).

## Analyzer service (development)

Use Python 3.11–3.13. From `services/analyzer-api`:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Keep this prototype bound to loopback. In the editor, open a Terraform workspace and run **TerraMind: Analyze Workspace**. The analyzer reports HCL parse failures and a broad AWS rule set: public SSH/admin/DB port exposure (including dynamic blocks backed by resolvable literal locals), unrestricted egress, default VPC/security-group use, wildcard IAM principals/actions/resources, long-lived access keys and weak password policies, KMS rotation, S3 public-access/ACL/encryption/versioning/lifecycle risks, EBS/EFS encryption, RDS/database public exposure, backups and deletion protection, EC2 public IPs and instance metadata, EKS public endpoints, ECS privileged containers, CloudTrail/flow-log/retention gaps, and literal credentials. Each finding carries a remediation recommendation, and results include evidence-scored security/reliability/maintainability ratings plus a prioritized improvement list. These are static heuristics. External `terraform fmt`, pre-initialized `terraform validate`, TFLint, and Checkov are optional and disabled by default via `terramind.analysis.runExternalTools`; the extension also skips them when VS Code reports Restricted Mode. TerraMind never runs `terraform init`, `plan`, or `apply`; `validate` may execute provider plugins already present in a workspace, so only enable external tools for a workspace you trust. The API's `workspace_trusted` field is a caller-provided signal, not authentication; keep the service on loopback.

To run the analyzer API tests:

```powershell
python -m pytest -q
```

The experimental risk model and generative dataset limits are documented in [docs/TRAINING_AND_MODEL.md](docs/TRAINING_AND_MODEL.md) and [docs/GENERATIVE_TRAINING.md](docs/GENERATIVE_TRAINING.md); the choice of an existing pre-trained code model over the tiny self-trained adapters, with an 8 GB-VRAM model matrix and speed levers, is in [docs/MODEL_STRATEGY.md](docs/MODEL_STRATEGY.md). Risk estimates are distinct from scanner findings and are not calibrated. External tool execution is off by default; opt in with `terramind.analysis.runExternalTools` only when you trust the workspace and its installed plugins/providers.

## Code-OSS development build

TerraMind uses the upstream Code-OSS build system and toolchain. Follow [docs/FORK_BUILD.md](docs/FORK_BUILD.md) and Microsoft's [Code-OSS contributor guide](https://github.com/microsoft/vscode/wiki/How-to-Contribute). The full application build has not yet been validated on the current Windows machine.

## Safety and scope

TerraMind does not deploy infrastructure and must never run `terraform apply`. Findings are evidence-tagged; static heuristics and the experimental model are not guarantees about runtime security, uptime, scalability, or cost. Generated Terraform is parsed and receives TerraMind's small static AWS security rule set before preview; if external tools are explicitly enabled and the workspace has a pre-initialized provider cache, `terraform validate` checks provider schemas in an isolated scratch directory before the user decides whether to save. TerraMind never runs `terraform init`, `plan`, or `apply`. Validation may execute locally installed provider plugins, so enable it only for a workspace you trust; it does not prove deployment behavior or external module correctness.

The Code-OSS base is distributed under its included MIT license and notices. Review upstream attribution and applicable licenses before redistribution.
