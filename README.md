# TerraMind

TerraMind is an experimental, private **Code-OSS fork** for Terraform authors. Terraform intelligence is bundled into the editor; it is not intended to be installed separately from the VS Code Marketplace.

## Project status

This is an early prototype, not a finished editor or production security product.

**Rough completion estimate: 60–65% of the agreed MVP scope.** This is a milestone-coverage estimate, not a quality claim: local Ollama generation has been exercised end to end and returned parser-accepted HCL, scanner adapters and evidence-based/unknown ratings are implemented, and a license-filtered generation corpus was prepared. No generative fine-tuning has run, output has not been provider-validated, and Windows/Linux desktop packages remain unverified. Evidence and blockers are in [PROGRESS.md](PROGRESS.md).

- Implemented: TerraMind product identity, bundled activity-bar contribution, Analyze and Generate commands, local FastAPI API, HCL parsing/static rules, opt-in `terraform fmt`/pre-initialized `terraform validate`/TFLint/Checkov integrations, Problems diagnostics, local Ollama-backed HCL generation with preview and explicit save, an experimental grouped-evaluation risk model, and a pinned, license-attributed SFT-data preparation pipeline.
- Still incomplete: actual cost/reliability/scalability scoring, repair proposals, a TerraMind fine-tuned generative adapter, independent generation evaluation, workspace authorization for external tools, automated analyzer lifecycle, and verified distributable desktop builds. The risk classifier uses only 46 controlled AWS cases and is not suitable for production decisions.
- Validation status: analyzer/ML/data-preparation suite passes 22 tests; the pinned IaCSecBench pipeline reproduces the committed feature dataset (normalized for platform line endings); the TerraMind extension compiles with 0 TypeScript errors. A real Ollama request returned HCL accepted by the HCL parser; Terraform/provider correctness is not established. The SFT preparation pipeline yielded 43,561 train and 2,229 validation rows locally; raw/prepared corpus and model files are not committed. Hosted Windows/Linux artifacts still need verification.

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
