# Training on a DGX (or any big GPU) and shipping to a small GPU

> **Status (2026-10-03):** confirmed target hardware is a **DGX H200 (141 GB/GPU)** — one GPU holds the 27 B teacher bf16 (~56 GB) and trains 7 B/14 B/32 B at 8192 context. `scripts/dgx_train.sh <mode>` does train → merge → `Q4_K_M` export; the student ships and runs on an 8 GB PC.

## The short answer
**Yes — you can fine-tune a much bigger model on a college DGX and still run it efficiently
on your 8 GB RTX 4060.** What matters for the *user's* experience is only **which base model
you pick** and **how hard you quantize it** — not where it was trained.

## Why training and running need different hardware
Training and inference are completely different memory problems:

| | What lives in GPU memory | Rough multiple of model size |
|---|---|---|
| **Training** (LoRA/Full) | weights + gradients + optimizer state + every activation kept for backprop | **~4–20×** |
| **Inference** (llama.cpp) | weights only + a small KV cache for the prompt | **~1×** |

So a 7 B model:
- **training** wants ~15–20 GB (that's why your 8 GB laptop chokes),
- **running** needs only ~4.4 GB once quantized to 4-bit (that's why it's fine on your 4060).

Training on the DGX removes the *training* bottleneck (VRAM, RAM, time, and the merge step
that OOMs on 16 GB). It does **not** change the size of the model you later run.

## Quantization is what makes it fit
The merged model is stored in 16-bit (~2 bytes/param). We convert it to **GGUF Q4_K_M**
(~0.55 bytes/param) with llama.cpp — roughly a **3.6× shrink** with a small quality loss:

| Base model | fp16 size | **Q4_K_M size** | Runs on 8 GB RTX 4060? | Speed on the 4060 |
|---|---|---|---|---|
| Qwen2.5-Coder-1.5B | 3.1 GB | **~1.0 GB** | ✅ easily | ~90–120 tok/s |
| Qwen3-4B / Qwen2.5-Coder-3B | 8 GB | **~2.5 GB** | ✅ easily | ~45–70 tok/s |
| **Qwen2.5-Coder-7B** | 15 GB | **~4.4 GB** | ✅ comfortably | **~25–45 tok/s** |
| Qwen2.5-Coder-14B | 29 GB | **~9 GB** | ⚠️ borderline (partial offload → slow) | ~5–12 tok/s |
| Qwen2.5-Coder-32B | 65 GB | **~20 GB** | ❌ no | — |

**Sweet spot for shipping to 8 GB GPUs: 7 B Q4_K_M (~4.4 GB).** It leaves ~3 GB for context
and still does tens of tokens/second. 14 B is the practical ceiling and only on 12–16 GB GPUs.

## Plan
1. **On the DGX:** fine-tune **Qwen2.5-Coder-7B-Instruct** (Apache-2.0) in bf16 with the kit,
   then merge and export Q4_K_M. `scripts/dgx_train.sh 7b` does all three.
2. **Ship two sizes:** keep the 1.5 B as the default (fast, tiny, CPU-friendly) and offer the
   7 B as the "quality" download. TerraMind auto-discovers whatever `.gguf` is in
   `services/analyzer-api/models/`.
3. Nothing else changes — the runtime, the scaffolder, and the analyzer stay identical.

## Running it on the DGX
```bash
unzip terramind-training-kit.zip -d terramind-kit && cd terramind-kit
bash dgx_train.sh 7b          # bf16 LoRA + merge + Q4_K_M export
# result: output/gguf-7b/*.gguf  ->  copy into services/analyzer-api/models/
```
- Modes: `1.5b | 4b | 7b` (bf16) or `4b-qlora | 7b-qlora` (if a node has a smaller GPU).
- The script prints the GPUs and sizes it sees first, so you can confirm it's on the DGX.
- 7 B bf16 needs ~16 GB free VRAM for training; a DGX clears that easily.
- Expect a few hours for 3 epochs over the 20 k examples — versus days that it would need on
  a laptop that has to spill.

## Commercial/licensing note
All base models listed above are **Apache-2.0** (redistributable). The corpus mixes CC-BY-4.0
dataset rows (attribution kept in the repo) and project-generated examples. `3B` Qwen2.5-Coder
and some other 3 B checkpoints are **non-commercial** — avoid them for an open-source product;
use Qwen3-4B or Qwen2.5-Coder-7B instead.
