@echo off
title TerraMind - Train model v3 (synth + security-filtered multi-cloud)
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
set TERRAMIND_LLAMA_CPP_DIR=C:\Users\shubh\Downloads\terramind\.build\tools\llama-cpp
set PYTHONPATH=C:\Users\shubh\Downloads\terramind\services\analyzer-api
cd /d "C:\Users\shubh\Downloads\terramind\services\analyzer-api"
echo ============================================================
echo   TerraMind model v3:
echo     synth scaffold data (8000) + security-filtered multi-cloud (12000)
echo     -> train -> merge -> export Q4_K_M GGUF
echo   Log: C:\Users\shubh\Downloads\terramind\.build\train-v3-log.txt
echo ============================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Continue'; & { $root='C:\Users\shubh\Downloads\terramind'; $py='C:\Users\shubh\Downloads\terramind\.build\sft-train-venv\Scripts\python.exe'; $out=\"$root\.build\terramind-combined-sft\"; New-Item -ItemType Directory -Force -Path $out | Out-Null; Write-Host '=== STEP 0/5: filter insecure examples out of the internet corpus ==='; & '.venv\Scripts\python.exe' -u -m tools.filter_secure_sft --input \"$root\.build\terramind-terraform-sft-all\train.jsonl\" --output \"$root\.build\_multi_train_secure.jsonl\" --keep-first 40000; & '.venv\Scripts\python.exe' -u -m tools.filter_secure_sft --input \"$root\.build\terramind-terraform-sft-all\validation.jsonl\" --output \"$root\.build\_multi_val_secure.jsonl\"; Write-Host '=== STEP 1/5: combine datasets ==='; Copy-Item \"$root\.build\terramind-synth-sft\train.jsonl\" \"$out\train.jsonl\" -Force; Get-Content \"$root\.build\_multi_train_secure.jsonl\" -TotalCount 12000 | Add-Content \"$out\train.jsonl\"; Copy-Item \"$root\.build\terramind-synth-sft\validation.jsonl\" \"$out\validation.jsonl\" -Force; Get-Content \"$root\.build\_multi_val_secure.jsonl\" -TotalCount 1000 | Add-Content \"$out\validation.jsonl\"; Write-Host '=== STEP 2/5: training (1 epoch) ==='; & $py -u -m terramind_ml.train_sft --train \"$out\train.jsonl\" --validation \"$out\validation.jsonl\" --output 'C:\Users\shubh\Downloads\terramind\.build\terramind-qwen2.5-coder-v3-lora' --max-length 512 --epochs 1 --lora-r 16 --lora-alpha 32 --save-strategy epoch; if ($LASTEXITCODE -ne 0) { throw 'training failed' }; Write-Host '=== STEP 4/5: merging ==='; & $py -u -m terramind_ml.merge_sft --adapter 'C:\Users\shubh\Downloads\terramind\.build\terramind-qwen2.5-coder-v3-lora' --output 'C:\Users\shubh\Downloads\terramind\.build\terramind-qwen2.5-coder-v3-merged'; if ($LASTEXITCODE -ne 0) { throw 'merge failed' }; Write-Host '=== STEP 5/5: exporting Q4_K_M GGUF ==='; & $py -u -m terramind_ml.export_gguf --merged 'C:\Users\shubh\Downloads\terramind\.build\terramind-qwen2.5-coder-v3-merged' --out-dir 'C:\Users\shubh\Downloads\terramind\.build\terramind-gguf-v3' --quant Q4_K_M --base-model 'Qwen/Qwen2.5-Coder-1.5B-Instruct' --base-revision '2e1fd397ee46e1388853d2af2c993145b0f1098a' --license 'Apache-2.0'; if ($LASTEXITCODE -ne 0) { throw 'export failed' }; Write-Host '=== ALL STEPS COMPLETE ===' } *>&1 | Tee-Object -FilePath 'C:\Users\shubh\Downloads\terramind\.build\train-v3-log.txt'"

echo.
echo === v3 build finished (exit %ERRORLEVEL%) ===
pause
