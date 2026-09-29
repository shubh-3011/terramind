import json

import pytest

from terramind_ml.evaluate_generation import evaluate_generation


def _example(resource_type: str, label: str) -> dict[str, object]:
    return {
        "messages": [
            {"role": "system", "content": "system"},
            {"role": "user", "content": f"Create {label}"},
            {"role": "assistant", "content": f'resource "{resource_type}" "example" {{}}'},
        ],
        "provenance": {"repo": f"repo-{label}", "file_path": f"{label}.tf", "license": "MIT"},
    }


def test_evaluation_reports_aggregate_metrics_without_storing_code(tmp_path):
    validation = tmp_path / "validation.jsonl"
    rows = [_example("aws_instance", "compute"), _example("aws_s3_bucket", "storage")]
    validation.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    calls = []

    def request(_api_url, prompt, _provider_workspace):
        calls.append(prompt)
        resource_type = "aws_instance" if "compute" in prompt else "aws_s3_bucket"
        return 200, {
            "model": "local-test-model",
            "terraform": f'resource "{resource_type}" "generated" {{}}',
            "checks": {"generation_repair": "not_needed"},
        }, 0.5, None

    report = evaluate_generation(validation, "http://127.0.0.1:8000", request_fn=request)

    assert report["evaluated_examples"] == 2
    assert report["parseable_hcl_rate"] == 1
    assert report["resource_type_micro_f1"] == 1
    assert report["backend_models"] == {"local-test-model": 2}
    assert report["generation_repair_status_counts"] == {"not_needed": 2}
    assert report["repaired_parseable_hcl_count"] == 0
    assert len(report["example_ids_sha256_prefixes"]) == 2
    serialized_report = json.dumps(report)
    assert "Create compute" not in serialized_report
    assert 'resource "aws_instance"' not in serialized_report
    assert len(calls) == 2


def test_evaluation_rejects_non_loopback_endpoint_before_sending_prompts(tmp_path):
    validation = tmp_path / "validation.jsonl"
    validation.write_text(json.dumps(_example("aws_instance", "compute")), encoding="utf-8")

    def forbidden_request(*_args):
        raise AssertionError("no prompt may be sent to a remote endpoint")

    with pytest.raises(ValueError, match="loopback"):
        evaluate_generation(validation, "https://example.com", request_fn=forbidden_request)


def test_evaluation_records_unparseable_http_responses_as_failures(tmp_path):
    validation = tmp_path / "validation.jsonl"
    validation.write_text(json.dumps(_example("aws_instance", "compute")), encoding="utf-8")

    report = evaluate_generation(
        validation,
        "http://localhost:8000",
        request_fn=lambda *_args: (422, None, 0.1, "HCL parse failure"),
    )

    assert report["http_success_count"] == 0
    assert report["parseable_hcl_count"] == 0
    assert report["parseable_hcl_rate"] == 0
    assert report["errors_by_kind"] == {"422": 1}


def test_evaluation_leaves_resource_f1_unknown_when_output_has_no_resources(tmp_path):
    validation = tmp_path / "validation.jsonl"
    validation.write_text(json.dumps(_example("aws_instance", "compute")), encoding="utf-8")

    report = evaluate_generation(
        validation,
        "http://127.0.0.1:8000",
        request_fn=lambda *_args: (200, {"terraform": 'terraform { required_version = ">= 1.5" }'}, 0.1, None),
    )

    assert report["resource_type_micro_precision"] is None
    assert report["resource_type_micro_recall"] == 0
    assert report["resource_type_micro_f1"] is None


def test_evaluation_reports_provider_schema_acceptance_without_paths_or_code(tmp_path):
    validation = tmp_path / "validation.jsonl"
    validation.write_text(json.dumps(_example("aws_s3_bucket", "storage")), encoding="utf-8")
    workspace = tmp_path / "trusted-provider-cache"
    (workspace / ".terraform" / "providers").mkdir(parents=True)
    (workspace / ".terraform.lock.hcl").write_text("fixture lock", encoding="utf-8")
    calls = []

    def request(_api_url, prompt, provider_workspace):
        calls.append((prompt, provider_workspace))
        return 200, {
            "model": "local-test-model",
            "terraform": 'resource "aws_s3_bucket" "generated" {}',
            "checks": {"terraform_validate": "passed", "generation_repair": "attempted once; review the returned validation findings"},
        }, 0.25, None

    report = evaluate_generation(
        validation, "http://127.0.0.1:8000", request_fn=request,
        provider_workspace=workspace,
    )

    assert report["provider_validation_status_counts"] == {"passed": 1}
    assert report["provider_schema_valid_count"] == 1
    assert report["repaired_parseable_hcl_count"] == 1
    assert calls[0][1] == str(workspace.resolve())
    assert str(workspace) not in json.dumps(report)
    assert "resource \"aws_s3_bucket\"" not in json.dumps(report)


def test_evaluation_requires_preinitialized_provider_workspace_before_generation(tmp_path):
    validation = tmp_path / "validation.jsonl"
    validation.write_text(json.dumps(_example("aws_instance", "compute")), encoding="utf-8")

    def forbidden_request(*_args):
        raise AssertionError("generation must not run without the requested provider cache")

    with pytest.raises(ValueError, match="initialized workspace"):
        evaluate_generation(
            validation, "http://127.0.0.1:8000", request_fn=forbidden_request,
            provider_workspace=tmp_path / "missing-cache",
        )
