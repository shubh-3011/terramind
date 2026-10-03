# Training TerraMind on a cloud / borrowed GPU

> **Status (2026-10-03):** a college **DGX H200 (141 GB/GPU)** is available, which covers the big-GPU paths below directly; cloud rental is a fallback only. See [DGX_TRAINING.md](DGX_TRAINING.md) and [DISTILLATION.md](DISTILLATION.md).

The developer laptop (8 GB VRAM, 16 GB RAM) can fine-tune the 1.5 B model but not a 4 B/7 B
one. Use one of these instead. The self-contained kit is `terramind-training-kit.zip`
(code + `data/train.jsonl` + `data/validation.jsonl` + `cloud_train.sh`).

## Option A - Kaggle (free, best free option)
- Free GPU: **T4 x2 (2 x 16 GB)** or **P100 16 GB**, **~30 GPU-hours/week**, up to ~12 h per session.
- Steps:
  1. Create a Kaggle Dataset from the kit's `data/` folder, or upload `terramind-training-kit.zip` as a dataset.
  2. New Notebook → Settings → Accelerator → **GPU T4 x2** → Internet **On**.
  3. First cell:
     ```bash
     !unzip -q /kaggle/input/terramind-training-kit/terramind-training-kit.zip -d /kaggle/working/kit
     %cd /kaggle/working/kit
     !bash cloud_train.sh 4b-qlora
     ```
     (or `7b-qlora` — Kaggle gives ~13-16 GB RAM, enough to merge the 4 B; a 7 B merge may need more.)
  4. Download `terramind-model-output.zip` from the notebook's Output tab.

## Option B - Google Colab (free tier)
- Free **T4 16 GB**; shorter sessions and possible disconnects (Colab Pro for long runs).
- Upload the kit (or mount Google Drive), then `!bash cloud_train.sh 4b-qlora`.
- Free Colab RAM (~12 GB) is enough for the 4 B merge.

## Option C - cheap rented GPU (fastest, small cost)
- **RunPod / Vast.ai / Paperspace / Lambda**: an RTX 4090 (24 GB) trains the 4 B QLoRA in ~2-3 h
  for roughly **$1-3 total**; a 7 B fits comfortably with 24 GB VRAM **and** enough RAM to merge.
- Upload the kit, `bash cloud_train.sh 7b-qlora`, download the adapter (or the GGUF if you run the
  export step too).

## Option D - a borrowed machine with >= 16 GB RAM
- If a machine has >= 16 GB RAM you can train **and merge 7 B** there (VRAM >= 8 GB is enough with
  4-bit QLoRA). Use `run_training.ps1 -Mode 7b-qlora` (Windows) or `cloud_train.sh 7b-qlora` (Linux).

## What to send back
Just `output/lora-<mode>/` (the small LoRA adapter, ~100-300 MB) plus `training-metadata.json`.
That is enough for me to merge + quantize to GGUF and wire it into the app. If you also produced
`output/merged-<mode>/`, include it.

## Notes
- Base models are **Apache-2.0** (Qwen3-4B-Instruct-2507, Qwen2.5-Coder-1.5B/7B) — redistributable.
- The corpus mixes CC-BY-4.0 dataset rows (attribution kept in the repo) and project-generated
  scaffolder examples.
- Never train on a machine with your cloud credentials configured; the scripts never use them.
