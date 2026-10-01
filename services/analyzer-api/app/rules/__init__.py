"""Registry for TerraMind's extensible deterministic AWS rules.

Each module in this package exports ``RULES: list[Rule]``.  Add the module to
``_MODULES`` below to register it.  Rules are evaluated defensively: a single
failing rule is skipped rather than failing the whole analysis request.
"""

from __future__ import annotations

from typing import Any, Mapping

from app.rules.base import CRITERIA_VERSION, Rule, RuleHelpers, RuleHit
from app.rules import compute, database, identity, network, observability, storage

_MODULES = (network, storage, identity, database, compute, observability)

ALL_RULES: list[Rule] = [rule for module in _MODULES for rule in module.RULES]
RULE_BY_ID: dict[str, Rule] = {rule.rule_id: rule for rule in ALL_RULES}

#: rule_id -> dimension, used by the ratings module to attribute evidence.
RULE_DIMENSIONS: dict[str, str] = {rule.rule_id: rule.dimension for rule in ALL_RULES}
#: rule_id -> service, used for per-service summaries.
RULE_SERVICES: dict[str, str] = {rule.rule_id: rule.service for rule in ALL_RULES}


def evaluate_rules(
    document: Mapping[str, Any], source: str, file: str,
) -> list[tuple[Rule, RuleHit]]:
    """Run every registered rule against one parsed document.

    Returns pairs of ``(rule, hit)`` so callers can build findings with the
    rule's metadata.  Exceptions from an individual rule are swallowed so a
    buggy check can never break an analysis request.
    """
    helpers = RuleHelpers(document, source)
    results: list[tuple[Rule, RuleHit]] = []
    for rule in ALL_RULES:
        try:
            hits = rule.check(document, file, helpers)
        except Exception:  # noqa: BLE001 - defensive isolation of third-party parsers
            continue
        for hit in hits or ():
            if isinstance(hit, RuleHit):
                results.append((rule, hit))
    return results


__all__ = [
    "ALL_RULES",
    "CRITERIA_VERSION",
    "RULE_BY_ID",
    "RULE_DIMENSIONS",
    "RULE_SERVICES",
    "Rule",
    "RuleHelpers",
    "RuleHit",
    "evaluate_rules",
]
