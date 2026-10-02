"""Generate synthetic supervised fine-tuning data from TerraMind's scaffolder.

The deterministic scaffolder in :mod:`app.scaffold` turns a small, structured
infrastructure request into valid, provider-oriented AWS Terraform **without a
language model**. This module samples many such requests with a seeded RNG, runs
each one through the scaffolder, and records the exact runtime prompt/response
pair as a JSONL training row.

Because every assistant target comes from the scaffolder, it is valid HCL by
construction and the corpus carries no third-party licensing obligations. The
point is to fine-tune the local draftsman on deterministic, always-valid targets
so it stops inventing undeclared variables or dropping requested resources.

The user message reproduces :func:`app.main._run_generation`'s prompt byte for
byte, including its fallback text for empty sections, and the system message is
the GGUF backend's instruction. That keeps the training distribution identical
to what the model sees at inference time.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path
from typing import Any

from terramind_ml.sft_data import SYSTEM_PROMPT

__all__ = [
    "GGUF_SYSTEM_PROMPT",
    "SOURCE",
    "LICENSE",
    "build_user_message",
    "generate_dataset",
    "main",
]

#: System message the GGUF backend sends. Kept byte-identical to
#: ``app.llama_cpp_backend._SYSTEM_INSTRUCTION``. The user message already embeds
#: :data:`terramind_ml.sft_data.SYSTEM_PROMPT`, mirroring the runtime.
GGUF_SYSTEM_PROMPT = (
    "You are TerraMind, a Terraform HCL drafting assistant. "
    "Return only Terraform HCL. Do not include analysis, Markdown fences, or prose."
)

SOURCE = "terramind-scaffolder"
LICENSE = "project-generated"
DEFAULT_MAX_LENGTH_CHARS = 30_000

#: Small, fixed list of AWS regions. The scaffolder detects one of these and sets
#: the ``aws_region`` variable default.
REGIONS = ("ap-south-1", "us-east-1", "eu-west-1", "us-west-2", "ap-southeast-2")

#: Middle section of the runtime prompt; extracted so :func:`build_user_message`
#: stays a single readable expression.
_PREAMBLE = (
    "Generate one complete Terraform configuration. Include required_providers and provider configuration "
    "when needed, use variables for environment-specific values, and make assumptions explicit as HCL comments."
)

# kind -> (min_count, max_count, singular, plural, short alias)
# The plural is used for the "3 VPCs" form; the singular for "VPC 3"; the alias
# for "vpc: 3" and "3x vpc". Every form is recognised by app.scaffold._ALIASES.
_COUNT_KINDS: dict[str, tuple[int, int, str, str, str]] = {
    "vpc": (1, 5, "VPC", "VPCs", "vpc"),
    "ec2": (1, 6, "EC2 instance", "EC2 instances", "ec2"),
    "s3": (0, 3, "S3 bucket", "S3 buckets", "s3"),
    "alb": (0, 2, "ALB", "ALBs", "alb"),
    "transit_gateway": (0, 1, "Transit Gateway", "Transit Gateways", "tgw"),
    "internet_gateway": (0, 4, "Internet Gateway", "Internet Gateways", "igw"),
    "nat_gateway": (0, 4, "NAT Gateway", "NAT Gateways", "nat"),
    "security_group": (1, 6, "security group", "security groups", "sg"),
    "private_subnet": (0, 6, "private subnet", "private subnets", "private subnet"),
    "public_subnet": (0, 4, "public subnet", "public subnets", "public subnet"),
    "flow_log": (0, 2, "VPC flow log", "VPC flow logs", "flow log"),
    "cloudwatch_log_group": (0, 2, "CloudWatch log group", "CloudWatch log groups", "log group"),
}
_IAM_MIN, _IAM_MAX = 0, 2
_IAM_STYLES = ("role", "profile")

_GUIDANCE = (
    "Follow AWS Well-Architected practices and prefer secure defaults.",
    "Keep the footprint minimal and the configuration easy to review.",
    "Parameterize every value that changes between environments.",
    "Bias toward least privilege and private networking.",
    "Make the configuration straightforward to extend later.",
)


def build_user_message(
    *,
    description: str,
    resource_inventory: str,
    connectivity: str,
    constraints: str,
) -> str:
    """Reproduce ``app.main._run_generation``'s user message byte for byte."""
    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"{_PREAMBLE}\n\n"
        f"Infrastructure requested:\n{description}\n\n"
        "Requested resources and counts:\n"
        f"{resource_inventory or 'No explicit inventory supplied; infer only what the description requires.'}\n\n"
        "Requested connections and traffic flow:\n"
        f"{connectivity or 'No explicit topology supplied; state assumptions in HCL comments.'}\n\n"
        f"Other constraints:\n{constraints or 'No extra constraints supplied.'}\n"
    )


# --- Seeded sampling --------------------------------------------------------


def _derive_seed(base_seed: int, split: str, index: int) -> int:
    """Derive an independent, platform-stable per-sample seed.

    ``hash()`` is salted per process, so it cannot be used here; SHA-256 gives the
    same value on every run and makes ``same seed -> byte-identical files`` hold.
    """
    digest = hashlib.sha256(f"{base_seed}:{split}:{index}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _sample_counts(rng: random.Random) -> tuple[dict[str, int], str]:
    """Draw one count per resource kind plus an IAM role/profile style."""
    counts = {kind: rng.randint(low, high) for kind, (low, high, *_rest) in _COUNT_KINDS.items()}
    counts["iam"] = rng.randint(_IAM_MIN, _IAM_MAX)
    return counts, rng.choice(_IAM_STYLES)


def _form_set(n: int, singular: str, plural: str, alias: str) -> tuple[str, ...]:
    """Return the four alias forms the scaffolder recognises."""
    return (f"{n} {plural}", f"{singular} {n}", f"{alias}: {n}", f"{n}x {alias}")


def _phrase(kind: str, n: int, iam_style: str, rng: random.Random) -> str:
    """Render one resource phrase using a randomly chosen alias form."""
    if kind == "iam":
        singular, plural, alias = (
            ("IAM role", "IAM roles", "iam role")
            if iam_style == "role"
            else ("instance profile", "instance profiles", "instance profile")
        )
    else:
        _low, _high, singular, plural, alias = _COUNT_KINDS[kind]
    return rng.choice(_form_set(n, singular, plural, alias))


def _natural_join(items: list[str], rng: random.Random) -> str:
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def _build_inventory(phrases: dict[str, str], rng: random.Random) -> str:
    present = list(phrases)
    rng.shuffle(present)
    separator = rng.choice((", ", ", ", " + ", "; ", " and "))
    return separator.join(phrases[kind] for kind in present)


def _build_description(phrases: dict[str, str], region: str, rng: random.Random) -> str:
    present = sorted(phrases)
    mentioned = rng.sample(present, min(len(present), rng.randint(1, 3)))
    summary = _natural_join([phrases[kind] for kind in mentioned], rng)
    opener = rng.choice(("We need", "Please provision", "Stand up", "Create", "Deploy", "Design"))
    environment = rng.choice(("production", "staging", "development", "sandbox"))
    statement = f"{opener} {summary} in {region} for the {environment} environment."
    return f"{statement} {rng.choice(_GUIDANCE)}"


def _build_connectivity(counts: dict[str, int], rng: random.Random) -> str:
    """Compose topology phrases that only name resources actually requested."""
    options: list[str] = []
    if counts.get("transit_gateway"):
        options.append("VPCs communicate privately via a Transit Gateway")
    if counts.get("alb"):
        options.append("the Application Load Balancer terminates HTTPS and forwards traffic to the instances")
    if counts.get("nat_gateway"):
        options.append("private subnets reach the internet through NAT gateways")
    if counts.get("internet_gateway"):
        options.append("public subnets route outbound traffic through the internet gateway")
    if counts.get("s3"):
        options.append("instances read and write the S3 buckets over the AWS network")
    if counts.get("flow_log"):
        options.append("VPC flow logs capture all accepted and rejected traffic")
    options.append("workload instances stay in private subnets with no inbound internet access")
    chosen = rng.sample(options, min(len(options), rng.randint(1, 3)))
    return "; ".join(chosen) + "."


def _build_constraints(counts: dict[str, int], region: str, rng: random.Random) -> str:
    options = [
        "no SSH from 0.0.0.0/0",
        "all EBS volumes encrypted",
        "IMDSv2 required on every instance",
        "private subnets only",
        "no public IP addresses on instances",
        "target 99.9% availability",
        "low cost",
        "least-privilege IAM",
        f"deploy everything in {region}",
    ]
    if counts.get("flow_log"):
        options.append("enable VPC flow logging")
    if counts.get("s3"):
        options.append("block all public S3 access")
    chosen = rng.sample(options, min(len(options), rng.randint(2, 5)))
    return "; ".join(chosen) + "."


def _generate_sample(
    index: int,
    base_seed: int,
    rng: random.Random,
    max_length_chars: int,
) -> tuple[dict[str, Any] | None, str | None]:
    """Scaffold one request; return ``(row, None)`` or ``(None, skip_reason)``."""
    from app.scaffold import scaffold_terraform

    counts, iam_style = _sample_counts(rng)
    region = rng.choice(REGIONS)
    phrases = {
        kind: _phrase(kind, count, iam_style, rng)
        for kind, count in counts.items()
        if count > 0
    }
    description = _build_description(phrases, region, rng)
    resource_inventory = _build_inventory(phrases, rng)
    connectivity = _build_connectivity(counts, rng)
    constraints = _build_constraints(counts, region, rng)

    result = scaffold_terraform(
        description=description,
        resource_inventory=resource_inventory,
        connectivity=connectivity,
        constraints=constraints,
    )
    if result is None:
        return None, "unsupported_inventory"
    hcl, _notes = result
    if not hcl.strip():
        return None, "empty_output"
    if len(hcl) > max_length_chars:
        return None, "too_long"

    row = {
        "messages": [
            {"role": "system", "content": GGUF_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": build_user_message(
                    description=description,
                    resource_inventory=resource_inventory,
                    connectivity=connectivity,
                    constraints=constraints,
                ),
            },
            {"role": "assistant", "content": hcl},
        ],
        "provenance": {
            "source": SOURCE,
            "seed": base_seed,
            "index": index,
            "license": LICENSE,
        },
    }
    return row, None


# --- Dataset assembly -------------------------------------------------------


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def generate_dataset(
    output_dir: Path | str,
    *,
    train_count: int,
    validation_count: int,
    seed: int = 17,
    max_length_chars: int = DEFAULT_MAX_LENGTH_CHARS,
) -> dict[str, Any]:
    """Sample, scaffold, and write ``train.jsonl``, ``validation.jsonl``, and ``manifest.json``.

    The two splits are sampled independently with distinct derived seeds and a
    shared monotonic index, so their provenance indices never collide. Up to
    ``50 * count`` attempts per split are made to reach the requested count; only
    unsupported or over-long scaffolds reduce the final row count.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    splits: dict[str, list[dict[str, Any]]] = {}
    skipped: dict[str, dict[str, int]] = {}
    counter = 0
    for split, count in (("train", train_count), ("validation", validation_count)):
        rows: list[dict[str, Any]] = []
        reasons: dict[str, int] = {}
        attempts = 0
        cap = max(count * 50, 100)
        while len(rows) < count and attempts < cap:
            rng = random.Random(_derive_seed(seed, split, counter))
            row, reason = _generate_sample(counter, seed, rng, max_length_chars)
            counter += 1
            attempts += 1
            if reason is None and row is not None:
                rows.append(row)
            else:
                reasons[reason or "unknown"] = reasons.get(reason or "unknown", 0) + 1
        splits[split] = rows
        skipped[split] = dict(sorted(reasons.items()))

    for split, rows in splits.items():
        _write_jsonl(output_dir / f"{split}.jsonl", rows)

    manifest = {
        "generator": "terramind_ml.synth_data",
        "source": SOURCE,
        "seed": seed,
        "max_length_chars": max_length_chars,
        "requested": {"train": train_count, "validation": validation_count},
        "counts": {"train": len(splits["train"]), "validation": len(splits["validation"])},
        "train_rows": len(splits["train"]),
        "validation_rows": len(splits["validation"]),
        "skipped": skipped,
        "files_sha256": {
            "train.jsonl": _sha256(output_dir / "train.jsonl"),
            "validation.jsonl": _sha256(output_dir / "validation.jsonl"),
        },
        "provenance": {"source": SOURCE, "license": LICENSE},
        "notice": (
            "Synthetic, deterministically generated, provider-oriented (AWS Terraform) examples produced by "
            "TerraMind's model-free scaffolder. They contain no third-party content and carry no third-party "
            "licensing obligations."
        ),
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Output directory (use ignored .build/)")
    parser.add_argument("--train", type=int, default=8000, help="Number of training rows to attempt")
    parser.add_argument("--validation", type=int, default=800, help="Number of validation rows to attempt")
    parser.add_argument("--seed", type=int, default=17, help="Base RNG seed; same seed reproduces the files")
    parser.add_argument(
        "--max-length-chars",
        type=int,
        default=DEFAULT_MAX_LENGTH_CHARS,
        help="Skip scaffolds longer than this many characters",
    )
    args = parser.parse_args(argv)
    if args.train < 1 or args.validation < 1:
        parser.error("--train and --validation must both be positive")

    manifest = generate_dataset(
        args.output,
        train_count=args.train,
        validation_count=args.validation,
        seed=args.seed,
        max_length_chars=args.max_length_chars,
    )
    print(json.dumps(
        {key: manifest[key] for key in ("counts", "seed", "skipped", "files_sha256")},
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
