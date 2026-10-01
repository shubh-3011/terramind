"""Networking rules (VPC, subnet, security group, NACL, load balancer).

Owner: network subagent.  Export ``RULES: list[Rule]``.

Rules here are pure functions of the parsed document plus its source text.
They only fire on explicitly evidenced attributes so a resource that leaves a
field at a benign provider default is never reported.
"""

from __future__ import annotations

from typing import Any, Iterator, Mapping

from app.rules.base import Rule, RuleHelpers, RuleHit

#: Ports that should essentially never be reachable from the public internet.
_RISKY_PORTS: dict[int, str] = {
    3389: "RDP (3389)",
    3306: "MySQL (3306)",
    5432: "PostgreSQL (5432)",
    6379: "Redis (6379)",
    27017: "MongoDB (27017)",
}

#: Protocol markers that mean "every port".
_ALL_PORT_PROTOCOLS = {"-1", "all"}


def _is_public(helpers: RuleHelpers, rule_block: Mapping[str, Any]) -> bool:
    """True when an ingress/egress block names a public CIDR explicitly."""
    return helpers.contains_public_cidr(rule_block.get("cidr_blocks")) or helpers.contains_public_cidr(
        rule_block.get("ipv6_cidr_blocks")
    )


def _covers_all_ports(rule_block: Mapping[str, Any]) -> bool:
    """True when the block opens every port, by protocol or explicit span."""
    protocol = str(rule_block.get("protocol", "")).strip('"').lower()
    if protocol in _ALL_PORT_PROTOCOLS:
        return True
    span = RuleHelpers.port_span(rule_block)
    return span is not None and span[0] <= 0 and span[1] >= 65535


def _ingress_blocks(helpers: RuleHelpers) -> Iterator[tuple[str, Mapping[str, Any]]]:
    """Yield ``(label, ingress_block)`` for security groups and SG rules."""
    for _type, attributes, label in helpers.resources_of("aws_security_group"):
        for ingress in helpers.blocks(attributes, "ingress"):
            yield label, ingress
    for _type, attributes, label in helpers.resources_of("aws_security_group_rule"):
        if str(attributes.get("type", "")).strip('"').lower() == "ingress":
            yield label, attributes


def _egress_blocks(helpers: RuleHelpers) -> Iterator[tuple[str, Mapping[str, Any]]]:
    """Yield ``(label, egress_block)`` for security groups and SG rules."""
    for _type, attributes, label in helpers.resources_of("aws_security_group"):
        for egress in helpers.blocks(attributes, "egress"):
            yield label, egress
    for _type, attributes, label in helpers.resources_of("aws_security_group_rule"):
        if str(attributes.get("type", "")).strip('"').lower() == "egress":
            yield label, attributes


def _check_public_risky_ports(document: Mapping[str, Any], file: str, helpers: RuleHelpers) -> list[RuleHit]:
    """TM-NET-002: admin/database ports exposed to the internet.

    SSH (22) is handled by TM-NET-001 in ``app.main``; this rule covers the
    remaining high-impact services (RDP, MySQL, PostgreSQL, Redis, MongoDB).
    """
    hits: list[RuleHit] = []
    for label, block in _ingress_blocks(helpers):
        if not _is_public(helpers, block):
            continue
        if _covers_all_ports(block):
            continue  # an all-ports opening is reported by TM-NET-004
        span = helpers.port_span(block)
        if span is None:
            continue
        exposed = [name for port, name in _RISKY_PORTS.items() if span[0] <= port <= span[1]]
        if not exposed:
            continue
        hits.append(RuleHit(
            message=f"Security group '{label}' exposes {', '.join(exposed)} to the public internet.",
            line=helpers.line_matching(r"\b(?:from_port|to_port)\b"),
            recommendation="Restrict administrative and database ports to trusted CIDRs or private subnets.",
        ))
    return hits


def _check_public_all_ports(document: Mapping[str, Any], file: str, helpers: RuleHelpers) -> list[RuleHit]:
    """TM-NET-004: an ingress rule open to 0.0.0.0/0 on every port."""
    hits: list[RuleHit] = []
    for label, block in _ingress_blocks(helpers):
        if _is_public(helpers, block) and _covers_all_ports(block):
            hits.append(RuleHit(
                message=f"Security group ingress for '{label}' opens all ports (0-65535) to the public internet.",
                line=helpers.line_of("from_port", "to_port", "protocol"),
                recommendation="Scope ingress to the concrete ports and trusted CIDRs the workload actually needs.",
            ))
    return hits


def _check_public_egress(document: Mapping[str, Any], file: str, helpers: RuleHelpers) -> list[RuleHit]:
    """TM-NET-005: unrestricted egress to 0.0.0.0/0.

    Only explicit egress blocks that open every port are reported; the provider
    creates a permissive default egress rule when none is declared, and absence
    alone is not treated as evidence here.
    """
    hits: list[RuleHit] = []
    for label, block in _egress_blocks(helpers):
        if _is_public(helpers, block) and _covers_all_ports(block):
            hits.append(RuleHit(
                message=f"Security group '{label}' allows unrestricted egress to the public internet.",
                line=helpers.line_of("egress"),
                recommendation="Restrict egress to known destinations and ports to limit data exfiltration paths.",
            ))
    return hits


def _check_default_network_resource(document: Mapping[str, Any], file: str, helpers: RuleHelpers) -> list[RuleHit]:
    """TM-NET-006: the account's default security group or default VPC is managed."""
    hits: list[RuleHit] = []
    for resource_type, _attributes, label in helpers.resources_of(
        "aws_default_security_group", "aws_default_vpc"
    ):
        kind = "security group" if resource_type == "aws_default_security_group" else "VPC"
        hits.append(RuleHit(
            message=f"AWS default {kind} '{label}' is managed by Terraform instead of a purpose-built resource.",
            line=helpers.line_of(f"aws_default_{'security_group' if kind == 'security group' else 'vpc'}"),
            recommendation="Use explicit security groups and VPCs so default resources stay unused and auditable.",
        ))
    return hits


def _check_public_route(document: Mapping[str, Any], file: str, helpers: RuleHelpers) -> list[RuleHit]:
    """TM-NET-008: a route sends public traffic to an internet gateway.

    Skipped when the document also defines a load balancer, because public
    subnets are a legitimate part of an internet-facing load balancer tier.
    """
    if any(helpers.resources_of("aws_lb", "aws_alb", "aws_lb_listener", "aws_alb_listener")):
        return []
    has_gateway = any(helpers.resources_of("aws_internet_gateway"))
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of("aws_route"):
        destination = helpers.attribute(
            attributes, "destination_cidr_block", "destination_ipv6_cidr_block"
        )
        gateway = helpers.attribute(attributes, "gateway_id")
        if gateway is None or not helpers.contains_public_cidr(destination):
            continue
        if not has_gateway and "internet_gateway" not in " ".join(helpers.strings(gateway)):
            continue
        hits.append(RuleHit(
            message=f"Route '{label}' sends public traffic (0.0.0.0/0) directly to an internet gateway.",
            line=helpers.line_of("destination_cidr_block", "destination_ipv6_cidr_block"),
            recommendation="Keep workloads in private subnets behind a load balancer or NAT gateway.",
        ))
    return hits


def _check_http_listener(document: Mapping[str, Any], file: str, helpers: RuleHelpers) -> list[RuleHit]:
    """TM-NET-009: a load balancer listener terminates plaintext HTTP."""
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of("aws_lb_listener", "aws_alb_listener"):
        protocol = str(attributes.get("protocol", "")).strip('"').lower()
        if protocol == "http":
            hits.append(RuleHit(
                message=f"Load balancer listener '{label}' uses plaintext HTTP instead of HTTPS.",
                line=helpers.line_of("protocol"),
                recommendation="Terminate TLS with protocol = \"HTTPS\" and a valid ACM certificate; redirect HTTP to HTTPS.",
            ))
    return hits


def _check_single_subnet_load_balancer(
    document: Mapping[str, Any], file: str, helpers: RuleHelpers
) -> list[RuleHit]:
    """TM-NET-010: a load balancer placed in fewer than two explicit subnets.

    Fires only when the configuration spells out exactly one subnet (via the
    ``subnets`` list or a ``subnet_mapping`` block); variable references are
    left alone because their count cannot be known statically.
    """
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of("aws_lb", "aws_alb"):
        subnets = attributes.get("subnets")
        explicit = len(subnets) if isinstance(subnets, list) else 0
        explicit += len(helpers.blocks(attributes, "subnet_mapping"))
        if explicit != 1:
            continue
        hits.append(RuleHit(
            message=f"Load balancer '{label}' is attached to a single subnet.",
            line=helpers.line_of("subnets", "subnet_mapping"),
            recommendation="Attach the load balancer to at least two subnets in different Availability Zones.",
        ))
    return hits


def _check_subnet_auto_public_ip(document: Mapping[str, Any], file: str, helpers: RuleHelpers) -> list[RuleHit]:
    """TM-NET-011: a subnet auto-assigns public IPs to launched instances."""
    hits: list[RuleHit] = []
    for _type, attributes, label in helpers.resources_of("aws_subnet"):
        if helpers.is_enabled(attributes.get("map_public_ip_on_launch")):
            hits.append(RuleHit(
                message=f"Subnet '{label}' automatically assigns public IP addresses to instances launched in it.",
                line=helpers.line_matching(r"map_public_ip_on_launch"),
                recommendation="Disable map_public_ip_on_launch and place internet-facing workloads behind a load balancer.",
            ))
    return hits


RULES: list[Rule] = [
    Rule(
        rule_id="TM-NET-002",
        title="Public ingress to administrative or database ports",
        severity="error",
        service="networking",
        dimension="security",
        recommendation="Restrict administrative and database ports to trusted CIDRs or private subnets.",
        check=_check_public_risky_ports,
    ),
    Rule(
        rule_id="TM-NET-004",
        title="Security group ingress open to all ports",
        severity="error",
        service="networking",
        dimension="security",
        recommendation="Scope ingress to the concrete ports and trusted CIDRs the workload actually needs.",
        check=_check_public_all_ports,
    ),
    Rule(
        rule_id="TM-NET-005",
        title="Unrestricted security group egress",
        severity="warning",
        service="networking",
        dimension="security",
        recommendation="Restrict egress to known destinations and ports to limit data exfiltration paths.",
        check=_check_public_egress,
    ),
    Rule(
        rule_id="TM-NET-006",
        title="AWS default network resource in use",
        severity="warning",
        service="networking",
        dimension="security",
        recommendation="Use explicit security groups and VPCs so default resources stay unused and auditable.",
        check=_check_default_network_resource,
    ),
    Rule(
        rule_id="TM-NET-008",
        title="Public route to an internet gateway",
        severity="warning",
        service="networking",
        dimension="security",
        recommendation="Keep workloads in private subnets behind a load balancer or NAT gateway.",
        check=_check_public_route,
    ),
    Rule(
        rule_id="TM-NET-009",
        title="Load balancer listener uses HTTP",
        severity="warning",
        service="networking",
        dimension="security",
        recommendation="Terminate TLS with protocol = \"HTTPS\" and a valid ACM certificate; redirect HTTP to HTTPS.",
        check=_check_http_listener,
    ),
    Rule(
        rule_id="TM-NET-010",
        title="Load balancer attached to a single subnet",
        severity="warning",
        service="networking",
        dimension="reliability",
        recommendation="Attach the load balancer to at least two subnets in different Availability Zones.",
        check=_check_single_subnet_load_balancer,
    ),
    Rule(
        rule_id="TM-NET-011",
        title="Subnet auto-assigns public IP addresses",
        severity="warning",
        service="networking",
        dimension="security",
        recommendation="Disable map_public_ip_on_launch and place internet-facing workloads behind a load balancer.",
        check=_check_subnet_auto_public_ip,
    ),
]
