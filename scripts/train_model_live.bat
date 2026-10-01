@echo off
title TerraMind - Model Training (live progress)
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
set PYTHONPATH=C:\Users\shubh\Downloads\terramind\services\analyzer-api
cd /d "C:\Users\shubh\Downloads\terramind\services\analyzer-api"
echo ============================================================
echo   TerraMind fine-tune: Qwen2.5-Coder-1.5B-Instruct (LoRA)
echo   Data: multi-cloud Terraform corpus (72k rows, subset)
echo   Live progress below. A copy is saved to:
echo     C:\Users\shubh\Downloads\terramind\.build\training-log.txt
echo ============================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "& 'C:\Users\shubh\Downloads\terramind\.build\sft-train-venv\Scripts\python.exe' -u -m terramind_ml.train_sft --train 'C:\Users\shubh\Downloads\terramind\.build\terramind-terraform-sft-all\train.jsonl' --validation 'C:\Users\shubh\Downloads\terramind\.build\terramind-terraform-sft-all\validation.jsonl' --output 'C:\Users\shubh\Downloads\terramind\.build\terramind-qwen2.5-coder-1.5b-terraform-lora' --max-train-samples 20000 --max-validation-samples 256 --max-length 512 --epochs 1 --lora-r 16 --lora-alpha 32 --save-strategy epoch 2>&1 | Tee-Object -FilePath 'C:\Users\shubh\Downloads\terramind\.build\training-log.txt'"

echo.
echo ============================================================
echo   Training finished (exit code %ERRORLEVEL%).
echo   Output: .build\terramind-qwen2.5-coder-1.5b-terraform-lora
echo ============================================================
pause
