# Running TerraMind with the bundled local model (no Ollama)

TerraMind ships an optional, locally hosted Terraform generator: a LoRA fine-tune of
`Qwen/Qwen2.5-Coder-1.5B-Instruct`, exported to a quantized GGUF and run through
`llama-cpp-python` (llama.cpp). It drafts Terraform HCL for review and never deploys
anything. **Ollama is not required.** The model file stays on your machine and the
analyzer binds to loopback only.

This guide is for an end user who wants copy-paste setup. For the model's provenance,
intended use, and limitations, see [MODEL_CARD.md](MODEL_CARD.md); for the release and
attribution checklist, see [OPEN_SOURCE.md](OPEN_SOURCE.md).

## At a glance

| Field | Value |
| --- | --- |
| Base model | `Qwen/Qwen2.5-Coder-1.5B-Instruct` |
| Base license | Apache-2.0 |
| Base revision | `2e1fd397ee46e1388853d2af2c993145b0f1098a` |
| Fine-tune | LoRA SFT; 20,000 multi-cloud Terraform examples; train_loss 0.475, eval_loss 0.470, 2,395 steps |
| Format | GGUF, `Q4_K_M` quant |
| File | `terramind-qwen2.5-coder-1.5b-terraform-merged-Q4_K_M.gguf` |
| Size | 940 MB (986,048,192 bytes; 940.37 MiB) |
| SHA-256 | `6917bf571e822b5739b671509c37e32c66800c78af9d54c6546326e13fec7906` |
| Runtime | `llama-cpp-python` (llama.cpp); **no Ollama** |

The GGUF is **not committed to Git**. It is large (940 MB) and must be hosted as a
GitHub release asset. See [OPEN_SOURCE.md](OPEN_SOURCE.md) for how it is published.

## 0. Built-in (no configuration)

TerraMind discovers its own model automatically. If a `.gguf` file is present in any of
these locations (first match wins) and `TERRAMIND_GENERATION_ENGINE` is `auto` (the default),
the analyzer selects the GGUF engine with **no environment variables and no Ollama**:

1. `TERRAMIND_GGUF_MODEL` (an explicit file path; always wins)
2. `TERRAMIND_MODELS_DIR` if set
3. `services/analyzer-api/models/` (next to the analyzer - the recommended install location)
4. `<repository>/models/`
5. `~/.terramind/models/` (`%USERPROFILE%\.terramind\models` on Windows)

So a packaged TerraMind just needs the `.gguf` dropped into `models/`; nothing else to configure.
Set `TERRAMIND_GENERATION_ENGINE=ollama` (or `transformers`) to override the choice.

## 1. Get the GGUF

Pick one of the following.

### Option A - download the GitHub release asset (recommended)

The release attaches the `.gguf` and `model-manifest.json` to a tag. With the example
release tag `terramind-v0.1.0-model`, the direct download URL is:

```text
https://github.com/shubh-3011/terramind/releases/download/terramind-v0.1.0-model/terramind-qwen2.5-coder-1.5b-terraform-merged-Q4_K_M.gguf
```

Download that file (and `model-manifest.json`) into a folder you will keep, for
example `%LOCALAPPDATA%\TerraMind\models\`. After downloading, verify the checksum:

```powershell
(Get-FileHash "$env:LOCALAPPDATA\TerraMind\models\terramind-qwen2.5-coder-1.5b-terraform-merged-Q4_K_M.gguf" -Algorithm SHA256).Hash.ToLower()
```

The result must equal the SHA-256 in the table above.

### Option B - use the helper script

`scripts/get_model.ps1` downloads the asset from the release URL, verifies the
SHA-256, and prints the environment variables to set. It never overwrites a valid
existing file.

```powershell
.\scripts\get_model.ps1 `
  -Repo shubh-3011/terramind `
  -Tag terramind-v0.1.0-model `
  -AssetName terramind-qwen2.5-coder-1.5b-terraform-merged-Q4_K_M.gguf `
  -OutDir "$env:LOCALAPPDATA\TerraMind\models" `
  -Sha256 6917bf571e822b5739b671509c37e32c66800c78af9d54c6546326e13fec7906
```

### Option C - build it from source

If you have the merged model directory and the llama.cpp tools, build the GGUF with the
export CLI. `TERRAMIND_LLAMA_CPP_DIR` must point at a llama.cpp checkout that contains
`convert_hf_to_gguf.py` and `llama-quantize`. No GPU is required.

```powershell
# From services\analyzer-api, inside the analyzer virtual environment
python -m terramind_ml.export_gguf `
  --merged ..\..\.build\terramind-qwen2.5-coder-1.5b-terraform-merged `
  --out-dir ..\..\.build\terramind-gguf `
  --quant Q4_K_M `
  --base-model Qwen/Qwen2.5-Coder-1.5B-Instruct `
  --base-revision 2e1fd397ee46e1388853d2af2c993145b0f1098a `
  --license Apache-2.0
```

The export writes the `.gguf` plus `model-manifest.json` (base model, pinned revision,
license, quant type, SHA-256, byte size). Keep the manifest with the model.

## 2. Install the inference runtime

Install `llama-cpp-python` into the **same virtual environment that runs the analyzer**
(for example `services\analyzer-api\.venv`, created per the README with Python 3.11-3.13).
The CPU wheel index avoids a local compiler toolchain:

```powershell
python -m pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
```

For a CUDA build, use the matching `cu12x` wheel index from the same project instead of
building from source. The import is lazy: the analyzer only loads `llama-cpp-python` when
the GGUF engine is actually used.

## 3. Point TerraMind at the GGUF

Set two environment variables in the shell that starts the analyzer. Use an absolute path
to the file you downloaded.

```powershell
$env:TERRAMIND_GENERATION_ENGINE = "gguf"
$env:TERRAMIND_GGUF_MODEL = "$env:LOCALAPPDATA\TerraMind\models\terramind-qwen2.5-coder-1.5b-terraform-merged-Q4_K_M.gguf"
```

Optional tuning (defaults shown). Leave them alone unless you need to change behaviour:

| Variable | Default | Purpose |
| --- | --- | --- |
| `TERRAMIND_GGUF_N_CTX` | 8192 | Context window in tokens |
| `TERRAMIND_GGUF_TEMPERATURE` | 0.1 | Sampling temperature |
| `TERRAMIND_GGUF_MAX_TOKENS` | 1024 | Maximum generated tokens |
| `TERRAMIND_GGUF_N_THREADS` | auto | CPU threads for inference |

## 4. Start the analyzer (loopback only)

From `services\analyzer-api`, with the virtual environment active:

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Keep the service bound to `127.0.0.1`. The model never leaves the machine.

## 5. Select the engine in the editor

In VS Code / TerraMind settings, set `terramind.generationEngine` (Settings UI:
**TerraMind: Generation Engine**). The allowed values are `auto`, `ollama`,
`transformers`, and `gguf`.

- **`gguf`** - force the bundled llama.cpp engine. Use this with the bundled model. If
  `TERRAMIND_GGUF_MODEL` is unset, the analyzer returns HTTP 503 with a clear message
  instead of falling back silently.
- **`ollama`** - use a local Ollama instance and the `terramind.generationModel` name
  (for example `qwen2.5-coder:3b`). This is the pre-existing path and does not use the
  bundled GGUF.
- **`auto`** - pick the best available engine: GGUF when `TERRAMIND_GGUF_MODEL` is set,
  then the in-process Transformers model, then Ollama.

Two things to remember about how the layers combine:

- The **environment** (`TERRAMIND_GGUF_MODEL`) tells the analyzer **where the file is**.
  Setting it also makes GGUF win under `auto`.
- The **editor setting** (`terramind.generationEngine`) is sent with each generate/repair
  request and decides **which engine runs**. If you set the `gguf` engine in the editor
  but never set `TERRAMIND_GGUF_MODEL`, generation fails with a 503.

Then run **TerraMind: Generate Infrastructure** from the command palette.

## 6. Verify it is working

- The analyzer log shows the GGUF model being loaded once and cached.
- A generate request returns a parsed HCL draft in the preview instead of an error.
- If you see `GGUF engine selected but TERRAMIND_GGUF_MODEL is not set`, set the variable
  in the analyzer shell and restart the analyzer.
- If you see `Configured GGUF model file does not exist`, the path is wrong; re-run
  `Resolve-Path` on the downloaded file.

## 7. Limitations (read this)

- **Parse-valid is not provider-valid.** The release-level held-out result is an HCL
  **parse rate of 8/8**, not provider-schema acceptance. Provider validity is the only
  defensible quality bar and has not been established at this sample size.
- **Training loss is not quality.** A low loss only means the model fits the corpus
  next-token distribution; it does not mean the generated infrastructure is correct,
  secure, or deployable.
- **Human review is required.** Every draft is a suggestion. Read it, edit it, and
  review the plan before applying anything. The model never applies.
- **The deterministic gates still run and still matter.** TerraMind parses the HCL,
  runs its static rules, and (when you opt in with `terramind.analysis.runExternalTools`,
  in a trusted workspace with an existing provider cache) runs `terraform validate`. It
  never runs `terraform init`, `plan`, or `apply`. These checks, the analyzer, and the
  human save step are the source of truth, not the model.
- **Small model, narrow scope.** It can emit invalid HCL, insecure defaults (public
  buckets, open CIDRs), or resources/providers/arguments that do not exist. Prompts are
  English-centric; long requests can truncate.

## 8. Troubleshooting

| Symptom | Likely cause and fix |
| --- | --- |
| 503 `TERRAMIND_GGUF_MODEL is not set` | Set the variable in the analyzer shell and restart it. |
| 503 `Configured GGUF model file does not exist` | The path is wrong or relative to a different directory; use an absolute path. |
| `No module named 'llama_cpp'` | `llama-cpp-python` was installed into a different Python than the analyzer; reinstall into the analyzer venv. |
| Download fails in `get_model.ps1` | The tag/asset name is wrong or the release is not public; verify `-Repo`, `-Tag`, `-AssetName`. |
| SHA-256 mismatch | The download was corrupted or the wrong asset; delete the file and re-run. |

## Files that must travel with the model

If you redistribute the GGUF, keep these together (see [MODEL_CARD.md](MODEL_CARD.md)):

1. `model-manifest.json` from the export CLI.
2. The upstream base `LICENSE` (and any `NOTICE`).
3. `ATTRIBUTION.csv` and the prepared-corpus `manifest.json` for any redistributed
   training derivative. The corpus is CC-BY-4.0; individual rows keep their source
   licenses. Credit `SASVAAI/terraform-multicloud`.
