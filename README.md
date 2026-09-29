# TerraMind

TerraMind is an experimental, private **Code-OSS fork** for Terraform authors. Terraform intelligence is bundled into the editor; it is not intended to be installed separately from the VS Code Marketplace.

## Project status

This is an early prototype, not a finished editor or production security product.

**Rough completion estimate: 65% of the agreed MVP scope.** This is a milestone-coverage estimate, not a model-quality or readiness claim: local generation, optional scanners, evidence-backed/unknown ratings, license-filtered data preparation, trained LoRA smoke adapters, and a local Transformers generation path are implemented. Smoke-model generations still fail provider-schema checks or HCL parsing; Windows/Linux desktop packages remain unverified. PR #6 and five Dependabot PRs are not green: GitHub reports workflow jobs were not started because of an account payment/spending-limit issue. No PR has been merged and `main` is unchanged. Evidence and blockers are in [PROGRESS.md](PROGRESS.md).

- Implemented: TerraMind product identity, bundled activity-bar contribution, Analyze and Generate commands, local FastAPI API, HCL parsing/static rules, opt-in `terraform fmt`/pre-initialized `terraform validate`/TFLint/Checkov integrations, Problems diagnostics, local Ollama or explicitly configured local Transformers generation with preview and explicit save, an experimental grouped-evaluation risk model, and a pinned, license-attributed SFT-data preparation/training/merge pipeline.
- Still incomplete: reliable provider-valid generation, cost/reliability/scalability scoring, repair proposals, independent generation evaluation, workspace authorization for external tools, automated analyzer lifecycle, and verified distributable desktop builds. The risk classifier uses only 46 controlled AWS cases and is not suitable for production decisions.
- Validation status: analyzer/ML/data-preparation/training-script suite passes 26 tests; the TerraMind extension compiles with 0 TypeScript errors. A CUDA LoRA run completed on 256/64 examples for Qwen3-0.6B; a short 128/32 run completed for Qwen3-1.7B. The merged 0.6B model produced HCL syntax that Terraform AWS provider v6.66.0 rejected with five schema errors; the 1.7B model returned unparsable output on the smoke prompt. These models are experimental, not usable-quality claims. The data pipeline yielded 43,561 train and 2,229 validation rows locally; datasets and weights remain uncommitted. Hosted Windows/Linux artifacts still need verification.

See [PLAN.md](PLAN.md), [ARCHITECTURE.md](ARCHITECTURE.md), and [PROGRESS.md](PROGRESS.md) for the roadmap, design contracts, and verified progress.

## Analyzer service (development)

Use Python 3.11–3.13. From `services/analyzer-api`:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Keep this prototype bound to loopback. In the editor, open a Terraform workspace and run **TerraMind: Analyze Workspace**. The analyzer reports HCL parse failures; public SSH ingress (including dynamic blocks backed by resolvable literal locals); unresolved dynamic ingress for review; wildcard IAM actions/resources; S3 public-access and ACL risks; mutable ECR tags; optional IMDSv2; and explicit EBS encryption disablement. These are static heuristics. External `terraform fmt`, pre-initialized `terraform validate`, TFLint, and Checkov are optional and disabled by default via `terramind.analysis.runExternalTools`. TerraMind never runs `terraform init`, `plan`, or `apply`; `validate` may execute provider plugins already present in a workspace, so only enable external tools for a workspace you trust.

To run the analyzer API tests:

```powershell
python -m pytest -q
```

The experimental risk model and generative dataset limits are documented in [docs/TRAINING_AND_MODEL.md](docs/TRAINING_AND_MODEL.md) and [docs/GENERATIVE_TRAINING.md](docs/GENERATIVE_TRAINING.md). Risk estimates are distinct from scanner findings and are not calibrated. External tool execution is off by default; opt in with `terramind.analysis.runExternalTools` only when you trust the workspace and its installed plugins/providers.

## Code-OSS development build

TerraMind uses the upstream Code-OSS build system and toolchain. Follow [docs/FORK_BUILD.md](docs/FORK_BUILD.md) and Microsoft's [Code-OSS contributor guide](https://github.com/microsoft/vscode/wiki/How-to-Contribute). The full application build has not yet been validated on the current Windows machine.

## Safety and scope

TerraMind does not deploy infrastructure and must never run `terraform apply`. Findings are evidence-tagged; static heuristics and the experimental model are not provider validation or guarantees about runtime security, uptime, scalability, or cost. Generated Terraform is previewed and requires explicit user approval before a workspace save, then is analyzed; syntax parsing alone does not establish provider correctness.

The Code-OSS base is distributed under its included MIT license and notices. Review upstream attribution and applicable licenses before redistribution.
