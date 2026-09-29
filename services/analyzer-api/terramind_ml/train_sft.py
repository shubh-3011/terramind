"""Fine-tune a small, license-permissive Terraform generation LoRA adapter."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path
from typing import Any

DEFAULT_MODEL = "Qwen/Qwen3-0.6B"
DEFAULT_MODEL_REVISION = "c1899de289a04d12100db370d81485cdf75e47ca"


def encode_conversation(tokenizer: Any, messages: list[dict[str, str]], max_length: int) -> dict[str, list[int]] | None:
    """Mask system/user tokens so SFT loss is applied only to the assistant answer."""
    if len(messages) != 3 or messages[2].get("role") != "assistant":
        return None
    prompt_ids = tokenizer.apply_chat_template(
        messages[:2], tokenize=True, add_generation_prompt=True,
    )
    full_ids = tokenizer.apply_chat_template(
        messages, tokenize=True, add_generation_prompt=False,
    )
    if isinstance(prompt_ids, dict):
        prompt_ids = prompt_ids["input_ids"]
    if isinstance(full_ids, dict):
        full_ids = full_ids["input_ids"]
    prompt_ids = list(prompt_ids)
    full_ids = list(full_ids)
    if not full_ids[:len(prompt_ids)] == prompt_ids:
        raise ValueError("Tokenizer chat template does not preserve the user/assistant prefix boundary")
    full_ids = full_ids[:max_length]
    if len(full_ids) <= len(prompt_ids) + 8:
        return None
    labels = [-100] * min(len(prompt_ids), len(full_ids)) + full_ids[len(prompt_ids):]
    return {"input_ids": full_ids, "labels": labels, "attention_mask": [1] * len(full_ids)}


def _read_jsonl(path: Path, limit: int | None, seed: int) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if limit is not None and len(rows) > limit:
        random.Random(seed).shuffle(rows)
        rows = rows[:limit]
    return rows


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--model-revision", default=DEFAULT_MODEL_REVISION)
    parser.add_argument("--max-train-samples", type=int, default=None,
                        help="Use a deterministic subset for a smoke/short training run")
    parser.add_argument("--max-validation-samples", type=int, default=256)
    parser.add_argument("--max-length", type=int, default=1024)
    parser.add_argument("--epochs", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args()

    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer, Trainer, TrainingArguments

    if not torch.cuda.is_available():
        parser.error("CUDA is required for this script; install the isolated CUDA-enabled training environment first")
    args.output.mkdir(parents=True, exist_ok=True)
    tokenizer = AutoTokenizer.from_pretrained(args.model, revision=args.model_revision, trust_remote_code=False)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    def encode_rows(path: Path, limit: int | None) -> list[dict[str, list[int]]]:
        source = _read_jsonl(path, limit, args.seed)
        encoded = [encode_conversation(tokenizer, row["messages"], args.max_length) for row in source]
        return [item for item in encoded if item is not None]

    train_rows = encode_rows(args.train, args.max_train_samples)
    eval_rows = encode_rows(args.validation, args.max_validation_samples)
    if not train_rows or not eval_rows:
        parser.error("No usable train or validation examples after chat-template encoding")

    dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    model = AutoModelForCausalLM.from_pretrained(
        args.model, revision=args.model_revision, dtype=dtype, trust_remote_code=False,
    )
    model.config.use_cache = False
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model = get_peft_model(model, LoraConfig(
        r=8,
        lora_alpha=16,
        lora_dropout=0.05,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        task_type="CAUSAL_LM",
    ))
    model.print_trainable_parameters()

    class PaddedDataset(torch.utils.data.Dataset):
        def __init__(self, rows: list[dict[str, list[int]]]):
            self.rows = rows

        def __len__(self) -> int:
            return len(self.rows)

        def __getitem__(self, index: int) -> dict[str, list[int]]:
            return self.rows[index]

    def collate(batch: list[dict[str, list[int]]]) -> dict[str, torch.Tensor]:
        width = max(len(item["input_ids"]) for item in batch)
        pad_id = int(tokenizer.pad_token_id)
        input_ids, masks, labels = [], [], []
        for item in batch:
            padding = width - len(item["input_ids"])
            input_ids.append(item["input_ids"] + [pad_id] * padding)
            masks.append(item["attention_mask"] + [0] * padding)
            labels.append(item["labels"] + [-100] * padding)
        return {
            "input_ids": torch.tensor(input_ids, dtype=torch.long),
            "attention_mask": torch.tensor(masks, dtype=torch.long),
            "labels": torch.tensor(labels, dtype=torch.long),
        }

    training_args = TrainingArguments(
        output_dir=str(args.output / "checkpoints"),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=1,
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=8,
        learning_rate=2e-4,
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        weight_decay=0.01,
        logging_steps=10,
        eval_strategy="epoch",
        save_strategy="no",
        bf16=dtype == torch.bfloat16,
        fp16=dtype == torch.float16,
        gradient_checkpointing=True,
        optim="adamw_torch",
        report_to=[],
        seed=args.seed,
        data_seed=args.seed,
        remove_unused_columns=False,
        dataloader_num_workers=0,
    )
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=PaddedDataset(train_rows),
        eval_dataset=PaddedDataset(eval_rows),
        data_collator=collate,
        processing_class=tokenizer,
    )
    train_result = trainer.train()
    evaluation = trainer.evaluate()
    model.save_pretrained(args.output, safe_serialization=True)
    tokenizer.save_pretrained(args.output)
    metadata = {
        "base_model": args.model,
        "base_model_revision": args.model_revision,
        "base_model_license": "Apache-2.0 (verify the pinned upstream LICENSE before redistribution)",
        "base_model_license_url": f"https://huggingface.co/{args.model}/blob/{args.model_revision}/LICENSE",
        "training_method": "LoRA supervised fine-tuning; assistant-response tokens only",
        "seed": args.seed,
        "train_jsonl_sha256": _digest(args.train),
        "validation_jsonl_sha256": _digest(args.validation),
        "train_examples_used": len(train_rows),
        "validation_examples_used": len(eval_rows),
        "max_length": args.max_length,
        "epochs": args.epochs,
        "train_metrics": train_result.metrics,
        "validation_metrics": evaluation,
        "limitations": [
            "Small, generated/back-translated training corpus; adapter quality is not established by loss alone.",
            "Not evaluated as safe, provider-valid, cost-optimized, reliable, or scalable Terraform.",
            "Evaluate against held-out executable Terraform cases before relying on generated configurations.",
        ],
    }
    (args.output / "training-metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metadata, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
