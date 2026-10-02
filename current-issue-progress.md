# TerraMind — current state, how to run it, and open issues

_Last updated: 2026-10-02. Branch: `testing` (mirrored to the default branch `main`)._

This is the single-page orientation doc: what TerraMind is, what is finished, exactly how to
run it, what AI it uses, and what is still broken or weak.

---

## 1. What TerraMind is

TerraMind is a **private, open-source-targeted Code-OSS fork for Terraform** (not a Marketplace
extension). Terraform intelligence is bundled into the editor: it can **analyse** a workspace,
**score** it, **recommend** fixes, and **generate** Terraform from a prompt or a resource
inventory. It ships its **own local model** and needs **no Ollama** for the default path.

Two run targets:

- **Native desktop app** (the real VS Code workbench, `VSCode-win32-x64\TerraMind.exe`).
- **Browser workbench** (`http://localhost:8080`, same workbench compiled for the web).

Both talk to the same local **FastAPI analyzer** at `http://127.0.0.1:8000`.

---

## 2. Where the project stands (2026-10-02)

| Area | State |
| --- | --- |
| Desktop app (native Windows) | **Works** — the window opens; workbench + extension load |
| Browser workbench | **Works** (http://localhost:8080) |
| Extension UI | Wizard (guided form), TerraMind Report panel, dashboard, diagnostics, health check, demo-fixture analysis, repair diff flow |
| Analyzer API | **66 deterministic AWS/general/Azure/GCP rules**, per-service ratings (security/reliability/maintainability), prioritized recommendations, workspace allowlist, opt-in `fmt`/`validate`/TFLint/Checkov |
| Deterministic **scaffolder** | **Works** — inventory → valid, secure AWS Terraform with no model (0.1–0.5 s) |
| Local AI model | Fine-tuned `Qwen2.5-Coder-1.5B` (Apache-2.0), **940 MB Q4_K_M GGUF**, auto-discovered, runs on the **GPU** via llama.cpp (~100 tok/s) |
| Generation progress | Real percentage (`0–100 %`) via a job API + cancellable notification |
| Tests | **157 passing** (analyzer/data/training/eval); extension TypeScript check clean |
| Git | Everything committed to `main` + `testing` |

**Overall estimate:** roughly **70–75 %** of the agreed MVP scope by milestone coverage — a
usable prototype/demo, **not** a production tool.

---

## 3. How to run it

### Prerequisites (already set up on the dev machine)

- Python venv at `services\analyzer-api\.venv` (FastAPI, hcl2, llama-cpp-python **CUDA** build).
- Bundled model at `services\analyzer-api\models\terramind-qwen2.5-coder-v2-merged-Q4_K_M.gguf`.
- Built app at `C:\Users\shubh\Downloads\VSCode-win32-x64\TerraMind.exe`.

### A. The native desktop app (recommended)

1. **Start the analyzer** (leave the window open):
   ```
   scripts\analyzer_live.bat
   ```
   This serves `http://127.0.0.1:8000` with the bundled model on the GPU (`n_gpu_layers=-1`,
   `TERRAMIND_GGUF_MAX_TOKENS=2048`, `TERRAMIND_GGUF_REPEAT_PENALTY=1.2`).
2. **Launch the app**:
   ```
   C:\Users\shubh\Downloads\VSCode-win32-x64\TerraMind.exe
   ```
   (or the dev build: `scripts\code.bat .`)
3. Open a Terraform folder, then use the Command Palette (`Ctrl+Shift+P`):
   - **TerraMind: Analyze Terraform Workspace** → Problems + Report (scores + recommendations).
   - **TerraMind: Generate Infrastructure (Guided)** → fill the form → **Generate**.
   - **TerraMind: Check Analyzer Connection** → confirms the analyzer is reachable.

### B. The browser workbench

1. `scripts\analyzer_live.bat` (above).
2. `scripts\web_live.bat` → serves `http://localhost:8080`; open it in **Edge/Chrome**
   (Brave needs `brave://flags/#file-system-access-api` → Enabled for local folders).
3. Without a folder, run **TerraMind: Analyze Demo Fixture** from the Command Palette.

### C. Rebuilding

```
# Analyzer tests
cd services\analyzer-api && .\.venv\Scripts\python.exe -m pytest -q

# Extension typecheck + browser bundle
node_modules\.bin\tsc.cmd --noEmit -p extensions/terramind-core/tsconfig.json
node --experimental-strip-types extensions/terramind-core/esbuild.browser.mts

# Windows desktop package (~30 min) -> VSCode-win32-x64\TerraMind.exe
npm run gulp vscode-win32-x64-min
```

### D. Example generation prompts

- **Scaffolder (fast, deterministic):** put a resource inventory in the wizard, e.g.
  `VPC 2, EC2 instance 2, S3 bucket 1, Application Load Balancer 1` → returns valid, secure HCL
  in well under a second.
- **AI (freeform):** leave the inventory empty and describe intent, e.g.
  `a private S3 bucket with encryption and versioning` → the GGUF model drafts it on the GPU.

---

## 4. What AI TerraMind uses

Three separate things, deliberately labelled apart in the UI:

1. **Deterministic scaffolder (no AI)** — `services/analyzer-api/app/scaffold.py`. Parses a
   resource inventory and emits valid, secure AWS Terraform from templates (VPCs, subnets,
   IGW/NAT + route tables, security groups, EC2 with encrypted EBS + IMDSv2, S3 with SSE +
   versioning + public-access-block, ALB, Transit Gateway attachments, IAM/SSM, flow logs).
   **Instant and always parseable.** Preferred automatically when an inventory is supplied.
2. **Local generative model** — a **LoRA fine-tune of `Qwen/Qwen2.5-Coder-1.5B-Instruct`**
   (Apache-2.0, pinned revision `2e1fd397ee46e1388853d2af2c993145b0f1098a`), trained on
   20,000 **multi-cloud** Terraform examples (2 epochs; train loss 0.424, eval loss 0.460) and
   exported to a **940 MB `Q4_K_M` GGUF**. It runs offline through **`llama-cpp-python`**
   (CUDA build) on the **RTX 4060 (~100 tok/s)**. No Ollama required; Ollama and Transformers
   backends remain optional.
3. **Experimental ML risk model** — a small logistic-regression classifier (46 benchmark
   examples) that estimates a benchmark-control risk probability. It is **uncalibrated** and
   shown separately from scanner findings.

Engine selection: the extension setting `terramind.generationEngine` (default `auto`).
`auto` → scaffolder when a resource inventory is present, else the GGUF model (a CUDA GGUF →
Transformers → Ollama). Explicit `scaffold` / `gguf` / `ollama` / `transformers` force one.

---

## 5. Current issues and limitations

**AI quality (the main one)**

1. The **1.5 B model is weak on complex prompts.** It handles simple requests (e.g. one S3
   bucket) but produces little or loops on large architectures (e.g. 5 VPCs + Transit Gateway).
   Measured on 12 held-out examples: **83 % parse, 42 % pass `terraform validate`** — and the
   parser accepts some deprecated/incorrect constructs. Treat AI output as a **draft only**.
2. Because of (1), the **deterministic scaffolder** is the recommended path for structured
   requests; the model is for freeform/edge cases.
3. Generation is **stochastic** — results vary run to run; truncated output is trimmed, which
   can drop the last resource.

**Product / platform**

4. The **packaged desktop app is a snapshot**: source changes require either a rebuild
   (`npm run gulp vscode-win32-x64-min`, ~30 min) or copying the compiled extension into
   `VSCode-win32-x64\resources\app\extensions\terramind-core\out`.
5. **Browser folder access** needs Edge/Chrome (or enabling the File System Access API flag in
   Brave); otherwise use **Analyze Demo Fixture**.
6. **CI is blocked**: GitHub-hosted checks do not run because of an account payment/spending
   limit; hosted packaging artifacts are therefore unverified.
7. Repo hygiene: `.build/`, model weights (`*.gguf`), venvs, and local launch state are
   git-ignored; the model must be shipped as a **release asset** (see `docs/OPEN_SOURCE.md`),
   not committed.

**Known technical limits**

8. The analyzer is **static**: modules/variables are not expanded, `jsonencode` policy bodies are
   not inspected, and ratings are transparent rubrics — not calibrated measurements.
9. The scaffolder covers common AWS patterns only; it is not a general-purpose generator and
   does not emit Azure/GCP scaffolds.
10. The experimental risk model is uncalibrated with a tiny sample — do not use it for decisions.

---

## 6. Suggested next steps

1. **Make the desktop launch reproducible**: rebuild the package from the current source so the
   scaffolder, save-flow fix, and timeouts are in the shipped `.exe`.
2. **Improve the model** (optional): train on more reviewed, provider-valid examples, or move to a
   larger base (`Qwen2.5-Coder-7B` Q4) on a bigger GPU.
3. **Broaden the scaffolder** (Azure/GCP, RDS, EKS) and add `terraform validate` to the
   scaffolder test suite.
4. **Unblock CI** (GitHub billing) so packaging and checks run and `main` can be merged normally.
5. **Evaluate**: run the held-out generator evaluation at a larger sample with a provider cache.

---

## 7. Repository map (quick)

```
PLAN.md, PROGRESS.md, ARCHITECTURE.md, README.md   project docs (this file is the current snapshot)
current-issue-progress.md                          this file
services/analyzer-api/app/                         analyzer: main.py, rules/, ratings.py, recommendations.py,
                                                    scaffold.py, llama_cpp_backend.py, generated_validator.py
services/analyzer-api/models/                      bundled GGUF (git-ignored)
services/analyzer-api/tests/                       analyzer/scaffold/ML tests (157 passing)
extensions/terramind-core/                         bundled extension (wizard, report, dashboard)
scripts/                                           *_live.bat launchers (analyzer, web, train, export, eval)
docs/                                              RUNNING_LOCAL_MODEL.md, MODEL_CARD.md, OPEN_SOURCE.md, ...
```
