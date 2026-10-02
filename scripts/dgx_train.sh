#!/usr/bin/env bash
# TerraMind training on a big Linux GPU box (DGX / A100 / H100 / 4090-24G).
#
# Why this is different from the laptop script: a DGX has plenty of VRAM *and* system RAM,
# so we fine-tune in full bf16 (no 4-bit), with a larger context (1024) and bigger batch,
# and we can MERGE + EXPORT the GGUF right there. The artifact that ships is identical
# regardless of the training hardware -- only the *base model size* decides what runs on
# a small GPU. See docs/DGX_TRAINING.md.
#
#   bash dgx_train.sh [1.5b|4b|7b|4b-qlora|7b-qlora]      (default: 7b)
set -euo pipefail
cd "$(dirname "$0")"
MODE="${1:-7b}"

echo "=== install dependencies ==="
python -m pip install -U pip
python -m pip install torch "transformers>=4.57.6,<5" "peft>=0.15,<1" \
  "accelerate>=1.6,<2" "safetensors>=0.4" "bitsandbytes>=0.45" gguf sentencepiece
python - <<'PY'
import torch
n = torch.cuda.device_count()
print("cuda:", torch.cuda.is_available(), "| gpus:", n)
for i in range(n):
    p = torch.cuda.get_device_properties(i)
    print(f"  gpu{i}: {p.name} | {p.total_memory/1e9:.0f} GB")
PY

case "$MODE" in
  1.5b)     PRESET="qwen2.5-coder-1.5b-instruct"; BASE_MODEL="Qwen/Qwen2.5-Coder-1.5B-Instruct"; BASE_REV="2e1fd397ee46e1388853d2af2c993145b0f1098a";
            FLAGS="--per-device-batch-size 16 --gradient-accumulation-steps 1" ;;
  4b)       PRESET="qwen3-4b-instruct-2507";       BASE_MODEL="Qwen/Qwen3-4B-Instruct-2507";       BASE_REV="cdbee75f17c01a7cc42f958dc650907174af0554";
            FLAGS="--per-device-batch-size 16 --gradient-accumulation-steps 1" ;;
  7b)       PRESET="qwen2.5-coder-7b-instruct";    BASE_MODEL="Qwen/Qwen2.5-Coder-7B-Instruct";    BASE_REV="c03e6d358207e414f1eca0bb1891e29f1db0e242";
            FLAGS="--per-device-batch-size 16 --gradient-accumulation-steps 1" ;;
  4b-qlora) PRESET="qwen3-4b-instruct-2507";       BASE_MODEL="Qwen/Qwen3-4B-Instruct-2507";       BASE_REV="cdbee75f17c01a7cc42f958dc650907174af0554";
            FLAGS="--load-in-4bit --per-device-batch-size 8 --gradient-accumulation-steps 2" ;;
  7b-qlora) PRESET="qwen2.5-coder-7b-instruct";    BASE_MODEL="Qwen/Qwen2.5-Coder-7B-Instruct";    BASE_REV="c03e6d358207e414f1eca0bb1891e29f1db0e242";
            FLAGS="--load-in-4bit --per-device-batch-size 8 --gradient-accumulation-steps 2" ;;
  *) echo "unknown mode: $MODE"; exit 1 ;;
esac

export PYTHONPATH="$PWD/code"

# Overridable so the same script trains on the distilled corpus at the teacher's context.
DATA_DIR="${DATA_DIR:-data}"
MAX_LEN="${MAX_LEN:-8192}"
EPOCHS="${EPOCHS:-2}"
VALID="$DATA_DIR/validation.jsonl"
[ -f "$VALID" ] || VALID="data/validation.jsonl"   # distilled sets reuse the kit's val split

echo "=== train ($MODE, bf16 unless *-qlora; ctx $MAX_LEN, epochs $EPOCHS, data $DATA_DIR) ==="
python -u -m terramind_ml.train_sft \
  --train "$DATA_DIR/train.jsonl" --validation "$VALID" \
  --output "output/lora-$MODE" --preset "$PRESET" $FLAGS \
  --max-length "$MAX_LEN" --epochs "$EPOCHS" --lora-r 32 --lora-alpha 64 --save-strategy epoch

echo "=== merge adapter into the base ==="
python -u -m terramind_ml.merge_sft --adapter "output/lora-$MODE" --output "output/merged-$MODE"

echo "=== export Q4_K_M GGUF (the artifact that ships to small GPUs) ==="
python -u -m terramind_ml.export_gguf --merged "output/merged-$MODE" \
  --out-dir "output/gguf-$MODE" --quant Q4_K_M \
  --base-model "$BASE_MODEL" --base-revision "$BASE_REV" --license "Apache-2.0"

echo "=== DONE: output/gguf-$MODE/*.gguf ==="
