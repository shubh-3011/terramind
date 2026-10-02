#!/usr/bin/env bash
# TerraMind distillation on a big-GPU box (DGX H200, 141 GB/GPU).
#
# Teacher (SASVAAI/qwen38-27b-terraform, 27 B bf16 = ~56 GB) fits on ONE H200 with
# room to spare. This turns the multicloud prompts into a validated student corpus.
#
#   bash dgx_distill.sh <prompts.jsonl> <out_dir> [limit] [batch]
#
# Typical:  bash dgx_distill.sh ../terramind-training-kit/data/train.jsonl distil 5000 8
set -euo pipefail
cd "$(dirname "$0")"

PROMPTS="${1:?usage: dgx_distill.sh <prompts.jsonl> <out_dir> [limit] [batch]}"
OUTDIR="${2:?missing out_dir}"
LIMIT="${3:-0}"
BATCH="${4:-8}"

echo "=== environment ==="
python -m pip install -U pip
# qwen3_5 (the 27B's architecture) is not in a stable transformers release; git main is required.
python -m pip install "git+https://github.com/huggingface/transformers.git@main" \
    accelerate safetensors sentencepiece python-hcl2

python - <<'PY'
import torch
n = torch.cuda.device_count()
print("cuda:", torch.cuda.is_available(), "| gpus:", n)
for i in range(n):
    p = torch.cuda.get_device_properties(i)
    print(f"  gpu{i}: {p.name} | {p.total_memory/1e9:.0f} GB")
PY

echo "=== generating teacher outputs ==="
python -u dgx_distill.py \
    --prompts "$PROMPTS" --output "$OUTDIR/train.jsonl" \
    --limit "$LIMIT" --batch-size "$BATCH" --max-new-tokens 2048

echo "=== DONE: $OUTDIR/train.jsonl (+ distil-manifest.json) ==="
echo "Next: validate with terraform locally, then:"
echo "  bash dgx_train.sh 7b     # (or 1.5b / 4b) using the distilled corpus"
