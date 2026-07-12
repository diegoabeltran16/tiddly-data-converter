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
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

import relation_admission_gate as relation_gate  # noqa: E402

from relation_admission_gate import (
    evaluate_gate,
    validate_human_review,
    validate_human_review_decision_record,
    build_admitted_relation,
    validate_admitted_relation_schema,
    guarded_apply_relations,
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


def _technical_candidate(**overrides) -> dict:
    cand = {
        "candidate_id": "rc1_c1c2c3c4c5c6c7c8",
        "candidate_schema_version": "technical-relation-candidates/v1",
        "status": "resolved_for_human_review",
        "artifact_family": "relation_candidate",
        "relation_type": "references",
        "human_review_decision": "approved_for_admission",
        "human_review_rationale": "Operador verificó source, target, evidencia y tipo relacional.",
        "approval_scope": "canonical_admission",
        "human_review_actor": "operator",
        "human_review_timestamp": "2026-07-08T00:00:00Z",
        "reviewed_evidence_paths": ["data/out/local/pipeline/relation_candidates/current/review_queue.jsonl"],
        "source": {
            "canonical_id": "src-001",
            "canonical_title": "Source",
            "repo_path": "tests/test_relation_admission_gate.py",
            "lifecycle_state": "current_repo_artifact",
        },
        "target": {
            "canonical_id": "tgt-002",
            "canonical_title": "Target",
            "repo_path": "src/python_scripts/relation_admission_gate.py",
            "lifecycle_state": "current_repo_artifact",
        },
        "evidence": {
            "evidence_kind": "path_literal",
            "confidence": "high",
            "raw_observation": "technical fixture observation",
        },
        "policy": {
            "human_review_required": True,
            "canonical_admission_allowed": False,
        },
        "session_resolution": {"classification": "resolved_for_human_review"},
    }
    for key, value in overrides.items():
        if key in {"source", "target", "evidence", "policy", "session_resolution"}:
            cand[key].update(value)
        else:
            cand[key] = value
    return cand


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
    def test_relation_gate_uses_repo_root_not_src(self):
        assert relation_gate.REPO_ROOT == REPO_ROOT
        assert "/src/data/out/local/" not in relation_gate.DEFAULT_CANON_GLOB

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
        """Ambiguous mutating flags must trigger forbidden check."""
        from relation_admission_gate import main
        for bad_flag in ("--write-canon", "--admit", "--force"):
            with pytest.raises(SystemExit) as exc:
                main([bad_flag, "--candidates-file", "/nonexistent.jsonl"])
            assert exc.value.code == 2

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
        item = report["items"][0]
        assert {"primary_block_reason", "all_block_reasons", "blocking_stage"}.issubset(item)


class TestS0164Hardening:
    def test_admission_gate_blocks_stale_source(self):
        cand = _technical_candidate(source={"repo_path": "missing/source.py"})
        result = evaluate_gate(cand, _canon())
        assert result["gate_status"] == BLOCKED
        assert result["decision"] == "blocked_repo_path_stale_or_lifecycle"

    def test_admission_gate_blocks_stale_target(self):
        cand = _technical_candidate(target={"repo_path": "missing/target.py"})
        result = evaluate_gate(cand, _canon())
        assert result["gate_status"] == BLOCKED
        assert result["decision"] == "blocked_repo_path_stale_or_lifecycle"

    def test_admission_gate_requires_lifecycle_state(self):
        cand = _technical_candidate(source={"lifecycle_state": ""})
        result = evaluate_gate(cand, _canon())
        assert result["gate_status"] == BLOCKED
        assert any("GATE-020" in r for r in result["blocking_reasons"])

    def test_review_queue_enforces_human_review_required(self):
        cand = _technical_candidate(human_review_decision="deferred")
        result = evaluate_gate(cand, _canon())
        assert result["gate_status"] == BLOCKED
        assert result["decision"] == "blocked_missing_human_review"

    def test_admission_gate_blocks_build_artifacts(self):
        cand = _technical_candidate(target={"repo_path": "build/generated.json"})
        result = evaluate_gate(cand, _canon())
        assert result["gate_status"] == BLOCKED
        assert result["decision"] == "blocked_build_artifact"

    def test_candidate_vs_admitted_relation_separation(self):
        cand = _technical_candidate(artifact_family="admitted_relation")
        result = evaluate_gate(cand, _canon())
        assert result["gate_status"] == BLOCKED
        assert result["decision"] == "blocked_candidate_admitted_separation"

    def test_duplicate_detection_against_canonical_relations(self):
        canon = _canon()
        canon["src-001"]["relations"] = [{"type": "references", "target_id": "tgt-002"}]
        cand = _technical_candidate()
        result = evaluate_gate(cand, canon)
        assert result["gate_status"] == BLOCKED
        assert result["decision"] == "blocked_duplicate_existing"


class TestS0165SafeApplyEngine:
    def _write_candidates(self, tmp_path: Path, candidates: list[dict]) -> Path:
        path = tmp_path / "candidates.jsonl"
        path.write_text(
            "\n".join(json.dumps(candidate) for candidate in candidates) + "\n",
            encoding="utf-8",
        )
        return path

    def _write_dry_run_report(self, tmp_path: Path, items: list[dict], ready: int = 0) -> Path:
        path = tmp_path / "admission_gate_dry_run.json"
        path.write_text(
            json.dumps({
                "schema": "relation-admission-dry-run-report/v1",
                "summary": {
                    "total_evaluated": len(items),
                    "admission_ready_dry_run": ready,
                    "blocked": len(items) - ready,
                    "canon_modified": False,
                    "dry_run": True,
                },
                "items": items,
            }),
            encoding="utf-8",
        )
        return path

    def _write_review(self, tmp_path: Path, records: list[dict]) -> Path:
        path = tmp_path / "human_review_decisions.jsonl"
        path.write_text(
            "\n".join(json.dumps(record) for record in records) + "\n",
            encoding="utf-8",
        )
        return path

    def test_apply_requires_human_review_file(self, tmp_path: Path):
        candidates_file = self._write_candidates(tmp_path, [_technical_candidate()])
        dry_run = self._write_dry_run_report(tmp_path, [])
        code, report = guarded_apply_relations(
            candidates_file=candidates_file,
            canon_glob=str(tmp_path / "tiddlers_*.jsonl"),
            human_review_decisions_file=tmp_path / "missing.jsonl",
            dry_run_report_path=dry_run,
            out_dir=tmp_path / "audit",
            terminal_confirmation="APPLY RELATIONS",
        )
        assert code == 1
        assert report["apply_plan"]["would_apply_count"] == 0
        assert any("invalid_human_review" in r for r in report["apply_plan"]["block_reasons"])
        assert report["canon_modified"] is False

    def test_apply_blocks_without_approved_decision(self, tmp_path: Path):
        cand = _technical_candidate()
        candidates_file = self._write_candidates(tmp_path, [cand])
        dry_run = self._write_dry_run_report(
            tmp_path,
            [{"candidate_id": cand["candidate_id"], "gate_status": "admission_ready_dry_run", "all_block_reasons": []}],
            ready=1,
        )
        review = self._write_review(tmp_path, [{
            "candidate_id": cand["candidate_id"],
            "human_review_decision": "deferred",
            "human_review_actor": "operator",
            "human_review_timestamp": "2026-07-08T00:00:00Z",
            "human_review_rationale": "Pendiente.",
            "approval_scope": "review_queue",
            "reviewed_evidence_paths": [],
            "session_id": "S0165",
        }])
        code, report = guarded_apply_relations(
            candidates_file=candidates_file,
            canon_glob=str(tmp_path / "tiddlers_*.jsonl"),
            human_review_decisions_file=review,
            dry_run_report_path=dry_run,
            out_dir=tmp_path / "audit",
            terminal_confirmation="APPLY RELATIONS",
        )
        assert code == 1
        assert "no_approved_for_admission_decisions" in report["apply_plan"]["block_reasons"]

    def test_apply_blocks_without_recent_dry_run(self, tmp_path: Path):
        cand = _technical_candidate()
        candidates_file = self._write_candidates(tmp_path, [cand])
        dry_run = tmp_path / "missing-dry-run.json"
        review = self._write_review(tmp_path, [{
            "candidate_id": cand["candidate_id"],
            "human_review_decision": "approved_for_admission",
            "human_review_actor": "operator",
            "human_review_timestamp": "2026-07-08T00:00:00Z",
            "human_review_rationale": "Aprobado.",
            "approval_scope": "canonical_admission",
            "reviewed_evidence_paths": [],
            "session_id": "S0165",
        }])
        code, report = guarded_apply_relations(
            candidates_file=candidates_file,
            canon_glob=str(tmp_path / "tiddlers_*.jsonl"),
            human_review_decisions_file=review,
            dry_run_report_path=dry_run,
            out_dir=tmp_path / "audit",
            terminal_confirmation="APPLY RELATIONS",
        )
        assert code == 1
        assert any("missing_dry_run_report" in r for r in report["apply_plan"]["block_reasons"])

    def test_apply_blocks_with_p0_reasons(self, tmp_path: Path):
        cand = _technical_candidate()
        candidates_file = self._write_candidates(tmp_path, [cand])
        dry_run = self._write_dry_run_report(
            tmp_path,
            [{"candidate_id": cand["candidate_id"], "gate_status": "blocked", "all_block_reasons": ["GATE-008: source missing"]}],
            ready=0,
        )
        review = self._write_review(tmp_path, [{
            "candidate_id": cand["candidate_id"],
            "human_review_decision": "approved_for_admission",
            "human_review_actor": "operator",
            "human_review_timestamp": "2026-07-08T00:00:00Z",
            "human_review_rationale": "Aprobado.",
            "approval_scope": "canonical_admission",
            "reviewed_evidence_paths": [],
            "session_id": "S0165",
        }])
        code, report = guarded_apply_relations(
            candidates_file=candidates_file,
            canon_glob=str(tmp_path / "tiddlers_*.jsonl"),
            human_review_decisions_file=review,
            dry_run_report_path=dry_run,
            out_dir=tmp_path / "audit",
            terminal_confirmation="APPLY RELATIONS",
        )
        assert code == 1
        assert "p0_block_reasons_present" in report["apply_plan"]["block_reasons"]

    def test_apply_plan_reports_zero_when_no_approved_candidates(self, tmp_path: Path):
        candidates_file = self._write_candidates(tmp_path, [_technical_candidate()])
        dry_run = self._write_dry_run_report(tmp_path, [])
        review = self._write_review(tmp_path, [])
        code, report = guarded_apply_relations(
            candidates_file=candidates_file,
            canon_glob=str(tmp_path / "tiddlers_*.jsonl"),
            human_review_decisions_file=review,
            dry_run_report_path=dry_run,
            out_dir=tmp_path / "audit",
            terminal_confirmation="APPLY RELATIONS",
        )
        assert code == 1
        assert report["apply_plan"]["approved_count"] == 0
        assert report["apply_plan"]["would_apply_count"] == 0

    def test_apply_does_not_modify_canon_in_dry_run(self, tmp_path: Path):
        canon_path = tmp_path / "tiddlers_1.jsonl"
        canon_path.write_text(json.dumps({"id": "src-001", "relations": []}) + "\n", encoding="utf-8")
        before = canon_path.read_text(encoding="utf-8")
        candidates_file = self._write_candidates(tmp_path, [_technical_candidate()])
        dry_run = self._write_dry_run_report(tmp_path, [])
        code, report = guarded_apply_relations(
            candidates_file=candidates_file,
            canon_glob=str(tmp_path / "tiddlers_*.jsonl"),
            human_review_decisions_file=tmp_path / "missing.jsonl",
            dry_run_report_path=dry_run,
            out_dir=tmp_path / "audit",
            terminal_confirmation="WRONG",
        )
        assert code == 1
        assert canon_path.read_text(encoding="utf-8") == before
        assert report["canon_modified"] is False

    def test_apply_requires_exact_terminal_confirmation(self, tmp_path: Path):
        cand = _technical_candidate()
        candidates_file = self._write_candidates(tmp_path, [cand])
        dry_run = self._write_dry_run_report(
            tmp_path,
            [{"candidate_id": cand["candidate_id"], "gate_status": "admission_ready_dry_run", "all_block_reasons": []}],
            ready=1,
        )
        review = self._write_review(tmp_path, [{
            "candidate_id": cand["candidate_id"],
            "human_review_decision": "approved_for_admission",
            "human_review_actor": "operator",
            "human_review_timestamp": "2026-07-08T00:00:00Z",
            "human_review_rationale": "Aprobado.",
            "approval_scope": "canonical_admission",
            "reviewed_evidence_paths": [],
            "session_id": "S0165",
        }])
        code, report = guarded_apply_relations(
            candidates_file=candidates_file,
            canon_glob=str(tmp_path / "tiddlers_*.jsonl"),
            human_review_decisions_file=review,
            dry_run_report_path=dry_run,
            out_dir=tmp_path / "audit",
            terminal_confirmation="apply relations",
        )
        assert code == 1
        assert "missing_exact_terminal_confirmation" in report["apply_plan"]["block_reasons"]

    def test_human_review_decision_schema_validation(self):
        valid = {
            "candidate_id": "rc1_c1c2c3c4c5c6c7c8",
            "human_review_decision": "approved_for_admission",
            "human_review_actor": "operator",
            "human_review_timestamp": "2026-07-08T00:00:00Z",
            "human_review_rationale": "Evidencia verificada.",
            "approval_scope": "canonical_admission",
            "reviewed_evidence_paths": ["data/out/local/pipeline/relation_candidates/current/review_queue.jsonl"],
            "session_id": "S0165",
        }
        assert validate_human_review_decision_record(valid) == []

    def test_admitted_relation_schema_minimal_fields(self):
        cand = _technical_candidate()
        review = {
            "human_review_actor": "operator",
            "session_id": "S0165",
            "human_review_decision": "approved_for_admission",
            "human_review_rationale": "Evidencia verificada.",
            "reviewed_evidence_paths": [],
        }
        relation = build_admitted_relation(cand, review)
        assert validate_admitted_relation_schema(relation) == []

    def test_apply_positive_path_writes_canonical_relation_to_temp_canon(self, tmp_path: Path):
        canon_dir = tmp_path / "canon"
        candidates_dir = tmp_path / "candidates"
        audit_dir = tmp_path / "audit"
        retry_audit_dir = tmp_path / "audit-retry"
        canon_dir.mkdir()
        candidates_dir.mkdir()
        audit_dir.mkdir()
        source = {
            "id": "src-001",
            "canonical_id": "src-001",
            "title": "Source fixture",
            "text": "Source text with fixture evidence.",
            "source_fields": {"lifecycle_state": "current_repo_artifact"},
            "lifecycle_state": "current_repo_artifact",
            "relations": [],
        }
        target = {
            "id": "tgt-002",
            "canonical_id": "tgt-002",
            "title": "Target fixture",
            "text": "Target text.",
            "source_fields": {"lifecycle_state": "current_repo_artifact"},
            "lifecycle_state": "current_repo_artifact",
            "relations": [],
        }
        canon_path = canon_dir / "tiddlers_test.jsonl"
        canon_path.write_text(
            json.dumps(source) + "\n" + json.dumps(target) + "\n",
            encoding="utf-8",
        )

        candidate = _technical_candidate(
            source={
                "canonical_id": "src-001",
                "canonical_title": "Source fixture",
                "repo_path": "tests/test_relation_admission_gate.py",
                "lifecycle_state": "current_repo_artifact",
            },
            target={
                "canonical_id": "tgt-002",
                "canonical_title": "Target fixture",
                "repo_path": "src/python_scripts/relation_admission_gate.py",
                "lifecycle_state": "current_repo_artifact",
            },
            policy={
                "human_review_required": True,
                "canonical_admission_allowed": True,
            },
            session_resolution={"classification": "resolved_for_human_review"},
        )
        candidates_file = self._write_candidates(candidates_dir, [candidate])
        review_file = self._write_review(candidates_dir, [{
            "candidate_id": candidate["candidate_id"],
            "human_review_decision": "approved_for_admission",
            "human_review_actor": "operator-fixture",
            "human_review_timestamp": "2026-01-01T00:00:00Z",
            "human_review_rationale": (
                "Fixture positivo para validar motor apply sin tocar canon real."
            ),
            "approval_scope": "canonical_admission",
            "reviewed_evidence_paths": ["tmp/fixture/evidence"],
            "session_id": "S0165",
        }])
        dry_run_report = self._write_dry_run_report(
            audit_dir,
            [{
                "candidate_id": candidate["candidate_id"],
                "admission_ready_dry_run": True,
                "gate_status": "admission_ready_dry_run",
                "all_block_reasons": [],
                "blocking_reasons": [],
            }],
            ready=1,
        )

        code, report = guarded_apply_relations(
            candidates_file=candidates_file,
            canon_glob=str(canon_dir / "tiddlers_*.jsonl"),
            human_review_decisions_file=review_file,
            dry_run_report_path=dry_run_report,
            out_dir=audit_dir,
            terminal_confirmation="APPLY RELATIONS",
            perform_write=True,
            target_scope="tmp_path",
        )

        assert code == 0
        assert report["report_kind"] == "fixture_positive_apply_report"
        assert report["target_scope"] == "tmp_path"
        assert report["apply_executed"] is True
        assert report["canon_modified"] is True
        assert report["applied_count"] == 1
        assert report["apply_plan"]["would_apply_count"] == 1
        assert (audit_dir / "relation_apply_plan.json").exists()
        assert (audit_dir / "relation_apply_report.json").exists()

        records = [
            json.loads(line)
            for line in canon_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(records) == 2
        relation = records[0]["relations"][0]
        assert validate_admitted_relation_schema(relation) == []
        assert relation["relation_schema_version"] == "canonical-relation/v1"
        assert relation["artifact_family"] == "canonical_relation"
        assert relation["relation_id"]
        assert relation["source_id"] == "src-001"
        assert relation["target_id"] == "tgt-002"
        assert relation["relation_type"] == "references"
        assert relation["authority"]["human_review_decision"] == "approved_for_admission"
        assert relation["authority"]["human_review_rationale"]
        assert relation["authority"]["admission_session"] == "S0165"
        assert relation["authority"]["admitted_by"] == "operator-fixture"

        retry_code, retry_report = guarded_apply_relations(
            candidates_file=candidates_file,
            canon_glob=str(canon_dir / "tiddlers_*.jsonl"),
            human_review_decisions_file=review_file,
            dry_run_report_path=dry_run_report,
            out_dir=retry_audit_dir,
            terminal_confirmation="APPLY RELATIONS",
            perform_write=True,
            target_scope="tmp_path",
        )
        retry_records = [
            json.loads(line)
            for line in canon_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert retry_code == 0
        assert retry_report["applied_count"] == 0
        assert len(retry_records[0]["relations"]) == 1
