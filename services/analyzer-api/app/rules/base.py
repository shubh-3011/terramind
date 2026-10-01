"""Shared contract for TerraMind's extensible deterministic AWS rule set.

Rules are pure functions over an already-parsed HCL document and its source
text.  They never execute Terraform, never touch the network, and never mutate
the workspace.  Keeping the contract here lets rule authors add checks in
isolated modules without editing the analyzer request handlers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence

SEVERITIES = ("error", "warning", "information")
DIMENSIONS = ("security", "reliability", "maintainability", "cost")

#: Bump when evidence semantics change so reports stay reproducible.
CRITERIA_VERSION = "aws-rubric-v2"


@dataclass(frozen=True)
class RuleHit:
    """A single match produced by a rule.

    ``main.py`` converts hits into navigable :class:`Finding` objects.  A hit
    may override the rule's default severity or recommendation when a specific
    instance is more (or less) severe than the rule's baseline.
    """

    message: str
    line: int | None = None
    recommendation: str | None = None
    severity: str | None = None


@dataclass(frozen=True)
class Rule:
    """Metadata plus the pure check function for one deterministic rule."""

    rule_id: str
    title: str
    severity: str
    service: str
    dimension: str
    recommendation: str
    check: Callable[[Mapping[str, Any], str, "RuleHelpers"], Sequence[RuleHit]]
    criteria_version: str = CRITERIA_VERSION

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"invalid severity for {self.rule_id}: {self.severity}")
        if self.dimension not in DIMENSIONS:
            raise ValueError(f"invalid dimension for {self.rule_id}: {self.dimension}")


class RuleHelpers:
    """Small, reusable helpers so rule modules stay declarative.

    Instances are cheap and stateless apart from the parsed document/source.
    They intentionally avoid any I/O and any dependency on ``app.main`` so the
    rules package can be imported on its own (for tests and future callers).
    """

    def __init__(self, document: Mapping[str, Any], source: str) -> None:
        self.document = document
        self.source = source
        self._lines = source.splitlines()

    # -- resource traversal -------------------------------------------------

    def resources(self) -> Iterable[tuple[str, dict[str, Any], str]]:
        """Yield ``(resource_type, attributes, label)`` for every resource block."""
        blocks = self.document.get("resource", [])
        if isinstance(blocks, Mapping):
            blocks = [blocks]
        for block in blocks if isinstance(blocks, list) else []:
            if not isinstance(block, Mapping):
                continue
            for resource_type, instances in block.items():
                if not isinstance(instances, Mapping):
                    continue
                for label, attributes in instances.items():
                    if isinstance(attributes, Mapping):
                        yield str(resource_type), attributes, str(label)

    def resources_of(self, *resource_types: str) -> Iterable[tuple[str, dict[str, Any], str]]:
        """Yield only resources whose type is in ``resource_types``."""
        wanted = set(resource_types)
        for resource_type, attributes, label in self.resources():
            if resource_type in wanted:
                yield resource_type, attributes, label

    @staticmethod
    def blocks(attributes: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
        """Return nested blocks under ``key`` as a flat list of mappings."""
        value = attributes.get(key)
        if isinstance(value, Mapping):
            return [value]
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)]
        return []

    # -- value helpers ------------------------------------------------------

    @staticmethod
    def strings(value: Any) -> list[str]:
        """Recursively collect scalar strings, quotes stripped, lower-cased."""
        if isinstance(value, str):
            return [value.strip('"').lower()]
        if isinstance(value, bool) or isinstance(value, (int, float)):
            return []
        if isinstance(value, Mapping):
            return [item for child in value.values() for item in RuleHelpers.strings(child)]
        if isinstance(value, list):
            return [item for child in value for item in RuleHelpers.strings(child)]
        return []

    @classmethod
    def contains_public_cidr(cls, value: Any) -> bool:
        return any(item in {"0.0.0.0/0", "::/0"} for item in cls.strings(value))

    @staticmethod
    def is_disabled(value: Any) -> bool:
        return value is False or value == 0 or value == "false"

    @staticmethod
    def is_enabled(value: Any) -> bool:
        return value is True or value == 1 or value == "true"

    @staticmethod
    def attribute(attributes: Mapping[str, Any], *names: str) -> Any:
        """Return the first present, non-``None`` attribute among ``names``."""
        for name in names:
            if name in attributes and attributes[name] is not None:
                return attributes[name]
        return None

    @staticmethod
    def port_span(attributes: Mapping[str, Any]) -> tuple[int, int] | None:
        """Return ``(from_port, to_port)`` when both are literal integers."""
        try:
            return (
                int(str(attributes.get("from_port", "")).strip('"')),
                int(str(attributes.get("to_port", "")).strip('"')),
            )
        except (TypeError, ValueError):
            return None

    # -- line location ------------------------------------------------------

    def line_matching(self, pattern: str | re.Pattern[str], flags: int = re.IGNORECASE) -> int | None:
        """First 1-based line matching ``pattern``, or ``None``."""
        compiled = re.compile(pattern, flags) if isinstance(pattern, str) else pattern
        for number, line in enumerate(self._lines, start=1):
            if compiled.search(line):
                return number
        return None

    def line_of(self, *needles: str) -> int | None:
        """First line containing any literal ``needles`` (case-insensitive)."""
        lowered = [needle.lower() for needle in needles]
        for number, line in enumerate(self._lines, start=1):
            candidate = line.lower()
            if any(needle in candidate for needle in lowered):
                return number
        return None
