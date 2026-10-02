"""Deterministic Terraform scaffolder.

This module turns a small, structured infrastructure request into valid and
secure AWS Terraform **without a language model**. It exists because small local
models reliably mangle requests that name an explicit resource inventory
(for example "5 VPC, 5 EC2 instance, 1 Transit Gateway"): they drop resources,
invent undeclared variables, or emit credential-shaped output.

The public entry point is :func:`scaffold_terraform`. It returns ``(hcl, notes)``
when the request matches a supported pattern and ``None`` when it does not, so
the caller can fall back to the language model. The generated HCL is pure
Terraform: it never contains provider credentials, secrets, or shell commands.

Design constraints:

* Standard library only (``re`` + ``dataclasses``); ``hcl2`` is never imported
  here so importing this module stays cheap and side-effect free.
* Output is deterministic: the same request always produces byte-identical HCL.
* Every ``var.*`` reference is declared, every resource reference points at a
  resource that was actually generated, and defaults are secure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

DEFAULT_REGION = "us-east-1"
DEFAULT_INSTANCE_TYPE = "t3.micro"
DEFAULT_PROJECT = "terramind"
DEFAULT_ENVIRONMENT = "dev"

# --- Kind recognition -------------------------------------------------------
#
# Ordered by specificity. More specific kinds are matched first and their spans
# are masked out so a broad kind (e.g. "subnet") cannot re-match the alias of a
# narrow one (e.g. "public subnet"), and "instance" cannot re-match inside
# "instance profile".
_ALIASES: list[tuple[str, str]] = [
    ("public_subnet", r"public\s+subnets?"),
    ("private_subnet", r"private\s+subnets?"),
    ("transit_gateway", r"(?:transit\s+gateways?|\btgw\b)"),
    ("internet_gateway", r"(?:internet\s+gateways?|\bigw\b)"),
    ("nat_gateway", r"(?:nat\s+gateways?|\bnat\b)"),
    ("route_table", r"(?:route\s+tables?|routing\s+tables?)"),
    ("security_group", r"(?:security\s+groups?|\bsg\b)"),
    ("flow_log", r"(?:vpc\s+flow\s+logs?|flow\s+logs?)"),
    ("cloudwatch_log_group", r"(?:cloudwatch\s+log\s+groups?|\blog\s+groups?)"),
    ("instance_profile", r"(?:iam\s+instance\s+profiles?|instance\s+profiles?)"),
    ("iam_role", r"(?:iam\s+roles?|\broles?\b)"),
    ("ec2", r"(?:ec2\s+instances?|\bec2\b|instances?|virtual\s+machines?|\bvms?\b)"),
    ("s3", r"(?:s3\s+buckets?|\bs3\b|buckets?)"),
    ("alb", r"(?:application\s+load\s+balancers?|network\s+load\s+balancers?|load\s+balancers?|\balbs?\b)"),
    ("vpc", r"\bvpcs?\b"),
    ("subnet", r"\bsubnets?\b"),
]

# Kinds that describe a network boundary; if any is requested we need a VPC.
_NETWORK_KINDS = frozenset(
    {
        "vpc",
        "public_subnet",
        "private_subnet",
        "subnet",
        "internet_gateway",
        "nat_gateway",
        "route_table",
        "security_group",
        "ec2",
        "alb",
        "transit_gateway",
        "flow_log",
    }
)

# Presence-only default counts: an EC2 mention means two instances when no
# number is given (matching the documented behaviour); everything else is one.
_PRESENCE_DEFAULT = {"ec2": 2}

# Varable names we know how to describe; any other referenced variable still
# gets a safe declaration so the output can never fail with "undeclared input".
_VARIABLE_ORDER = [
    "aws_region",
    "project",
    "environment",
    "ami_id",
    "instance_type",
    "acm_certificate_arn",
]
_VARIABLE_SPECS: dict[str, tuple[str, str | None, str]] = {
    "aws_region": ("string", f'"{DEFAULT_REGION}"', "AWS region that all resources are deployed into."),
    "project": ("string", f'"{DEFAULT_PROJECT}"', "Project name used for resource naming and tags."),
    "environment": ("string", f'"{DEFAULT_ENVIRONMENT}"', "Environment name applied to every resource tag."),
    "ami_id": ("string", '""', "AMI ID used by every EC2 instance; set this per region."),
    "instance_type": ("string", f'"{DEFAULT_INSTANCE_TYPE}"', "EC2 instance type."),
    "acm_certificate_arn": ("string", None, "ACM certificate ARN used by the HTTPS load-balancer listener."),
}

_VAR_REFERENCE = re.compile(r"\bvar\.([A-Za-z_][A-Za-z0-9_]*)")
_REGION_RE = re.compile(r"\b(?:us-gov|us|eu|ap|sa|ca|me|af|il|mx|cn)-[a-z]+(?:-[a-z]+)?-\d\b")


@dataclass
class _Subnet:
    """One generated subnet and the VPC it belongs to."""

    label: str
    vpc: int
    kind: str  # "public" | "private"
    cidr: str = ""


@dataclass
class _Request:
    """Resolved counts for one scaffold request."""

    counts: dict[str, int] = field(default_factory=dict)

    def get(self, kind: str) -> int:
        return self.counts.get(kind, 0)


def scaffold_terraform(
    *,
    description: str,
    resource_inventory: str,
    connectivity: str,
    constraints: str,
) -> tuple[str, list[str]] | None:
    """Return ``(hcl, notes)`` when the request matches a supported pattern, else ``None``.

    ``notes`` is a short list of human-readable notes (assumptions and what was
    generated). Returning ``None`` means "not supported; fall back to the
    language model".
    """
    texts = {
        "description": description or "",
        "resource_inventory": resource_inventory or "",
        "connectivity": connectivity or "",
        "constraints": constraints or "",
    }
    resolved = _resolve_counts(texts["resource_inventory"], texts["description"])
    if not resolved:
        return None

    region = (
        _detect_region(texts["constraints"])
        or _detect_region(texts["description"])
        or _detect_region(texts["connectivity"])
        or _detect_region(texts["resource_inventory"])
        or DEFAULT_REGION
    )
    combined = " ".join(texts.values()).lower()

    request = _Request(counts=resolved)
    notes: list[str] = []
    body = _generate_resources(request, combined, notes)
    # The provider block always references var.aws_region, so include it even
    # though only the resource body is scanned here.
    referenced = set(_VAR_REFERENCE.findall(body)) | {"aws_region"}
    variable_text = _render_variables(referenced, region)
    hcl = _assemble(region, variable_text, body)
    return hcl, notes


# --- Count parsing ----------------------------------------------------------


def _parse_text(text: str) -> dict[str, int | None]:
    """Extract kind counts from one block of text.

    Returns a mapping ``kind -> count`` where ``None`` means the kind was
    mentioned without an explicit number (resolved to a default later). Spans of
    matched kinds are masked so broader aliases cannot double count.
    """
    chars = list((text or "").lower())
    found: dict[str, int | None] = {}
    for kind, alias in _ALIASES:
        masked = "".join(chars)
        matches: list[tuple[int, int, int]] = []
        before = re.compile(rf"(\d+)\s*x?\s*(?:of\s+)?(?:{alias})\b")
        after = re.compile(rf"(?:{alias})\b\s*(?:count\s*)?[:=]?\s*(\d+)")
        for match in before.finditer(masked):
            matches.append((match.start(), match.end(), int(match.group(1))))
        for match in after.finditer(masked):
            matches.append((match.start(), match.end(), int(match.group(1))))
        if matches:
            matches.sort(key=lambda item: (item[0], item[1]))
            found[kind] = matches[0][2]
            for start, end, _ in matches:
                _mask(chars, start, end)
            continue
        presence = re.search(alias, masked)
        if presence is not None:
            found[kind] = None
            _mask(chars, presence.start(), presence.end())
    return found


def _mask(chars: list[str], start: int, end: int) -> None:
    """Replace a span with spaces, preserving offsets for later searches."""
    for index in range(start, min(end, len(chars))):
        chars[index] = " "


def _resolve_counts(inventory: str, description: str) -> dict[str, int]:
    """Combine inventory (primary) and description (secondary) into final counts.

    An explicit number in the inventory wins, then an explicit number in the
    description, then a presence-only default. Returns an empty dict when no
    supported kind is recognised.
    """
    primary = _parse_text(inventory)
    secondary = _parse_text(description)
    combined: dict[str, int | None] = {}
    for kind in {*primary, *secondary}:
        if primary.get(kind) is not None:
            combined[kind] = primary[kind]
        elif secondary.get(kind) is not None:
            combined[kind] = secondary[kind]
        else:
            combined[kind] = None
    resolved: dict[str, int] = {}
    for kind, value in combined.items():
        resolved[kind] = _PRESENCE_DEFAULT.get(kind, 1) if value is None else max(1, int(value))
    return resolved


def _detect_region(text: str) -> str | None:
    """Return the first AWS region-looking token in ``text``."""
    match = _REGION_RE.search(text or "")
    return match.group(0) if match else None


# --- HCL rendering helpers --------------------------------------------------


def _tags(prefix: str, name: str) -> str:
    return (
        "  tags = {\n"
        f'    Name        = "{prefix}-{name}"\n'
        "    Project     = var.project\n"
        "    Environment = var.environment\n"
        "  }\n"
    )


def _resource(resource_type: str, label: str, body: str) -> str:
    return f'resource "{resource_type}" "{label}" {{\n{body}}}\n'


def _variable(name: str, type_: str, default: str | None, description: str) -> str:
    lines = [
        f'variable "{name}" {{',
        f"  type        = {type_}",
        f'  description = "{description}"',
    ]
    if default is not None:
        lines.append(f"  default     = {default}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _render_variables(referenced: set[str], region: str) -> str:
    """Declare every referenced variable, in a stable, readable order."""
    ordered = [name for name in _VARIABLE_ORDER if name in referenced]
    ordered += sorted(name for name in referenced if name not in _VARIABLE_ORDER)
    blocks: list[str] = []
    for name in ordered:
        if name == "aws_region":
            type_, default, description = ("string", f'"{region}"', "AWS region that all resources are deployed into.")
        elif name in _VARIABLE_SPECS:
            type_, default, description = _VARIABLE_SPECS[name]
        else:
            # Defensive: the generator never emits an unknown variable, but a
            # declaration keeps any future change from producing invalid HCL.
            type_, default, description = ("string", "null", "Value required by the generated configuration.")
        blocks.append(_variable(name, type_, default, description))
    return "\n".join(blocks)


# --- Resource generation ----------------------------------------------------


def _generate_resources(request: _Request, combined: str, notes: list[str]) -> str:
    """Generate every resource block and append human-readable notes."""
    vpc_count = request.get("vpc")
    public = request.get("public_subnet")
    private = request.get("private_subnet")
    generic = request.get("subnet")
    igw_requested = request.get("internet_gateway")
    nat_requested = request.get("nat_gateway")
    rt_requested = request.get("route_table")
    sg_requested = request.get("security_group")
    ec2 = request.get("ec2")
    s3 = request.get("s3")
    alb = request.get("alb")
    tgw = request.get("transit_gateway")
    iam_role_requested = request.get("iam_role")
    profile_requested = request.get("instance_profile")
    cw_requested = request.get("cloudwatch_log_group")
    flow_log = request.get("flow_log")

    network = any(request.get(kind) for kind in _NETWORK_KINDS)
    if network and vpc_count == 0:
        vpc_count = 1
        notes.append("No VPC count was supplied, so one VPC was generated as the network boundary.")

    if generic:
        if public == 0:
            public = generic
            notes.append(f"Treated {generic} generic subnet(s) as public because no public/private split was given.")
        else:
            private += generic
            notes.append(f"Added {generic} generic subnet(s) as private because public subnets were specified.")

    if ec2 and private == 0:
        private = max(1, min(vpc_count, ec2))
        notes.append(f"Added {private} private subnet(s) so EC2 instances are never placed in a public subnet.")

    if (nat_requested or alb) and public == 0:
        public = max(1, min(vpc_count, nat_requested or alb))
        notes.append("Added a public subnet because a NAT gateway / load balancer requires one.")

    subnets = _build_subnets(public, private, vpc_count, tgw, notes)

    # Internet gateways: one per VPC that has public subnets, plus any explicit
    # request. Cannot exceed the number of VPCs (an IGW attaches to one VPC).
    vpcs_with_public = sorted({subnet.vpc for subnet in subnets if subnet.kind == "public"})
    igw_targets = set(vpcs_with_public)
    if igw_requested:
        igw_targets.update(range(1, min(igw_requested, vpc_count) + 1))
    if (public or nat_requested) and not igw_targets:
        igw_targets.add(1)
    igw_vpcs = sorted(igw_targets)
    igw_label = {vpc: f"igw_{vpc}" for vpc in igw_vpcs}

    # NAT gateways are placed in public subnets, one per requested gateway.
    public_subnets = [subnet for subnet in subnets if subnet.kind == "public"]
    nat_placements: list[tuple[str, _Subnet]] = []
    for index in range(1, nat_requested + 1):
        subnet = public_subnets[(index - 1) % len(public_subnets)]
        nat_placements.append((f"nat_{index}", subnet))

    vpcs_with_private = sorted({subnet.vpc for subnet in subnets if subnet.kind == "private"})
    public_rt = {vpc: f"public_rt_{vpc}" for vpc in vpcs_with_public if vpc in igw_label}
    private_rt = {vpc: f"private_rt_{vpc}" for vpc in vpcs_with_private}

    if ec2 and sg_requested == 0:
        sg_requested = 1
        notes.append("Added one security group with VPC-scoped ingress so instances do not rely on the default group.")
    security_groups = [
        (f"sg_{index}", (index - 1) % vpc_count + 1) for index in range(1, sg_requested + 1)
    ]

    want_ssm = bool(re.search(r"\bssm\b|\bmanaged\b|instance\s+profile", combined))
    want_role = bool(iam_role_requested) or bool(profile_requested) or bool(re.search(r"\bssm\b|\bmanaged\b", combined))
    want_profile = bool(profile_requested) or bool(re.search(r"\bssm\b|\bmanaged\b|instance\s+profile", combined))

    # --- Render -------------------------------------------------------------
    blocks: list[str] = []

    if vpc_count:
        blocks.append("# --- VPCs (non-overlapping /16 CIDRs) ---")
        for index in range(1, vpc_count + 1):
            vpc_cidr = f"10.{index}.0.0/16"
            body = (
                f'  cidr_block           = "{vpc_cidr}"\n'
                "  enable_dns_support   = true\n"
                "  enable_dns_hostnames = true\n\n"
                + _tags("vpc", str(index))
            )
            blocks.append(_resource("aws_vpc", f"vpc_{index}", body))

    if subnets:
        blocks.append("# --- Subnets ---")
        for subnet in subnets:
            public_ip = "true" if subnet.kind == "public" else "false"
            body = (
                f"  vpc_id                  = aws_vpc.vpc_{subnet.vpc}.id\n"
                f'  cidr_block              = "{subnet.cidr}"\n'
                f"  map_public_ip_on_launch = {public_ip}\n\n"
                + _tags("subnet", subnet.label)
            )
            blocks.append(_resource("aws_subnet", subnet.label, body))

    if igw_vpcs:
        blocks.append("# --- Internet gateways ---")
        for vpc in igw_vpcs:
            body = f"  vpc_id = aws_vpc.vpc_{vpc}.id\n\n" + _tags("igw", str(vpc))
            blocks.append(_resource("aws_internet_gateway", igw_label[vpc], body))

    if nat_placements:
        blocks.append("# --- NAT gateways (one elastic IP each) ---")
        for label, subnet in nat_placements:
            index = label.split("_")[1]
            eip_body = "  domain = \"vpc\"\n\n" + _tags("nat-eip", index)
            blocks.append(_resource("aws_eip", f"nat_eip_{index}", eip_body))
            depends_on = f"  depends_on    = [aws_internet_gateway.igw_{subnet.vpc}]\n"
            nat_body = (
                f"  allocation_id = aws_eip.nat_eip_{index}.id\n"
                f"  subnet_id     = aws_subnet.{subnet.label}.id\n"
                f"{depends_on}\n"
                + _tags("nat", index)
            )
            blocks.append(_resource("aws_nat_gateway", label, nat_body))

    if public_rt or private_rt or rt_requested:
        blocks.append("# --- Route tables and subnet associations ---")
        for vpc in sorted(public_rt):
            route = (
                "  route {\n"
                '    cidr_block = "0.0.0.0/0"\n'
                f"    gateway_id = aws_internet_gateway.{igw_label[vpc]}.id\n"
                "  }\n\n"
            )
            body = f"  vpc_id = aws_vpc.vpc_{vpc}.id\n\n" + route + _tags("public-rt", str(vpc))
            blocks.append(_resource("aws_route_table", public_rt[vpc], body))

        nat_in_vpc: dict[int, str] = {}
        for label, subnet in nat_placements:
            nat_in_vpc.setdefault(subnet.vpc, label)

        for vpc in sorted(private_rt):
            body = f"  vpc_id = aws_vpc.vpc_{vpc}.id\n\n"
            routes = ""
            if vpc in nat_in_vpc:
                routes += (
                    "  route {\n"
                    '    cidr_block     = "0.0.0.0/0"\n'
                    f"    nat_gateway_id = aws_nat_gateway.{nat_in_vpc[vpc]}.id\n"
                    "  }\n\n"
                )
            if tgw:
                # A broad private route lets every attached VPC reach the others
                # through the transit gateway without enumerating peer CIDRs.
                routes += (
                    "  route {\n"
                    '    cidr_block         = "10.0.0.0/8"\n'
                    "    transit_gateway_id = aws_ec2_transit_gateway.tgw_1.id\n"
                    "  }\n\n"
                )
            blocks.append(_resource("aws_route_table", private_rt[vpc], body + routes + _tags("private-rt", str(vpc))))

        generated_tables = len(public_rt) + len(private_rt)
        for index in range(1, max(0, rt_requested - generated_tables) + 1):
            vpc = (index - 1) % vpc_count + 1
            body = f"  vpc_id = aws_vpc.vpc_{vpc}.id\n\n" + _tags("route-table", str(index))
            blocks.append(_resource("aws_route_table", f"route_table_extra_{index}", body))

        for subnet in subnets:
            if subnet.kind == "public" and subnet.vpc in public_rt:
                rt_label = public_rt[subnet.vpc]
            elif subnet.kind == "private" and subnet.vpc in private_rt:
                rt_label = private_rt[subnet.vpc]
            else:
                continue
            kind = subnet.kind
            body = (
                f"  subnet_id      = aws_subnet.{subnet.label}.id\n"
                f"  route_table_id = aws_route_table.{rt_label}.id\n"
            )
            blocks.append(_resource("aws_route_table_association", f"{kind}_rta_{subnet.label}", body))

    if security_groups:
        blocks.append("# --- Security groups (ingress scoped to each VPC CIDR) ---")
        for label, vpc in security_groups:
            vpc_cidr = f"10.{vpc}.0.0/16"
            body = (
                f'  name        = "${{var.project}}-{label}"\n'
                '  description = "TerraMind scaffold security group"\n'
                f"  vpc_id      = aws_vpc.vpc_{vpc}.id\n\n"
                "  ingress {\n"
                '    description = "HTTPS from within the VPC"\n'
                "    from_port   = 443\n"
                "    to_port     = 443\n"
                '    protocol    = "tcp"\n'
                f'    cidr_blocks = ["{vpc_cidr}"]\n'
                "  }\n\n"
                "  ingress {\n"
                '    description = "SSH from within the VPC only"\n'
                "    from_port   = 22\n"
                "    to_port     = 22\n"
                '    protocol    = "tcp"\n'
                f'    cidr_blocks = ["{vpc_cidr}"]\n'
                "  }\n\n"
                "  egress {\n"
                '    description = "Allow all outbound traffic"\n'
                "    from_port   = 0\n"
                "    to_port     = 0\n"
                '    protocol    = "-1"\n'
                '    cidr_blocks = ["0.0.0.0/0"]\n'
                "  }\n\n"
                + _tags("sg", label.split("_")[1])
            )
            blocks.append(_resource("aws_security_group", label, body))

    if want_role:
        blocks.append("# --- IAM role / instance profile (SSM managed instance core) ---")
        role_body = (
            f'  name = "${{var.project}}-ec2-instance-role"\n\n'
            "  assume_role_policy = jsonencode({\n"
            '    Version = "2012-10-17"\n'
            "    Statement = [\n"
            "      {\n"
            '        Effect    = "Allow"\n'
            "        Principal = { Service = \"ec2.amazonaws.com\" }\n"
            '        Action    = "sts:AssumeRole"\n'
            "      }\n"
            "    ]\n"
            "  })\n\n"
            + _tags("iam-role", "ec2")
        )
        blocks.append(_resource("aws_iam_role", "ec2_instance_role", role_body))
        if want_ssm or profile_requested:
            attach_body = (
                "  role       = aws_iam_role.ec2_instance_role.name\n"
                '  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"\n'
            )
            blocks.append(_resource("aws_iam_role_policy_attachment", "ec2_ssm_core", attach_body))
        if want_profile:
            profile_body = (
                f'  name = "${{var.project}}-ec2-instance-profile"\n'
                "  role = aws_iam_role.ec2_instance_role.name\n"
            )
            blocks.append(_resource("aws_iam_instance_profile", "ec2_instance_profile", profile_body))

    if ec2:
        blocks.append("# --- EC2 instances (private by default, IMDSv2 required, encrypted root) ---")
        instance_subnets = [subnet for subnet in subnets if subnet.kind == "private"] or public_subnets
        for index in range(1, ec2 + 1):
            subnet = instance_subnets[(index - 1) % len(instance_subnets)]
            body = (
                "  ami                         = var.ami_id\n"
                "  instance_type               = var.instance_type\n"
                f"  subnet_id                   = aws_subnet.{subnet.label}.id\n"
                "  associate_public_ip_address = false\n\n"
            )
            if security_groups:
                sg_label = security_groups[(index - 1) % len(security_groups)][0]
                body += f"  vpc_security_group_ids      = [aws_security_group.{sg_label}.id]\n"
            if want_profile:
                body += "  iam_instance_profile        = aws_iam_instance_profile.ec2_instance_profile.name\n"
            body += (
                "\n  metadata_options {\n"
                '    http_endpoint = "enabled"\n'
                '    http_tokens   = "required"\n'
                "  }\n\n"
                "  root_block_device {\n"
                "    encrypted   = true\n"
                '    volume_type = "gp3"\n'
                "  }\n\n"
                + _tags("ec2", str(index))
            )
            blocks.append(_resource("aws_instance", f"instance_{index}", body))

    if s3:
        blocks.append("# --- S3 buckets (KMS encryption, versioning, public access blocked) ---")
        for index in range(1, s3 + 1):
            label = f"bucket_{index}"
            bucket_body = (
                f'  bucket = "${{var.project}}-bucket-{index}"\n\n' + _tags("bucket", str(index))
            )
            blocks.append(_resource("aws_s3_bucket", label, bucket_body))
            encryption_body = (
                f"  bucket = aws_s3_bucket.{label}.id\n\n"
                "  rule {\n"
                "    apply_server_side_encryption_by_default {\n"
                '      sse_algorithm = "aws:kms"\n'
                "    }\n"
                "    bucket_key_enabled = true\n"
                "  }\n"
            )
            blocks.append(_resource("aws_s3_bucket_server_side_encryption_configuration", label, encryption_body))
            versioning_body = (
                f"  bucket = aws_s3_bucket.{label}.id\n\n"
                "  versioning_configuration {\n"
                '    status = "Enabled"\n'
                "  }\n"
            )
            blocks.append(_resource("aws_s3_bucket_versioning", label, versioning_body))
            pab_body = (
                f"  bucket = aws_s3_bucket.{label}.id\n\n"
                "  block_public_acls       = true\n"
                "  block_public_policy     = true\n"
                "  ignore_public_acls      = true\n"
                "  restrict_public_buckets = true\n"
            )
            blocks.append(_resource("aws_s3_bucket_public_access_block", label, pab_body))

    if alb:
        blocks.append("# --- Application load balancer (HTTPS listener on 443) ---")
        for index in range(1, alb + 1):
            vpc = _pick_vpc_with_public(public_subnets, vpc_count)
            alb_subnets = [subnet for subnet in public_subnets if subnet.vpc == vpc]
            subnet_refs = ", ".join(f"aws_subnet.{subnet.label}.id" for subnet in alb_subnets)
            sg_label = security_groups[(index - 1) % len(security_groups)][0] if security_groups else ""
            body = (
                f'  name               = "${{var.project}}-alb-{index}"\n'
                "  internal           = false\n"
                '  load_balancer_type = "application"\n'
            )
            if sg_label:
                body += f"  security_groups    = [aws_security_group.{sg_label}.id]\n"
            body += f"  subnets            = [{subnet_refs}]\n\n" + _tags("alb", str(index))
            blocks.append(_resource("aws_lb", f"alb_{index}", body))

            tg_body = (
                f'  name     = "${{var.project}}-tg-{index}"\n'
                "  port     = 443\n"
                '  protocol = "HTTPS"\n'
                f"  vpc_id   = aws_vpc.vpc_{vpc}.id\n\n"
                "  health_check {\n"
                '    path     = "/"\n'
                '    protocol = "HTTPS"\n'
                '    matcher  = "200"\n'
                "  }\n\n"
                + _tags("tg", str(index))
            )
            blocks.append(_resource("aws_lb_target_group", f"alb_{index}", tg_body))

            listener_body = (
                f"  load_balancer_arn = aws_lb.alb_{index}.arn\n"
                "  port              = 443\n"
                '  protocol          = "HTTPS"\n'
                '  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"\n'
                "  certificate_arn   = var.acm_certificate_arn\n\n"
                "  default_action {\n"
                '    type             = "forward"\n'
                f"    target_group_arn = aws_lb_target_group.alb_{index}.arn\n"
                "  }\n"
            )
            blocks.append(_resource("aws_lb_listener", f"alb_{index}", listener_body))

    if tgw:
        blocks.append("# --- Transit gateway: every VPC attached and routed privately ---")
        for index in range(1, tgw + 1):
            tgw_body = (
                '  description = "TerraMind scaffold transit gateway"\n\n' + _tags("tgw", str(index))
            )
            blocks.append(_resource("aws_ec2_transit_gateway", f"tgw_{index}", tgw_body))
        for vpc in range(1, vpc_count + 1):
            attachment_vpc_subnets = [
                subnet for subnet in subnets if subnet.vpc == vpc and subnet.kind == "private"
            ] or [subnet for subnet in subnets if subnet.vpc == vpc]
            subnet_refs = ", ".join(f"aws_subnet.{subnet.label}.id" for subnet in attachment_vpc_subnets)
            attach_body = (
                f"  subnet_ids         = [{subnet_refs}]\n"
                "  transit_gateway_id = aws_ec2_transit_gateway.tgw_1.id\n"
                f"  vpc_id             = aws_vpc.vpc_{vpc}.id\n\n"
                + _tags("tgw-attach", str(vpc))
            )
            blocks.append(_resource("aws_ec2_transit_gateway_vpc_attachment", f"tgw_attach_{vpc}", attach_body))
            assoc_body = (
                f"  transit_gateway_attachment_id  = aws_ec2_transit_gateway_vpc_attachment.tgw_attach_{vpc}.id\n"
                "  transit_gateway_route_table_id = aws_ec2_transit_gateway.tgw_1.association_default_route_table_id\n"
            )
            blocks.append(_resource("aws_ec2_transit_gateway_route_table_association", f"tgw_assoc_{vpc}", assoc_body))
            prop_body = (
                f"  transit_gateway_attachment_id  = aws_ec2_transit_gateway_vpc_attachment.tgw_attach_{vpc}.id\n"
                "  transit_gateway_route_table_id = aws_ec2_transit_gateway.tgw_1.association_default_route_table_id\n"
            )
            blocks.append(_resource("aws_ec2_transit_gateway_route_table_propagation", f"tgw_prop_{vpc}", prop_body))
        notes.append(f"Attached all {vpc_count} VPC(s) to the transit gateway with route-table association and propagation.")

    if cw_requested:
        blocks.append("# --- CloudWatch log groups ---")
        for index in range(1, cw_requested + 1):
            body = (
                f'  name              = "/terramind/log-group-{index}"\n'
                "  retention_in_days = 30\n\n"
                + _tags("log-group", str(index))
            )
            blocks.append(_resource("aws_cloudwatch_log_group", f"log_group_{index}", body))

    if flow_log:
        blocks.append("# --- VPC flow logs to CloudWatch ---")
        flow_group_body = (
            '  name              = "/terramind/vpc-flow-logs"\n'
            "  retention_in_days = 30\n\n"
            + _tags("flow-logs", "vpc")
        )
        blocks.append(_resource("aws_cloudwatch_log_group", "vpc_flow_logs", flow_group_body))
        flow_role_policy = (
            "  assume_role_policy = jsonencode({\n"
            '    Version = "2012-10-17"\n'
            "    Statement = [\n"
            "      {\n"
            '        Effect    = "Allow"\n'
            '        Principal = { Service = "vpc-flow-logs.amazonaws.com" }\n'
            '        Action    = "sts:AssumeRole"\n'
            "      }\n"
            "    ]\n"
            "  })\n"
        )
        blocks.append(_resource("aws_iam_role", "flow_logs_role", flow_role_policy))
        inline_policy = (
            "  role = aws_iam_role.flow_logs_role.id\n\n"
            "  policy = jsonencode({\n"
            '    Version = "2012-10-17"\n'
            "    Statement = [\n"
            "      {\n"
            '        Effect = "Allow"\n'
            "        Action = [\n"
            '          "logs:CreateLogGroup",\n'
            '          "logs:CreateLogStream",\n'
            '          "logs:PutLogEvents",\n'
            '          "logs:DescribeLogGroups",\n'
            '          "logs:DescribeLogStreams"\n'
            "        ]\n"
            '        Resource = "${aws_cloudwatch_log_group.vpc_flow_logs.arn}:*"\n'
            "      }\n"
            "    ]\n"
            "  })\n"
        )
        blocks.append(_resource("aws_iam_role_policy", "flow_logs_policy", inline_policy))
        for index in range(1, flow_log + 1):
            vpc = (index - 1) % vpc_count + 1
            body = (
                f"  vpc_id               = aws_vpc.vpc_{vpc}.id\n"
                '  traffic_type         = "ALL"\n'
                '  log_destination_type = "cloud-watch-logs"\n'
                "  log_destination      = aws_cloudwatch_log_group.vpc_flow_logs.arn\n"
                "  iam_role_arn         = aws_iam_role.flow_logs_role.arn\n\n"
                + _tags("flow-log", str(index))
            )
            blocks.append(_resource("aws_flow_log", f"flow_log_{index}", body))

    return "\n".join(blocks)


def _build_subnets(
    public: int, private: int, vpc_count: int, tgw: int, notes: list[str]
) -> list[_Subnet]:
    """Distribute public/private subnets across VPCs and assign unique CIDRs."""
    subnets: list[_Subnet] = []
    public_index = 0
    private_index = 0
    for index in range(1, public + 1):
        public_index += 1
        subnets.append(_Subnet(f"public_subnet_{public_index}", (index - 1) % vpc_count + 1, "public"))
    for index in range(1, private + 1):
        private_index += 1
        subnets.append(_Subnet(f"private_subnet_{private_index}", (index - 1) % vpc_count + 1, "private"))

    if tgw:
        covered = {subnet.vpc for subnet in subnets}
        added = 0
        for vpc in range(1, vpc_count + 1):
            if vpc not in covered:
                private_index += 1
                subnets.append(_Subnet(f"private_subnet_{private_index}", vpc, "private"))
                added += 1
        if added:
            notes.append(f"Added {added} private subnet(s) so every VPC can attach to the transit gateway.")

    counters: dict[int, int] = {}
    for subnet in subnets:
        next_cidr = counters.get(subnet.vpc, 0) + 1
        counters[subnet.vpc] = next_cidr
        subnet.cidr = f"10.{subnet.vpc}.{next_cidr}.0/24"
    return subnets


def _pick_vpc_with_public(public_subnets: list[_Subnet], vpc_count: int) -> int:
    """Return the VPC that has public subnets (fall back to the first VPC)."""
    if public_subnets:
        return public_subnets[0].vpc
    return 1 if vpc_count else 1


def _assemble(region: str, variable_text: str, body: str) -> str:
    """Wrap generated resources with terraform, provider, and variable blocks."""
    terraform_block = (
        "terraform {\n"
        '  required_version = ">= 1.5"\n\n'
        "  required_providers {\n"
        "    aws = {\n"
        '      source  = "hashicorp/aws"\n'
        '      version = "~> 5.0"\n'
        "    }\n"
        "  }\n"
        "}\n"
    )
    provider_block = (
        'provider "aws" {\n'
        "  region = var.aws_region\n"
        "}\n"
    )
    header = (
        "# Terraform scaffold generated deterministically by TerraMind (no language model).\n"
        f"# Region detected/supplied: {region} (overridable with var.aws_region).\n"
        "# Review before applying; environment-specific values such as the AMI ID must be set.\n"
    )
    return (
        f"{header}\n"
        f"{terraform_block}\n"
        f"{provider_block}\n"
        "# --- Variables ---\n"
        f"{variable_text}\n"
        "# --- Resources ---\n"
        f"{body}"
    )
