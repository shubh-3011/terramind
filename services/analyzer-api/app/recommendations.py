"""Prioritized, grouped repair plan derived from deterministic findings.

The analyzer emits a flat list of findings.  A flat list makes it hard to see
which problem to fix first, especially when one rule fires many times.  This
module folds findings into one entry per ``rule_id`` and ranks those groups by
severity, then by how often they occur, then by ``rule_id`` for stability.

The module is deliberately dependency-light and fully defensive:

* findings may be pydantic objects or plain mappings;
* missing/``None`` fields never raise;
* unknown severities degrade to ``information``;
* arbitrary text is coerced to ``str`` so the result is always JSON-safe.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

#: Number of groups returned when no usable ``limit`` is supplied.
DEFAULT_LIMIT = 20

#: Caps for the per-group lists so one noisy rule cannot bloat the payload.
MAX_FILES = 10
MAX_EVIDENCE_IDS = 10

#: Fallback guidance when neither the rule nor the finding carries any.
GENERIC_RECOMMENDATION = "Review this finding and re-run analysis after changes."

#: Lower rank sorts first; only the three documented severities are ranked.
SEVERITY_RANK = {"error": 0, "warning": 1, "information": 2}
DEFAULT_SEVERITY = "information"

try:  # Rules are an optional layer; recommendations must load on their own.
    from app.rules import RULE_BY_ID as _RULE_BY_ID
except Exception:  # noqa: BLE001 - never let rule registration break reporting
    _RULE_BY_ID: Mapping[str, Any] = {}


def build_recommendations(findings: Any, limit: int = 20) -> list[dict[str, Any]]:
    """Return a ranked, de-duplicated repair plan grouped by ``rule_id``.

    Groups are ordered by severity (``error`` before ``warning`` before
    ``information``), then by number of occurrences (descending), then by
    ``rule_id`` (ascending) for deterministic output.  ``limit`` caps the number
    of returned groups; an invalid or ``None`` limit falls back to
    :data:`DEFAULT_LIMIT`.
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for finding in _iter_findings(findings):
        rule_id = _as_text(_field(finding, "rule_id", ""))
        occurrence = {
            "severity": _normalize_severity(_field(finding, "severity")),
            "message": _as_text(_field(finding, "message", "")),
            "file": _as_text(_field(finding, "file", "")),
            "recommendation": _as_text(_field(finding, "recommendation", "")),
            "id": _as_text(_field(finding, "id", "")),
        }
        groups.setdefault(rule_id, []).append(occurrence)

    ranked = sorted(
        groups.items(),
        key=lambda item: _group_sort_key(item[0], item[1]),
    )

    recommendations: list[dict[str, Any]] = []
    for priority, (rule_id, occurrences) in enumerate(ranked[: _coerce_limit(limit)], start=1):
        recommendations.append(_build_group(rule_id, occurrences, priority))
    return recommendations


def _build_group(rule_id: str, occurrences: list[dict[str, Any]], priority: int) -> dict[str, Any]:
    """Fold one rule's occurrences into a single recommendation entry."""
    rule = _RULE_BY_ID.get(rule_id) if isinstance(_RULE_BY_ID, Mapping) else None
    best = _best_occurrence(occurrences)

    if rule is not None:
        # Registered rules are authoritative for title and severity.
        severity = _normalize_severity(_field(rule, "severity", best["severity"]))
        title = _as_text(_field(rule, "title", "")) or f"Terraform rule {rule_id}"
        recommendation = (
            _as_text(_field(rule, "recommendation", ""))
            or best["recommendation"]
            or GENERIC_RECOMMENDATION
        )
    else:
        severity = best["severity"]
        title = f"Terraform rule {rule_id}"
        recommendation = best["recommendation"] or GENERIC_RECOMMENDATION

    files = sorted({occurrence["file"] for occurrence in occurrences if occurrence["file"]})
    evidence_ids: list[str] = []
    for occurrence in occurrences:
        if occurrence["id"] and occurrence["id"] not in evidence_ids:
            evidence_ids.append(occurrence["id"])

    return {
        "rule_id": rule_id,
        "title": title,
        "severity": severity,
        "count": len(occurrences),
        "priority": priority,
        "message": best["message"],
        "recommendation": recommendation,
        "files": files[:MAX_FILES],
        "evidence_ids": evidence_ids[:MAX_EVIDENCE_IDS],
    }


def _best_occurrence(occurrences: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the most severe occurrence, breaking ties by first appearance."""
    return min(
        occurrences,
        key=lambda occurrence: (SEVERITY_RANK.get(occurrence["severity"], 2),),
    )


def _group_sort_key(rule_id: str, occurrences: list[dict[str, Any]]) -> tuple[int, int, str]:
    severity = _best_occurrence(occurrences)["severity"] if occurrences else DEFAULT_SEVERITY
    if isinstance(_RULE_BY_ID, Mapping) and rule_id in _RULE_BY_ID:
        severity = _normalize_severity(_field(_RULE_BY_ID[rule_id], "severity", severity))
    return (SEVERITY_RANK.get(severity, 2), -len(occurrences), rule_id)


def _iter_findings(findings: Any):
    if findings is None or isinstance(findings, (str, bytes, Mapping)):
        return
    try:
        iterator = iter(findings)
    except TypeError:
        return
    for finding in iterator:
        if finding is not None:
            yield finding


def _field(source: Any, name: str, default: Any = None) -> Any:
    """Read ``name`` from a mapping or an object without ever raising."""
    if isinstance(source, Mapping):
        value = source.get(name, default)
    else:
        value = getattr(source, name, default)
    return default if value is None else value


def _as_text(value: Any, default: str = "") -> str:
    """Coerce arbitrary (possibly attacker-controlled) values to a plain string."""
    if isinstance(value, str):
        return value
    if value is None:
        return default
    return str(value)


def _normalize_severity(value: Any) -> str:
    text = _as_text(value).strip().lower()
    return text if text in SEVERITY_RANK else DEFAULT_SEVERITY


def _coerce_limit(limit: Any) -> int:
    """Return a usable non-negative limit, falling back to ``DEFAULT_LIMIT``."""
    if limit is None or isinstance(limit, bool):
        return DEFAULT_LIMIT
    try:
        value = int(limit)
    except (TypeError, ValueError, OverflowError):
        return DEFAULT_LIMIT
    return value if value >= 0 else DEFAULT_LIMIT


__all__ = ["DEFAULT_LIMIT", "GENERIC_RECOMMENDATION", "build_recommendations"]
