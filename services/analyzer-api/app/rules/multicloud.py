"""Non-AWS cloud rules (Azure, Google Cloud) for Terraform in general.

Owner: multicloud subagent.  Export ``RULES: list[Rule]``.

Every check is a pure function of the parsed document plus its source text.
Rules fire on attributes that are literally written in HCL, except for a small
number of cases where the provider default is genuinely unsafe (Cloud SQL's
default public IPv4 address, and GKE's missing private/authorized-network
hardening); those exceptions are called out in comments next to the rule.

Service names follow the vocabulary consumed by ``app.ratings``: ``storage``,
``database``, ``compute``, ``networking`` and ``secrets``.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from app.rules.base import Rule, RuleHelpers, RuleHit

#: Ports that must not be reachable from the public internet via an admin rule.
_ADMIN_PORTS: dict[int, str] = {
    22: "SSH (22)",
    3389: "RDP (3389)",
}

#: Literal source values that mean "the whole internet" for Azure NSG rules.
_PUBLIC_SOURCES = {"*", "internet", "0.0.0.0/0", "::/0", "any"}


# -- line helpers -----------------------------------------------------------


def _resource_line(helpers: RuleHelpers, resource_type: str, label: str) -> int | None:
    """Line of a specific ``resource "<type>" "<label>"`` header, best effort."""
    pattern = rf'resource\s+"{re.escape(resource_type)}"\s+"{re.escape(label)}"'
    return helpers.line_matching(pattern) or helpers.line_of(f'"{label}"')


def _attribute_line(helpers: RuleHelpers, attribute: str) -> int | None:
    return helpers.line_matching(rf"\b{re.escape(attribute)}\b")


def _literal(value: Any) -> str:
    """Return a scalar as a quote-stripped, lower-cased literal string."""
    if isinstance(value, str):
        return value.strip().strip('"').lower()
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value).lower()
    return ""


def _is_public_source(helpers: RuleHelpers, attributes: Mapping[str, Any]) -> bool:
    """True when an NSG rule's source prefix(es) name the whole internet."""
    sources = set(helpers.strings(attributes.get("source_address_prefix")))
    sources |= set(helpers.strings(attributes.get("source_address_prefixes")))
    return bool(sources & _PUBLIC_SOURCES)


# -- port range helpers -----------------------------------------------------


def _covers_port(token: str, port: int) -> bool:
    """True when a ``"22"``/``"22-30"``/``"*"`` token includes ``port``."""
    token = token.strip().strip('"')
    if token in {"*", ""}:
        return token == "*"
    if "-" in token:
        low, _, high = token.partition("-")
        try:
            return int(low) <= port <= int(high)
        except ValueError:
            return False
    try:
        return int(token) == port
    except ValueError:
        return False


def _destination_tokens(attributes: Mapping[str, Any]) -> list[str]:
    """Collect destination port tokens from the single- and list-valued attrs."""
    tokens: list[str] = []
    single = attributes.get("destination_port_range")
    if isinstance(single, str):
        tokens.append(single)
    many = attributes.get("destination_port_ranges")
    if isinstance(many, list):
        tokens.extend(item for item in many if isinstance(item, str))
    return tokens


# -- Azure: storage ---------------------------------------------------------


def _check_az_storage_public_nested_items(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers,
) -> list[RuleHit]:
    """TM-AZ-STOR-001: an Azure storage account allows nested public items."""
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of("azurerm_storage_account"):
        if not helpers.is_enabled(attributes.get("allow_nested_items_to_be_public")):
            continue
        hits.append(RuleHit(
            message=f"Storage account '{label}' sets allow_nested_items_to_be_public = true.",
            line=_attribute_line(helpers, "allow_nested_items_to_be_public"),
            recommendation="Set allow_nested_items_to_be_public = false so containers and blobs cannot be made public.",
        ))
    return hits


def _check_az_storage_min_tls(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers,
) -> list[RuleHit]:
    """TM-AZ-STOR-002: an Azure storage account allows TLS below 1.2.

    Only fires on an explicit literal below ``TLS1_2``; a variable reference is
    left alone because its value cannot be known statically.
    """
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of("azurerm_storage_account"):
        tls = _literal(attributes.get("min_tls_version"))
        if tls not in {"tls1_0", "tls1_1"}:
            continue
        hits.append(RuleHit(
            message=f"Storage account '{label}' sets min_tls_version = {tls.upper()} instead of TLS1_2.",
            line=_attribute_line(helpers, "min_tls_version"),
            recommendation='Set min_tls_version = "TLS1_2" to reject legacy TLS 1.0/1.1 clients.',
        ))
    return hits


def _check_az_storage_public_network(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers,
) -> list[RuleHit]:
    """TM-AZ-STOR-003: an Azure storage account is reachable from all networks."""
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of("azurerm_storage_account"):
        if not helpers.is_enabled(attributes.get("public_network_access_enabled")):
            continue
        hits.append(RuleHit(
            message=f"Storage account '{label}' sets public_network_access_enabled = true.",
            line=_attribute_line(helpers, "public_network_access_enabled"),
            recommendation="Set public_network_access_enabled = false and reach the account through a private endpoint.",
        ))
    return hits


def _check_az_storage_https(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers,
) -> list[RuleHit]:
    """TM-AZ-STOR-004: an Azure storage account permits plaintext HTTP traffic."""
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of("azurerm_storage_account"):
        https = helpers.attribute(attributes, "https_traffic_only_enabled", "enable_https_traffic_only")
        if not helpers.is_disabled(https):
            continue
        hits.append(RuleHit(
            message=f"Storage account '{label}' disables HTTPS-only traffic, allowing unencrypted HTTP.",
            line=_attribute_line(helpers, "https_traffic_only_enabled") or _attribute_line(
                helpers, "enable_https_traffic_only"
            ),
            recommendation="Set https_traffic_only_enabled = true so only HTTPS requests are accepted.",
        ))
    return hits


# -- Azure: key vault -------------------------------------------------------


def _check_az_key_vault_purge_protection(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers,
) -> list[RuleHit]:
    """TM-AZ-KV-001: a key vault can be permanently purged during its soft-delete window."""
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of("azurerm_key_vault"):
        if not helpers.is_disabled(attributes.get("purge_protection_enabled")):
            continue
        hits.append(RuleHit(
            message=f"Key vault '{label}' sets purge_protection_enabled = false.",
            line=_attribute_line(helpers, "purge_protection_enabled"),
            recommendation="Set purge_protection_enabled = true so secrets and keys cannot be purged before retention ends.",
        ))
    return hits


# -- Azure: networking ------------------------------------------------------


def _check_az_nsg_public_admin_ports(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers,
) -> list[RuleHit]:
    """TM-AZ-NET-001: an NSG rule opens SSH/RDP to the whole internet."""
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of("azurerm_network_security_rule"):
        if attributes.get("access") is not None and _literal(attributes.get("access")) != "allow":
            continue
        direction = _literal(attributes.get("direction"))
        if direction and direction != "inbound":
            continue
        if not _is_public_source(helpers, attributes):
            continue
        tokens = _destination_tokens(attributes)
        if not tokens:
            continue
        exposed = [
            name for port, name in _ADMIN_PORTS.items()
            if any(_covers_port(token, port) for token in tokens)
        ]
        if not exposed:
            continue
        hits.append(RuleHit(
            message=f"Network security rule '{label}' exposes {', '.join(exposed)} to the internet.",
            line=_attribute_line(helpers, "source_address_prefix") or _resource_line(
                helpers, "azurerm_network_security_rule", label
            ),
            recommendation="Restrict the source to trusted CIDRs and keep SSH/RDP behind a bastion or VPN.",
        ))
    return hits


# -- Azure: database --------------------------------------------------------


def _check_az_mssql_public_network(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers,
) -> list[RuleHit]:
    """TM-AZ-DB-001: an Azure SQL server is reachable from all networks."""
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of("azurerm_mssql_server"):
        if not helpers.is_enabled(attributes.get("public_network_access_enabled")):
            continue
        hits.append(RuleHit(
            message=f"Azure SQL server '{label}' sets public_network_access_enabled = true.",
            line=_attribute_line(helpers, "public_network_access_enabled"),
            recommendation="Set public_network_access_enabled = false and connect through a private endpoint.",
        ))
    return hits


# -- Google Cloud: storage --------------------------------------------------


def _check_gcp_bucket_uniform_access(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers,
) -> list[RuleHit]:
    """TM-GCP-STOR-001: GCS uniform bucket-level access is explicitly disabled."""
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of("google_storage_bucket"):
        if not helpers.is_disabled(attributes.get("uniform_bucket_level_access")):
            continue
        hits.append(RuleHit(
            message=f"Bucket '{label}' sets uniform_bucket_level_access = false, keeping per-object ACLs.",
            line=_attribute_line(helpers, "uniform_bucket_level_access"),
            recommendation="Set uniform_bucket_level_access = true and grant access only through IAM policies.",
        ))
    return hits


def _check_gcp_bucket_public_access_prevention(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers,
) -> list[RuleHit]:
    """TM-GCP-STOR-002: GCS public access prevention is not enforced.

    Only an explicit non-``enforced`` value is reported.  The provider default
    is ``inherited`` (not enforced), so absence is genuinely weak, but it is not
    treated as evidence here to keep the rule high-signal; the bucket must opt
    into a weaker value in configuration.
    """
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of("google_storage_bucket"):
        if "public_access_prevention" not in attributes:
            continue
        prevention = _literal(attributes.get("public_access_prevention"))
        if prevention == "enforced":
            continue
        hits.append(RuleHit(
            message=f"Bucket '{label}' sets public_access_prevention = \"{prevention or 'inherited'}\", not \"enforced\".",
            line=_attribute_line(helpers, "public_access_prevention"),
            recommendation='Set public_access_prevention = "enforced" to block public access even if IAM would allow it.',
        ))
    return hits


# -- Google Cloud: networking -----------------------------------------------


def _firewall_allows_admin_ports(helpers: RuleHelpers, attributes: Mapping[str, Any]) -> list[str]:
    """Admin ports exposed by a GCP firewall's ``allow`` blocks, if any."""
    exposed: set[str] = set()
    for allow in helpers.blocks(attributes, "allow"):
        protocol = _literal(allow.get("protocol"))
        if protocol not in {"tcp", "all", ""}:
            continue
        ports = allow.get("ports")
        if not isinstance(ports, list) or not ports:
            # A tcp/all rule without explicit ports opens every port.
            exposed.update(_ADMIN_PORTS.values())
            continue
        for port, name in _ADMIN_PORTS.items():
            if any(_covers_port(item, port) for item in ports if isinstance(item, str)):
                exposed.add(name)
    return sorted(exposed)


def _check_gcp_firewall_public_admin_ports(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers,
) -> list[RuleHit]:
    """TM-GCP-NET-001: a firewall rule opens SSH/RDP to the whole internet."""
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of("google_compute_firewall"):
        direction = _literal(attributes.get("direction"))
        if direction and direction != "ingress":
            continue
        if not helpers.contains_public_cidr(attributes.get("source_ranges")):
            continue
        exposed = _firewall_allows_admin_ports(helpers, attributes)
        if not exposed:
            continue
        hits.append(RuleHit(
            message=f"Firewall rule '{label}' allows {', '.join(exposed)} from 0.0.0.0/0.",
            line=_attribute_line(helpers, "source_ranges"),
            recommendation="Restrict source_ranges to trusted CIDRs and place SSH/RDP behind IAP or a bastion.",
        ))
    return hits


# -- Google Cloud: database -------------------------------------------------


def _check_gcp_sql_public_ip(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers,
) -> list[RuleHit]:
    """TM-GCP-DB-001: a Cloud SQL instance has a public IPv4 address.

    Cloud SQL defaults ``ipv4_enabled`` to true and enables a public address
    when no ``ip_configuration`` is present, so absence is reported as well as
    an explicit ``ipv4_enabled = true``.  This is one of the few checks that
    reasons about a genuinely unsafe provider default.
    """
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of("google_sql_database_instance"):
        settings_blocks = helpers.blocks(attributes, "settings")
        if not settings_blocks:
            hits.append(RuleHit(
                message=f"Cloud SQL instance '{label}' has no settings.ip_configuration, so it defaults to a public IP.",
                line=_resource_line(helpers, "google_sql_database_instance", label),
                recommendation="Add settings { ip_configuration { ipv4_enabled = false, private_network = ... } }.",
            ))
            continue
        public = False
        saw_ip_configuration = False
        for settings in settings_blocks:
            for ip_configuration in helpers.blocks(settings, "ip_configuration"):
                saw_ip_configuration = True
                ipv4 = ip_configuration.get("ipv4_enabled")
                if ipv4 is None or helpers.is_enabled(ipv4):
                    public = True
        if public or not saw_ip_configuration:
            hits.append(RuleHit(
                message=f"Cloud SQL instance '{label}' allows a public IPv4 address (default or ipv4_enabled = true).",
                line=_attribute_line(helpers, "ipv4_enabled") or _resource_line(
                    helpers, "google_sql_database_instance", label
                ),
                recommendation="Set ipv4_enabled = false and connect over a private network or the Cloud SQL Auth Proxy.",
            ))
    return hits


# -- Google Cloud: compute --------------------------------------------------


def _check_gcp_cluster_private_hardening(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers,
) -> list[RuleHit]:
    """TM-GCP-CMP-001: a GKE cluster lacks private/authorized-network hardening."""
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of("google_container_cluster"):
        missing: list[str] = []
        if not helpers.blocks(attributes, "private_cluster_config"):
            missing.append("private_cluster_config")
        if not helpers.blocks(attributes, "master_authorized_networks_config"):
            missing.append("master_authorized_networks_config")
        if not missing:
            continue
        hits.append(RuleHit(
            message=f"GKE cluster '{label}' is missing {', '.join(missing)}.",
            line=_resource_line(helpers, "google_container_cluster", label),
            recommendation="Add private_cluster_config and master_authorized_networks_config to limit control-plane exposure.",
        ))
    return hits


RULES: list[Rule] = [
    Rule(
        rule_id="TM-AZ-STOR-001",
        title="Azure storage account allows nested public items",
        severity="error",
        service="storage",
        dimension="security",
        recommendation="Set allow_nested_items_to_be_public = false so containers and blobs cannot be made public.",
        check=_check_az_storage_public_nested_items,
    ),
    Rule(
        rule_id="TM-AZ-STOR-002",
        title="Azure storage account allows TLS below 1.2",
        severity="warning",
        service="storage",
        dimension="security",
        recommendation='Set min_tls_version = "TLS1_2" to reject legacy TLS 1.0/1.1 clients.',
        check=_check_az_storage_min_tls,
    ),
    Rule(
        rule_id="TM-AZ-STOR-003",
        title="Azure storage account is publicly reachable",
        severity="warning",
        service="storage",
        dimension="security",
        recommendation="Set public_network_access_enabled = false and use a private endpoint.",
        check=_check_az_storage_public_network,
    ),
    Rule(
        rule_id="TM-AZ-STOR-004",
        title="Azure storage account permits plaintext HTTP",
        severity="warning",
        service="storage",
        dimension="security",
        recommendation="Set https_traffic_only_enabled = true so only HTTPS requests are accepted.",
        check=_check_az_storage_https,
    ),
    Rule(
        rule_id="TM-AZ-KV-001",
        title="Azure key vault purge protection disabled",
        severity="warning",
        service="secrets",
        dimension="reliability",
        recommendation="Set purge_protection_enabled = true so keys and secrets cannot be purged early.",
        check=_check_az_key_vault_purge_protection,
    ),
    Rule(
        rule_id="TM-AZ-NET-001",
        title="Azure NSG rule exposes an admin port to the internet",
        severity="error",
        service="networking",
        dimension="security",
        recommendation="Restrict the source to trusted CIDRs and keep SSH/RDP behind a bastion or VPN.",
        check=_check_az_nsg_public_admin_ports,
    ),
    Rule(
        rule_id="TM-AZ-DB-001",
        title="Azure SQL server is publicly reachable",
        severity="warning",
        service="database",
        dimension="security",
        recommendation="Set public_network_access_enabled = false and connect through a private endpoint.",
        check=_check_az_mssql_public_network,
    ),
    Rule(
        rule_id="TM-GCP-STOR-001",
        title="GCS uniform bucket-level access disabled",
        severity="warning",
        service="storage",
        dimension="security",
        recommendation="Set uniform_bucket_level_access = true and grant access only through IAM policies.",
        check=_check_gcp_bucket_uniform_access,
    ),
    Rule(
        rule_id="TM-GCP-STOR-002",
        title="GCS public access prevention not enforced",
        severity="warning",
        service="storage",
        dimension="security",
        recommendation='Set public_access_prevention = "enforced" to block public access.',
        check=_check_gcp_bucket_public_access_prevention,
    ),
    Rule(
        rule_id="TM-GCP-NET-001",
        title="GCP firewall exposes an admin port to the internet",
        severity="error",
        service="networking",
        dimension="security",
        recommendation="Restrict source_ranges to trusted CIDRs and use IAP or a bastion for SSH/RDP.",
        check=_check_gcp_firewall_public_admin_ports,
    ),
    Rule(
        rule_id="TM-GCP-DB-001",
        title="Cloud SQL instance has a public IP",
        severity="warning",
        service="database",
        dimension="security",
        recommendation="Set ipv4_enabled = false and connect over a private network or the Cloud SQL Auth Proxy.",
        check=_check_gcp_sql_public_ip,
    ),
    Rule(
        rule_id="TM-GCP-CMP-001",
        title="GKE cluster lacks private control-plane hardening",
        severity="information",
        service="compute",
        dimension="security",
        recommendation="Add private_cluster_config and master_authorized_networks_config to limit control-plane exposure.",
        check=_check_gcp_cluster_private_hardening,
    ),
]
