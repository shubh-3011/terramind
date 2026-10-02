from __future__ import annotations

import json

import pytest

from terramind_ml.train_sft import (
    DEFAULT_MODEL,
    DEFAULT_MODEL_REVISION,
    DEFAULT_PRESET,
    PRESETS,
    build_arg_parser,
    build_bnb_config,
    encode_conversation,
    resolve_base_model,
    summarize_encoding,
)


class FakeTokenizer:
    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
        assert tokenize is True
        if add_generation_prompt:
            return [1, 2, 3]
        return list(range(1, 16))


def test_sft_encoding_masks_prompt_and_trains_only_assistant_tokens():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "request"},
        {"role": "assistant", "content": "resource \"aws_s3_bucket\" {}"},
    ]
    encoded = encode_conversation(FakeTokenizer(), messages, max_length=64)
    assert encoded is not None
    assert encoded["labels"][:3] == [-100, -100, -100]
    assert encoded["labels"][3:] == encoded["input_ids"][3:]


def test_sft_encoding_skips_examples_with_inconsistent_chat_template_prefix():
    class MismatchTokenizer(FakeTokenizer):
        def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
            tokens = super().apply_chat_template(messages, tokenize=tokenize, add_generation_prompt=add_generation_prompt)
            if not add_generation_prompt:
                tokens[0] = 999
            return tokens

    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "request"},
        {"role": "assistant", "content": "a sufficiently long Terraform answer"},
    ]
    # A row whose prompting cannot be located is skipped, never fatal to the run.
    assert encode_conversation(MismatchTokenizer(), messages, max_length=64) is None


def test_sft_encoding_uses_assistant_marker_in_token_stream():
    """Blank-line answers move the BPE boundary; the assistant marker must be found inline."""
    class MarkerTokenizer:
        MARKER = [151644, 77091, 198]

        def encode(self, text, add_special_tokens=False):
            return list(self.MARKER)

        def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
            if add_generation_prompt:
                return [10, 11] + list(self.MARKER)
            return [10, 11] + list(self.MARKER) + list(range(20, 30))

    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "request"},
        {"role": "assistant", "content": "\n\nresource \"aws_s3_bucket\" \"b\" {}"},
    ]
    encoded = encode_conversation(MarkerTokenizer(), messages, max_length=64)
    assert encoded is not None
    assert encoded["labels"][:5] == [-100] * 5
    assert encoded["labels"][5:] == encoded["input_ids"][5:]


def test_sft_encoding_skips_examples_with_no_answer_tokens_after_truncation():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "request"},
        {"role": "assistant", "content": "resource \"aws_s3_bucket\" {}"},
    ]
    assert encode_conversation(FakeTokenizer(), messages, max_length=8) is None


def test_default_preset_points_at_qwen2_5_coder_1_5b_instruct():
    assert DEFAULT_PRESET == "qwen2.5-coder-1.5b-instruct"
    entry = PRESETS[DEFAULT_PRESET]
    assert entry["model"] == "Qwen/Qwen2.5-Coder-1.5B-Instruct"
    assert entry["revision"] == "2e1fd397ee46e1388853d2af2c993145b0f1098a"
    assert entry["license"] == "Apache-2.0"
    assert entry["redistributable"] is True
    assert (DEFAULT_MODEL, DEFAULT_MODEL_REVISION) == (entry["model"], entry["revision"])


def test_every_preset_pins_a_revision_and_records_license():
    expected = {
        "qwen2.5-coder-1.5b-instruct": ("Qwen/Qwen2.5-Coder-1.5B-Instruct", "2e1fd397ee46e1388853d2af2c993145b0f1098a"),
        "qwen3-0.6b": ("Qwen/Qwen3-0.6B", "c1899de289a04d12100db370d81485cdf75e47ca"),
        "qwen3-1.7b": ("Qwen/Qwen3-1.7B", "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e"),
        "qwen2.5-coder-7b-instruct": ("Qwen/Qwen2.5-Coder-7B-Instruct", "c03e6d358207e414f1eca0bb1891e29f1db0e242"),
        "qwen3-4b-instruct-2507": ("Qwen/Qwen3-4B-Instruct-2507", "cdbee75f17c01a7cc42f958dc650907174af0554"),
    }
    assert set(PRESETS) == set(expected)
    for name, (model, revision) in expected.items():
        entry = PRESETS[name]
        assert entry["model"] == model
        assert entry["revision"] == revision
        assert len(entry["revision"]) == 40
        assert entry["license"] == "Apache-2.0"
        assert entry["redistributable"] is True


def test_resolve_base_model_rejects_unknown_preset():
    with pytest.raises(ValueError, match="Unknown base model preset"):
        resolve_base_model("does-not-exist")


def test_resolve_base_model_explicit_overrides_win_over_preset():
    resolved = resolve_base_model(
        DEFAULT_PRESET, model="acme/custom-coder", model_revision="deadbeef",
    )
    assert resolved["preset"] == DEFAULT_PRESET
    assert resolved["model"] == "acme/custom-coder"
    assert resolved["revision"] == "deadbeef"
    # License/redistribution still track the named preset.
    assert resolved["license"] == "Apache-2.0"
    assert resolved["redistributable"] is True


def test_resolve_base_model_defaults_to_preset_values():
    resolved = resolve_base_model(DEFAULT_PRESET)
    assert resolved["model"] == DEFAULT_MODEL
    assert resolved["revision"] == DEFAULT_MODEL_REVISION


def _conversation(row_id: str, answer: str = 'resource "aws_s3_bucket" "example" {}') -> dict:
    return {
        "messages": [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": f"Create {row_id}"},
            {"role": "assistant", "content": answer},
        ]
    }


def test_dry_run_summary_encodes_rows_without_torch(tmp_path):
    train = tmp_path / "train.jsonl"
    validation = tmp_path / "validation.jsonl"
    train.write_text(
        "\n".join(json.dumps(row) for row in [_conversation("a"), _conversation("b"), {"messages": [{"role": "user", "content": "no assistant"}]}]),
        encoding="utf-8",
    )
    validation.write_text(json.dumps(_conversation("c")), encoding="utf-8")

    summary = summarize_encoding(
        FakeTokenizer(), train, validation, max_length=64, seed=17, max_validation_samples=256,
    )

    assert summary["dry_run"] is True
    assert summary["train"] == {
        "examples": 3,
        "examples_usable": 2,
        "examples_skipped": 1,
        "input_tokens": 30,
        "supervised_tokens": 24,
    }
    assert summary["validation"]["examples_usable"] == 1
    assert summary["validation"]["input_tokens"] == 15


def test_qwen2_5_coder_7b_preset_is_pinned_and_redistributable():
    entry = PRESETS["qwen2.5-coder-7b-instruct"]
    assert entry["model"] == "Qwen/Qwen2.5-Coder-7B-Instruct"
    assert entry["revision"] == "c03e6d358207e414f1eca0bb1891e29f1db0e242"
    assert len(entry["revision"]) == 40
    assert entry["license"] == "Apache-2.0"
    assert entry["redistributable"] is True
    resolved = resolve_base_model("qwen2.5-coder-7b-instruct")
    assert resolved["model"] == entry["model"]
    assert resolved["revision"] == entry["revision"]


def test_build_bnb_config_returns_expected_fields():
    config = build_bnb_config("nf4", "bfloat16", True)
    assert config["load_in_4bit"] is True
    assert config["bnb_4bit_quant_type"] == "nf4"
    assert config["bnb_4bit_compute_dtype"] == "bfloat16"
    assert config["bnb_4bit_use_double_quant"] is True


def test_build_bnb_config_rejects_unknown_quant_type_deterministically():
    with pytest.raises(ValueError, match="Unsupported 4-bit quant type"):
        build_bnb_config("int8", "bfloat16", True)


def test_build_bnb_config_accepts_fp4_and_rejects_bad_dtype():
    config = build_bnb_config("fp4", "float16", False)
    assert config["bnb_4bit_quant_type"] == "fp4"
    assert config["bnb_4bit_compute_dtype"] == "float16"
    assert config["bnb_4bit_use_double_quant"] is False
    with pytest.raises(ValueError, match="Unsupported 4-bit compute dtype"):
        build_bnb_config("nf4", "float8", True)


def test_load_in_4bit_flag_defaults_quant_type_to_nf4():
    parser = build_arg_parser()
    args = parser.parse_args(
        ["--train", "t.jsonl", "--validation", "v.jsonl", "--output", "out", "--load-in-4bit"]
    )
    assert args.load_in_4bit is True
    assert args.bnb_4bit_quant_type == "nf4"
    assert args.bnb_4bit_compute_dtype == "bfloat16"
    assert args.bnb_4bit_double_quant is True


def test_load_in_4bit_disabled_by_default():
    parser = build_arg_parser()
    args = parser.parse_args(
        ["--train", "t.jsonl", "--validation", "v.jsonl", "--output", "out"]
    )
    assert args.load_in_4bit is False
    assert args.bnb_4bit_quant_type == "nf4"


def test_no_bnb_double_quant_flag_disables_double_quant():
    parser = build_arg_parser()
    args = parser.parse_args(
        ["--train", "t.jsonl", "--validation", "v.jsonl", "--output", "out",
         "--load-in-4bit", "--no-bnb-4bit-double-quant"]
    )
    assert args.bnb_4bit_double_quant is False
