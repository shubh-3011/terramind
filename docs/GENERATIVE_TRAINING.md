# Local Terraform generation and optional training data

## What is implemented

The built-in **Generate Infrastructure** command collects a resource/connectivity description and constraints, calls a locally hosted Ollama model through the loopback-only analyzer API, parses the returned text as HCL, and opens it for review. Nothing is written until the user selects **Save Draft to Workspace**, chooses a path inside the open workspace, and confirms any overwrite. The saved draft is then sent through workspace analysis.

The initial local model is a general code model, not a TerraMind fine-tune. The current experimental logistic-regression model is a separate, small binary risk estimator and does not generate Terraform. Neither model provides cost, uptime, scalability, or production-security guarantees. The generation route verifies HCL syntax only; Terraform provider/schema validation is separate.

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

TerraMind does not yet train or ship a custom generative adapter. The local machine has an RTX 4060 with 8 GB VRAM, but its installed Python is CPU-only and WSL is not configured as a general Linux distribution. Installing a GPU training stack is a separate, large environment change; the dataset and generation integration are prepared, but no fine-tuning run or adapter quality is claimed. The downloaded Qwen2.5-Coder base model uses a research/non-commercial license; do not use it commercially or redistribute model weights/adapters without a license review. The existing risk model can be retrained from its small labeled benchmark using the commands in [TRAINING_AND_MODEL.md](TRAINING_AND_MODEL.md).
