# TerraMind

TerraMind is an experimental, private **Code-OSS fork** for Terraform authors. Terraform intelligence is bundled into the editor; it is not intended to be installed separately from the VS Code Marketplace.

## Project status

This is an early prototype, not a finished editor or production security product.

- Implemented: TerraMind product identity, bundled activity-bar contribution, Analyze Workspace command, local FastAPI API, HCL syntax parsing, first-pass public-SSH and wildcard-IAM findings, and VS Code Problems diagnostics.
- Not implemented: Terraform CLI/provider validation, TFLint, Checkov, cost/availability/scalability ratings, prompt-to-Terraform generation, Ollama integration, trained risk model, or repair proposals.
- Build status: TerraMind contribution compiles. A complete Code-OSS app build and launch are not yet verified because Windows native dependencies are incomplete.

See [PLAN.md](PLAN.md), [ARCHITECTURE.md](ARCHITECTURE.md), and [PROGRESS.md](PROGRESS.md) for the roadmap, design contracts, and verified progress.

## Analyzer service (development)

Use Python 3.11–3.13. From `services/analyzer-api`:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Keep this prototype bound to loopback. In the editor, open a Terraform workspace and run **TerraMind: Analyze Workspace**. The analyzer parses `.tf` files and currently reports public SSH ingress and literal wildcard IAM actions. It does not run `terraform init`, providers, `terraform validate`, TFLint, or Checkov. The report marks those checks as not run.

To run the analyzer API tests:

```powershell
python -m pytest -q
```

## Code-OSS development build

TerraMind uses the upstream Code-OSS build system and toolchain. Follow [docs/FORK_BUILD.md](docs/FORK_BUILD.md) and Microsoft's [Code-OSS contributor guide](https://github.com/microsoft/vscode/wiki/How-to-Contribute). The full application build has not yet been validated on the current Windows machine.

## Safety and scope

TerraMind does not deploy infrastructure and must never run `terraform apply`. Findings are evidence-tagged; static heuristics are not provider validation or guarantees about runtime security, uptime, scalability, or cost. Generated Terraform, when implemented, must be analyzed and previewed before any user-approved workspace change.

The Code-OSS base is distributed under its included MIT license and notices. Review upstream attribution and applicable licenses before redistribution.
