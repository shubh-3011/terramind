"""Provider-agnostic Terraform project-hygiene rules.

These checks apply to any Terraform project (AWS, Azure, GCP, or on-prem)
because they reason about core Terraform constructs - ``terraform`` blocks,
provider pins, variables, outputs, and modules - rather than cloud resources.
They are the "general Terraform" half of the analyzer, paired with the
cloud-specific modules.

Every check is a pure function over one parsed document plus its source text.
The analyzer invokes rules per file, so "absence" checks are deliberately
scoped to the constructs a single document actually declares: a resource-only
``.tf`` fragment is not reported for a missing ``terraform`` block or backend.
That keeps partial configurations and single-resource examples free of noise
while still catching a root configuration that forgot to pin its tooling.
"""

from __future__ import annotations

import re
from typing import Any, Iterator, Mapping

from app.rules.base import Rule, RuleHelpers, RuleHit

#: Provider attributes that select where infrastructure lives.  A literal here
#: means the same provider block cannot be reused across environments.
_LOCATION_KEYS = ("region", "location", "project", "zone")

#: ``namespace/name/provider`` (optionally ``//submodule``) is a Terraform
#: Registry address.  Local and VCS sources already carry a version in the ref.
_REGISTRY_SOURCE = re.compile(r"^[\w.-]+/[\w.-]+/[\w.-]+$")

#: Version constraints that do not meaningfully constrain the CLI.
_UNCONSTRAINED = re.compile(r"^(?:\*|(?:>=?|~>)\s*0(?:\.0)*|0\.0\.0)$")


# -- shape helpers ----------------------------------------------------------


def _as_mappings(value: Any) -> list[Mapping[str, Any]]:
    """Normalize an HCL block that may be a single mapping or a list of them."""
    if isinstance(value, Mapping):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, Mapping)]
    return []


def _named_blocks(
    document: Mapping[str, Any], key: str
) -> Iterator[tuple[str, Mapping[str, Any]]]:
    """Yield ``(name, attributes)`` for variable/output/module/provider blocks.

    These top-level blocks parse as a list of single-key dicts mapping the
    block label to its attributes (for example ``{"aws": {...}}``).
    """
    for block in _as_mappings(document.get(key)):
        for name, attributes in block.items():
            if isinstance(attributes, Mapping):
                yield str(name), attributes


def _terraform_blocks(document: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return _as_mappings(document.get("terraform"))


def _scalar_text(value: Any) -> str | None:
    """Return a trimmed scalar as text, or ``None`` for absent/non-scalars."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip().strip('"').strip()
        return text or None
    if isinstance(value, (int, float)):
        return str(value)
    return None


def _literal(value: Any) -> str | None:
    """Return a bare literal string, or ``None`` when absent/interpolated."""
    text = _scalar_text(value)
    if text is None or "${" in text or "{{" in text:
        return None
    return text


def _is_registry_source(source: str) -> bool:
    text = source.strip().strip('"').strip()
    if not text:
        return False
    lowered = text.lower()
    if lowered.startswith(
        ("./", "../", "git::", "hg::", "s3::", "gcs::", "github.com/", "bitbucket.org/")
    ):
        return False
    base = text.split("//", 1)[0]
    if "://" in base:
        return False
    return bool(_REGISTRY_SOURCE.match(base))


# -- checks -----------------------------------------------------------------


def _check_required_version(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers
) -> list[RuleHit]:
    """TM-GEN-001: the CLI version is never pinned.

    Only reported when the document actually configures Terraform (it declares
    a ``terraform`` or ``provider`` block) but no ``required_version`` appears.
    A resource-only fragment or a variable/output-only include is not flagged,
    which keeps partial ``.tf`` files from producing noise.
    """
    blocks = _terraform_blocks(document)
    if not blocks and not any(True for _ in _named_blocks(document, "provider")):
        return []
    if any(_scalar_text(block.get("required_version")) for block in blocks):
        return []
    return [RuleHit(
        message="No required_version pins the Terraform CLI version for this configuration.",
        line=helpers.line_matching(r"\bterraform\s*\{") or helpers.line_of("provider"),
        recommendation='Declare terraform { required_version = ">= 1.6.0" } so every user shares a supported CLI.',
    )]


def _check_provider_versions(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers
) -> list[RuleHit]:
    """TM-GEN-002: a provider is used without any version constraint.

    Covers both ``required_providers`` entries that omit ``version`` and
    ``provider`` blocks whose provider name is never pinned in this file.
    Emits one hit per unpinned provider.
    """
    pinned: set[str] = set()
    declared: dict[str, bool] = {}
    for terraform_block in _terraform_blocks(document):
        for required in _as_mappings(terraform_block.get("required_providers")):
            for raw_name, config in required.items():
                provider = str(raw_name)
                if isinstance(config, Mapping):
                    is_pinned = bool(_scalar_text(config.get("version")))
                else:
                    # Legacy ``aws = "~> 5.0"`` form pins in a single string.
                    is_pinned = bool(_scalar_text(config))
                if is_pinned:
                    pinned.add(provider)
                declared.setdefault(provider, is_pinned)

    hits: list[RuleHit] = []
    reported: set[str] = set()
    for provider, is_pinned in declared.items():
        if is_pinned:
            continue
        reported.add(provider)
        hits.append(RuleHit(
            message=f"Provider '{provider}' is declared in required_providers without a version constraint.",
            line=helpers.line_matching(rf"^\s*{re.escape(provider)}\s*=\s*\{{")
            or helpers.line_of("required_providers"),
            recommendation=f'Add version = "~> X.Y" to the {provider} entry in required_providers.',
        ))
    for provider, _attributes in _named_blocks(document, "provider"):
        if provider in pinned or provider in reported:
            continue
        reported.add(provider)
        hits.append(RuleHit(
            message=f"Provider block '{provider}' has no version constraint anywhere in this configuration.",
            line=helpers.line_matching(rf'provider\s+"{re.escape(provider)}"'),
            recommendation=f'Pin {provider} in terraform {{ required_providers {provider} = {{ version = "~> X.Y" }} }}.',
        ))
    return hits


def _check_remote_state(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers
) -> list[RuleHit]:
    """TM-GEN-003: module-based configuration with no backend or cloud block.

    Deliberately requires a ``module`` block: state sharing matters most when
    composing reusable modules, and a standalone resource file is a common
    legitimate local-state layout.  A ``backend`` or ``cloud`` block anywhere
    in the document suppresses the check.
    """
    for terraform_block in _terraform_blocks(document):
        if "backend" in terraform_block or "cloud" in terraform_block:
            return []
    if not any(True for _ in _named_blocks(document, "module")):
        return []
    return [RuleHit(
        message="No backend or cloud block configures remote state for this module-based configuration.",
        line=helpers.line_of("module"),
        recommendation="Add a backend (for example S3 with DynamoDB locking) or a cloud block so state is shared and locked.",
    )]


def _check_variable_type(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers
) -> list[RuleHit]:
    """TM-GEN-004: a variable declares no type."""
    hits: list[RuleHit] = []
    for name, attributes in _named_blocks(document, "variable"):
        if _scalar_text(attributes.get("type")):
            continue
        hits.append(RuleHit(
            message=f"Variable '{name}' does not declare a type.",
            line=helpers.line_matching(rf'variable\s+"{re.escape(name)}"'),
            recommendation=f'Add an explicit type to variable "{name}" (for example type = string) to validate inputs.',
        ))
    return hits


def _check_variable_description(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers
) -> list[RuleHit]:
    """TM-GEN-005: a variable declares no description."""
    hits: list[RuleHit] = []
    for name, attributes in _named_blocks(document, "variable"):
        if _scalar_text(attributes.get("description")):
            continue
        hits.append(RuleHit(
            message=f"Variable '{name}' has no description.",
            line=helpers.line_matching(rf'variable\s+"{re.escape(name)}"'),
            recommendation=f'Describe variable "{name}" so callers understand its expected input.',
        ))
    return hits


def _check_output_description(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers
) -> list[RuleHit]:
    """TM-GEN-006: an output declares no description."""
    hits: list[RuleHit] = []
    for name, attributes in _named_blocks(document, "output"):
        if _scalar_text(attributes.get("description")):
            continue
        hits.append(RuleHit(
            message=f"Output '{name}' has no description.",
            line=helpers.line_matching(rf'output\s+"{re.escape(name)}"'),
            recommendation=f'Describe output "{name}" so its value and consumers are documented.',
        ))
    return hits


def _check_module_version(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers
) -> list[RuleHit]:
    """TM-GEN-007: a registry module source with no version constraint."""
    hits: list[RuleHit] = []
    for name, attributes in _named_blocks(document, "module"):
        source = _scalar_text(attributes.get("source"))
        if not source or not _is_registry_source(source):
            continue
        if _scalar_text(attributes.get("version")):
            continue
        hits.append(RuleHit(
            message=f"Module '{name}' uses registry source '{source[:60]}' without a version constraint.",
            line=helpers.line_of("source"),
            recommendation=f'Pin module "{name}" with version = "~> X.Y" so upgrades to the registry source are deliberate.',
        ))
    return hits


def _check_hardcoded_location(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers
) -> list[RuleHit]:
    """TM-GEN-008: a provider block hardcodes a literal location.

    Only fires on a bare literal (no ``${...}`` interpolation); a value sourced
    from a variable, local, or data reference is left alone.
    """
    hits: list[RuleHit] = []
    for name, attributes in _named_blocks(document, "provider"):
        for key in _LOCATION_KEYS:
            literal = _literal(attributes.get(key))
            if literal is None:
                continue
            hits.append(RuleHit(
                message=f"Provider '{name}' hardcodes {key} = \"{literal[:40]}\"; use a variable instead.",
                line=helpers.line_matching(rf"^\s*{re.escape(key)}\s*="),
                recommendation=f"Set {key} from a variable (for example var.{key}) so each environment can differ.",
            ))
    return hits


def _check_unconstrained_version(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers
) -> list[RuleHit]:
    """TM-GEN-009: required_version is present but does not constrain anything."""
    hits: list[RuleHit] = []
    for terraform_block in _terraform_blocks(document):
        version = _scalar_text(terraform_block.get("required_version"))
        if version is None or not _UNCONSTRAINED.match(version):
            continue
        hits.append(RuleHit(
            message=f"required_version '{version}' does not meaningfully constrain the Terraform CLI.",
            line=helpers.line_matching(r"\brequired_version\b"),
            recommendation='Use a bounded range, for example ">= 1.6.0, < 2.0.0".',
        ))
    return hits


RULES: list[Rule] = [
    Rule(
        rule_id="TM-GEN-001",
        title="Terraform core version is not pinned",
        severity="warning",
        service="general",
        dimension="maintainability",
        recommendation='Declare terraform { required_version = ">= 1.6.0" } so every user shares a supported CLI.',
        check=_check_required_version,
    ),
    Rule(
        rule_id="TM-GEN-002",
        title="Provider version is not pinned",
        severity="warning",
        service="general",
        dimension="maintainability",
        recommendation='Pin each provider with version = "~> X.Y" in required_providers.',
        check=_check_provider_versions,
    ),
    Rule(
        rule_id="TM-GEN-003",
        title="Remote state backend is not configured",
        severity="information",
        service="general",
        dimension="maintainability",
        recommendation="Configure a backend or cloud block so state is shared and locked across the team.",
        check=_check_remote_state,
    ),
    Rule(
        rule_id="TM-GEN-004",
        title="Variable has no type",
        severity="information",
        service="general",
        dimension="maintainability",
        recommendation="Give every variable an explicit type so inputs are validated before apply.",
        check=_check_variable_type,
    ),
    Rule(
        rule_id="TM-GEN-005",
        title="Variable has no description",
        severity="information",
        service="general",
        dimension="maintainability",
        recommendation="Describe every variable so callers understand the expected value.",
        check=_check_variable_description,
    ),
    Rule(
        rule_id="TM-GEN-006",
        title="Output has no description",
        severity="information",
        service="general",
        dimension="maintainability",
        recommendation="Describe every output so its value and consumers are documented.",
        check=_check_output_description,
    ),
    Rule(
        rule_id="TM-GEN-007",
        title="Registry module source is not version-pinned",
        severity="warning",
        service="general",
        dimension="maintainability",
        recommendation='Pin registry modules with version = "~> X.Y" to control upgrades.',
        check=_check_module_version,
    ),
    Rule(
        rule_id="TM-GEN-008",
        title="Provider configuration hardcodes a location",
        severity="warning",
        service="general",
        dimension="maintainability",
        recommendation="Drive region/location/project/zone from variables instead of literal values.",
        check=_check_hardcoded_location,
    ),
    Rule(
        rule_id="TM-GEN-009",
        title="Terraform core version is unconstrained",
        severity="warning",
        service="general",
        dimension="maintainability",
        recommendation='Use a bounded required_version range such as ">= 1.6.0, < 2.0.0".',
        check=_check_unconstrained_version,
    ),
]
