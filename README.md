# TerraMind

**A local, open-source AI assistant for Terraform, built into a Code-OSS editor.**

TerraMind analyses a Terraform workspace, scores it, recommends fixes, and generates Terraform
from a prompt or a resource inventory — running **entirely on your machine**. No Ollama, no
cloud API, no account.

- Repository: **https://github.com/shubh-3011/terramind** (public)
- Releases: **https://github.com/shubh-3011/terramind/releases**
- Model: **https://huggingface.co/shubh-3011/terramind-qwen2.5-coder-1.5b-terraform** (Hugging Face, public)

---

## Download & run (Windows x64 beta)

**TerraMind Beta 1** — a portable, self-contained build. No Python, no Node, no Ollama, no GPU.

1. Download **`TerraMind-beta1-win32-x64-full.zip`** from the
   [latest release](https://github.com/shubh-3011/terramind/releases/latest).
2. Extract it anywhere (e.g. `D:\TerraMind`).
3. Double-click **`TerraMind.bat`** (not `TerraMind.exe` directly).

On first launch, `TerraMind.bat` downloads the local AI model (~940 MB, once) into
`%USERPROFILE%\.terramind\models\`, starts the analysis service, and opens the app. Later
launches take a second or two.

Then press `Ctrl+Shift+P`:
- **TerraMind: Analyze Demo Fixture** — works with no folder open
- **TerraMind: Generate Infrastructure (Guided)** — e.g. `VPC 2, EC2 2, S3 bucket 1`
- **TerraMind: Analyze Terraform Workspace** — open a `.tf` folder first

The packaging model and model hosting (Hugging Face primary, GitHub release fallback) are documented
in [docs/DISTRIBUTION.md](docs/DISTRIBUTION.md).

---

## Project status (2026-10-03)

This is a **beta**, not a finished or production security product. Roughly **75% of the agreed
MVP scope** by milestone coverage.

| Area | State |
| --- | --- |
| Repository | **Public**; default branch `main` (kept in sync with `testing`) |
| Desktop app (Windows x64) | **Works**; packaged and released as a portable beta |
| Browser workbench | **Works** (`http://localhost:8080`) |
| Analyzer API | **66 deterministic rules** (general + AWS + Azure + GCP), evidence-scored ratings, prioritized recommendations, opt-in `fmt`/`validate`/TFLint/Checkov |
| Deterministic scaffolder | **Works** — inventory → valid, secure Terraform in ~0.1 s, no model |
| Local AI model | Fine-tuned `Qwen2.5-Coder-1.5B` (Apache-2.0), **940 MB Q4_K_M GGUF**, auto-discovered, downloaded on first run |
| Tests | **171 passing** (`services/analyzer-api`, `pytest`); extension TypeScript check clean |
| CI | GitHub Actions **disabled**; the inherited VS Code workflows and Dependabot were removed |

### Honest model quality
On **12 held-out examples** through the shipped GGUF engine: **~83% parse, ~33% pass
`terraform validate`**. A larger retrain (v3: 8k generated + 12k security-filtered examples) did
**not** improve on it (67% / 33%), so **v2 remains the bundled model**. The generative model is a
**review-required draft assistant**; the deterministic scaffolder is the reliable path for
structured requests. Never apply AI output without `terraform validate` / `terraform plan`.

Next quality lever: **distillation** — fine-tune a larger teacher on a DGX and distil its
validated output into the small model ([docs/DISTILLATION.md](docs/DISTILLATION.md)).

---

## What it does

- **Analyze** a workspace: 66 static rules across general Terraform hygiene and AWS/Azure/GCP,
  `aws-rubric-v2` evidence-scored security/reliability/maintainability ratings, prioritized
  recommendations, and Problems diagnostics.
- **Generate**: a deterministic **scaffolder** (valid, secure AWS Terraform from a resource
  inventory, no model) plus a **local generative model** for freeform prompts, with preview and
  explicit save, and one bounded parser/provider-feedback retry.
- **Repair**: propose a full-file fix for a `.tf` document from TerraMind diagnostics, shown as a
  diff, applied only after approval.
- Everything stays **local**: the analyzer binds to `127.0.0.1`, generation runs on CPU (this
  beta) or a CUDA `llama-cpp-python` build (dev), and no telemetry leaves the machine.

---

## Running from source (development)

**Analyzer** (Python 3.11–3.13):
```powershell
cd services\analyzer-api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
scripts\..\..\scripts\analyzer_live.bat     # or: uvicorn app.main:app --host 127.0.0.1 --port 8000
```
Tests:
```powershell
cd services\analyzer-api
.\.venv\Scripts\python.exe -m pytest -q
```

**Browser workbench:**
```powershell
scripts\analyzer_live.bat      # http://127.0.0.1:8000
scripts\web_live.bat           # http://localhost:8080
```

**Desktop app:** build with `npm run gulp vscode-win32-x64-min` (produces
`VSCode-win32-x64\TerraMind.exe`), or run the dev build with `scripts\code.bat .`.

The analyzer auto-discovers a bundled GGUF under `services/analyzer-api/models/`
(see [docs/RUNNING_LOCAL_MODEL.md](docs/RUNNING_LOCAL_MODEL.md)); external tools are off by
default and opt-in via `terramind.analysis.runExternalTools`.

---

## Documentation

| Doc | What it covers |
| --- | --- |
| [docs/REPOSITORY_SETUP.md](docs/REPOSITORY_SETUP.md) | Public/private repos, remotes, model hosting, releases, and CI |
| [docs/DISTRIBUTION.md](docs/DISTRIBUTION.md) | How the portable beta is built and shipped |
| [docs/RUNNING_LOCAL_MODEL.md](docs/RUNNING_LOCAL_MODEL.md) | The bundled GGUF engine |
| [docs/MODEL_STRATEGY.md](docs/MODEL_STRATEGY.md) | Model-size / hardware matrix |
| [docs/MODEL_CARD.md](docs/MODEL_CARD.md) | The shipped model, data, and licences |
| [docs/DISTILLATION.md](docs/DISTILLATION.md) / [docs/DGX_TRAINING.md](docs/DGX_TRAINING.md) | Big-GPU training and distillation |
| [docs/OPEN_SOURCE.md](docs/OPEN_SOURCE.md) | Licensing and open-source readiness |

Internal planning notes (`PLAN.md`, `PROGRESS.md`, `ARCHITECTURE.md`, `current-issue-progress.md`)
are kept **local** and are not published to this repository.

Contributors: development happens on the private mirror
([`shubh-3011/terramind-dev`](https://github.com/shubh-3011/terramind-dev), remote `dev`, `testing`
branch); this public repository publishes only `main` — see
[docs/REPOSITORY_SETUP.md](docs/REPOSITORY_SETUP.md).

---

## Safety and scope

TerraMind **never deploys infrastructure** and must never run `terraform apply`. Findings are
static heuristics tagged with evidence; they are not guarantees about runtime security, uptime,
scalability, or cost. Generated drafts are parsed and receive static security rules before
preview; optional provider validation runs only against a pre-initialised cache in a scratch
directory, and may execute locally installed provider plugins — enable it only for a workspace you
trust. `validate` may run provider plugins; TerraMind never runs `init`, `plan`, or `apply`.

---

## Licences

- Code OSS / VS Code: **MIT** (see `LICENSE.txt` and upstream notices).
- Fine-tuned model: **Apache-2.0** (`Qwen/Qwen2.5-Coder-1.5B-Instruct`).
- Training data includes **CC-BY-4.0** rows (`SASVAAI/terraform-multicloud`); attribution is
  retained in the repository (`ATTRIBUTION.csv`, [docs/MODEL_CARD.md](docs/MODEL_CARD.md)).
