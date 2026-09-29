# TerraMind

TerraMind is an experimental, private **Code-OSS fork** for Terraform authors. Terraform intelligence is bundled into the editor; it is not intended to be installed separately from the VS Code Marketplace.

## Project status

This is an early prototype, not a finished editor or production security product.

**Rough completion estimate: 65% of the agreed MVP scope.** This is a milestone-coverage estimate, not a model-quality or readiness claim: local generation, optional scanners, evidence-backed/unknown ratings, license-filtered data preparation, trained LoRA smoke adapters, and a local Transformers generation path are implemented. Smoke-model generations still fail provider-schema checks or HCL parsing; Windows/Linux desktop packages remain unverified. PR #6 and five Dependabot PRs are not green: GitHub reports workflow jobs were not started because of an account payment/spending-limit issue. No PR has been merged and `main` is unchanged. Evidence and blockers are in [PROGRESS.md](PROGRESS.md).

- Implemented: TerraMind product identity, bundled activity-bar contribution, Analyze and Generate commands, local FastAPI API, HCL parsing/static rules, opt-in `terraform fmt`/pre-initialized `terraform validate`/TFLint/Checkov integrations, generated-draft provider-schema validation against an existing local cache, Problems diagnostics, local Ollama or explicitly configured local Transformers generation with preview and explicit save, an experimental grouped-evaluation risk model, and a pinned, license-attributed SFT-data preparation/training/merge pipeline.
- Still incomplete: reliable provider-valid generation, evidence-backed cost/reliability/scalability scoring, representative independent generation and repair evaluation, authenticated workspace authorization for external tools, automated analyzer lifecycle, interactive repair-workflow tests, and verified distributable desktop builds. Single-file repair proposals now have a diff/approval/re-analysis path, but the UI has not been interactively exercised. Generation accepts separate requirements, resource/count inventory, topology, and constraints, and permits one retry from parser/provider diagnostics. These are workflow capabilities, not evidence of model quality. The risk classifier uses only 46 controlled AWS cases and is not suitable for production decisions.
- Validation status: analyzer/ML/data-preparation/training/evaluation suite passes 43 tests; the extension TypeScript project check passes with no diagnostics. The official full `npm run compile-client` succeeds with zero errors and compiles TerraMind alongside built-in extensions. A real isolated workbench launch still exits because this Windows setup lacks the native `@vscode/policy-watcher` binary; the installed Visual Studio toolchain reports missing Spectre-mitigated libraries when that native dependency is built. Generated drafts receive static security rules and evidence-limited service summaries before preview; when `terramind.analysis.runExternalTools` is enabled, VS Code reports a trusted workspace, and an existing provider cache is present, the editor also runs schema validation in an isolated scratch directory without `terraform init`. One bounded retry may feed parser/provider diagnostics back to the configured local model. The Generate dialog accepts separate resource/count and connectivity inputs. Post-retry smoke evaluation on three held-out examples parsed 2/3 (one recovered after retry), with one HTTP 422; resource-type micro-F1 was 0.471 over the two parseable cases. With the cached AWS provider enabled, neither parsed result passed provider validation (0/2) after retry. These tiny runs are pipeline evidence only, not model-quality claims. The larger CUDA LoRA run used 256/64 examples; a second run used 128/32 for Qwen3-1.7B. The data pipeline yielded 43,561 train and 2,229 validation rows locally; datasets and weights remain uncommitted. GitHub hosted package jobs were prevented from starting by an account payment/spending-limit restriction. The single-file repair command is implemented but has not received an interactive workbench test.

See [PLAN.md](PLAN.md), [ARCHITECTURE.md](ARCHITECTURE.md), and [PROGRESS.md](PROGRESS.md) for the roadmap, design contracts, and verified progress.

Current local validation after adding the single-file repair-proposal workflow is 43 analyzer/data/training/evaluation tests plus a clean TerraMind extension TypeScript check. The proposal diff is explicit and local; multi-file repair, semantic correctness, repair-quality evaluation, and successful hosted desktop packaging remain unverified.

## Analyzer service (development)

Use Python 3.11–3.13. From `services/analyzer-api`:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Keep this prototype bound to loopback. In the editor, open a Terraform workspace and run **TerraMind: Analyze Workspace**. The analyzer reports HCL parse failures; public SSH ingress (including dynamic blocks backed by resolvable literal locals); unresolved dynamic ingress for review; wildcard IAM actions/resources; S3 public-access and ACL risks; mutable ECR tags; optional IMDSv2; and explicit EBS encryption disablement. These are static heuristics. External `terraform fmt`, pre-initialized `terraform validate`, TFLint, and Checkov are optional and disabled by default via `terramind.analysis.runExternalTools`; the extension also skips them when VS Code reports Restricted Mode. TerraMind never runs `terraform init`, `plan`, or `apply`; `validate` may execute provider plugins already present in a workspace, so only enable external tools for a workspace you trust. The API's `workspace_trusted` field is a caller-provided signal, not authentication; keep the service on loopback.

To run the analyzer API tests:

```powershell
python -m pytest -q
```

The experimental risk model and generative dataset limits are documented in [docs/TRAINING_AND_MODEL.md](docs/TRAINING_AND_MODEL.md) and [docs/GENERATIVE_TRAINING.md](docs/GENERATIVE_TRAINING.md). Risk estimates are distinct from scanner findings and are not calibrated. External tool execution is off by default; opt in with `terramind.analysis.runExternalTools` only when you trust the workspace and its installed plugins/providers.

## Code-OSS development build

TerraMind uses the upstream Code-OSS build system and toolchain. Follow [docs/FORK_BUILD.md](docs/FORK_BUILD.md) and Microsoft's [Code-OSS contributor guide](https://github.com/microsoft/vscode/wiki/How-to-Contribute). The full application build has not yet been validated on the current Windows machine.

## Safety and scope

TerraMind does not deploy infrastructure and must never run `terraform apply`. Findings are evidence-tagged; static heuristics and the experimental model are not guarantees about runtime security, uptime, scalability, or cost. Generated Terraform is parsed and receives TerraMind's small static AWS security rule set before preview; if external tools are explicitly enabled and the workspace has a pre-initialized provider cache, `terraform validate` checks provider schemas in an isolated scratch directory before the user decides whether to save. TerraMind never runs `terraform init`, `plan`, or `apply`. Validation may execute locally installed provider plugins, so enable it only for a workspace you trust; it does not prove deployment behavior or external module correctness.

The Code-OSS base is distributed under its included MIT license and notices. Review upstream attribution and applicable licenses before redistribution.
