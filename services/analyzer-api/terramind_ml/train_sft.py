"""Fine-tune a small, license-permissive Terraform generation LoRA adapter."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
from pathlib import Path
from typing import Any

# Named base-model presets. Each preset pins an exact upstream revision and records
# the license so the shipped adapter can be audited for redistribution.
PRESETS: dict[str, dict[str, Any]] = {
    "qwen2.5-coder-1.5b-instruct": {
        "model": "Qwen/Qwen2.5-Coder-1.5B-Instruct",
        "revision": "2e1fd397ee46e1388853d2af2c993145b0f1098a",
        "license": "Apache-2.0",
        "redistributable": True,
    },
    "qwen3-0.6b": {
        "model": "Qwen/Qwen3-0.6B",
        "revision": "c1899de289a04d12100db370d81485cdf75e47ca",
        "license": "Apache-2.0",
        "redistributable": True,
    },
    "qwen3-1.7b": {
        "model": "Qwen/Qwen3-1.7B",
        "revision": "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e",
        "license": "Apache-2.0",
        "redistributable": True,
    },
}

DEFAULT_PRESET = "qwen2.5-coder-1.5b-instruct"
DEFAULT_TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]

# Backwards-compatible module constants (merge_sft imports these as defaults).
DEFAULT_MODEL = PRESETS[DEFAULT_PRESET]["model"]
DEFAULT_MODEL_REVISION = PRESETS[DEFAULT_PRESET]["revision"]


def resolve_base_model(preset: str, model: str | None = None, model_revision: str | None = None) -> dict[str, Any]:
    """Resolve a preset plus explicit overrides into the exact base to train on."""
    try:
        entry = PRESETS[preset]
    except KeyError:
        known = ", ".join(sorted(PRESETS))
        raise ValueError(f"Unknown base model preset {preset!r}; choose one of: {known}") from None
    return {
        "preset": preset,
        "model": model or entry["model"],
        "revision": model_revision or entry["revision"],
        "license": entry["license"],
        "redistributable": bool(entry["redistributable"]),
    }


#: ChatML marker that starts the assistant turn in the Qwen family chat templates.
ASSISTANT_HEADER = "<|im_start|>assistant\n"


def _last_subsequence_end(sequence: list[int], subsequence: list[int]) -> int | None:
    """Return the end index of the last occurrence of ``subsequence`` in ``sequence``."""
    if not subsequence or len(subsequence) > len(sequence):
        return None
    for start in range(len(sequence) - len(subsequence), -1, -1):
        if sequence[start:start + len(subsequence)] == subsequence:
            return start + len(subsequence)
    return None


def _assistant_mask_length(tokenizer: Any, full_ids: list[int], messages: list[dict[str, str]]) -> int | None:
    """Find how many leading tokens belong to the prompt (loss must ignore them).

    Tokenizing the assistant header on its own is not reliable: when the answer
    begins with blank lines, byte-pair merges absorb the header's trailing
    newline differently than in the full conversation, so an exact-prefix check
    fails on a meaningful fraction of rows. Instead we search for the assistant
    header inside the real token stream and mask everything up to its end.
    """
    try:
        marker_ids = list(tokenizer.encode(ASSISTANT_HEADER, add_special_tokens=False))
    except Exception:  # noqa: BLE001 - some tokenizers require special handling
        marker_ids = []
    mask = _last_subsequence_end(full_ids, marker_ids)
    if mask is not None:
        return mask
    # Fallback for templates without the ChatML marker: use the prompt prefix.
    prompt_ids = tokenizer.apply_chat_template(messages[:2], tokenize=True, add_generation_prompt=True)
    if isinstance(prompt_ids, dict):
        prompt_ids = prompt_ids["input_ids"]
    prompt_ids = list(prompt_ids)
    if full_ids[:len(prompt_ids)] == prompt_ids:
        return len(prompt_ids)
    return None


def encode_conversation(tokenizer: Any, messages: list[dict[str, str]], max_length: int) -> dict[str, list[int]] | None:
    """Mask system/user tokens so SFT loss is applied only to the assistant answer."""
    if len(messages) != 3 or messages[2].get("role") != "assistant":
        return None
    full_ids = tokenizer.apply_chat_template(
        messages, tokenize=True, add_generation_prompt=False,
    )
    if isinstance(full_ids, dict):
        full_ids = full_ids["input_ids"]
    full_ids = list(full_ids)
    mask_length = _assistant_mask_length(tokenizer, full_ids, messages)
    if mask_length is None:
        return None
    full_ids = full_ids[:max_length]
    mask_length = min(mask_length, len(full_ids))
    if len(full_ids) <= mask_length + 8:
        return None
    labels = [-100] * mask_length + full_ids[mask_length:]
    if len(labels) != len(full_ids):
        return None
    return {"input_ids": full_ids, "labels": labels, "attention_mask": [1] * len(full_ids)}


def _read_jsonl(path: Path, limit: int | None, seed: int) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if limit is not None and len(rows) > limit:
        random.Random(seed).shuffle(rows)
        rows = rows[:limit]
    return rows


def encode_rows(
    tokenizer: Any, path: Path, limit: int | None, max_length: int, seed: int,
) -> list[dict[str, list[int]]]:
    """Read, subset, and chat-template-encode a JSONL split, dropping unusable rows."""
    source = _read_jsonl(path, limit, seed)
    encoded = [encode_conversation(tokenizer, row["messages"], max_length) for row in source]
    return [item for item in encoded if item is not None]


def summarize_encoding(
    tokenizer: Any,
    train_path: Path,
    validation_path: Path,
    *,
    max_length: int,
    seed: int,
    max_train_samples: int | None = None,
    max_validation_samples: int | None = 256,
) -> dict[str, Any]:
    """Encode both splits and return a data/ tokenization summary (no torch required)."""
    sections: dict[str, Any] = {}
    for name, path, limit in (
        ("train", train_path, max_train_samples),
        ("validation", validation_path, max_validation_samples),
    ):
        source = _read_jsonl(path, limit, seed)
        rows = [encode_conversation(tokenizer, row["messages"], max_length) for row in source]
        usable = [item for item in rows if item is not None]
        sections[name] = {
            "examples": len(source),
            "examples_usable": len(usable),
            "examples_skipped": len(source) - len(usable),
            "input_tokens": sum(len(item["input_ids"]) for item in usable),
            "supervised_tokens": sum(sum(1 for label in item["labels"] if label != -100) for item in usable),
        }
    return {
        "dry_run": True,
        "max_length": max_length,
        "train": sections["train"],
        "validation": sections["validation"],
    }


def _parse_target_modules(value: str) -> list[str]:
    modules = [part.strip() for part in value.split(",") if part.strip()]
    if not modules:
        raise ValueError("--target-modules must list at least one module name")
    return modules


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
    parser.add_argument("--preset", default=DEFAULT_PRESET, choices=sorted(PRESETS),
                        help="Named base-model preset; explicit --model/--model-revision override it")
    parser.add_argument("--model", default=None,
                        help="Override the preset's base model id")
    parser.add_argument("--model-revision", default=None,
                        help="Override the preset's pinned base model revision")
    parser.add_argument("--max-train-samples", type=int, default=None,
                        help="Use a deterministic subset for a smoke/short training run")
    parser.add_argument("--max-validation-samples", type=int, default=256)
    parser.add_argument("--max-length", type=int, default=1024)
    parser.add_argument("--epochs", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=8)
    parser.add_argument("--per-device-batch-size", type=int, default=1)
    parser.add_argument("--lora-r", type=int, default=8)
    parser.add_argument("--lora-alpha", type=int, default=16)
    parser.add_argument("--lora-dropout", type=float, default=0.05)
    parser.add_argument("--target-modules", default=",".join(DEFAULT_TARGET_MODULES),
                        help="Comma-separated LoRA target module names")
    parser.add_argument("--save-strategy", choices=["no", "epoch", "steps"], default="epoch")
    parser.add_argument("--save-steps", type=int, default=200)
    parser.add_argument("--save-total-limit", type=int, default=2)
    parser.add_argument("--resume", action="store_true",
                        help="Resume from the latest checkpoint in the output directory")
    parser.add_argument("--dry-run", action="store_true",
                        help="Encode/validate the data and print a summary without loading a model or CUDA")
    args = parser.parse_args()

    base = resolve_base_model(args.preset, args.model, args.model_revision)
    target_modules = _parse_target_modules(args.target_modules)

    if args.dry_run:
        from transformers import AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(
            base["model"], revision=base["revision"], trust_remote_code=False,
        )
        if tokenizer.pad_token_id is None:
            tokenizer.pad_token = tokenizer.eos_token
        summary = summarize_encoding(
            tokenizer,
            args.train,
            args.validation,
            max_length=args.max_length,
            seed=args.seed,
            max_train_samples=args.max_train_samples,
            max_validation_samples=args.max_validation_samples,
        )
        if not summary["train"]["examples_usable"] or not summary["validation"]["examples_usable"]:
            parser.error("No usable train or validation examples after chat-template encoding")
        summary["preset"] = base["preset"]
        summary["base_model"] = base["model"]
        summary["base_model_revision"] = base["revision"]
        print(json.dumps(summary, indent=2))
        return 0

    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer, Trainer, TrainingArguments

    if not torch.cuda.is_available():
        parser.error("CUDA is required for this script; install the isolated CUDA-enabled training environment first")
    args.output.mkdir(parents=True, exist_ok=True)
    tokenizer = AutoTokenizer.from_pretrained(base["model"], revision=base["revision"], trust_remote_code=False)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    train_rows = encode_rows(tokenizer, args.train, args.max_train_samples, args.max_length, args.seed)
    eval_rows = encode_rows(tokenizer, args.validation, args.max_validation_samples, args.max_length, args.seed)
    if not train_rows or not eval_rows:
        parser.error("No usable train or validation examples after chat-template encoding")

    dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    model = AutoModelForCausalLM.from_pretrained(
        base["model"], revision=base["revision"], dtype=dtype, trust_remote_code=False,
    )
    model.config.use_cache = False
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model = get_peft_model(model, LoraConfig(
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        target_modules=target_modules,
        task_type="CAUSAL_LM",
    ))
    # Explicitly place the model on the GPU. Relying on the Trainer to move it can
    # silently leave a PEFT model on CPU, which turns a ~1 s/step run into ~25 s/step.
    model = model.to("cuda")
    model.print_trainable_parameters()
    print(f"Training device: {next(model.parameters()).device}")

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
        per_device_train_batch_size=args.per_device_batch_size,
        per_device_eval_batch_size=args.per_device_batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        learning_rate=args.learning_rate,
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        weight_decay=0.01,
        logging_steps=10,
        eval_strategy="epoch",
        save_strategy=args.save_strategy,
        save_steps=args.save_steps,
        save_total_limit=args.save_total_limit if args.save_strategy != "no" else None,
        bf16=dtype == torch.bfloat16,
        fp16=dtype == torch.float16,
        gradient_checkpointing=True,
        optim="adamw_torch",
        report_to=[],
        seed=args.seed,
        data_seed=args.seed,
        remove_unused_columns=False,
        dataloader_num_workers=0,
        use_cpu=False,
        # Pinned memory can be pathologically slow on Windows/WDDM and can add
        # tens of seconds per step, so keep it off unless explicitly requested.
        dataloader_pin_memory=os.environ.get("TERRAMIND_TRAIN_PIN_MEMORY", "0") == "1",
        tf32=True,
    )
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=PaddedDataset(train_rows),
        eval_dataset=PaddedDataset(eval_rows),
        data_collator=collate,
        processing_class=tokenizer,
    )
    train_result = trainer.train(resume_from_checkpoint=True if args.resume else None)
    evaluation = trainer.evaluate()
    model.save_pretrained(args.output, safe_serialization=True)
    tokenizer.save_pretrained(args.output)
    metadata = {
        "preset": base["preset"],
        "base_model": base["model"],
        "base_model_revision": base["revision"],
        "base_model_license": base["license"],
        "base_model_redistributable": base["redistributable"],
        "base_model_license_url": f"https://huggingface.co/{base['model']}/blob/{base['revision']}/LICENSE",
        "training_method": "LoRA supervised fine-tuning; assistant-response tokens only",
        "seed": args.seed,
        "train_jsonl_sha256": _digest(args.train),
        "validation_jsonl_sha256": _digest(args.validation),
        "train_examples_used": len(train_rows),
        "validation_examples_used": len(eval_rows),
        "max_length": args.max_length,
        "epochs": args.epochs,
        "learning_rate": args.learning_rate,
        "gradient_accumulation_steps": args.gradient_accumulation_steps,
        "per_device_batch_size": args.per_device_batch_size,
        "lora": {
            "r": args.lora_r,
            "alpha": args.lora_alpha,
            "dropout": args.lora_dropout,
            "target_modules": target_modules,
        },
        "save_strategy": args.save_strategy,
        "save_steps": args.save_steps,
        "save_total_limit": args.save_total_limit,
        "train_metrics": train_result.metrics,
        "validation_metrics": evaluation,
        "limitations": [
            "Training/validation loss does not measure Terraform validity; low loss does not imply parseable, "
            "provider-valid, safe, cost-optimized, reliable, or deployable Terraform.",
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
