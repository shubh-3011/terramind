# Model strategy: self-train versus reuse an existing code model

## Question

Should TerraMind keep fine-tuning a tiny Qwen3 base for Terraform generation, or use an
existing pre-trained code model as the generator? This document answers that question with
the evidence already recorded in [GENERATIVE_TRAINING.md](GENERATIVE_TRAINING.md),
[TRAINING_AND_MODEL.md](TRAINING_AND_MODEL.md), and [../PROGRESS.md](../PROGRESS.md).
It is a decision record, not a benchmark result.

## What we already tried

Two short LoRA smoke runs were trained on the Windows development machine (RTX 4060 Laptop,
8 GB VRAM, CUDA 12.6) using the license-filtered, repository-disjoint Terraform corpus
(43,561 AWS train / 2,229 validation rows after filtering). All of the following numbers are
observed on this machine and come from `PROGRESS.md` and `GENERATIVE_TRAINING.md`; they are not
quality estimates.

- **Qwen3-0.6B (Apache-2.0, pinned revision):** 256 train / 64 validation examples, 32 optimizer
  steps. Train loss **1.004**, validation loss **0.942**. On a smoke request it returned HCL that
  parsed, but Terraform 1.16.4 with AWS provider 6.66.0 rejected it with **five schema/type
  errors** (unsupported S3 arguments/blocks and an invalid resource type).
- **Qwen3-1.7B (Apache-2.0, pinned revision):** 128 train / 32 validation examples, 16 optimizer
  steps. Train loss **0.913**, validation loss **0.626**. Its smoke generation returned
  **unparsable HCL (HTTP 422)**.
- **Latency:** a 3-example held-out run on the 0.6B adapter had mean response latency **83.5 s**
  pre-retry; the retry-enabled run averaged **99.7 s** (parse-only) and **107.3 s** with cached
  provider validation. The 1.7B adapter exceeded the evaluator's **180-second** timeout at the
  768- and 2,048-token caps.
- **Truncation:** at an explicit 384-token cap, the 0.6B model stopped at exactly token 384 and
  emitted truncated HCL (parse error at line 38); both adapters returned HTTP 422 after about
  **146 s**. This is why the Transformers default cap stays at 2,048 tokens.
- **Tooling:** Ollama 0.18.0 rejected importing the merged Qwen3 Safetensors directory with
  `unsupported architecture "Qwen3ForCausalLM"`, so the merged adapters are not usable as Ollama
  models today. The optional Transformers backend is the only route for them, and it is not ready
  for interactive generation on this hardware.
- **Sample quality:** the corpus prompts are model-written back-translations of source HCL, so
  training inherits that teacher's limitations. Resource-type micro-F1 on the tiny eval runs was
  0.286 (one parseable case) and 0.471 (two parseable cases); the sample is far too small to
  estimate quality.

## Why tiny fine-tuning underperforms

- A **0.6B/1.7B base has very little Terraform knowledge to begin with**. Fine-tuning teaches
  formatting and hint-following far more readily than provider schemas, resource argument
  semantics, or cross-resource wiring.
- A **few hundred paraphrased examples cannot install that knowledge**. The 0.6B/1.7B runs are
  smoke runs, and the corpus, while large, is back-translated text rather than reviewed,
  provider-valid configurations.
- **Back-translated prompts inherit teacher noise.** Training on paraphrases of source HCL can
  reproduce the teacher's mistakes rather than correct them.
- **Training loss does not measure Terraform validity.** A falling loss only says the model fits
  the next-token distribution of the corpus; it says nothing about whether `terraform validate`
  or a provider schema accepts the output. The evidence above shows exactly this gap: lower
  validation loss still produced provider-invalid or unparsable HCL.

## Recommendation

**Use an existing pre-trained code model as the generator and stop self-training for now.**
Serve it locally through Ollama with a quantized build; keep the self-trained adapters as
research artifacts only.

Concrete model matrix for a single 8 GB VRAM laptop GPU. Weight sizes and speed/quality notes are
approximate expectations unless marked observed; every quantized model must be pulled and measured
on the target machine before being trusted.

| Model (Ollama tag) | Approx. Q4 weight size | Role | Speed / quality tradeoff |
| --- | --- | --- | --- |
| `qwen2.5-coder:1.5b` | ~1.1 GB | **Lite / fast** | Fastest interactive drafts; least Terraform knowledge; expect the most review. |
| `qwen2.5-coder:3b` | ~2 GB | **Balanced default** | Current TerraMind default. Reasonable speed for interactive use with moderate quality. |
| `qwen2.5-coder:7b` | ~4.7 GB | **Quality** | Best quality of the Qwen coder set that fits 8 GB; noticeably slower and leaves less room for context. |
| `deepseek-coder:6.7b` | ~4 GB | Alternative | Strong code prior; different licensing/behavior; measure locally. |
| `granite-code:8b` | ~4.9 GB | Alternative (Apache-2.0) | Redistribution-friendly base; measure provider-valid output locally. |
| `codegemma:7b` | ~5 GB | Alternative | Code-focused; benchmark before trusting in the generate flow. |

Recommendation for the product:

- Ship a **"lite/fast" default for interactive use** (for example `qwen2.5-coder:1.5b` or `:3b`)
  so the first draft appears quickly, and
- offer a **"quality" option** (for example `qwen2.5-coder:7b` Q4) that the user can select when
  they would rather wait for a better draft.

Do **not** go larger than ~7-8B parameters at Q4 on 8 GB VRAM; a 14B Q4 build (~9 GB) does not fit
comfortably and will fall back to CPU or fail to load. Be explicit that **model quality for
provider-valid Terraform is not guaranteed by size alone**: a larger model is more capable on
average, but none of these models is validated to emit schema-correct AWS Terraform, and the
existing static + optional provider checks must still gate every draft.

## If you still want to fine-tune

Fine-tuning is not forbidden, but it should meet real prerequisites before it is treated as a
product path:

- **A larger base (>= 3B).** The 0.6B/1.7B results show the base is the bottleneck; a >= 3B
  coder base has enough prior to adapt.
- **Far more reviewed examples.** Move from a few hundred paraphrased pairs to a substantially
  larger, human-reviewed corpus with per-source license and provenance recorded.
- **An executable provider-valid benchmark**, such as IaC-Eval or an equivalent held-out set that
  runs `terraform validate`/provider schemas, so success is measured by accepted output rather
  than training loss.
- **A held-out intent benchmark** that scores whether the generated configuration matches the
  user's requested resources, topology, and constraints, not just resource-type overlap.
- **Licensing.** Keep track of redistribution rights: `qwen2.5-coder:3b` is under the **Qwen
  Research License (non-commercial)**, so it is unsuitable as a redistributed base. Prefer
  **Apache-2.0** bases (for example Qwen3 and IBM Granite Code) when a distributable model or
  adapter is required, and review each upstream license before shipping weights.

## Speed levers

These make local generation feel interactive without pretending the model is correct:

- **New bounded Ollama options (env-configurable, safe defaults).** Set on the analyzer process:
  `TERRAMIND_OLLAMA_NUM_PREDICT` (default **4096**, clamp **256-8192**),
  `TERRAMIND_OLLAMA_TEMPERATURE` (default **0.1**, clamp **0.0-1.0**),
  `TERRAMIND_OLLAMA_NUM_CTX` (default **8192**, clamp **2048-32768**), and
  `TERRAMIND_OLLAMA_KEEP_ALIVE` (default **"10m"**; empty/invalid falls back to the default).
  Lower `num_predict`/`num_ctx` cuts response time but risks truncating HCL before it parses.
- **`keep_alive`** keeps the model resident in VRAM between requests, avoiding repeated cold-load
  latency during an interactive session.
- **Quantized builds** (Q4_K_M or Q5) fit larger models into 8 GB and run faster than full
  precision; measure the accuracy cost locally.
- **Constrained output**: low temperature, a bounded `num_predict`, and HCL-only prompting reduce
  wasted tokens, but do not by themselves produce valid Terraform.
- **Deterministic scaffolding/rules as a backstop.** TerraMind's static rules and the optional
  `terraform validate` gate must remain the source of truth; the model only proposes a draft, and
  generation must never be described as provider-valid because of model size, speed, or loss.

## Sources

- [GENERATIVE_TRAINING.md](GENERATIVE_TRAINING.md) - corpus, LoRA runs, latency, truncation, and
  the Ollama Safetensors rejection.
- [TRAINING_AND_MODEL.md](TRAINING_AND_MODEL.md) - the separate risk model and the "keep code
  generation in a separate local LLM adapter" decision.
- [../PROGRESS.md](../PROGRESS.md) - dated observed-on-this-machine measurements and CI/blocker
  state.
