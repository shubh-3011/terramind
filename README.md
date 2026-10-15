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

## Project status (2026-10-15)

This is a **beta**, not a finished or production security product. Roughly **75% of the agreed
MVP scope** by milestone coverage.

| Area | State |
| --- | --- |
| Repository | **Public `main`** + private `terramind-dev` (`main` + `testing`, where work happens) |
| Desktop app (Windows x64) | **Works**; packaged and released as a portable beta (`v0.1.0-beta.2`) |
| Browser workbench | **Works** (`http://localhost:8080`) |
| Analyzer API | **66 deterministic rules** (general + AWS + Azure + GCP), evidence-scored ratings, prioritized recommendations, **monthly cost estimate**, opt-in `fmt`/`validate`/TFLint/Checkov |
| Deterministic scaffolder | **Works** — inventory → valid, secure Terraform in ~0.1 s, no model (VPC/subnet/IGW/NAT/routes/SG/EC2/S3/ALB/TGW/IAM-SSM/flow logs **+ RDS + EKS**) |
| Local AI models | Default `Qwen2.5-Coder-1.5B` (**940 MB Q4_K_M**, CPU-friendly) + opt-in `Qwen2.5-Coder-7B` multi-task (**~4.4 GB Q4_K_M**), both auto-discovered and downloaded on first run |
| Tests | **195 passing** (`services/analyzer-api`, `pytest`); extension TypeScript check clean |
| CI | GitHub Actions **disabled**; the inherited VS Code workflows and Dependabot were removed |

### Honest model quality

Through the shipped GGUF engine with an **offline provider cache**, on 12 held-out examples
(a mixed multi-cloud slice, then an AWS-only slice so `terraform validate` is meaningful):

| Slice / model | Parses as HCL | Passes `terraform validate` | Resource-type F1 |
| --- | --- | --- | --- |
| Mixed — default **1.5 B** | 8/12 (67%) | 2/8 (25%) | 0.21 |
| Mixed — opt-in **7 B (v2)** | 10/12 (83%) | 2/10 (20%) | 0.40 |
| AWS-only — default **1.5 B** | 6/12 (50%) | 2/6 (33%) | 0.46 |
| AWS-only — opt-in **7 B (v2)** | 11/12 (92%) | 1/11 (9%) | 0.77 |
| **Combined — 1.5 B** | **14/24 (58%)** | **4/14 (29%)** | 0.33 |
| **Combined — 7 B (v2)** | **21/24 (88%)** | 3/21 (14%) | **0.58** |

The **7 B (v2)** is the review-weighted retrain: review answers are canonicalised into
strict `CRITICAL → HIGH → MEDIUM → LOW` order, CRITICAL/HIGH rows are oversampled, and a slice of
no-finding rows is kept so the model does not hallucinate findings. It beat the previous 7 B on the
combined slices (parse **21/24 vs 20/24**, mean F1 **0.58 vs 0.53**) and clearly on AWS-only
(92% vs 75% parse), though on the mixed slice it parses one example fewer — a real but modest gain.

Read this honestly: the **7 B is a clearly better drafter** than the 1.5 B — it parses far more
often and matches many more of the reference resource types. But it is **not** a better
*validator-conformant* generator: it emits richer, newer HCL that the cached provider rejects more
often. Multi-cloud drafts cannot be validated offline at all — our cache holds only
`hashicorp/aws` — so they report `provider_validation: failed` for a missing plugin, not bad HCL.
Parser and analyzer coverage are provider-agnostic and are the cross-cloud signal.

Next quality lever: **distillation** — distil a larger teacher's validated output into the small
model so the *default* improves too ([docs/DISTILLATION.md](docs/DISTILLATION.md)).

**New (2026-10-15): monthly cost estimate + RDS/EKS scaffolding.**
`app/pricing.py` produces a static, region-aware monthly list-price estimate (AWS/Azure/GCP) with
billing basis, unit price and confidence per line, plus an explicit **unpriced** bucket for
usage-based resources — an estimate, not a quote, and it never calls a cloud API. It appears in
the report panel and the output channel. The deterministic scaffolder now also emits **RDS**
(private, encrypted, Multi-AZ, `manage_master_user_password` so no password is written) and
**EKS** (cluster + node roles, managed node group across two AZs).

**New (2026-10-10): a 7 B multi-task model.** `Qwen/Qwen2.5-Coder-7B-Instruct` was fine-tuned
(QLoRA, 4-bit) to **both generate and review** Terraform — generation produces valid multi-cloud
HCL; review emits structured `SECURE`/`INSECURE` findings with real `AVD-*` (tfsec) rule IDs. It
is exported to **Q4_K_M (~4.4 GB)** and runs on an 8 GB GPU. It ships as an optional **quality**
model: place the `.gguf` in `services/analyzer-api/models/` and pick it with
**`TerraMind: Select Model`** (or `TERRAMIND_GGUF_MODEL=<path>`). The **1.5 B remains the
default** (small, CPU-friendly), and the deterministic 66-rule analyzer stays the security
authority — the model's review output is explanation, not a guarantee. The portable bundle adds
GPU acceleration in place with `enable-gpu.bat` (no separate download).
**Updated (2026-10-15):** the 7 B was retrained as **v2** on a review-weighted,
severity-canonicalised corpus to fix the prioritisation weakness — see the table above and the
[model card](https://huggingface.co/shubh-3011/terramind-7b-terraform).

---

## What it does

- **Analyze** a workspace: 66 static rules across general Terraform hygiene and AWS/Azure/GCP,
  `aws-rubric-v2` evidence-scored security/reliability/maintainability ratings, prioritized
  recommendations, and Problems diagnostics.
- **Estimate cost**: a static, region-aware monthly list-price estimate (AWS/Azure/GCP) with a
  billing basis, unit price and confidence per line, and an explicit list of resources it cannot
  price — an estimate, not a quote.
- **Generate**: a deterministic **scaffolder** (valid, secure AWS Terraform from a resource
  inventory, no model — now including **RDS** and **EKS**) plus a **local generative model** for
  freeform prompts, with preview and explicit save, and one bounded parser/provider-feedback
  retry.
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
scalability, or cost — the cost figure is a **static list-price estimate, not a quote**.
Generated drafts are parsed and receive static security rules before
preview; optional provider validation runs only against a pre-initialised cache in a scratch
directory, and may execute locally installed provider plugins — enable it only for a workspace you
trust. `validate` may run provider plugins; TerraMind never runs `init`, `plan`, or `apply`.

---

## Licences

- Code OSS / VS Code: **MIT** (see `LICENSE.txt` and upstream notices).
- Fine-tuned model: **Apache-2.0** (`Qwen/Qwen2.5-Coder-1.5B-Instruct`).
- Training data includes **CC-BY-4.0** rows (`SASVAAI/terraform-multicloud`); attribution is
  retained in the repository (`ATTRIBUTION.csv`, [docs/MODEL_CARD.md](docs/MODEL_CARD.md)).
