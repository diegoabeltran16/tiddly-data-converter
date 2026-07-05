"""S0140 tests for persisted human-review admission gate."""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

from relation_admission_gate import (  # noqa: E402
    ADMISSION_READY,
    BLOCKED,
    apply_persisted_human_review,
    build_deferred_human_decisions,
    build_patch_preview,
    build_review_queue,
    evaluate_gate,
    validate_human_review_decisions_doc,
    write_review_artifacts,
    write_s0140_admission_outputs,
)


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canon(relations: list[dict] | None = None, source_text: str = "approved excerpt") -> dict:
    return {
        "src-001": {
            "id": "src-001",
            "title": "Source",
            "text": source_text,
            "relations": relations or [],
        },
        "tgt-002": {
            "id": "tgt-002",
            "title": "Target",
            "text": "target text",
            "relations": [],
        },
    }


def _candidate(
    cid: str = "rc1_a1b2c3d4e5f6a7b8",
    rel_type: str = "referencia_a",
    tgt_id: str = "tgt-002",
    resolution_status: str = "resolved",
    excerpt: str = "approved excerpt",
    score: float = 0.92,
) -> dict:
    return {
        "candidate_id": cid,
        "schema_version": "relations-candidate/v1",
        "status": "candidate",
        "source": {"tiddler_id": "src-001", "title": "Source"},
        "target": {
            "tiddler_id": tgt_id,
            "title": "Target",
            "resolution_status": resolution_status,
        },
        "relation": {"type": rel_type, "direction": "source_to_target"},
        "evidence": {"kind": "explicit_reference", "excerpt": excerpt},
        "confidence": {"score": score, "method": "rule_based", "risk_flags": []},
        "provenance": {"source_path": "data/out/local/tiddlers_1.jsonl"},
    }


def _approved_decisions(cid: str = "rc1_a1b2c3d4e5f6a7b8") -> dict:
    return {
        "schema": "relation-human-review-decisions/v1",
        "session": "S0140",
        "dry_run": True,
        "applied_to_canon": False,
        "reviewer": {
            "reviewer_id": "local-operator",
            "reviewer_role": "human_operator",
        },
        "decisions": [
            {
                "candidate_id": cid,
                "decision": "approved_for_dry_run",
                "reviewed_at": "2026-06-10T12:00:00Z",
                "rationale": "Evidence, source, target and type were checked.",
                "checks": {
                    "source_verified": True,
                    "target_verified": True,
                    "evidence_excerpt_verified": True,
                    "relation_type_checked_against_s0139": True,
                    "not_duplicate_of_existing_relation": True,
                    "no_canonical_write_requested": True,
                },
            }
        ],
    }


def _deferred_decisions(cid: str = "rc1_a1b2c3d4e5f6a7b8") -> dict:
    doc = _approved_decisions(cid)
    doc["decisions"][0]["decision"] = "deferred"
    doc["decisions"][0]["reviewed_at"] = ""
    doc["decisions"][0]["rationale"] = "No human approval persisted."
    doc["decisions"][0]["checks"] = {
        "source_verified": False,
        "target_verified": False,
        "evidence_excerpt_verified": False,
        "relation_type_checked_against_s0139": False,
        "not_duplicate_of_existing_relation": False,
        "no_canonical_write_requested": True,
    }
    return doc


def _apply_and_eval(candidate: dict, decisions: dict | None, canon: dict, type_policy: dict | None = None) -> dict:
    merged, notes = apply_persisted_human_review(candidate, decisions)
    return evaluate_gate(merged, canon, type_policy=type_policy, human_review_notes=notes)


def test_approved_human_candidate_reaches_admission_ready_dry_run() -> None:
    result = _apply_and_eval(_candidate(), _approved_decisions(), _canon())

    assert result["gate_status"] == ADMISSION_READY
    assert result["decision"] == ADMISSION_READY
    assert result["applied_to_canon"] is False


def test_candidate_without_human_review_is_blocked() -> None:
    result = evaluate_gate(_candidate(), _canon())

    assert result["gate_status"] == BLOCKED
    assert result["decision"] == "blocked_missing_human_review"


def test_deferred_human_review_is_blocked() -> None:
    result = _apply_and_eval(_candidate(), _deferred_decisions(), _canon())

    assert result["gate_status"] == BLOCKED
    assert result["decision"] == "blocked_missing_human_review"


def test_unresolved_target_is_blocked() -> None:
    candidate = _candidate(tgt_id="missing-target", resolution_status="unresolved")
    result = _apply_and_eval(candidate, _approved_decisions(), _canon())

    assert result["gate_status"] == BLOCKED
    assert result["decision"] == "blocked_unresolved_target"


def test_unverified_evidence_is_blocked() -> None:
    result = _apply_and_eval(_candidate(excerpt="not in source"), _approved_decisions(), _canon())

    assert result["gate_status"] == BLOCKED
    assert result["decision"] == "blocked_unverified_evidence"


def test_duplicate_relation_is_blocked() -> None:
    canon = _canon(relations=[{"type": "referencia_a", "target_id": "tgt-002"}])
    result = _apply_and_eval(_candidate(), _approved_decisions(), canon)

    assert result["gate_status"] == BLOCKED
    assert result["decision"] == "blocked_duplicate_existing"


def test_legacy_readonly_type_cannot_be_ready() -> None:
    policy = {"define": {"decision_status": "legacy_readonly"}}
    result = _apply_and_eval(_candidate(rel_type="define"), _approved_decisions(), _canon(), policy)

    assert result["gate_status"] == BLOCKED
    assert result["decision"] == "blocked_s0139_type_policy"


def test_structural_only_type_cannot_be_ready() -> None:
    policy = {"child_of": {"decision_status": "structural_only"}}
    result = _apply_and_eval(_candidate(rel_type="child_of"), _approved_decisions(), _canon(), policy)

    assert result["gate_status"] == BLOCKED
    assert result["decision"] == "blocked_s0139_type_policy"


def test_alias_candidate_is_not_applied_automatically() -> None:
    policy = {"usa": {"decision_status": "legacy_alias_candidate", "proposed_canonical_type": "references"}}
    result = _apply_and_eval(_candidate(rel_type="usa"), _approved_decisions(), _canon(), policy)

    assert result["gate_status"] == BLOCKED
    assert result["decision"] == "blocked_legacy_alias_policy"
    assert result["relation_type"] == "usa"


def test_patch_preview_declares_not_applied() -> None:
    ready = _apply_and_eval(_candidate(), _approved_decisions(), _canon())
    preview = build_patch_preview([ready])

    assert preview["dry_run"] is True
    assert preview["applied_to_canon"] is False
    assert preview["canon_modified"] is False
    assert preview["not_a_patch"] is True


def test_no_tiddlers_jsonl_changes_during_gate_test(tmp_path: Path) -> None:
    shard = tmp_path / "tiddlers_1.jsonl"
    shard.write_text(json.dumps({"id": "src-001", "relations": []}) + "\n", encoding="utf-8")
    before = _hash(shard)

    _apply_and_eval(_candidate(), _approved_decisions(), _canon())

    assert _hash(shard) == before


def test_human_review_decisions_doc_validates_against_schema(tmp_path: Path) -> None:
    doc = _approved_decisions()
    assert validate_human_review_decisions_doc(doc) == []

    queue = build_review_queue(
        {"results": [{"decision": "review_required", **_candidate(), "source_id": "src-001",
                      "target_id": "tgt-002", "relation_type": "referencia_a",
                      "confidence_score": 0.92, "evidence_kind": "explicit_reference",
                      "evidence_excerpt": "approved excerpt", "risk_level": "low"}]},
        source_report="test-report.json",
    )
    paths = write_review_artifacts(tmp_path, queue, build_deferred_human_decisions(queue))
    assert json.loads(paths["schema"].read_text(encoding="utf-8"))["$id"] == "relation-human-review-decisions/v1"


def test_report_csv_contains_required_columns(tmp_path: Path) -> None:
    result = _apply_and_eval(_candidate(), _approved_decisions(), _canon())
    paths = write_s0140_admission_outputs(
        tmp_path,
        [result],
        candidates_file=tmp_path / "candidates.jsonl",
        canon_glob=str(tmp_path / "tiddlers_*.jsonl"),
    )

    with paths["review_csv"].open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        assert {"candidate_id", "decision", "human_review_decision"}.issubset(reader.fieldnames or [])
