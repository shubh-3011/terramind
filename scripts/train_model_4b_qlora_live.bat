@echo off
title TerraMind - Train model v4 (Qwen3-4B QLoRA 4-bit)
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
set TERRAMIND_LLAMA_CPP_DIR=C:\Users\shubh\Downloads\terramind\.build\tools\llama-cpp
set PYTHONPATH=C:\Users\shubh\Downloads\terramind\services\analyzer-api
cd /d "C:\Users\shubh\Downloads\terramind\services\analyzer-api"
echo ============================================================
echo   TerraMind model v4: Qwen3-4B-Instruct-2507 (Apache-2.0) QLoRA 4-bit
echo     synth(8000) + security-filtered multi-cloud(4000) -> train -> merge -> Q4 GGUF
echo   Log: C:\Users\shubh\Downloads\terramind\.build\train-v4-log.txt
echo ============================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Continue'; & { $root='C:\Users\shubh\Downloads\terramind'; $py='C:\Users\shubh\Downloads\terramind\.build\sft-train-venv\Scripts\python.exe'; $out=\"$root\.build\terramind-combined-4b\"; New-Item -ItemType Directory -Force -Path $out | Out-Null; Write-Host '=== STEP 0/5: filter insecure multi-cloud examples ==='; & '.venv\Scripts\python.exe' -u -m tools.filter_secure_sft --input \"$root\.build\terramind-terraform-sft-all\train.jsonl\" --output \"$root\.build\_multi_train_secure4b.jsonl\" --keep-first 20000; & '.venv\Scripts\python.exe' -u -m tools.filter_secure_sft --input \"$root\.build\terramind-terraform-sft-all\validation.jsonl\" --output \"$root\.build\_multi_val_secure4b.jsonl\"; Write-Host '=== STEP 1/5: combine ==='; Copy-Item \"$root\.build\terramind-synth-sft\train.jsonl\" \"$out\train.jsonl\" -Force; Get-Content \"$root\.build\_multi_train_secure4b.jsonl\" -TotalCount 4000 | Add-Content \"$out\train.jsonl\"; Copy-Item \"$root\.build\terramind-synth-sft\validation.jsonl\" \"$out\validation.jsonl\" -Force; Get-Content \"$root\.build\_multi_val_secure4b.jsonl\" -TotalCount 500 | Add-Content \"$out\validation.jsonl\"; Write-Host '=== STEP 2/5: QLoRA 4-bit training ==='; & $py -u -m terramind_ml.train_sft --train \"$out\train.jsonl\" --validation \"$out\validation.jsonl\" --output 'C:\Users\shubh\Downloads\terramind\.build\terramind-qwen3-4b-lora' --preset qwen3-4b-instruct-2507 --load-in-4bit --max-length 512 --epochs 1 --lora-r 16 --lora-alpha 32 --save-strategy epoch; if ($LASTEXITCODE -ne 0) { throw 'training failed' }; Write-Host '=== STEP 3/5: merging (needs ~8GB RAM) ==='; & $py -u -m terramind_ml.merge_sft --adapter 'C:\Users\shubh\Downloads\terramind\.build\terramind-qwen3-4b-lora' --output 'C:\Users\shubh\Downloads\terramind\.build\terramind-qwen3-4b-merged' --model 'Qwen/Qwen3-4B-Instruct-2507' --model-revision 'cdbee75f17c01a7cc42f958dc650907174af0554'; if ($LASTEXITCODE -ne 0) { throw 'merge failed' }; Write-Host '=== STEP 4/5: exporting Q4_K_M GGUF ==='; & $py -u -m terramind_ml.export_gguf --merged 'C:\Users\shubh\Downloads\terramind\.build\terramind-qwen3-4b-merged' --out-dir 'C:\Users\shubh\Downloads\terramind\.build\terramind-gguf-4b' --quant Q4_K_M --base-model 'Qwen/Qwen3-4B-Instruct-2507' --base-revision 'cdbee75f17c01a7cc42f958dc650907174af0554' --license 'Apache-2.0'; if ($LASTEXITCODE -ne 0) { throw 'export failed' }; Write-Host '=== ALL STEPS COMPLETE ===' } *>&1 | Tee-Object -FilePath 'C:\Users\shubh\Downloads\terramind\.build\train-v4-log.txt'"

echo.
echo === v4 build finished (exit %ERRORLEVEL%) ===
pause
