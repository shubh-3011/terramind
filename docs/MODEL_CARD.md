# TerraMind Terraform Generator — Model Card

This is the model card for the optional, locally hosted **Terraform generation** model that
ships with TerraMind. It is a small instruction-tuned code model, exported to GGUF and run
on the user's own machine through llama.cpp. It drafts Terraform HCL for review; it does not
deploy, validate against a provider, or guarantee security, cost, uptime, or correctness.
Every draft is a suggestion and must be reviewed by a human before it is applied.

TerraMind's separate logistic-regression risk estimator is documented in
[TRAINING_AND_MODEL.md](TRAINING_AND_MODEL.md); that model classifies findings and is not this
generator. Observed smoke-run evidence for earlier training experiments (which used Qwen3 bases)
lives in [GENERATIVE_TRAINING.md](GENERATIVE_TRAINING.md) and
[MODEL_STRATEGY.md](MODEL_STRATEGY.md).

## Model summary

| Field | Value |
| --- | --- |
| Artifact name | TerraMind Terraform Generator (`terramind-terraform`) |
| Base model | `Qwen/Qwen2.5-Coder-1.5B-Instruct` |
| Base license | Apache-2.0 |
| Base revision | `<PINNED_REVISION>` — replace with the upstream commit before release |
| Fine-tuning method | LoRA supervised fine-tuning; assistant-response tokens only |
| Training task | Natural-language request → reviewable Terraform HCL |
| Distribution format | GGUF (`Q4_K_M` by default), produced by `terramind_ml.export_gguf` |
| Runtime | local `llama-cpp-python` (llama.cpp) via `TERRAMIND_GGUF_MODEL`; no Ollama required |
| Language(s) | English prompts; Terraform HCL output (HCL2) |
| Developer | the TerraMind project |

Pin `<PINNED_REVISION>` to a specific upstream commit before publishing a release. Do not
advertise a moving branch (`main`) as the base: it is not reproducible and the license/text can
change without notice. Record the pinned value in the release manifest produced by the export
CLI.

## Intended use

### Primary intended use

- **Drafting Terraform HCL** from a short natural-language description of resources and
  connectivity (for example, "a private S3 bucket with versioning and encryption").
- **Review and repair assistance** as a starting point for a human who then edits, validates,
  and applies the configuration themselves.

The built-in TerraMind flow is: generate a draft → parse the HCL → run static checks and
optional provider-schema validation → show the user a diff → **write nothing until the user
explicitly saves the draft**. The model only proposes; it never applies.

### Intended users

Developers and reviewers who want a fast, local first draft and who will run Terraform's own
tooling (`terraform fmt`, `terraform validate`, provider schemas, plan review) before shipping.

### Out-of-scope use

- **No deployment.** The model never runs `terraform init`, `plan`, or `apply`, and must never be
  given that authority automatically.
- **No cost, uptime, scalability, or performance guarantee.** Generated HCL is not costed or
  capacity-planned.
- **No security guarantee.** A generated configuration can be insecure. It is not a substitute
  for security review, policy-as-code, or `checkov`/`tflint`-style gates.
- **No provider-schema authority.** The draft may reference unsupported arguments or resource
  types. Provider validation is required before the draft is trusted.
- **No production decisions.** Do not use the model as the sole source of truth for regulated,
  safety-critical, or production infrastructure.
- **Not a risk/label model.** Generation output must never be treated as ground-truth security
  labels or outcomes.

## Training data and provenance

| Field | Value |
| --- | --- |
| Dataset | [`SASVAAI/terraform-multicloud`](https://huggingface.co/datasets/SASVAAI/terraform-multicloud) |
| Dataset license | CC-BY-4.0 |
| Pinned dataset revision | `dced854e79a6aadb89f12b3ba74b31720264ea40` |
| Preparation script | `terramind_ml.sft_data` |
| Filtering | AWS provider-family rows only; HCL parse check; source-license allowlist |
| Provenance files | `train.jsonl`, `validation.jsonl`, `ATTRIBUTION.csv`, `manifest.json` |

The corpus is a set of natural-language → HCL examples. **Its prompts are model-written
back-translations of the source HCL**, so the model can inherit the teacher's mistakes as easily
as its correct patterns. Individual rows retain their **source-repository licenses** (for example
MIT, Apache-2.0, BSD, ISC). The preparation script keeps only rows whose source license is on an
allowlist and records every repository/license pair in `ATTRIBUTION.csv`.

**Keep `ATTRIBUTION.csv` (and `manifest.json`) with any redistributed prepared corpus or model.**
CC-BY-4.0 requires attribution to the dataset, and the per-row source licenses continue to apply
to their content. Review any upstream Apache `NOTICE` files before redistribution, because they
are not bundled by the dataset.

The preparation pipeline is described in [GENERATIVE_TRAINING.md](GENERATIVE_TRAINING.md). Prepared
JSONL and model weights are local, git-ignored build artifacts; the raw dataset is not committed.

## Evaluation

### How to evaluate

Provider-valid evaluation (for example an IaC-Eval-style held-out set that runs
`terraform validate`/provider schemas) is the only defensible way to judge whether a draft is
acceptable. TerraMind ships a generation evaluator
(`terramind_ml.evaluate_generation`) that measures HCL parse rate, resource-type overlap, latency,
and — when explicitly opted in with a pre-initialized provider cache — provider-schema acceptance.

### Caveats

- **Training/validation loss is not validity.** A falling loss only means the model fits the
  next-token distribution of the corpus; it says nothing about whether `terraform validate` or a
  provider schema accepts the output. Recorded smoke runs show exactly this gap (lower validation
  loss still produced provider-invalid or unparsable HCL).
- **The corpus is not a quality benchmark.** It is back-translated text, not reviewed,
  provider-valid configurations, and not a security/cost/outage label set.
- **Small held-out samples prove plumbing, not quality.** Report parse rate, provider acceptance,
  and latency for the exact base revision, quant type, and hardware; do not generalize from a
  handful of examples.
- **Quantization changes behaviour.** Measure the specific GGUF (`Q4_K_M`, `Q5_K_M`, …) you ship;
  do not assume full-precision metrics transfer.

No quality claim for this model is established by its presence on this card. Treat it as an
experimental drafting aid until it passes a provider-valid, user-intent benchmark.

## Limitations and risks

- **May emit non-compiling or invalid HCL**, unsupported resource arguments, or wrong resource
  types.
- **May emit insecure defaults** (public buckets, open CIDRs, weak IAM).
- **May hallucinate** modules, providers, arguments, or versions that do not exist.
- **Prompt-sensitive.** Long or ambiguous requests can truncate before the HCL is complete.
- **English-centric.** Non-English prompts are untested.
- **No memory of your environment.** It does not know your provider versions, regions, accounts,
  or existing state; those must be parameterized and reviewed.

Mitigations already in the product: HCL parsing, 66 static rules, `aws-rubric-v2` scoring, an
optional `terraform validate`/TFLint/Checkov gate, Problems diagnostics, and an explicit
human save step. These are the source of truth, **not** the model.

## Licensing and redistribution

- **Base model:** `Qwen/Qwen2.5-Coder-1.5B-Instruct`, Apache-2.0. Include the upstream `LICENSE`
  (and any `NOTICE`) with the redistributed GGUF. The merged model directory produced by
  `terramind_ml.merge_sft` already writes a `LICENSE` naming the base and its license.
- **Training corpus:** CC-BY-4.0, with per-row source licenses. Keep `ATTRIBUTION.csv` and
  `manifest.json`; provide attribution to `SASVAAI/terraform-multicloud`.
- **Do not bundle non-permissive bases.** For example, `qwen2.5-coder:3b` is under the **Qwen
  Research License (non-commercial)** and must not be redistributed. Prefer Apache-2.0 bases.
- **The export manifest** (`model-manifest.json`) records the base model, pinned revision,
  license, quant type, SHA-256, and byte size of the GGUF. Publish it alongside the release asset.
- See [OPEN_SOURCE.md](OPEN_SOURCE.md) for the full attribution and hosting checklist.

## How it is deployed locally (GGUF + llama.cpp)

TerraMind runs the generator locally through `llama-cpp-python`, which wraps llama.cpp. No Ollama
installation is required. The GGUF is either downloaded from a GitHub release or built by the
export pipeline.

Export a merged model (no GPU needed):

```powershell
# From services/analyzer-api
.\.venv\Scripts\python.exe -m terramind_ml.export_gguf `
  --merged ..\..\.build\terramind-qwen3-terraform-merged `
  --out-dir ..\..\.build\gguf `
  --quant Q4_K_M `
  --base-model Qwen/Qwen2.5-Coder-1.5B-Instruct `
  --base-revision <PINNED_REVISION> `
  --license Apache-2.0
```

Preview the exact commands and manifest without running anything:

```powershell
.\.venv\Scripts\python.exe -m terramind_ml.export_gguf `
  --merged ..\..\.build\terramind-qwen3-terraform-merged `
  --out-dir ..\..\.build\gguf --dry-run
```

Run it in TerraMind by pointing the analyzer at the GGUF:

```powershell
python -m pip install llama-cpp-python
$env:TERRAMIND_GGUF_MODEL = "C:\path\to\terramind-terraform-Q4_K_M.gguf"
$env:TERRAMIND_GENERATION_ENGINE = "gguf"
```

`app/llama_cpp_backend.py` loads the file once, caches it, and bounds inference with
`TERRAMIND_GGUF_N_CTX`, `TERRAMIND_GGUF_TEMPERATURE`, `TERRAMIND_GGUF_MAX_TOKENS`, and
`TERRAMIND_GGUF_N_THREADS`. The analyzer binds to loopback only; the model never leaves the
machine.

## Files that must travel with the model

1. `docs/MODEL_CARD.md` (this file).
2. `model-manifest.json` from the export CLI (base model, pinned revision, license, quant type,
   SHA-256, size).
3. The upstream base `LICENSE`/`NOTICE`.
4. `ATTRIBUTION.csv` and the prepared-corpus `manifest.json` if any training derivative is
   redistributed.
