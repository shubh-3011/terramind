# Distributing TerraMind (portable Windows build)

> **Status (2026-10-03):** the model is now hosted on **Hugging Face** (primary), with the GitHub
> release asset kept as a **fallback**. The launcher and build script are version-controlled in
> `packaging/`. See [REPOSITORY_SETUP.md](REPOSITORY_SETUP.md) for the public/private repo split.

## What ships
A single portable ZIP (`TerraMind-beta1-win32-x64-full.zip`) that unzips into:

```
TerraMind-beta1-win32-x64-full/
  TerraMind.exe            the desktop app (Code-OSS workbench)
  resources/               app + the terramind-core extension
  analyzer/                the local analysis service
    runtime/               portable Python 3.13 (no install required)
    app/                   the FastAPI analyzer source
    terramind_ml/          (included for completeness)
    models/                empty until the model is downloaded
    run-analyzer.bat       starts uvicorn with the bundled Python
  TerraMind.bat            the launcher (first-run model download + start)
  README-FIRST.txt
```

Sizes: app ~1.35 GB, analyzer ~245 MB, model **not** bundled (see below). ZIP ≈ 600 MB.

The launcher (`TerraMind.bat`) and the script that assembles the ZIP are version-controlled in the
**[`packaging/`](../packaging/)** folder; that folder is the source of truth for the portable
build. Edit `packaging/TerraMind.bat` there, then rebuild/re-release — do not maintain a launcher
only in local build output.

## Why the model is downloaded, not bundled
- The Q4_K_M GGUF is ~940 MB. Bundling it pushes the ZIP past 1.6 GB and burns release storage
  for every release, even though the file never changes.
- Download-on-first-run is the norm (Ollama, LM Studio). `TerraMind.bat` fetches it once into
  `%USERPROFILE%\.terramind\models\`, where the analyzer's own discovery already looks.

## Where the model is hosted
Single source of truth: the `MODEL_URL` variable at the top of `packaging/TerraMind.bat`. It now
points at **Hugging Face** as the **primary** host:

```
https://huggingface.co/shubh-3011/terramind-qwen2.5-coder-1.5b-terraform/resolve/main/terramind-qwen2.5-coder-v2-merged-Q4_K_M.gguf
```

The **GitHub release asset** is retained as a **fallback** (download it if Hugging Face is
unreachable or for offline mirroring):

```
https://github.com/shubh-3011/terramind/releases/download/v0.1.0-beta.1/terramind-qwen2.5-coder-v2-merged-Q4_K_M.gguf
```

Hugging Face gives a better CDN, resumable and versioned downloads, and clearer model metadata.
Both sources are public, so no credentials are required.

**To change `MODEL_URL`:**
1. Upload the GGUF to the Hugging Face repo
   ([`shubh-3011/terramind-qwen2.5-coder-1.5b-terraform`](https://huggingface.co/shubh-3011/terramind-qwen2.5-coder-1.5b-terraform))
   and copy its direct `.../resolve/main/<file>.gguf` URL.
2. Edit `MODEL_URL` at the top of `packaging/TerraMind.bat` and rebuild the ZIP (or just edit the
   launcher and re-zip). Record the new SHA-256 for download verification.
3. Update [MODEL_CARD.md](MODEL_CARD.md) and this document if the artifact name or checksum changes.
No other change is needed — the launcher and the analyzer are agnostic to the host.

## Building the analyzer payload (dev machine)
```powershell
$an = "<bundle>\analyzer"
New-Item -ItemType Directory -Force "$an\models" | Out-Null
Copy-Item "C:\Python313" "$an\runtime" -Recurse -Force      # portable runtime
# IMPORTANT: install with --target so packages land INSIDE the bundle, not the user profile
& "$an\runtime\python.exe" -m pip install --target "$an\runtime\Lib\site-packages" `
  "fastapi>=0.115,<1.0" "uvicorn[standard]>=0.30,<1.0" "python-hcl2>=7.3,<8" `
  "httpx>=0.27,<1.0" python-multipart "llama-cpp-python==0.3.36" `
  --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
Copy-Item "<repo>\services\analyzer-api\app" "$an\app" -Recurse -Force
```
The **CPU** llama-cpp-python wheel is ~12 MB (vs ~1.9 GB for the CUDA build), which is what makes
a one-file download possible. The CUDA build would exceed GitHub's 2 GB per-asset limit.

## GPU variant (planned, separate asset)
For users with an NVIDIA GPU, ship a second payload with the CUDA `llama-cpp-python` build and
set `TERRAMIND_GGUF_N_GPU_LAYERS=-1` in the launcher. Keep it a separate asset because it is
~1.9 GB.

## Verify a build locally
```powershell
# start the bundled analyzer and check health (no need to run the whole app)
$env:PYTHONNOUSERSITE="1"; $env:TERRAMIND_GGUF_N_GPU_LAYERS="0"
& "<bundle>\analyzer\runtime\python.exe" -m uvicorn app.main:app --port 8010
curl.exe -s http://127.0.0.1:8010/health      # -> {"status":"ok"}
```
