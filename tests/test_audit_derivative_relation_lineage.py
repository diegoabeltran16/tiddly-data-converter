#!/usr/bin/env python3
"""Focused tests for the S0179 derivative relation lineage audit."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

import audit_derivative_relation_lineage as audit  # noqa: E402


def _fixture_relation(source: str, target: str, evidence: str = "content_embedded") -> dict:
    return {
        "_source": source,
        "type": "define",
        "target_id": target,
        "evidence": evidence,
    }


def test_audit_output_contains_required_machine_readable_blocks(tmp_path: Path) -> None:
    out_dir = tmp_path / "s0179"

    subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "src/python_scripts/audit_derivative_relation_lineage.py"),
            "--out",
            str(out_dir),
        ],
        cwd=REPO_ROOT,
        check=True,
    )

    lineage = json.loads((out_dir / "current_derivative_relation_lineage.json").read_text())
    assert lineage["candidate_direct_consumption"]["detected"] is False
    assert lineage["controlled_v1"]["is_canonical_relation_v1"] is False
    assert lineage["controlled_v1"]["grants_canonical_authority"] is False
    assert lineage["content_embedded_count_semantics"]["explained"] is True

    report = (out_dir / "derivative_relation_contract_report.md").read_text()
    for section in audit.REQUIRED_REPORT_SECTIONS:
        assert f"## {section}" in report


def test_candidate_direct_consumption_negative_probe_detects_path_reader(tmp_path: Path) -> None:
    candidate_file = tmp_path / "relation_candidates.jsonl"
    candidate_file.write_text('{"candidate_id":"candidate_1"}\n', encoding="utf-8")

    result = audit.analyze_candidate_direct_consumption(
        candidate_path=candidate_file,
        candidate_ids={"candidate_1"},
        productive_serialized_text="no candidate ids here",
        producer_sources={
            "diagnostic_probe.py": "Path('data/out/local/pipeline/relation_candidates/current').read_text()",
        },
        fixture_probe_used=True,
    )

    assert result["detected"] is True
    assert result["producer_path_hits"] == ["diagnostic_probe.py"]
    assert result["explicit_reader_hits"] == ["diagnostic_probe.py"]


def test_controlled_v1_negative_authority_probe_detects_mislabeled_schema() -> None:
    result = audit.classify_controlled_v1("canonical-relation/v1")

    assert result["elevation_detected"] is True
    assert result["is_canonical_relation_v1"] is True
    assert result["grants_canonical_authority"] is False


def test_count_semantics_distinguish_explained_delta_from_loss() -> None:
    embedded = [
        _fixture_relation("s1", "t1"),
        _fixture_relation("s1", "t2"),
        _fixture_relation("s2", "t1"),
    ]
    projected = [
        _fixture_relation("s1", "t1"),
        _fixture_relation("s1", "t2"),
    ]

    result = audit.explain_content_embedded_counts(embedded, projected)

    assert result["delta"]["value"] == 1
    assert result["delta"]["comparable"] is True
    assert result["delta"]["disposition"].startswith("not_a_target_universe_loss")
    assert result["explained"] is True
    assert result["delta"]["unprojected_occurrences"][0]["source_id"] == "s2"


def test_count_semantics_marks_unexplained_difference_for_review() -> None:
    embedded = [_fixture_relation("s1", "t1"), _fixture_relation("s1", "t2")]
    projected = [_fixture_relation("s1", "t1")]

    result = audit.explain_content_embedded_counts(embedded, projected)

    assert result["delta"]["value"] == 1
    assert result["delta"]["disposition"] == "requires_review"
    assert result["explained"] is False
