from __future__ import annotations

import pytest

from terramind_ml.train_sft import encode_conversation


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


def test_sft_encoding_rejects_inconsistent_chat_template_prefix():
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
    with pytest.raises(ValueError, match="prefix boundary"):
        encode_conversation(MismatchTokenizer(), messages, max_length=64)


def test_sft_encoding_skips_examples_with_no_answer_tokens_after_truncation():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "request"},
        {"role": "assistant", "content": "resource \"aws_s3_bucket\" {}"},
    ]
    assert encode_conversation(FakeTokenizer(), messages, max_length=8) is None
