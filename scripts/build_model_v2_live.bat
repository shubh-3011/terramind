@echo off
title TerraMind - Build model v2 (train -^> merge -^> GGUF)
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
set TERRAMIND_GENERATION_ENGINE=gguf
set TERRAMIND_LLAMA_CPP_DIR=C:\Users\shubh\Downloads\terramind\.build\tools\llama-cpp
set PYTHONPATH=C:\Users\shubh\Downloads\terramind\services\analyzer-api
cd /d "C:\Users\shubh\Downloads\terramind\services\analyzer-api"
echo ============================================================
echo   TerraMind model v2: train (2 epochs) -^> merge -^> Q4 GGUF
echo   Live progress below. A copy is saved to:
echo     C:\Users\shubh\Downloads\terramind\.build\build-model-v2-log.txt
echo ============================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Continue'; & { $py='C:\Users\shubh\Downloads\terramind\.build\sft-train-venv\Scripts\python.exe'; Write-Host '=== STEP 1/3: training (2 epochs) ==='; & $py -u -m terramind_ml.train_sft --train 'C:\Users\shubh\Downloads\terramind\.build\terramind-terraform-sft-all\train.jsonl' --validation 'C:\Users\shubh\Downloads\terramind\.build\terramind-terraform-sft-all\validation.jsonl' --output 'C:\Users\shubh\Downloads\terramind\.build\terramind-qwen2.5-coder-v2-lora' --max-train-samples 20000 --max-validation-samples 256 --max-length 512 --epochs 2 --lora-r 16 --lora-alpha 32 --save-strategy epoch; if ($LASTEXITCODE -ne 0) { throw 'training failed' }; Write-Host '=== STEP 2/3: merging adapter ==='; & $py -u -m terramind_ml.merge_sft --adapter 'C:\Users\shubh\Downloads\terramind\.build\terramind-qwen2.5-coder-v2-lora' --output 'C:\Users\shubh\Downloads\terramind\.build\terramind-qwen2.5-coder-v2-merged'; if ($LASTEXITCODE -ne 0) { throw 'merge failed' }; Write-Host '=== STEP 3/3: exporting Q4_K_M GGUF ==='; & $py -u -m terramind_ml.export_gguf --merged 'C:\Users\shubh\Downloads\terramind\.build\terramind-qwen2.5-coder-v2-merged' --out-dir 'C:\Users\shubh\Downloads\terramind\.build\terramind-gguf-v2' --quant Q4_K_M --base-model 'Qwen/Qwen2.5-Coder-1.5B-Instruct' --base-revision '2e1fd397ee46e1388853d2af2c993145b0f1098a' --license 'Apache-2.0'; if ($LASTEXITCODE -ne 0) { throw 'export failed' }; Write-Host '=== ALL STEPS COMPLETE ===' } *>&1 | Tee-Object -FilePath 'C:\Users\shubh\Downloads\terramind\.build\build-model-v2-log.txt'"

echo.
echo === Build finished (exit %ERRORLEVEL%) ===
pause
