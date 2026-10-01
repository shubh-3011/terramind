"""Integration tests for the AWS rule registry and the analysis endpoint.

These tests exercise ``POST /v1/analyze`` against reusable Terraform fixtures.
They lock two things the unit tests do not:

* the exact rule_ids the 45-rule AWS registry emits for known-bad HCL, and
* the false-positive guard: a genuinely well-configured project must produce
  zero findings.

Fixtures live in ``tests/fixtures/`` and are copied into ``tmp_path`` before
each request so the analyzed directory is isolated and read-only in source.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.rules import ALL_RULES
from app.rules.base import DIMENSIONS, SEVERITIES

client = TestClient(app)

FIXTURES = Path(__file__).resolve().parent / "fixtures"

#: Severity ordering used to assert the recommendation ranking.
SEVERITY_RANK = {"error": 0, "warning": 1, "information": 2}


def _copy_fixture(name: str, tmp_path: Path) -> Path:
    """Copy ``tests/fixtures/<name>`` into ``tmp_path`` and return the copy."""
    destination = tmp_path / name
    shutil.copytree(FIXTURES / name, destination)
    return destination


def _analyze(workspace: Path) -> dict:
    response = client.post("/v1/analyze", json={"workspace_path": str(workspace)})
    assert response.status_code == 200, response.text
    return response.json()


# -- insecure fixture -------------------------------------------------------


def test_insecure_fixture_reports_each_expected_rule(tmp_path):
    """Every high-impact insecure pattern in the fixture is reported."""
    report = _analyze(_copy_fixture("insecure", tmp_path))
    rule_ids = {finding["rule_id"] for finding in report["findings"]}

    expected = {
        "TM-NET-002",    # RDP (3389) exposed to 0.0.0.0/0
        "TM-NET-005",    # unrestricted egress
        "TM-DB-001",     # RDS publicly_accessible = true
        "TM-DB-003",     # backup_retention_period = 0
        "TM-SECRET-002",  # literal credential in source
        "TM-IAM-004",    # wildcard principal in a policy document
        "TM-IAM-005",    # long-lived IAM access key
    }
    assert expected.issubset(rule_ids), sorted(expected - rule_ids)


def test_insecure_fixture_ratings_stay_evidence_limited(tmp_path):
    """Database scores reflect findings while unknown dimensions stay unknown."""
    report = _analyze(_copy_fixture("insecure", tmp_path))
    database = next(
        rating for rating in report["service_ratings"] if rating["service"] == "database"
    )
    dimensions = database["dimensions"]

    assert dimensions["security"]["score"] < 100
    assert dimensions["reliability"]["score"] < 100

    for dimension in ("scalability", "cost"):
        assert dimensions[dimension]["score"] is None
        assert dimensions[dimension]["status"] == "insufficient_information"


def test_insecure_fixture_recommendations_are_prioritized(tmp_path):
    """Recommendations are grouped, ranked, and numbered from one."""
    report = _analyze(_copy_fixture("insecure", tmp_path))
    recommendations = report["recommendations"]

    assert recommendations
    priorities = [item["priority"] for item in recommendations]
    assert priorities == list(range(1, len(recommendations) + 1))

    ranks = [SEVERITY_RANK[item["severity"]] for item in recommendations]
    assert ranks == sorted(ranks)

    # Every recommendation is backed by at least one concrete finding.
    finding_ids = {finding["id"] for finding in report["findings"]}
    for item in recommendations:
        assert item["count"] >= 1
        assert set(item["evidence_ids"]).issubset(finding_ids)


# -- secure fixture (false-positive guard) ---------------------------------


def test_secure_fixture_produces_no_findings(tmp_path):
    """A well-configured project must not trip any rule."""
    report = _analyze(_copy_fixture("secure", tmp_path))

    assert report["terraform_file_count"] == 4
    assert report["parsed_file_count"] == 4
    assert report["findings"] == []


# -- parser robustness ------------------------------------------------------


def test_malformed_file_reports_hcl_error_and_keeps_analyzing(tmp_path):
    """A syntax error is reported without aborting the rest of the workspace."""
    report = _analyze(_copy_fixture("malformed", tmp_path))

    assert report["terraform_file_count"] == 2
    assert report["parsed_file_count"] == 1

    rule_ids = {finding["rule_id"] for finding in report["findings"]}
    assert "TM-HCL-001" in rule_ids      # malformed file reported
    assert "TM-NET-001" in rule_ids      # valid sibling still analyzed


# -- registry invariants ----------------------------------------------------


def test_rule_registry_ids_are_unique_and_metadata_is_valid():
    """The registry stays unique and well-formed as modules are added."""
    rule_ids = [rule.rule_id for rule in ALL_RULES]

    # Do not hardcode a total: the registry spans AWS, multi-cloud, and
    # provider-agnostic general Terraform rules and grows over time. Assert the
    # invariants that matter instead of an exact count.
    assert len(rule_ids) >= 45
    assert len(rule_ids) == len(set(rule_ids))

    for rule in ALL_RULES:
        assert rule.rule_id.startswith("TM-")
        assert rule.title and rule.service and rule.recommendation
        assert rule.severity in SEVERITIES
        assert rule.dimension in DIMENSIONS
