"""Merge a trained LoRA adapter into its pinned base for local inference runtimes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from terramind_ml.train_sft import DEFAULT_MODEL, DEFAULT_MODEL_REVISION


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--model-revision", default=DEFAULT_MODEL_REVISION)
    args = parser.parse_args()
    metadata_path = args.adapter / "training-metadata.json"
    if not metadata_path.is_file():
        parser.error("Adapter directory is missing training-metadata.json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("base_model") != args.model or metadata.get("base_model_revision") != args.model_revision:
        parser.error("Requested base model/revision does not match the adapter's recorded training base")

    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    args.output.mkdir(parents=True, exist_ok=True)
    base = AutoModelForCausalLM.from_pretrained(
        args.model, revision=args.model_revision, dtype="auto", trust_remote_code=False,
    )
    tuned = PeftModel.from_pretrained(base, args.adapter)
    merged = tuned.merge_and_unload(safe_merge=True)
    merged.save_pretrained(args.output, safe_serialization=True, max_shard_size="2GB")
    tokenizer = AutoTokenizer.from_pretrained(args.model, revision=args.model_revision, trust_remote_code=False)
    tokenizer.save_pretrained(args.output)
    (args.output / "LICENSE").write_text(
        f"Base model: {metadata['base_model']}\n"
        f"License: {metadata['base_model_license']}\n"
        f"Upstream license: {metadata.get('base_model_license_url', 'Review the base model license before use')}\n"
        "TerraMind LoRA training data provenance is in the adapter's training-metadata.json.\n",
        encoding="utf-8",
    )
    print(f"Merged adapter saved to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
