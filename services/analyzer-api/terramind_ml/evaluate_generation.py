"""Evaluate a local Terraform generation backend on a repository-disjoint split.

The report contains aggregate metrics and one-way hashes only; it never stores
source prompts, reference HCL, generated HCL, or source repository paths.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any, Callable


RequestResult = tuple[int, dict[str, Any] | None, float, str | None]
RequestFunction = Callable[[str, str, str | None], RequestResult]


def _validate_local_api_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    try:
        is_loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        valid_port = parsed.port is None or 1 <= parsed.port <= 65535
    except ValueError:
        is_loopback, valid_port = False, False
    if (
        parsed.scheme != "http" or not is_loopback or not valid_port
        or parsed.username is not None or parsed.password is not None
        or parsed.query or parsed.fragment
    ):
        raise ValueError("Generation evaluation accepts only a loopback HTTP analyzer URL")
    return value.rstrip("/")


def _request_generation(api_url: str, description: str, provider_workspace: str | None = None) -> RequestResult:
    payload = json.dumps({
        "description": description,
        "workspace_path": provider_workspace,
        "run_external_tools": provider_workspace is not None,
        "workspace_trusted": provider_workspace is not None,
    }).encode("utf-8")
    request = urllib.request.Request(
        f"{api_url}/v1/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    started = time.perf_counter()
    try:
        with opener.open(request, timeout=180) as response:
            body = json.loads(response.read(2_000_000).decode("utf-8"))
            return response.status, body if isinstance(body, dict) else None, time.perf_counter() - started, None
    except urllib.error.HTTPError as error:
        try:
            detail = json.loads(error.read(64_000).decode("utf-8"))
            message = str(detail.get("detail", "HTTP error")) if isinstance(detail, dict) else "HTTP error"
        except (UnicodeDecodeError, json.JSONDecodeError):
            message = "HTTP error with invalid response body"
        return error.code, None, time.perf_counter() - started, message[:500]
    except (urllib.error.URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return 0, None, time.perf_counter() - started, str(error)[:500]


def _resource_types(document: dict[str, Any]) -> Counter[str]:
    result: Counter[str] = Counter()
    blocks = document.get("resource", [])
    if not isinstance(blocks, list):
        return result
    for block in blocks:
        if not isinstance(block, dict):
            continue
        for resource_type, labels in block.items():
            if isinstance(labels, dict):
                result[str(resource_type)] += len(labels)
    return result


def _example_id(row: dict[str, Any]) -> str:
    provenance = row.get("provenance", {})
    encoded = json.dumps(provenance, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def evaluate_generation(
    validation_path: Path,
    api_url: str,
    max_examples: int = 8,
    seed: int = 17,
    request_fn: RequestFunction = _request_generation,
    provider_workspace: Path | None = None,
) -> dict[str, Any]:
    """Measure parse success and per-resource-type overlap on a fixed split."""
    import hcl2

    api_url = _validate_local_api_url(api_url)
    if max_examples < 1:
        raise ValueError("max_examples must be positive")
    if provider_workspace is not None:
        provider_workspace = provider_workspace.expanduser().resolve()
        if (
            not provider_workspace.is_dir()
            or not (provider_workspace / ".terraform.lock.hcl").is_file()
            or not (provider_workspace / ".terraform" / "providers").is_dir()
        ):
            raise ValueError("Provider evaluation requires a trusted, initialized workspace with a lockfile and local provider cache")
    rows = [
        json.loads(line) for line in validation_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not rows:
        raise ValueError("Validation split is empty")
    sampled = random.Random(seed).sample(rows, min(max_examples, len(rows)))

    parseable = 0
    http_success = 0
    errors: Counter[str] = Counter()
    model_names: Counter[str] = Counter()
    latencies: list[float] = []
    predicted_resources = 0
    expected_resources = 0
    matching_resources = 0
    provider_checks: Counter[str] = Counter()

    for row in sampled:
        messages = row.get("messages")
        if not isinstance(messages, list) or len(messages) < 3:
            raise ValueError("Validation example has no prepared SFT messages")
        prompt, target = messages[1].get("content"), messages[2].get("content")
        if not isinstance(prompt, str) or not isinstance(target, str):
            raise ValueError("Validation example has invalid user/assistant content")
        try:
            expected = _resource_types(hcl2.loads(target))
        except Exception as error:
            raise ValueError("Prepared validation answer no longer parses as HCL") from error

        status, body, elapsed, error = request_fn(
            api_url, prompt, str(provider_workspace) if provider_workspace else None,
        )
        latencies.append(elapsed)
        if status != 200 or body is None:
            errors[str(status)] += 1
            continue
        http_success += 1
        model = body.get("model")
        if isinstance(model, str):
            model_names[model] += 1
        checks = body.get("checks")
        if isinstance(checks, dict):
            provider_status = checks.get("terraform_validate")
            if isinstance(provider_status, str):
                provider_checks[provider_status.split(":", maxsplit=1)[0]] += 1
        generated = body.get("terraform")
        if not isinstance(generated, str) or not generated.strip():
            errors["invalid_response"] += 1
            continue
        try:
            actual = _resource_types(hcl2.loads(generated))
        except Exception:
            errors["unparseable_hcl"] += 1
            continue

        parseable += 1
        predicted_resources += actual.total()
        expected_resources += expected.total()
        matching_resources += sum((actual & expected).values())

    precision = matching_resources / predicted_resources if predicted_resources else None
    recall = matching_resources / expected_resources if expected_resources else None
    if precision is None or recall is None:
        f1 = None
    else:
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    manifest_path = validation_path.parent / "manifest.json"
    manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest() if manifest_path.is_file() else None
    return {
        "evaluation": "local-terraform-generation-v1",
        "validation_file_sha256": hashlib.sha256(validation_path.read_bytes()).hexdigest(),
        "source_manifest_sha256": manifest_hash,
        "seed": seed,
        "requested_examples": max_examples,
        "evaluated_examples": len(sampled),
        "http_success_count": http_success,
        "parseable_hcl_count": parseable,
        "parseable_hcl_rate": parseable / len(sampled),
        "resource_type_micro_precision": precision,
        "resource_type_micro_recall": recall,
        "resource_type_micro_f1": f1,
        "resource_type_metric_examples": parseable,
        "resource_type_overlap_counts": {
            "matched": matching_resources,
            "generated": predicted_resources,
            "reference": expected_resources,
        },
        "provider_validation_status_counts": dict(provider_checks),
        "provider_schema_valid_count": provider_checks["passed"],
        "mean_generation_seconds": statistics.mean(latencies) if latencies else None,
        "backend_models": dict(model_names),
        "errors_by_kind": dict(errors),
        "limitations": [
            "Prompts are back-translations of source HCL; this is not an independent user-intent benchmark.",
            "Resource type overlap does not measure semantic correctness, provider compatibility, security, cost, uptime, or scalability.",
            "Provider-schema results are included only when an initialized, explicitly supplied provider cache was used; they do not verify runtime behavior or deployment safety.",
            "A parseable output is not a valid or safe Terraform deployment.",
            "Only aggregate metrics and hashed example IDs are written; raw prompts and code are not retained.",
        ],
        "example_ids_sha256_prefixes": [_example_id(row) for row in sampled],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validation", type=Path, required=True, help="Prepared, repository-disjoint validation.jsonl")
    parser.add_argument("--output", type=Path, required=True, help="JSON report path (use ignored .build/)")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000", help="Loopback analyzer URL only")
    parser.add_argument("--max-examples", type=int, default=8)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument(
        "--provider-workspace", type=Path,
        help="Optional trusted initialized workspace with .terraform.lock.hcl and .terraform/providers; local provider plugins will execute during validate",
    )
    args = parser.parse_args()

    try:
        report = evaluate_generation(
            args.validation, args.api_url, args.max_examples, args.seed,
            provider_workspace=args.provider_workspace,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        key: report[key] for key in (
            "evaluated_examples", "parseable_hcl_count", "parseable_hcl_rate",
            "resource_type_micro_f1", "errors_by_kind", "backend_models",
            "provider_validation_status_counts", "provider_schema_valid_count",
        )
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
