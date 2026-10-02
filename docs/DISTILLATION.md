# Distillation: a big teacher on the DGX → a small model that runs anywhere

## Why
Our 1.5 B student has **hit its capacity ceiling**: adding data (v3) *reduced* its parse rate
(67 % vs 83 %). Meanwhile `SASVAAI/qwen38-27b-terraform` — a 27 B fine-tune **on the same
multicloud data we use**, but with a **8192-token** context and 2 epochs on 8×H200 — reports
`eval_loss 0.353`. Same data, 16× the context, 18× the parameters.

So the lever is **capacity + context**, and the proof is already public. A DGX **H200
(141 GB/GPU)** lets us use that 27 B as a **teacher** and distil its *validated* output into a
model small enough to ship to weak PCs.

```
teacher (27 B, H200)  ──prompts──▶  candidate HCL  ──validate──▶  clean corpus
                                                                      │
                                              small student (1.5 B / 4 B / 7 B)
                                                                      │
                                                          Q4_K_M GGUF ▶ runs on 8 GB
```

## Hardware: what one H200 unlocks
| Job | Memory | H200 (141 GB) |
|---|---|---|
| Run the 27 B teacher, bf16 | ~56 GB | ✅ one GPU, comfortable |
| Run it in Q4 (`Q4_K_M`, 16.8 GB) | ~17 GB | ✅ trivially (even a 24 GB 4090) |
| Fine-tune 7 B at 8192 ctx | ~30–40 GB | ✅ |
| Fine-tune 14 B / 32 B at 8192 ctx | 40–80 GB | ✅ |

## Step 1 — generate the distilled corpus (on the DGX)
```bash
unzip terramind-training-kit.zip -d kit && cd kit
bash dgx_distill.sh data/train.jsonl distil 5000 8
# -> distil/train.jsonl  (system/user/assistant rows)  +  distil-manifest.json
```
Notes:
- Uses the teacher's **exact training contract**: the system prompt from the model card, a
  **description wrapped in a code fence**, and **`enable_thinking=False`**. Off-contract
  prompting will not reproduce the model's behaviour.
- Keeps only completions that **parse as HCL** (`python-hcl2`); drop unparseable output.
- 27 B bf16 fits one H200; use `--batch-size 8` (raise if memory allows).

## Step 2 — validate (locally, or on the DGX if Terraform is installed)
Run the distilled set through the **golden-corpus pipeline** (normalize → `terraform validate`
→ dedupe) so the student is trained only on configs that actually validate. This is optional
but strongly recommended: it removes the residual ~30 % invalid drafts the teacher also makes.

## Step 3 — train the student (on the DGX)
```bash
DATA_DIR=distil MAX_LEN=8192 EPOCHS=2 bash dgx_train.sh 7b     # or 1.5b / 4b
```
`dgx_train.sh` now honours `DATA_DIR`, `MAX_LEN` and `EPOCHS`. Matching the teacher's **8192
context** matters — at our old 512, 37 % of targets were truncated.

## Step 4 — evaluate and ship
```bash
# back on the dev machine: same 12-example held-out harness we already use
scripts\eval_provider_model_live.bat  <gguf>  .build\provider-eval-distil-log.txt
```
Beat the current **83 % parse / 33 % `terraform validate`**, then drop the GGUF into
`services/analyzer-api/models/` (auto-discovered).

## Licensing
- Teacher + base: **Apache-2.0** (`SASVAAI/qwen38-27b-terraform`, `Qwen/Qwen3.8-27B`).
- Data: `SASVAAI/terraform-multicloud` is **CC-BY-4.0** — keep `ATTRIBUTION.csv` with any
  redistribution.
- Distilling an Apache-2.0 model into your own small model is permitted; keep the license and
  the teacher citation (`docs/MODEL_CARD.md`).

## Runtime caveat
The teacher's architecture is `qwen35` — it needs **transformers git main** (to *generate*) and
**llama.cpp ≥ 7cf1c54 / Ollama ≥ 0.34.0** (to *serve* a GGUF). The **student** we train and ship
is an ordinary `qwen2.5`/`qwen3` model, so the app keeps its current runtime; only the DGX
teacher needs the bleeding-edge stack.
