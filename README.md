# TerraMind

TerraMind is an experimental, private **Code-OSS fork** for Terraform authors. Terraform intelligence is bundled into the editor; it is not intended to be installed separately from the VS Code Marketplace.

## Project status

This is an early prototype, not a finished editor or production security product.

**Rough completion estimate: 35–40% of the agreed MVP scope.** The analyzer and experimental ML foundation are underway, but external Terraform tools, full workbench UX, AI generation/repair, and a verified desktop build remain. This is a milestone-coverage estimate, not a schedule or quality claim; see [PROGRESS.md](PROGRESS.md).

- Implemented: TerraMind product identity, bundled activity-bar contribution, Analyze Workspace command, local FastAPI API, HCL syntax parsing, initial SSH/IAM/S3/ECR/EC2/EBS static rules, VS Code Problems diagnostics, and an experimental grouped-evaluation logistic-regression risk estimate.
- Not implemented: Terraform provider validation, TFLint, Checkov, cost/availability/scalability ratings, prompt-to-Terraform generation, Ollama integration, or repair proposals. The model is trained on only 46 controlled AWS cases and is not suitable for production decisions.
- Validation status: analyzer/ML suite passes 11 tests; the pinned IaCSecBench pipeline reproduces the committed feature dataset (normalized for platform line endings); model evaluation now reports pair-group bootstrap intervals. The TerraMind extension compiles with 0 TypeScript errors. Hosted attempts exposed dataset path/line-ending issues and missing native-build setup/sequencing in packaging; fixes are on `testing` and reruns are pending. The analyzer service still requires manual startup, so preview packages are not end-user-ready.

See [PLAN.md](PLAN.md), [ARCHITECTURE.md](ARCHITECTURE.md), and [PROGRESS.md](PROGRESS.md) for the roadmap, design contracts, and verified progress.

## Analyzer service (development)

Use Python 3.11–3.13. From `services/analyzer-api`:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Keep this prototype bound to loopback. In the editor, open a Terraform workspace and run **TerraMind: Analyze Workspace**. The analyzer reports HCL parse failures; public SSH ingress (including dynamic blocks backed by resolvable literal locals); unresolved dynamic ingress for review; wildcard IAM actions/resources; S3 public-access and ACL risks; mutable ECR tags; optional IMDSv2; and explicit EBS encryption disablement. These are static heuristics. It does not run `terraform init`, providers, `terraform validate`, TFLint, or Checkov; the report marks those checks as not run.

To run the analyzer API tests:

```powershell
python -m pytest -q
```

The experimental dataset/model workflow and its limits are documented in [docs/TRAINING_AND_MODEL.md](docs/TRAINING_AND_MODEL.md). The risk estimate is distinct from scanner findings and is not calibrated.

## Code-OSS development build

TerraMind uses the upstream Code-OSS build system and toolchain. Follow [docs/FORK_BUILD.md](docs/FORK_BUILD.md) and Microsoft's [Code-OSS contributor guide](https://github.com/microsoft/vscode/wiki/How-to-Contribute). The full application build has not yet been validated on the current Windows machine.

## Safety and scope

TerraMind does not deploy infrastructure and must never run `terraform apply`. Findings are evidence-tagged; static heuristics and the experimental model are not provider validation or guarantees about runtime security, uptime, scalability, or cost. Generated Terraform, when implemented, must be analyzed and previewed before any user-approved workspace change.

The Code-OSS base is distributed under its included MIT license and notices. Review upstream attribution and applicable licenses before redistribution.
