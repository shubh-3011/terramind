# Packaging TerraMind (portable Windows beta)

This folder holds the versioned inputs for the portable Windows distribution. It
is the source of truth for the launcher, the end-user readme, the analyzer
starter and the build script. Nothing here is copied into the app at build time;
the build script copies these files into the assembled bundle.

## Files

| File | Purpose |
| --- | --- |
| `TerraMind.bat` | Launcher shipped in the ZIP. Downloads the GGUF on first run (Hugging Face), starts the analyzer, waits on `/health`, opens the app. |
| `readme-first.txt` | End-user readme. Copied into the bundle as `README-FIRST.txt`. |
| `analyzer/run-analyzer.bat` | Starts the bundled portable Python + uvicorn with `PYTHONNOUSERSITE=1`. |
| `build-portable.ps1` | Assembles the full bundle from the built app + analyzer sources, then optionally zips it. |
| `README.md` | This file. |

## Bundle layout

The assembled ZIP unzips into one self-contained folder:

```
TerraMind-beta1-win32-x64-full/
  TerraMind.exe            desktop app (Code-OSS workbench)
  resources/               app + the terramind-core extension
  *.dll, *.pak, locales/   Electron/Chromium runtime files
  analyzer/
    runtime/               portable Python 3.13 (no install required)
      Lib/site-packages/   analyzer deps installed with --target
    app/                   the FastAPI analyzer source
    terramind_ml/          feature extraction + risk helpers
    models/                empty; the GGUF is downloaded on first run
    pyproject.toml
    run-analyzer.bat       starts uvicorn with the bundled Python
  TerraMind.bat            the launcher (start here)
  README-FIRST.txt
```

Sizes: app ~1.35 GB, analyzer ~245 MB. The model is **not** bundled (see below),
so the ZIP stays around 600 MB.

## Why the model is downloaded, not bundled

- The Q4_K_M GGUF is ~940 MB. Bundling it pushes the ZIP past 1.6 GB and burns
  release storage on every release even though the file never changes.
- Download-on-first-run is the norm (Ollama, LM Studio). `TerraMind.bat` fetches
  it once into `%USERPROFILE%\.terramind\models\`, where the analyzer's own model
  discovery (`_gguf_search_dirs` in `app/main.py`) already looks.

The launcher is the single source of truth for the model URL:

```
https://huggingface.co/shubh-3011/terramind-qwen2.5-coder-1.5b-terraform/resolve/main/terramind-qwen2.5-coder-v2-merged-Q4_K_M.gguf
```

To move hosts, change `MODEL_URL` in `packaging/TerraMind.bat` and rebuild (or
just edit the bat and re-zip). The analyzer is host-agnostic.

## Building the bundle

Prerequisites on the build machine:

- A built desktop app folder containing `TerraMind.exe` and `resources/`
  (by default the script looks for a sibling `VSCode-win32-x64` next to this
  repository).
- A full CPython install to copy as the portable runtime (default `C:\Python313`,
  Python 3.11-3.13).
- Internet access for `pip` (Hugging Face/`pip` and the CPU llama-cpp index).

Run:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build-portable.ps1
# add -Zip to also produce TerraMind-beta1-win32-x64-full.zip
# override locations:
#   -SourceApp   D:\build\VSCode-win32-x64
#   -PythonSource D:\Python313
#   -OutputDir   D:\dist\terramind
```

What the script does, in order:

1. Stages a clean output folder.
2. Copies the desktop app, excluding any stale `analyzer/`, `TerraMind.bat` and
   `README-FIRST.txt`.
3. Copies the portable Python runtime into `analyzer\runtime` (stripping
   `__pycache__`).
4. `pip install --target analyzer\runtime\Lib\site-packages` for
   `fastapi`, `uvicorn[standard]`, `python-hcl2`, `httpx`, `python-multipart` and
   the CPU `llama-cpp-python==0.3.36` from
   `https://abetlen.github.io/llama-cpp-python/whl/cpu`. **`--target` is the key
   flag** — it keeps packages inside the bundle instead of the user profile.
5. Copies `services/analyzer-api/app` and `services/analyzer-api/terramind_ml`.
6. Drops in `TerraMind.bat`, `README-FIRST.txt` and
   `analyzer/run-analyzer.bat` from this folder.

## Verifying a build

Start just the bundled analyzer and check health (no need to run the whole app):

```powershell
$env:PYTHONNOUSERSITE="1"; $env:TERRAMIND_GGUF_N_GPU_LAYERS="0"
& "<bundle>\analyzer\runtime\python.exe" -m uvicorn app.main:app --port 8010
curl.exe -s http://127.0.0.1:8010/health      # -> {"status":"ok"}
```

## Shipping

Upload `TerraMind-beta1-win32-x64-full.zip` as a release asset. The model lives
on Hugging Face, so no release asset is needed for it, which keeps each release
asset under GitHub's 2 GB per-file limit.

## GPU variant (planned)

Ship a separate asset with the CUDA `llama-cpp-python` build and set
`TERRAMIND_GGUF_N_GPU_LAYERS=-1`. Keep it separate because the CUDA build is
~1.9 GB.
