#!/usr/bin/env python3
"""Focused tests for RULE-23 relational coverage metrics."""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python_scripts"))

import audit_normative_projection as audit  # noqa: E402


def test_rule23_reports_canon_and_chunk_coverage() -> None:
    canon_records = [
        {
            "id": "n1",
            "title": "#### 🌀 Balance de sesión 1 = ejemplo",
            "role_primary": "log",
            "taxonomy_path": ["session/log"],
            "relations": [],
        },
        {
            "id": "n2",
            "title": "## 🧭🧱 Protocolo de Sesión",
            "role_primary": "glossary",
            "taxonomy_path": ["core/protocol"],
            "relations": [{"type": "usa", "target_id": "n1"}],
        },
    ]
    chunks = [
        {
            "chunk_id": "n2::chunk:0",
            "relation_targets": [{"type": "usa", "target_id": "n1"}],
            "relation_count": 1,
        },
        {
            "chunk_id": "n1::chunk:0",
            "relation_targets": [],
            "relation_count": 0,
        },
    ]

    findings = audit.evaluate_corpus_level(canon_records, [], [], chunks)
    rule23 = next(f for f in findings if f["rule_id"] == "RULE-23")
    metrics = rule23["metrics"]

    assert metrics["rule"] == "RULE-23"
    assert metrics["name"] == "relational_coverage"
    assert metrics["total_nodes"] == 2
    assert metrics["nodes_with_relations"] == 1
    assert metrics["coverage_pct"] == 50.0
    assert metrics["by_role_primary"]["log"]["nodes_without_relations"] == 1
    assert metrics["chunks_ai"]["total_chunks"] == 2
    assert metrics["chunks_ai"]["chunks_with_relation_targets"] == 2
    assert metrics["chunks_ai"]["chunks_with_non_empty_relation_targets"] == 1
    assert metrics["chunks_ai"]["chunks_with_relation_count_mismatch"] == 0
    assert rule23["compliance_status"] == "warn"
