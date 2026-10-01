from fastapi.testclient import TestClient

from app.main import Finding, app
from app.recommendations import build_recommendations

client = TestClient(app)


def _finding(rule_id, severity, message, file="main.tf", finding_id=None, recommendation=None):
    """Return a dict-shaped finding; missing fields stay absent on purpose."""
    finding = {
        "id": finding_id or f"{file}:{rule_id}:1",
        "source": "terramind-rules",
        "rule_id": rule_id,
        "severity": severity,
        "message": message,
        "file": file,
    }
    if recommendation is not None:
        finding["recommendation"] = recommendation
    return finding


def test_groups_by_rule_id_and_aggregates_count_and_evidence():
    findings = [
        _finding("TM-NET-001", "error", "ssh one", "a.tf", "id-1"),
        _finding("TM-NET-001", "error", "ssh two", "b.tf", "id-2"),
        _finding("TM-ECR-001", "warning", "mutable tags", "c.tf", "id-3"),
    ]

    recommendations = build_recommendations(findings)

    assert [item["rule_id"] for item in recommendations] == ["TM-NET-001", "TM-ECR-001"]
    ssh = recommendations[0]
    assert ssh["count"] == 2
    assert ssh["files"] == ["a.tf", "b.tf"]
    assert ssh["evidence_ids"] == ["id-1", "id-2"]
    assert ssh["message"] == "ssh one"
    assert recommendations[1]["count"] == 1


def test_orders_by_severity_then_count_then_rule_id():
    findings = (
        [_finding("TM-WARN-1", "warning", "w") for _ in range(2)]
        + [_finding("TM-INFO-1", "information", "i")]
        + [_finding("TM-ERR-1", "error", "e")]
    )

    recommendations = build_recommendations(findings)

    assert [item["severity"] for item in recommendations] == ["error", "warning", "information"]

    # Same severity: higher count first, then rule_id for equal counts.
    same_severity = [
        _finding("TM-B", "warning", "b1"),
        _finding("TM-B", "warning", "b2"),
        _finding("TM-A", "warning", "a"),
    ]
    assert [item["rule_id"] for item in build_recommendations(same_severity)] == ["TM-B", "TM-A"]

    tied = [_finding("TM-B", "warning", "b"), _finding("TM-A", "warning", "a")]
    assert [item["rule_id"] for item in build_recommendations(tied)] == ["TM-A", "TM-B"]


def test_priority_is_one_based_and_contiguous():
    findings = [
        _finding("TM-ERR-1", "error", "e1"),
        _finding("TM-ERR-1", "error", "e2"),
        _finding("TM-WARN-1", "warning", "w1"),
        _finding("TM-INFO-1", "information", "i1"),
    ]

    priorities = [item["priority"] for item in build_recommendations(findings)]

    assert priorities == [1, 2, 3]


def test_limit_caps_groups_and_invalid_limit_falls_back_to_default():
    findings = [_finding(f"TM-{index:03d}", "warning", f"m{index}") for index in range(30)]

    assert len(build_recommendations(findings, limit=5)) == 5
    assert len(build_recommendations(findings, limit=0)) == 0
    assert len(build_recommendations(findings, limit=None)) == 20
    assert len(build_recommendations(findings, limit="not-a-number")) == 20
    assert len(build_recommendations(findings, limit=-4)) == 20


def test_accepts_pydantic_objects_dicts_and_missing_fields():
    object_finding = Finding(
        id="object-id",
        source="terramind-rules",
        rule_id="TM-NET-001",
        severity="error",
        message="object ssh",
        file="object.tf",
    )
    dict_finding = {
        "rule_id": "TM-NET-001",
        "severity": "error",
        "message": "dict ssh",
        "file": "dict.tf",
        "id": "dict-id",
    }
    malformed_finding = {"severity": "warning"}  # no rule_id, id, message or file

    recommendations = build_recommendations([object_finding, dict_finding, malformed_finding])
    by_rule = {item["rule_id"]: item for item in recommendations}

    assert by_rule["TM-NET-001"]["count"] == 2
    assert by_rule["TM-NET-001"]["severity"] == "error"
    assert by_rule["TM-NET-001"]["title"] == "Terraform rule TM-NET-001"
    assert by_rule["TM-NET-001"]["recommendation"] == (
        "Review this finding and re-run analysis after changes."
    )
    assert by_rule["TM-NET-001"]["files"] == ["dict.tf", "object.tf"]
    assert by_rule["TM-NET-001"]["evidence_ids"] == ["object-id", "dict-id"]
    # The malformed finding is grouped under its empty rule_id rather than raising.
    assert by_rule[""]["severity"] == "warning"


def test_registered_rule_supplies_title_severity_and_recommendation():
    # TM-NET-011 is a registered rule; its metadata must win over the finding's.
    finding = _finding(
        "TM-NET-011", "information", "public ip subnet", "net.tf",
        recommendation="untrusted finding text",
    )

    recommendation = build_recommendations([finding])[0]

    assert recommendation["title"] == "Subnet auto-assigns public IP addresses"
    assert recommendation["severity"] == "warning"
    assert "map_public_ip_on_launch" in recommendation["recommendation"]


def test_non_string_values_are_coerced_to_json_safe_strings():
    hostile = {
        "rule_id": "TM-NET-001",
        "severity": "error",
        "message": {"nested": ["<script>", "quote\"and\\backslash"]},
        "file": ["not", "a", "path"],
        "id": 12345,
        "recommendation": None,
    }

    recommendation = build_recommendations([hostile])[0]

    assert isinstance(recommendation["message"], str)
    assert isinstance(recommendation["files"], list)
    assert all(isinstance(item, str) for item in recommendation["files"])
    assert recommendation["evidence_ids"] == ["12345"]


def test_caps_files_and_evidence_ids():
    findings = [
        _finding("TM-NET-001", "error", f"ssh {index}", f"file-{index}.tf", f"id-{index}")
        for index in range(15)
    ]

    recommendation = build_recommendations(findings)[0]

    assert len(recommendation["files"]) == 10
    assert len(recommendation["evidence_ids"]) == 10


def test_analyze_endpoint_returns_public_ssh_recommendation(tmp_path):
    (tmp_path / "main.tf").write_text(
        '''resource "aws_security_group" "web" {
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
''',
        encoding="utf-8",
    )

    response = client.post("/v1/analyze", json={"workspace_path": str(tmp_path)})

    assert response.status_code == 200
    recommendations = response.json()["recommendations"]
    assert isinstance(recommendations, list)
    ssh = next(item for item in recommendations if item["rule_id"] == "TM-NET-001")
    assert ssh["severity"] == "error"
    assert ssh["count"] == 1
    assert ssh["priority"] == 1
    assert ssh["evidence_ids"]
