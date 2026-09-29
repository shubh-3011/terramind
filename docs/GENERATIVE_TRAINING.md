# Local Terraform generation and optional training data

## What is implemented

The built-in **Generate Infrastructure** command collects a resource/connectivity description and constraints, calls a locally hosted Ollama model through the loopback-only analyzer API, parses the returned text as HCL, and opens it for review. Nothing is written until the user selects **Save Draft to Workspace**, chooses a path inside the open workspace, and confirms any overwrite. The saved draft is then sent through workspace analysis.

TerraMind now has an experimental LoRA fine-tuning path, and `/v1/generate` can use a locally merged Transformers model when `TERRAMIND_HF_MODEL_PATH` points to it. Ollama remains the default backend when that variable is unset. Transformers generation is capped by `TERRAMIND_HF_MAX_NEW_TOKENS` (default 2,048; accepted range 128–2,048). Lower limits may return faster but can truncate Terraform before it parses: a matched 0.6B sample stopped at exactly 384 tokens and failed HCL parsing at line 38. At the 2,048-token cap, the 1.7B adapter exceeded the 180-second evaluator timeout; both adapters returned HTTP 422 at the explicit 384-token cap after about 146 seconds. This optional Transformers path is not ready for interactive use on the development RTX 4060. The logistic-regression model is a separate, small binary risk estimator and does not generate Terraform. Neither model provides cost, uptime, scalability, or production-security guarantees. HCL parsing and TerraMind static checks always run; optional Terraform provider/schema validation runs only when `terramind.analysis.runExternalTools` is enabled, the VS Code extension reports the workspace trusted (not in Restricted Mode), and an existing provider cache and lockfile are present. It uses the installed Terraform binary from `PATH` or `TERRAMIND_TERRAFORM_PATH`, and never runs `terraform init`, `plan`, or `apply`. The API's `workspace_trusted` request value is a caller-provided signal rather than a security credential; bind the API to loopback and only validate workspaces you trust.

## Run a local model

Install Ollama from its official website, then download a model in a terminal:

```powershell
ollama pull qwen2.5-coder:3b
ollama run qwen2.5-coder:3b
```

TerraMind defaults to `qwen2.5-coder:3b`; change `terramind.generationModel` in editor Settings to a model already installed in Ollama. The 3B model is a practical starting point for a local GPU with 8 GB VRAM; close other GPU-heavy applications if inference is slow or runs out of memory. Smaller 1.5B and larger 7B variants are available, but a larger model does not by itself ensure correct infrastructure.

Start the analyzer API bound to `127.0.0.1` following the README. Then run **TerraMind: Generate Infrastructure**. Ollama stays on the local machine. Do not expose either local service on a public interface.

## Reproducible Terraform generation corpus

The public [SASVAAI/terraform-multicloud dataset](https://huggingface.co/datasets/SASVAAI/terraform-multicloud) provides natural-language → HCL examples. The dataset card reports 78,912 rows across 15 provider families, including 45,123 AWS train rows; its validation split is repository-disjoint. It is a code-generation corpus, **not** a security/outage/cost label dataset or a quality benchmark. Its prompts are model-written back-translations of the source HCL, so training on it alone can reproduce that teacher's limitations.

The source dataset is released as CC-BY-4.0, and individual HCL rows retain their source-repository licenses. TerraMind's preparation script pins dataset revision `dced854e79a6aadb89f12b3ba74b31720264ea40`, keeps only AWS rows with an explicit allowlisted source license and parseable HCL, preserves repository/file/license attribution, verifies that repositories do not cross train/validation splits, and writes the prepared text only to the chosen output folder. Apache NOTICE files are not bundled upstream; check the source repository before redistributing adapters or training derivatives. The script does not download user workspaces or put the raw dataset in Git.

From `services/analyzer-api`, install the optional corpus-reader dependency and prepare the data into the git-ignored `.build` folder:

```powershell
python -m pip install -e ".[sft-data]"
python -m terramind_ml.sft_data --output ..\..\.build\terramind-terraform-sft
```

The output includes `train.jsonl`, `validation.jsonl`, `ATTRIBUTION.csv`, and `manifest.json` with exact hashes and filter counts. Keep those attribution/provenance files with any redistributed prepared data. Before training a distributable model adapter, select a training framework/base model, review the individual licenses and Apache NOTICE obligations, and evaluate the adapter against a separate executable Terraform benchmark such as IaC-Eval. A lower validation loss on these paraphrased pairs does not establish that the generated Terraform is safe or valid.

On the development machine, the pinned revision produced 43,561 AWS training rows and 2,229 AWS validation rows after source-license and HCL-parse filtering. The preparation recorded repository-disjoint splits. These local counts are reproducibility evidence, not model-quality results; the JSONL and model cache remain local and are not committed to Git.

## Current training limitation

### Reproducible LoRA run

The Windows development machine has an RTX 4060 Laptop GPU (8 GB VRAM), Python 3.12, and CUDA Toolkit 12.6. Training uses a separate ignored environment; it does not modify the editor/API virtual environment or upload weights to GitHub. From the repository root in PowerShell:

```powershell
py -3.12 -m venv .build\sft-train-venv
.build\sft-train-venv\Scripts\python.exe -m pip install torch==2.7.1 --index-url https://download.pytorch.org/whl/cu126
Push-Location services\analyzer-api
..\..\.build\sft-train-venv\Scripts\python.exe -m pip install -e ".[dev,sft-data,sft-train]"
Pop-Location
.build\sft-train-venv\Scripts\python.exe -m terramind_ml.sft_data --output .build\terramind-terraform-sft
.build\sft-train-venv\Scripts\python.exe -m terramind_ml.train_sft `
  --train .build\terramind-terraform-sft\train.jsonl `
  --validation .build\terramind-terraform-sft\validation.jsonl `
  --output .build\terramind-qwen3-terraform-lora
.build\sft-train-venv\Scripts\python.exe -m terramind_ml.merge_sft `
  --adapter .build\terramind-qwen3-terraform-lora `
  --output .build\terramind-qwen3-terraform-merged
$env:TERRAMIND_HF_MODEL_PATH = (Resolve-Path .build\terramind-qwen3-terraform-merged).Path
.build\sft-train-venv\Scripts\python.exe -m uvicorn app.main:app --app-dir services\analyzer-api --host 127.0.0.1 --port 8000
```

The base is [Qwen3-0.6B](https://huggingface.co/Qwen/Qwen3-0.6B/blob/c1899de289a04d12100db370d81485cdf75e47ca/LICENSE), pinned to revision `c1899de289a04d12100db370d81485cdf75e47ca` and licensed Apache-2.0. The trained adapter and merged model remain under `.build/`; the metadata includes source JSONL hashes, model revision, training parameters, and measured train/validation losses. For a short smoke run, add `--max-train-samples 256 --max-validation-samples 64 --max-length 512 --epochs 1`.

On this machine, that run used 256 train and 64 repository-disjoint validation examples for 1 epoch / 32 optimizer steps. It recorded training loss **1.004** and validation loss **0.942**. A second run used [Qwen3-1.7B](https://huggingface.co/Qwen/Qwen3-1.7B/tree/70d244cc86ccca08cf5af4e1e306ecf908b1ad5e), pinned at `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e`, with 128 train and 32 validation examples for 16 optimizer steps; it recorded train loss **0.913** and validation loss **0.626**. The runs differ in model size and sample count, so their losses are not directly comparable. Neither result demonstrates useful generation without a base-model baseline and independent task evaluation.

The 0.6B model returned HCL that passed parsing, but Terraform 1.16.4 with AWS provider 6.66.0 rejected it with five schema/type errors, including unsupported S3 arguments/blocks and an invalid resource type. The 1.7B model returned unparsable HCL on the same smoke request (HTTP 422). Therefore both remain research artifacts; do not use these smoke adapters to generate real infrastructure. Ollama 0.18.0 rejected importing merged Qwen3 Safetensors (`unsupported architecture "Qwen3ForCausalLM"`), so the current configured inference route for these merged weights is the optional Transformers backend above; do not advertise them as Ollama models.

### Run a local generation evaluation

With the analyzer running locally and `TERRAMIND_HF_MODEL_PATH` pointing to a merged model (or with Ollama selected as the local backend), run this from `services/analyzer-api`:

```powershell
..\..\.build\sft-train-venv\Scripts\python.exe -m terramind_ml.evaluate_generation `
  --validation ..\..\.build\terramind-terraform-sft\validation.jsonl `
  --output ..\..\.build\generation-eval.json `
  --max-examples 8 `
  --seed 29
```

To include provider-schema acceptance in the same report, add `--provider-workspace <path>` pointing to a workspace whose `.terraform.lock.hcl` and `.terraform/providers` cache already exist. This explicitly opts the run into executing the installed Terraform provider plugins against each generated draft. The evaluator rejects missing/uninitialized cache paths before sending generation requests; it never runs `terraform init`, `plan`, or `apply`. Keep the provider cache and workspace trusted, and do not use a production workspace for this evaluation.

The evaluator refuses non-loopback API URLs, samples deterministically, and writes aggregate HCL-parse/resource-type-overlap metrics, latency, split/manifest hashes, and hashed example identifiers. It does not save prompts, source snippets, reference HCL, or generated HCL. Resource overlap is a basic structural signal, not semantic or provider validation; resource-type precision/recall/F1 are computed only on parseable generations. On the current Qwen3-0.6B smoke adapter, seed 29 over 3 held-out examples yielded 1 parseable HCL response and 2 HTTP 422 parse rejections (0.33 parse rate, resource-type micro-F1 0.286 on the one parseable example; mean response latency 83.5 seconds). Three examples are far too few to estimate model quality; this run verifies the measurement pipeline and documents poor observed behavior only.

When `--provider-workspace` is supplied, the evaluator additionally reports provider-schema status counts and the number of generated configurations accepted by `terraform validate`. It does not save the workspace path or generated source. This optional check improves compatibility evidence but does not establish semantic correctness, safe infrastructure, deployment behavior, or model quality.

Generation now retries once when the initial HCL fails parsing, or when explicitly enabled trusted-workspace provider validation returns errors. The prompt includes the initial draft and bounded diagnostics; the returned Terraform is re-parsed and, when opted in, revalidated. The version-2 evaluator records retry-status counts and parse recovery without retaining source text. A same-split/seed, three-case post-retry smoke run parsed 2/3 outputs (one recovered after retry), with one HTTP 422; resource-type micro-F1 was 0.471 over the two parseable cases and mean latency 99.7 seconds. Repeating with a locally cached AWS provider showed both parsed outputs still provider-invalid after retry (0/2 valid), while the third remained HTTP 422; mean latency 107.3 seconds. These tiny runs verify evaluator/retry plumbing, not model quality. Reports remain local ignored `.build` artifacts; source datasets and model weights are not committed.

The current API/data/training/evaluation-script suite passes 44 tests. Keep both adapters experimental and do not infer quality from their training losses. Token-limit tuning is not a substitute for a provider-valid, user-intent benchmark.

The separate default `qwen2.5-coder:3b` Ollama model uses the Qwen Research License, which restricts use to non-commercial purposes. Review the upstream license before commercial use or model/adapter redistribution. The existing risk model can be retrained from its small labeled benchmark using the commands in [TRAINING_AND_MODEL.md](TRAINING_AND_MODEL.md).
