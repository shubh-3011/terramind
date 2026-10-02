"""Distil Terraform generation from a large teacher into a small student corpus.

Run this on a big GPU box (e.g. a DGX H200, 141 GB/GPU). It asks a strong teacher
model for Terraform, keeps only outputs that parse as HCL (and optionally pass
``terraform validate``), and writes a student-ready chat-format JSONL that
``terramind_ml.train_sft`` can consume directly.

Why: capacity is the lever (see docs/DISTILLATION.md). Our 1.5 B student has a low
ceiling; a 27 B teacher's *validated* outputs are far better supervision than raw,
sometimes-truncated real-world files.

Example (single H200, bf16 teacher):
    python dgx_distill.py \
        --prompts ../terramind-training-kit/data/train.jsonl \
        --output distil/train.jsonl --limit 5000 --batch-size 8

Prompt input formats:
  * ``messages``     - rows shaped {"messages":[{"role","content"},...]} (our prepared corpus)
  * ``instruction_input`` - rows shaped {"instruction","input"} (raw HF datasets)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

DEFAULT_TEACHER = "SASVAAI/qwen38-27b-terraform"
DEFAULT_SYSTEM = (
    "You are a Terraform expert. Given a plain-language description of infrastructure, "
    "output the complete, valid Terraform HCL configuration (including any required "
    "terraform, provider, resource, data, variable, and output blocks) that implements it. "
    "Output raw HCL only—no markdown, no explanations, no commentary."
)

HCL_START = re.compile(
    r'(?m)^\s*(terraform\s*\{|provider\s+"|resource\s+"|data\s+"|variable\s+"|'
    r'output\s+"|module\s+"|locals\s*\{|moved\s*\{|import\s*\{)'
)


def _text_after_think(text: str) -> str:
    """Drop a leading  thinking...<｜end▁of▁thinking｜> block (the teacher is trained with an empty one)."""
    cleaned = re.sub(r"(?is)^\s*<think>.*?</think>\s*", "", text)
    return cleaned


def _strip_fences(text: str) -> str:
    text = text.strip()
    # remove a single fenced block if the whole answer is fenced
    m = re.match(r"(?is)^```[a-zA-Z0-9_+-]*\s*\n(.*?)\n```\s*$", text)
    if m:
        return m.group(1).strip()
    # or the first fenced block
    m = re.search(r"(?is)```[a-zA-Z0-9_+-]*\s*\n(.*?)```", text)
    if m:
        return m.group(1).strip()
    return text


def _extract_hcl(text: str) -> str:
    """Best-effort isolation of the HCL body from a chatty completion."""
    text = _strip_fences(_text_after_think(text)).strip()
    match = HCL_START.search(text)
    if match and match.start() > 0:
        text = text[match.start():]
    return text.strip()


def _row_to_prompt(row: dict[str, Any], fmt: str) -> tuple[str, str] | None:
    """Return (instruction, description) or None if the row is unusable."""
    if fmt == "instruction_input":
        instruction = str(row.get("instruction", "")).strip()
        description = str(row.get("input", "")).strip()
        return (instruction, description) if description else None
    messages = row.get("messages")
    if not isinstance(messages, list):
        return None
    system = next((m.get("content", "") for m in messages if m.get("role") == "system"), "")
    user = next((m.get("content", "") for m in messages if m.get("role") == "user"), "")
    if not user:
        return None
    # our prepared user turn is "instruction\n\n<description>"
    parts = user.split("\n\n", 1)
    instruction = parts[0].strip()
    description = parts[1].strip() if len(parts) > 1 else parts[0].strip()
    return instruction, description


def _build_user_turn(instruction: str, description: str, fence: bool) -> str:
    if fence:
        return f"{instruction}\n\n```\n{description}\n```"
    return f"{instruction}\n\n{description}"


def _load_model(teacher: str, revision: str | None):
    import torch
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(teacher, revision=revision)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "left"

    loaded = None
    # qwen3_5 is a multimodal config; AutoModelForCausalLM cannot load it.
    for loader_name in ("AutoModelForImageTextToText", "AutoModelForCausalLM"):
        try:
            module = __import__("transformers", fromlist=[loader_name])
            loader = getattr(module, loader_name)
            loaded = loader.from_pretrained(
                teacher, revision=revision, dtype=torch.bfloat16, device_map="auto",
            )
            print(f"loaded with {loader_name}", flush=True)
            break
        except Exception as error:  # noqa: BLE001
            print(f"{loader_name} failed: {str(error)[:160]}", flush=True)
    if loaded is None:
        raise SystemExit(
            "Could not load the teacher. qwen3_5 needs a git-main transformers build:\n"
            "  pip install 'git+https://github.com/huggingface/transformers.git@main'"
        )
    loaded.eval()
    return tokenizer, loaded


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--prompts", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--teacher", default=DEFAULT_TEACHER)
    parser.add_argument("--teacher-revision", default=None)
    parser.add_argument("--system-prompt", default=DEFAULT_SYSTEM)
    parser.add_argument("--prompts-format", choices=["messages", "instruction_input", "auto"], default="auto")
    parser.add_argument("--limit", type=int, default=0, help="0 = all rows")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--max-new-tokens", type=int, default=2048)
    parser.add_argument("--no-fence", action="store_true", help="Do not wrap the description in a code fence")
    parser.add_argument("--keep-only-parseable", action="store_true", default=True)
    parser.add_argument("--allow-unparseable", dest="keep_only_parseable", action="store_false")
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args()

    try:
        import hcl2  # noqa: F401
        can_parse = True
    except Exception:  # noqa: BLE001
        can_parse = False
        if args.keep_only_parseable:
            print("warning: python-hcl2 not installed; disabling parse filtering "
                  "(pip install python-hcl2)", flush=True)

    rows: list[dict[str, Any]] = []
    with args.prompts.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    if args.limit:
        rows = rows[: args.limit]
    print(f"prompts: {len(rows)} from {args.prompts}", flush=True)

    fmt = args.prompts_format
    if fmt == "auto":
        fmt = "instruction_input" if "instruction" in rows[0] else "messages"
    print(f"format : {fmt}", flush=True)

    import torch

    tokenizer, model = _load_model(args.teacher, args.teacher_revision)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    kept = dropped_parse = dropped_empty = 0
    started = time.time()
    sink = args.output.open("w", encoding="utf-8", newline="\n")

    def flush_batch(batch_rows: list[dict[str, Any]]) -> None:
        nonlocal kept, dropped_parse, dropped_empty
        prompts, keep_meta = [], []
        for row in batch_rows:
            parsed = _row_to_prompt(row, fmt)
            if parsed is None:
                continue
            instruction, description = parsed
            user = _build_user_turn(instruction, description, not args.no_fence)
            messages = [{"role": "system", "content": args.system_prompt},
                        {"role": "user", "content": user}]
            try:
                text = tokenizer.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True, enable_thinking=False,
                )
            except TypeError:
                text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            prompts.append(text)
            keep_meta.append((row, instruction, user))
        if not prompts:
            return
        enc = tokenizer(prompts, return_tensors="pt", padding=True, truncation=True,
                        max_length=8192).to(model.device)
        with torch.no_grad():
            generated = model.generate(
                **enc, max_new_tokens=args.max_new_tokens, do_sample=False,
                temperature=None, top_p=None, top_k=None,
                pad_token_id=tokenizer.pad_token_id,
            )
        for i, (row, instruction, user) in enumerate(keep_meta):
            completion = tokenizer.decode(
                generated[i][enc["input_ids"].shape[-1]:], skip_special_tokens=True,
            )
            hcl = _extract_hcl(completion)
            if not hcl:
                dropped_empty += 1
                continue
            if args.keep_only_parseable and can_parse:
                try:
                    import hcl2
                    with __import__("io").StringIO(hcl) as handle:
                        hcl2.load(handle)
                except Exception:  # noqa: BLE001
                    dropped_parse += 1
                    continue
            record = {
                "messages": [
                    {"role": "system", "content": args.system_prompt},
                    {"role": "user", "content": user},
                    {"role": "assistant", "content": hcl},
                ],
                "source": {
                    "teacher": args.teacher,
                    "teacher_revision": args.teacher_revision,
                    "description_sha256": hashlib.sha256(user.encode("utf-8")).hexdigest(),
                },
            }
            sink.write(json.dumps(record, ensure_ascii=False) + "\n")
            kept += 1
        sink.flush()
        rate = kept / max(1.0, time.time() - started)
        print(f"kept {kept} | dropped(parse) {dropped_parse} | dropped(empty) {dropped_empty} "
              f"| {rate:.2f} rows/s", flush=True)

    batch: list[dict[str, Any]] = []
    for row in rows:
        batch.append(row)
        if len(batch) >= args.batch_size:
            flush_batch(batch)
            batch = []
    if batch:
        flush_batch(batch)
    sink.close()

    manifest = {
        "teacher": args.teacher,
        "teacher_revision": args.teacher_revision,
        "prompts": str(args.prompts),
        "prompts_format": fmt,
        "rows_in": len(rows),
        "rows_kept": kept,
        "dropped_parse": dropped_parse,
        "dropped_empty": dropped_empty,
        "max_new_tokens": args.max_new_tokens,
        "batch_size": args.batch_size,
        "fenced_description": not args.no_fence,
        "system_prompt": args.system_prompt,
        "seed": args.seed,
    }
    (args.output.parent / "distil-manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8",
    )
    print("=== DONE ===", flush=True)
    print(json.dumps(manifest, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
