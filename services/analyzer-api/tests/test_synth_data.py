"""Tests for the synthetic scaffolder-backed SFT data generator."""

import json
from pathlib import Path

import hcl2
import pytest

from terramind_ml import synth_data
from terramind_ml.sft_data import SYSTEM_PROMPT

EXPECTED_GGUF_SYSTEM = (
    "You are TerraMind, a Terraform HCL drafting assistant. "
    "Return only Terraform HCL. Do not include analysis, Markdown fences, or prose."
)

SECTION_LABELS = (
    "Infrastructure requested:",
    "Requested resources and counts:",
    "Requested connections and traffic flow:",
    "Other constraints:",
)


def _read_rows(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture(scope="module")
def tiny_dataset(tmp_path_factory):
    output = tmp_path_factory.mktemp("synth-data")
    manifest = synth_data.generate_dataset(output, train_count=20, validation_count=5, seed=17)
    return output, manifest


def test_generate_dataset_writes_requested_shape(tiny_dataset):
    output, manifest = tiny_dataset

    assert 1 <= manifest["counts"]["train"] <= 20
    assert 1 <= manifest["counts"]["validation"] <= 5
    # Every request includes a VPC, an EC2 instance, and a security group, so the
    # scaffolder should never skip in practice.
    assert manifest["counts"]["train"] == 20
    assert manifest["counts"]["validation"] == 5

    train = _read_rows(output / "train.jsonl")
    validation = _read_rows(output / "validation.jsonl")
    assert len(train) == manifest["counts"]["train"]
    assert len(validation) == manifest["counts"]["validation"]
    assert len(train) == manifest["train_rows"]
    assert len(validation) == manifest["validation_rows"]

    for row in [*train, *validation]:
        messages = row["messages"]
        assert len(messages) == 3
        assert [message["role"] for message in messages] == ["system", "user", "assistant"]
        assert all(message["content"].strip() for message in messages)


def test_every_assistant_turn_parses_as_hcl2(tiny_dataset):
    output, _manifest = tiny_dataset
    for name in ("train.jsonl", "validation.jsonl"):
        rows = _read_rows(output / name)
        assert rows
        for row in rows:
            document = hcl2.loads(row["messages"][2]["content"])
            assert document


def test_system_and_user_messages_match_runtime(tiny_dataset):
    output, _manifest = tiny_dataset
    assert synth_data.GGUF_SYSTEM_PROMPT == EXPECTED_GGUF_SYSTEM

    for row in _read_rows(output / "train.jsonl"):
        system, user, _assistant = row["messages"]
        assert system["content"] == EXPECTED_GGUF_SYSTEM
        # The runtime user message embeds the SFT system prompt ahead of the body.
        assert user["content"].startswith(SYSTEM_PROMPT)
        for label in SECTION_LABELS:
            assert f"{label}\n" in user["content"]


def test_build_user_message_uses_runtime_fallbacks():
    message = synth_data.build_user_message(
        description="Create a VPC.",
        resource_inventory="1 VPC",
        connectivity="",
        constraints="",
    )
    assert "No explicit topology supplied; state assumptions in HCL comments." in message
    assert "No extra constraints supplied." in message
    assert message.startswith(SYSTEM_PROMPT)


def test_provenance_is_project_generated_and_splits_do_not_share_indices(tiny_dataset):
    output, _manifest = tiny_dataset
    train = _read_rows(output / "train.jsonl")
    validation = _read_rows(output / "validation.jsonl")

    for row in [*train, *validation]:
        provenance = row["provenance"]
        assert provenance["source"] == "terramind-scaffolder"
        assert provenance["license"] == "project-generated"
        assert provenance["seed"] == 17

    train_indices = {row["provenance"]["index"] for row in train}
    validation_indices = {row["provenance"]["index"] for row in validation}
    assert train_indices.isdisjoint(validation_indices)


def test_same_seed_produces_byte_identical_files(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    manifest_first = synth_data.generate_dataset(first, train_count=6, validation_count=2, seed=23)
    manifest_second = synth_data.generate_dataset(second, train_count=6, validation_count=2, seed=23)

    for name in ("train.jsonl", "validation.jsonl"):
        assert (first / name).read_bytes() == (second / name).read_bytes()
    assert manifest_first["files_sha256"] == manifest_second["files_sha256"]


def test_cli_writes_dataset_and_manifest(tmp_path):
    code = synth_data.main([
        "--output", str(tmp_path),
        "--train", "5",
        "--validation", "2",
        "--seed", "3",
        "--max-length-chars", "30000",
    ])
    assert code == 0

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["seed"] == 3
    assert manifest["requested"] == {"train": 5, "validation": 2}
    assert manifest["counts"]["train"] >= 1
    assert manifest["counts"]["validation"] >= 1
    assert set(manifest["files_sha256"]) == {"train.jsonl", "validation.jsonl"}
    assert "no third-party" in manifest["notice"].lower()
    assert (tmp_path / "train.jsonl").exists()
    assert (tmp_path / "validation.jsonl").exists()
