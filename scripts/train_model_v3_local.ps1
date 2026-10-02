# TerraMind v3 local training - runs in a visible console with live progress.
# Tuned for an 8 GB GPU: batch 4 x accum 2 (batch 8+ spills into shared memory and is
# ~25x slower), limited CPU threads and expandable CUDA segments to keep the desktop usable.
$ErrorActionPreference = "Continue"
$root = "C:\Users\shubh\Downloads\terramind"
$py   = "$root\.build\sft-train-venv\Scripts\python.exe"

$env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"
$env:OMP_NUM_THREADS                 = "4"
$env:MKL_NUM_THREADS                 = "4"
$env:PYTORCH_CUDA_ALLOC_CONF         = "expandable_segments:True"
$env:PYTHONPATH                      = "$root\services\analyzer-api"
$env:TERRAMIND_LLAMA_CPP_DIR         = "$root\.build\tools\llama-cpp"

$data   = "$root\.build\terramind-combined-sft"
$lora   = "$root\.build\terramind-qwen2.5-coder-v3-lora"
$merged = "$root\.build\terramind-qwen2.5-coder-v3-merged"
$gguf   = "$root\.build\terramind-gguf-v3"
$log    = "$root\.build\train-v3-local-log.txt"

Set-Location "$root\services\analyzer-api"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " TerraMind v3 - Qwen2.5-Coder-1.5B-Instruct (Apache-2.0)" -ForegroundColor Cyan
Write-Host " data    : 8,000 scaffolder-generated + 12,000 security-filtered = 20,000" -ForegroundColor Cyan
Write-Host " config  : bf16 LoRA r16, 1 epoch, batch 4 x accum 2, max_len 512" -ForegroundColor Cyan
Write-Host " watch   : 'step N/2439 loss ... (s/step)' below = live progress" -ForegroundColor Cyan
Write-Host " log     : $log" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "=== STEP 1/3: training ===" -ForegroundColor Yellow
& $py -u -m terramind_ml.train_sft `
    --train    "$data\train.jsonl" `
    --validation "$data\validation.jsonl" `
    --output   $lora `
    --max-length 512 --epochs 1 --lora-r 16 --lora-alpha 32 `
    --per-device-batch-size 4 --gradient-accumulation-steps 2 --save-strategy epoch *>&1 |
    Tee-Object -FilePath $log
if ($LASTEXITCODE -ne 0) { Write-Host "training failed (exit $LASTEXITCODE)" -ForegroundColor Red; exit 1 }

Write-Host "=== STEP 2/3: merging adapter into the base ===" -ForegroundColor Yellow
& $py -u -m terramind_ml.merge_sft --adapter $lora --output $merged *>&1 | Tee-Object -FilePath $log -Append
if ($LASTEXITCODE -ne 0) { Write-Host "merge failed (exit $LASTEXITCODE)" -ForegroundColor Red; exit 1 }

Write-Host "=== STEP 3/3: exporting Q4_K_M GGUF ===" -ForegroundColor Yellow
& $py -u -m terramind_ml.export_gguf --merged $merged --out-dir $gguf --quant Q4_K_M `
    --base-model "Qwen/Qwen2.5-Coder-1.5B-Instruct" `
    --base-revision "2e1fd397ee46e1388853d2af2c993145b0f1098a" `
    --license "Apache-2.0" *>&1 | Tee-Object -FilePath $log -Append
if ($LASTEXITCODE -ne 0) { Write-Host "export failed (exit $LASTEXITCODE)" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "=== COMPLETE. Copy $gguf\*.gguf into services\analyzer-api\models\ ===" -ForegroundColor Green
