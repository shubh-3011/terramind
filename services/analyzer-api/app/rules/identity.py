"""Identity and access rules (IAM, KMS, secrets).

Owner: identity subagent.  Export ``RULES: list[Rule]``.

Every check is a pure function of the parsed document and its source text and
only reports explicitly evidenced attributes.  IAM policy documents authored
with ``data "aws_iam_policy_document"`` are inspected alongside ``resource``
blocks, so the traversal below intentionally covers both kinds.
"""

from __future__ import annotations

import re
from typing import Any, Iterator, Mapping

from app.rules.base import Rule, RuleHelpers, RuleHit

#: Matches a wildcard principal inside a JSON policy string, e.g.
#: ``"Principal": "*"`` or ``"Principal": {"AWS": "*"}``.
_WILDCARD_PRINCIPAL = re.compile(r'principal.{0,40}?\*', re.IGNORECASE | re.DOTALL)

#: Keys that express deny-by-exception instead of an explicit allow list.
_NEGATIVE_SCOPE_KEYS = {"not_action", "not_actions", "not_resource", "not_resources"}

#: Password-policy flags that should stay enabled on an AWS account.
_REQUIRED_PASSWORD_FLAGS = (
    "require_symbols",
    "require_numbers",
    "require_uppercase_characters",
    "require_lowercase_characters",
)


def _document_blocks(helpers: RuleHelpers) -> Iterator[tuple[str, Mapping[str, Any], str]]:
    """Yield ``(type, attributes, label)`` for ``resource`` and ``data`` blocks."""
    for kind in ("resource", "data"):
        blocks = helpers.document.get(kind, [])
        if isinstance(blocks, Mapping):
            blocks = [blocks]
        for block in blocks if isinstance(blocks, list) else []:
            if not isinstance(block, Mapping):
                continue
            for block_type, instances in block.items():
                if not isinstance(instances, Mapping):
                    continue
                for label, attributes in instances.items():
                    if isinstance(attributes, Mapping):
                        yield str(block_type), attributes, str(label)


def _walk_keys(value: Any) -> Iterator[str]:
    """Yield lower-cased mapping keys found anywhere under ``value``."""
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield str(key).lower()
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def _policy_strings(attributes: Mapping[str, Any]) -> Iterator[str]:
    """Yield literal policy strings from the common IAM/POLICY attributes."""
    for key in ("policy", "assume_role_policy", "policy_json", "policy_document"):
        value = attributes.get(key)
        if isinstance(value, str):
            yield value


def _check_not_action_not_resource(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers
) -> list[RuleHit]:
    """TM-IAM-003: a policy scopes access with NotAction or NotResource."""
    hits: list[RuleHit] = []
    for _type, attributes, label in _document_blocks(helpers):
        found = sorted(_NEGATIVE_SCOPE_KEYS.intersection(_walk_keys(attributes)))
        if found:
            hits.append(RuleHit(
                message=f"IAM policy on '{label}' scopes permissions with {', '.join(found)}.",
                line=helpers.line_of("not_action", "not_resource"),
                recommendation="Prefer explicit allow lists; deny-by-exception is hard to review and easy to widen.",
            ))
    return hits


def _check_wildcard_principal(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers
) -> list[RuleHit]:
    """TM-IAM-004: a resource-based policy trusts the wildcard principal ``*``."""
    hits: list[RuleHit] = []
    for block_type, attributes, label in _document_blocks(helpers):
        if block_type == "aws_iam_policy_document":
            if any(
                "*" in helpers.strings(principal.get("identifiers"))
                for statement in helpers.blocks(attributes, "statement")
                for principal in helpers.blocks(statement, "principals")
            ):
                hits.append(RuleHit(
                    message=f"IAM policy document '{label}' grants access to the wildcard principal (*).",
                    line=helpers.line_of("identifiers", "principals", "principal"),
                    recommendation="Scope principals to specific account, role, or service ARNs instead of *.",
                ))
        elif block_type in {"aws_iam_policy", "aws_iam_group_policy", "aws_iam_user_policy"}:
            if any(_WILDCARD_PRINCIPAL.search(value) for value in _policy_strings(attributes)):
                hits.append(RuleHit(
                    message=f"IAM policy '{label}' grants access to the wildcard principal (*).",
                    line=helpers.line_of("policy"),
                    recommendation="Scope principals to specific account, role, or service ARNs instead of *.",
                ))
    return hits


def _check_access_key(document: Mapping[str, Any], file: str, helpers: RuleHelpers) -> list[RuleHit]:
    """TM-IAM-005: a long-lived IAM access key is created."""
    hits: list[RuleHit] = []
    for _type, _attributes, label in helpers.resources_of("aws_iam_access_key"):
        hits.append(RuleHit(
            message=f"IAM access key '{label}' creates a long-lived programmatic credential.",
            line=helpers.line_of("aws_iam_access_key", label),
            recommendation="Prefer short-lived credentials from IAM roles, SSO, or federation; rotate and remove unused keys.",
        ))
    return hits


def _check_weak_password_policy(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers
) -> list[RuleHit]:
    """TM-IAM-006: the account password policy is explicitly weak."""
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of("aws_iam_account_password_policy"):
        issues: list[str] = []
        minimum = attributes.get("minimum_password_length")
        if isinstance(minimum, (int, float)) and not isinstance(minimum, bool) and minimum < 14:
            issues.append(f"minimum length {int(minimum)} (<14)")
        if attributes.get("password_reuse_prevention") == 0:
            issues.append("no password reuse prevention")
        for flag in _REQUIRED_PASSWORD_FLAGS:
            if helpers.is_disabled(attributes.get(flag)):
                issues.append(f"{flag} disabled")
        if issues:
            hits.append(RuleHit(
                message=f"Account password policy '{label}' is weak: {', '.join(issues)}.",
                line=helpers.line_of("minimum_password_length", "password_reuse_prevention", "require_"),
                recommendation="Require at least 14 characters, prevent reuse, and enable all complexity flags.",
            ))
    return hits


def _check_kms_rotation(document: Mapping[str, Any], file: str, helpers: RuleHelpers) -> list[RuleHit]:
    """TM-IAM-007: a symmetric KMS key does not enable annual rotation.

    AWS (and the provider) default rotation to disabled, which is genuinely
    insecure for customer-managed symmetric keys, so an absent flag is reported.
    Asymmetric and HMAC keys do not support rotation and are skipped.
    """
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of("aws_kms_key"):
        usage = str(attributes.get("key_usage", "")).strip('"').lower()
        key_spec = str(attributes.get("key_spec", "")).strip('"').lower()
        if usage and usage != "encrypt_decrypt":
            continue
        # Rotation is only supported for symmetric keys (SYMMETRIC_DEFAULT);
        # RSA/ECC/HMAC specs are skipped.
        if key_spec and not key_spec.startswith("symmetric"):
            continue
        if helpers.is_enabled(attributes.get("enable_key_rotation")):
            continue
        hits.append(RuleHit(
            message=f"KMS key '{label}' does not enable key rotation.",
            line=helpers.line_matching(r"enable_key_rotation"),
            recommendation="Set enable_key_rotation = true on customer-managed symmetric keys.",
        ))
    return hits


def _check_role_trust_wildcard(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers
) -> list[RuleHit]:
    """TM-IAM-008: an IAM role trust policy allows any principal to assume it."""
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of("aws_iam_role"):
        if any(_WILDCARD_PRINCIPAL.search(value) for value in _policy_strings(attributes)):
            hits.append(RuleHit(
                message=f"IAM role '{label}' trust policy lets any principal (*) assume the role.",
                line=helpers.line_of("assume_role_policy"),
                recommendation="Restrict the trust policy Principal to specific accounts, roles, or AWS services.",
            ))
    return hits


RULES: list[Rule] = [
    Rule(
        rule_id="TM-IAM-003",
        title="IAM policy uses NotAction or NotResource",
        severity="information",
        service="iam",
        dimension="security",
        recommendation="Prefer explicit allow lists; deny-by-exception is hard to review and easy to widen.",
        check=_check_not_action_not_resource,
    ),
    Rule(
        rule_id="TM-IAM-004",
        title="IAM policy trusts the wildcard principal",
        severity="error",
        service="iam",
        dimension="security",
        recommendation="Scope principals to specific account, role, or service ARNs instead of *.",
        check=_check_wildcard_principal,
    ),
    Rule(
        rule_id="TM-IAM-005",
        title="Long-lived IAM access key",
        severity="warning",
        service="iam",
        dimension="security",
        recommendation="Prefer short-lived credentials from IAM roles, SSO, or federation; rotate and remove unused keys.",
        check=_check_access_key,
    ),
    Rule(
        rule_id="TM-IAM-006",
        title="Weak IAM account password policy",
        severity="warning",
        service="iam",
        dimension="security",
        recommendation="Require at least 14 characters, prevent reuse, and enable all complexity flags.",
        check=_check_weak_password_policy,
    ),
    Rule(
        rule_id="TM-IAM-007",
        title="KMS key rotation is not enabled",
        severity="warning",
        service="iam",
        dimension="security",
        recommendation="Set enable_key_rotation = true on customer-managed symmetric keys.",
        check=_check_kms_rotation,
    ),
    Rule(
        rule_id="TM-IAM-008",
        title="IAM role trust policy allows any principal",
        severity="error",
        service="iam",
        dimension="security",
        recommendation="Restrict the trust policy Principal to specific accounts, roles, or AWS services.",
        check=_check_role_trust_wildcard,
    ),
]
