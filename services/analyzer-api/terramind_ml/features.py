"""Versioned, label-blind features shared by training and inference."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

FEATURE_VERSION = "terraform-risk-features-v1"
FEATURE_NAMES = (
    "terraform_file_count",
    "noncomment_line_count",
    "resource_count",
    "aws_resource_count",
    "module_count",
    "provider_count",
    "network_resource_count",
    "storage_resource_count",
    "iam_resource_count",
    "public_cidr_count",
    "public_ssh_ingress_count",
    "wildcard_iam_action_count",
    "wildcard_iam_resource_count",
    "disabled_encryption_count",
    "disabled_public_access_control_count",
    "public_acl_count",
    "public_exposure_flag_count",
    "logging_disabled_count",
    "sensitive_boolean_false_count",
    "sensitive_boolean_true_count",
    "weak_security_literal_count",
)

_NETWORK_TYPES = ("security_group", "subnet", "vpc", "route", "network_acl", "internet_gateway", "eip", "load_balancer")
_STORAGE_TYPES = ("s3_", "ebs", "efs", "volume", "bucket")
_IAM_TYPES = ("iam_", "kms_key")
_PUBLIC_CIDR_KEYS = {"cidr_blocks", "ipv6_cidr_blocks", "cidr_ipv4", "cidr_ipv6", "source_ranges"}
_PUBLIC_ACCESS_KEYS = {"block_public_acls", "block_public_policy", "ignore_public_acls", "restrict_public_buckets"}
_PUBLIC_EXPOSURE_KEYS = {"publicly_accessible", "associate_public_ip_address", "assign_public_ip"}
_SENSITIVE_KEY_TOKENS = (
    "public", "encrypt", "scan", "immutable", "logging", "multi_az", "versioning",
    "mfa", "require", "protect", "block", "restrict", "imds", "tls", "ssl",
    "https", "authentication", "force_destroy", "kms", "backup", "access",
    "password", "credential", "root", "admin", "deletion", "rotation", "monitoring",
)
_WEAK_SECURITY_LITERALS = {
    "mutable", "http", "tls1.0", "tls1_0", "tls1.1", "tls1_1", "public-read",
    "public-read-write", "0.0.0.0/0", "::/0", "*",
}


def extract_features(documents: Iterable[Mapping[str, Any]], sources: Iterable[str]) -> dict[str, int]:
    """Extract simple numeric HCL structure/risk indicators, never sample labels."""
    parsed_documents = list(documents)
    source_texts = list(sources)
    resource_types = [resource_type for document in parsed_documents for resource_type in _resource_types(document)]
    flat_items = [item for document in parsed_documents for item in _walk(document)]

    features = {name: 0 for name in FEATURE_NAMES}
    features["terraform_file_count"] = len(source_texts)
    features["noncomment_line_count"] = sum(
        1 for source in source_texts for line in source.splitlines()
        if line.strip() and not line.lstrip().startswith(("#", "//"))
    )
    features["resource_count"] = len(resource_types)
    features["aws_resource_count"] = sum(resource_type.startswith("aws_") for resource_type in resource_types)
    features["module_count"] = sum(key == "module" for key, _ in flat_items)
    features["provider_count"] = sum(key == "provider" for key, _ in flat_items)
    features["network_resource_count"] = sum(any(token in resource_type for token in _NETWORK_TYPES) for resource_type in resource_types)
    features["storage_resource_count"] = sum(any(token in resource_type for token in _STORAGE_TYPES) for resource_type in resource_types)
    features["iam_resource_count"] = sum(any(token in resource_type for token in _IAM_TYPES) for resource_type in resource_types)

    for key, value in flat_items:
        if key in _PUBLIC_CIDR_KEYS:
            features["public_cidr_count"] += sum(item in {"0.0.0.0/0", "::/0"} for item in _strings(value))
        if key in {"actions", "action", "not_actions", "not_action"}:
            features["wildcard_iam_action_count"] += _wildcard_count(value)
        if key in {"resources", "resource"}:
            features["wildcard_iam_resource_count"] += _wildcard_count(value)
        if "encrypt" in key and _is_disabled(value):
            features["disabled_encryption_count"] += 1
        if key in _PUBLIC_ACCESS_KEYS and _is_disabled(value):
            features["disabled_public_access_control_count"] += 1
        if key in {"acl", "access_control_policy"} and any("public" in item for item in _strings(value)):
            features["public_acl_count"] += 1
        if key in _PUBLIC_EXPOSURE_KEYS and _is_enabled(value):
            features["public_exposure_flag_count"] += 1
        if "logging" in key and _is_disabled(value):
            features["logging_disabled_count"] += 1
        if any(token in key for token in _SENSITIVE_KEY_TOKENS):
            if _is_disabled(value):
                features["sensitive_boolean_false_count"] += 1
            elif _is_enabled(value):
                features["sensitive_boolean_true_count"] += 1
            features["weak_security_literal_count"] += sum(
                item in _WEAK_SECURITY_LITERALS for item in _strings(value)
            )

    features["public_ssh_ingress_count"] = _count_public_ssh(parsed_documents)
    return features


def _resource_types(document: Mapping[str, Any]) -> list[str]:
    result: list[str] = []
    blocks = document.get("resource", [])
    if isinstance(blocks, Mapping):
        blocks = [blocks]
    if not isinstance(blocks, list):
        return result
    for block in blocks:
        if not isinstance(block, Mapping):
            continue
        result.extend(str(resource_type).lower() for resource_type in block)
    return result


def expand_dynamic_ingress(
    document: Mapping[str, Any], attributes: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], bool]:
    """Resolve simple Terraform dynamic ingress blocks backed by literal locals."""
    locals_values: dict[str, Any] = {}
    local_blocks = document.get("locals", [])
    if isinstance(local_blocks, Mapping):
        local_blocks = [local_blocks]
    for local_block in local_blocks if isinstance(local_blocks, list) else []:
        if isinstance(local_block, Mapping):
            locals_values.update(local_block)

    dynamic_blocks = attributes.get("dynamic", [])
    if isinstance(dynamic_blocks, Mapping):
        dynamic_blocks = [dynamic_blocks]
    expanded: list[dict[str, Any]] = []
    unresolved = False
    for dynamic_block in dynamic_blocks if isinstance(dynamic_blocks, list) else []:
        if not isinstance(dynamic_block, Mapping) or "ingress" not in dynamic_block:
            continue
        dynamic = dynamic_block["ingress"]
        if not isinstance(dynamic, Mapping):
            unresolved = True
            continue
        iterator_name = str(dynamic.get("iterator", "ingress")).strip('"')
        values = _resolve_static_value(dynamic.get("for_each"), locals_values, iterator_name, None)
        if values is None:
            unresolved = True
            continue
        if not isinstance(values, list):
            values = [values]
        content_blocks = dynamic.get("content", [])
        if isinstance(content_blocks, Mapping):
            content_blocks = [content_blocks]
        for item in values:
            for content in content_blocks if isinstance(content_blocks, list) else []:
                if not isinstance(content, Mapping):
                    continue
                result = dict(content)
                cidrs = result.get("cidr_blocks")
                if cidrs is not None:
                    resolved_cidrs = _resolve_static_value(cidrs, locals_values, iterator_name, item)
                    if resolved_cidrs is None:
                        unresolved = True
                        continue
                    result["cidr_blocks"] = resolved_cidrs if isinstance(resolved_cidrs, list) else [resolved_cidrs]
                expanded.append(result)
    return expanded, unresolved


def _resolve_static_value(value: Any, locals_values: Mapping[str, Any], iterator_name: str, iterator_value: Any) -> Any:
    if isinstance(value, list):
        resolved = [_resolve_static_value(item, locals_values, iterator_name, iterator_value) for item in value]
        return None if any(item is None for item in resolved) else resolved
    if not isinstance(value, str):
        return value
    normalized = value.strip('"')
    local_reference = re.fullmatch(r"\$\{\s*local\.([A-Za-z0-9_-]+)\s*\}", normalized)
    if local_reference:
        return locals_values.get(local_reference.group(1))
    iterator_reference = re.fullmatch(rf"\$\{{\s*{re.escape(iterator_name)}\.value\s*\}}", normalized)
    if iterator_reference:
        return iterator_value
    return value if not normalized.startswith("${") else None


def _walk(value: Any):
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized_key = str(key).lower()
            yield normalized_key, child
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip('"').lower()]
    if isinstance(value, list):
        return [item for child in value for item in _strings(child)]
    return []


def _wildcard_count(value: Any) -> int:
    return sum(item == "*" for item in _strings(value))


def _is_disabled(value: Any) -> bool:
    return value is False or value == 0 or value == "false"


def _is_enabled(value: Any) -> bool:
    return value is True or value == 1 or value == "true"


def _count_public_ssh(documents: Iterable[Mapping[str, Any]]) -> int:
    count = 0
    for document in documents:
        blocks = document.get("resource", [])
        if isinstance(blocks, Mapping):
            blocks = [blocks]
        for block in blocks if isinstance(blocks, list) else []:
            if not isinstance(block, Mapping):
                continue
            for resource_type, instances in block.items():
                if not isinstance(instances, Mapping):
                    continue
                for attributes in instances.values():
                    if not isinstance(attributes, Mapping):
                        continue
                    ingress_blocks = attributes.get("ingress", [])
                    dynamic_ingress, _ = expand_dynamic_ingress(document, attributes)
                    if isinstance(ingress_blocks, Mapping):
                        ingress_blocks = [ingress_blocks]
                    ingress_blocks = [
                        *(ingress_blocks if isinstance(ingress_blocks, list) else []),
                        *dynamic_ingress,
                    ]
                    if str(resource_type) == "aws_security_group_rule":
                        ingress_blocks = [attributes] if str(attributes.get("type", "")).strip('"') == "ingress" else []
                    for ingress in ingress_blocks if isinstance(ingress_blocks, list) else []:
                        if not isinstance(ingress, Mapping):
                            continue
                        try:
                            from_port = int(str(ingress.get("from_port", "")).strip('"'))
                            to_port = int(str(ingress.get("to_port", "")).strip('"'))
                        except (TypeError, ValueError):
                            continue
                        public_ranges = _strings(ingress.get("cidr_blocks", [])) + _strings(ingress.get("ipv6_cidr_blocks", []))
                        if from_port <= 22 <= to_port and any(item in {"0.0.0.0/0", "::/0"} for item in public_ranges):
                            count += 1
    return count
