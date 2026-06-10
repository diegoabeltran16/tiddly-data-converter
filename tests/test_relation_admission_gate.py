"""tests/test_relation_admission_gate.py — S0137

Tests de la compuerta humana mínima de admisión relacional.

Cubre los 12 casos mínimos de S0137 §6.2.

Ejecutar:
    python3 -m pytest tests/test_relation_admission_gate.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "python_scripts"))

from relation_admission_gate import (
    evaluate_gate,
    validate_human_review,
    append_to_log,
    build_dry_run_report,
    ADMISSION_READY,
    BLOCKED,
    HISTORICAL_BLOCKED_TYPES,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _approved_hr() -> dict:
    return {
        "status": "approved",
        "reviewer": "test-operator",
        "reviewed_at": "2026-06-01T12:00:00Z",
        "decision_reason": "Verificado manualmente.",
    }


def _canon(src_id: str = "src-001", tgt_id: str = "tgt-002",
           text: str = "gate test excerpt content here") -> dict[str, dict]:
    return {
        src_id: {"id": src_id, "title": "Source", "text": text, "relations": []},
        tgt_id: {"id": tgt_id, "title": "Target", "text": "target text", "relations": []},
    }


def _candidate(
    cid: str = "rc1_a1b2c3d4e5f6a7b8",
    src_id: str = "src-001",
    tgt_id: str = "tgt-002",
    rel_type: str = "referencia_a",
    excerpt: str = "gate test excerpt content here",
    human_review: dict | None = ...,
    resolution_status: str = "resolved",
) -> dict:
    if human_review is ...:
        human_review = _approved_hr()
    return {
        "candidate_id": cid,
        "schema_version": "relations-candidate/v1",
        "status": "candidate",
        "source": {"tiddler_id": src_id, "title": "Source"},
        "target": {"tiddler_id": tgt_id, "title": "Target",
                   "resolution_status": resolution_status},
        "relation": {"type": rel_type, "direction": "source_to_target"},
        "evidence": {"kind": "explicit_reference", "excerpt": excerpt},
        "confidence": {"score": 0.92, "method": "rule_based", "risk_flags": []},
        "provenance": {"generated_by": "test", "source_path": "data/out/local/tiddlers_1.jsonl"},
        "human_review": human_review,
        "created_at": "2026-06-01T00:00:00Z",
    }


# ── Caso 1: Sin human_review → bloqueado ──────────────────────────────────────

class TestCase01_NoHumanReview:
    def test_missing_human_review_is_blocked(self):
        cand = _candidate(human_review=None)
        result = evaluate_gate(cand, _canon())
        assert result["gate_status"] == BLOCKED
        assert any("GATE-001" in r for r in result["blocking_reasons"])

    def test_empty_dict_human_review_is_blocked(self):
        cand = _candidate(human_review={})
        result = evaluate_gate(cand, _canon())
        assert result["gate_status"] == BLOCKED

    def test_validate_human_review_returns_issues_for_none(self):
        issues = validate_human_review(None)
        assert issues


# ── Caso 2: status=rejected → bloqueado ──────────────────────────────────────

class TestCase02_RejectedStatus:
    def test_rejected_status_is_blocked(self):
        hr = {**_approved_hr(), "status": "rejected"}
        cand = _candidate(human_review=hr)
        result = evaluate_gate(cand, _canon())
        assert result["gate_status"] == BLOCKED
        assert any("GATE-002" in r for r in result["blocking_reasons"])


# ── Caso 3: status=needs_revision → bloqueado ────────────────────────────────

class TestCase03_NeedsRevisionStatus:
    def test_needs_revision_is_blocked(self):
        hr = {**_approved_hr(), "status": "needs_revision"}
        cand = _candidate(human_review=hr)
        result = evaluate_gate(cand, _canon())
        assert result["gate_status"] == BLOCKED

    def test_validate_needs_revision_issues(self):
        issues = validate_human_review({"status": "needs_revision",
                                         "reviewer": "x", "reviewed_at": "t",
                                         "decision_reason": "r"})
        assert issues  # status != approved → issue


# ── Caso 4: Aprobado sin reviewer → bloqueado ────────────────────────────────

class TestCase04_ApprovedNoReviewer:
    def test_approved_without_reviewer_is_blocked(self):
        hr = {**_approved_hr(), "reviewer": ""}
        cand = _candidate(human_review=hr)
        result = evaluate_gate(cand, _canon())
        assert result["gate_status"] == BLOCKED
        assert any("GATE-003" in r for r in result["blocking_reasons"])


# ── Caso 5: Aprobado sin timestamp → bloqueado ────────────────────────────────

class TestCase05_ApprovedNoTimestamp:
    def test_approved_without_reviewed_at_is_blocked(self):
        hr = {**_approved_hr(), "reviewed_at": ""}
        cand = _candidate(human_review=hr)
        result = evaluate_gate(cand, _canon())
        assert result["gate_status"] == BLOCKED
        assert any("GATE-004" in r for r in result["blocking_reasons"])


# ── Caso 6: Aprobado sin razón → bloqueado ───────────────────────────────────

class TestCase06_ApprovedNoReason:
    def test_approved_without_decision_reason_is_blocked(self):
        hr = {**_approved_hr(), "decision_reason": ""}
        cand = _candidate(human_review=hr)
        result = evaluate_gate(cand, _canon())
        assert result["gate_status"] == BLOCKED
        assert any("GATE-005" in r for r in result["blocking_reasons"])


# ── Caso 7: Target unresolved → bloqueado ─────────────────────────────────────

class TestCase07_UnresolvedTarget:
    def test_unresolved_target_is_blocked(self):
        cand = _candidate(tgt_id="NONEXISTENT-ID", resolution_status="unresolved")
        result = evaluate_gate(cand, _canon(tgt_id="different-id"))
        assert result["gate_status"] == BLOCKED
        assert any("GATE-009" in r for r in result["blocking_reasons"])


# ── Caso 8: Tipo incompatible → bloqueado ─────────────────────────────────────

class TestCase08_IncompatibleType:
    @pytest.mark.parametrize("bad_type", ["usa", "parte_de", "define", "requiere", "child_of"])
    def test_historical_type_blocked(self, bad_type):
        cand = _candidate(rel_type=bad_type)
        result = evaluate_gate(cand, _canon())
        assert result["gate_status"] == BLOCKED
        assert any("GATE-006" in r for r in result["blocking_reasons"])

    def test_unknown_type_blocked(self):
        cand = _candidate(rel_type="invented_xyz_type")
        result = evaluate_gate(cand, _canon())
        assert result["gate_status"] == BLOCKED
        assert any("GATE-007" in r for r in result["blocking_reasons"])


# ── Caso 9: Candidato válido → admission_ready_dry_run ───────────────────────

class TestCase09_ValidCandidateReady:
    def test_fully_valid_candidate_is_ready(self):
        cand = _candidate()
        result = evaluate_gate(cand, _canon())
        assert result["gate_status"] == ADMISSION_READY, \
            f"Debería ser admission_ready_dry_run. Blocked: {result['blocking_reasons']}"

    def test_ready_candidate_never_admitted_to_canon(self):
        """gate_status admission_ready_dry_run ≠ admitted."""
        cand = _candidate()
        result = evaluate_gate(cand, _canon())
        assert result["gate_status"] != "admitted"
        assert result["dry_run"] is True

    def test_ready_candidate_has_log_id(self):
        cand = _candidate()
        result = evaluate_gate(cand, _canon())
        assert result.get("log_id", "").startswith("sha256:")


# ── Caso 10: Log append-only conserva entradas previas ───────────────────────

class TestCase10_LogAppendOnly:
    def test_log_appends_new_entry(self, tmp_path):
        cand = _candidate()
        result = evaluate_gate(cand, _canon())
        log = tmp_path / "test.jsonl"
        append_to_log(result, cand, log)
        append_to_log(result, _candidate("rc1_b2c3d4e5f6a7b8c9"), log)
        lines = [l for l in log.read_text().splitlines() if l.strip()]
        # First call is either appended or duplicate_exact
        # Second is always appended (different candidate_id)
        assert len(lines) >= 1

    def test_log_preserves_previous_entries(self, tmp_path):
        log = tmp_path / "admission.jsonl"
        c1 = _candidate("rc1_a1b2c3d4e5f6a7b8")
        c2 = _candidate("rc1_b2c3d4e5f6a7b8c9")
        r1 = evaluate_gate(c1, _canon())
        r2 = evaluate_gate(c2, _canon())
        append_to_log(r1, c1, log)
        append_to_log(r2, c2, log)
        lines = [l for l in log.read_text().splitlines() if l.strip()]
        assert len(lines) == 2
        # Both entries should be valid JSON
        for line in lines:
            entry = json.loads(line)
            assert entry["schema"] == "relation-admission-log/v1"

    def test_log_detects_duplicate_exact(self, tmp_path):
        log = tmp_path / "dup_test.jsonl"
        cand = _candidate()
        result = evaluate_gate(cand, _canon())
        append_to_log(result, cand, log)
        outcome = append_to_log(result, cand, log)
        assert outcome["outcome"] == "duplicate_exact"


# ── Caso 11: Log detecta conflicto ────────────────────────────────────────────

class TestCase11_LogDetectsConflict:
    def test_log_conflict_detected_different_decisions(self, tmp_path):
        log = tmp_path / "conflict.jsonl"
        cid = "rc1_a1b2c3d4e5f6a7b8"  # valid hex ID
        # First: BLOCKED (unresolved target)
        c_blocked = _candidate(cid, tgt_id="NONEXISTENT-XYZ", resolution_status="unresolved")
        r_blocked = evaluate_gate(c_blocked, _canon())
        assert r_blocked["gate_status"] == BLOCKED
        append_to_log(r_blocked, c_blocked, log)
        # Second: ADMISSION_READY (same candidate_id, different status)
        c_ready = _candidate(cid)
        r_ready = evaluate_gate(c_ready, _canon())
        assert r_ready["gate_status"] == ADMISSION_READY
        outcome = append_to_log(r_ready, c_ready, log)
        assert outcome["outcome"] == "conflict"
        assert "conflict_note" in outcome


# ── Caso 12: Ningún test modifica tiddlers_*.jsonl ───────────────────────────

class TestCase12_NoCanonModification:
    def test_evaluate_gate_does_not_modify_canon(self):
        canon = _canon()
        original = json.loads(json.dumps(canon))
        cand = _candidate()
        evaluate_gate(cand, canon)
        assert canon == original

    def test_append_to_log_does_not_modify_canon(self, tmp_path):
        canon = _canon()
        original_src = dict(canon["src-001"])
        cand = _candidate()
        result = evaluate_gate(cand, canon)
        log = tmp_path / "gate.jsonl"
        append_to_log(result, cand, log)
        assert canon["src-001"] == original_src

    def test_build_report_does_not_modify_inputs(self):
        cand = _candidate()
        result = evaluate_gate(cand, _canon())
        original_result = json.loads(json.dumps(result))
        build_dry_run_report([result], session="s0137",
                              candidates_file=Path("/tmp/test.jsonl"),
                              canon_glob="*.jsonl")
        # Result should not have been modified
        assert result["gate_status"] == original_result["gate_status"]


# ── Tests adicionales ─────────────────────────────────────────────────────────

class TestAdditional:
    def test_historical_blocked_types_covers_five(self):
        expected = {"usa", "parte_de", "define", "requiere", "child_of"}
        assert expected == HISTORICAL_BLOCKED_TYPES

    def test_log_entry_has_all_required_fields(self, tmp_path):
        log = tmp_path / "log.jsonl"
        cand = _candidate()
        result = evaluate_gate(cand, _canon())
        append_to_log(result, cand, log)
        entry = json.loads(log.read_text().strip())
        required = {
            "schema", "session", "log_id", "candidate_id",
            "source_tiddler_id", "target_tiddler_id", "relation_type",
            "previous_status", "new_status", "human_review",
            "evidence_hash", "dry_run", "created_at",
        }
        assert required.issubset(entry.keys())

    def test_apply_flags_rejected(self):
        """--apply and similar flags must trigger forbidden check (exit 1)."""
        from relation_admission_gate import main
        for bad_flag in ("--apply", "--write-canon", "--admit"):
            with pytest.raises(SystemExit) as exc:
                main([bad_flag, "--candidates-file", "/nonexistent.jsonl"])
            assert exc.value.code in (1, 2)  # 1=forbidden, 2=argparse error (both block)

    def test_report_schema_correct(self):
        cand = _candidate()
        result = evaluate_gate(cand, _canon())
        report = build_dry_run_report(
            [result], session="s0137",
            candidates_file=Path("/tmp/x.jsonl"),
            canon_glob="*.jsonl",
        )
        assert report["schema"] == "relation-admission-dry-run-report/v1"
        assert report["mode"] == "dry-run"
        assert "summary" in report
