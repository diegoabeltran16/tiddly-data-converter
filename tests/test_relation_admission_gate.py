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
    build_apply_plan,
    ADMISSION_READY,
    BLOCKED,
    HISTORICAL_BLOCKED_TYPES,
    rotate_current_run,
    rollback_relational_apply,
)


def test_current_rotation_archives_previous_mixed_log(tmp_path: Path) -> None:
    current = tmp_path / "relation_admission/current"
    current.mkdir(parents=True)
    (current / "current_relation_admission_log.jsonl").write_text(
        json.dumps({"candidate_id": "rc_s0161_old"}) + "\n",
        encoding="utf-8",
    )
    (current / "admission_gate_dry_run.json").write_text("{}\n", encoding="utf-8")

    rotation = rotate_current_run(current)

    assert rotation["rotated"] is True
    assert not (current / "current_relation_admission_log.jsonl").exists()
    archived = Path(rotation["history_path"])
    assert (archived / "current_relation_admission_log.jsonl").exists()


def test_apply_plan_deduplicates_same_canonical_edge_with_distinct_evidence(tmp_path: Path) -> None:
    first = _technical_candidate(candidate_id="rc1_" + "1" * 16)
    second = json.loads(json.dumps(first))
    second["candidate_id"] = "rc1_" + "2" * 16
    second["evidence"]["raw_observation"] = "same edge, second evidence"
    decisions = {
        candidate["candidate_id"]: {
            "human_review_decision": "approved_for_admission",
            "approval_scope": "canonical_admission",
            "human_review_reason_code": "EVIDENCE_AND_ENDPOINTS_VERIFIED",
        }
        for candidate in (first, second)
    }
    report_path = tmp_path / "dry-run.json"
    report_path.write_text("{}\n", encoding="utf-8")
    plan = build_apply_plan(
        candidates=[first, second],
        canon_glob=str(tmp_path / "tiddlers_*.jsonl"),
        human_review_decisions=decisions,
        dry_run_report={
            "items": [
                {"candidate_id": first["candidate_id"], "gate_status": ADMISSION_READY},
                {"candidate_id": second["candidate_id"], "gate_status": ADMISSION_READY},
            ],
        },
        dry_run_report_path=report_path,
        dry_run_recent=True,
    )
    assert plan["approved_count"] == 2
    assert plan["would_apply_count"] == 1
    assert plan["omitted_planned_count"] == 1
    assert plan["blocked_count"] == 0


def _write_current_run_artifacts(current: Path, run_id: str = "run-previous") -> dict[str, str]:
    current.mkdir(parents=True, exist_ok=True)
    payloads = {
        "current_relation_admission_log.jsonl": json.dumps({"candidate_id": "rc_old"}) + "\n",
        "admission_gate_dry_run.json": json.dumps({"summary": {"total_evaluated": 1}}) + "\n",
        "current_run_manifest.json": json.dumps({"run_id": run_id}) + "\n",
        "relational_operational_state.json": json.dumps({"verdict": "old"}) + "\n",
    }
    for name, content in payloads.items():
        (current / name).write_text(content, encoding="utf-8")
    return {name: relation_gate.sha256_path(current / name) for name in payloads}


def test_current_rotation_moves_all_explicit_artifacts_with_verified_archive(tmp_path: Path) -> None:
    current = tmp_path / "relation_admission/current"
    before = _write_current_run_artifacts(current)

    rotation = rotate_current_run(current)

    history = Path(rotation["history_path"])
    assert rotation["rotated"] is True
    assert not any((current / name).exists() for name in before)
    archive_manifest = json.loads((history / "archive_manifest.json").read_text())
    assert {item["source"].rsplit("/", 1)[-1] for item in archive_manifest["files"]} == set(before)
    assert {name: relation_gate.sha256_path(history / name) for name in before} == before
    assert not (history.parent / ".run-previous.tmp").exists()


def test_current_rotation_restores_all_files_when_a_move_fails(tmp_path: Path, monkeypatch) -> None:
    current = tmp_path / "relation_admission/current"
    before = _write_current_run_artifacts(current)
    original_move = relation_gate.shutil.move
    calls = 0

    def fail_second_move(source: str, destination: str) -> str:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated second move failure")
        return original_move(source, destination)

    monkeypatch.setattr(relation_gate.shutil, "move", fail_second_move)

    with pytest.raises(RuntimeError, match="current run archive aborted"):
        rotate_current_run(current)

    assert {name: relation_gate.sha256_path(current / name) for name in before} == before
    assert not (current.parent / "history/run-previous").exists()
    assert not (current.parent / "history/.run-previous.tmp").exists()


def test_current_rotation_handles_empty_current_and_rejects_history_collisions(tmp_path: Path) -> None:
    empty_current = tmp_path / "empty/current"
    assert rotate_current_run(empty_current) == {"rotated": False, "archived_files": [], "history_path": None}

    current = tmp_path / "relation_admission/current"
    before = _write_current_run_artifacts(current)
    (current.parent / "history/run-previous").mkdir(parents=True)

    with pytest.raises(FileExistsError, match="history collision"):
        rotate_current_run(current)

    assert {name: relation_gate.sha256_path(current / name) for name in before} == before


def test_current_manifest_is_published_only_after_report_and_log(tmp_path: Path) -> None:
    out = tmp_path / "audit/current"
    out.mkdir(parents=True)
    report = out / "admission_gate_dry_run.json"
    log = out / "current_relation_admission_log.jsonl"

    with pytest.raises(RuntimeError, match="requires published report and log"):
        relation_gate.write_current_run_manifest(
            out=out, candidates_file=tmp_path / "queue.jsonl", canon_glob=str(tmp_path / "canon/*.jsonl"),
            report_path=report, log_path=log, evaluated=0, human_decisions_path=None,
            rotation={"rotated": False, "archived_files": [], "history_path": None},
        )

    report.write_text("{}\n", encoding="utf-8")
    log.write_text("\n", encoding="utf-8")
    manifest = relation_gate.write_current_run_manifest(
        out=out, candidates_file=tmp_path / "queue.jsonl", canon_glob=str(tmp_path / "canon/*.jsonl"),
        report_path=report, log_path=log, evaluated=0, human_decisions_path=None,
        rotation={"rotated": False, "archived_files": [], "history_path": None},
    )

    assert manifest.exists()
    assert not (out / "current_run_manifest.json.tmp").exists()


def test_gate_summary_separates_awaiting_review_from_invalid() -> None:
    result = evaluate_gate(_candidate(human_review=None), _canon())
    report = build_dry_run_report(
        [result], session="current", candidates_file=Path("queue.jsonl"), canon_glob="canon/*.jsonl"
    )
    assert report["summary"]["awaiting_human_review"] == 1
    assert report["summary"]["technically_invalid"] == 0
    assert report["summary"]["human_deferred"] == 0
    assert "blocked" not in report["summary"]


def test_gate_summary_does_not_count_explicit_deferred_as_awaiting() -> None:
    result = evaluate_gate(_technical_candidate(human_review_decision="deferred"), _canon())
    report = build_dry_run_report(
        [result], session="current", candidates_file=Path("queue.jsonl"), canon_glob="canon/*.jsonl",
        persistent_human_decisions={"rc1_c1c2c3c4c5c6c7c8": {"human_review_decision": "deferred"}},
    )
    assert report["summary"]["awaiting_human_review"] == 0
    assert report["summary"]["human_deferred"] == 1
    assert report["summary"]["technically_invalid"] == 0


def test_human_review_status_is_derived_from_current_decision() -> None:
    result = evaluate_gate(_technical_candidate(), _canon())
    assert result["human_review_status"] == "approved_for_admission"
    assert result["human_review_decision"] == "approved_for_admission"
    assert result["human_review_status"] != "(absent)"


def test_structured_final_mix_reports_140_ready_and_17_deferred_without_invalid() -> None:
    ready = [
        {
            "candidate_id": f"ready-{index}", "gate_status": ADMISSION_READY,
            "decision": ADMISSION_READY, "relation_type": "depende_de",
            "blocking_reasons": [], "ok_reasons": [],
            "human_review_status": "approved_for_admission",
        }
        for index in range(140)
    ]
    deferred = [
        {
            "candidate_id": f"stale-{index}", "gate_status": BLOCKED,
            "decision": "blocked_missing_human_review", "relation_type": "depende_de",
            "blocking_reasons": ["GATE-016", "GATE-022"], "ok_reasons": [],
            "human_review_status": "deferred",
        }
        for index in range(17)
    ]
    decisions = {
        item["candidate_id"]: {"human_review_decision": "approved_for_admission"}
        for item in ready
    } | {
        item["candidate_id"]: {
            "human_review_decision": "deferred",
            "human_review_reason_code": "STALE_TARGET_PATH",
        }
        for item in deferred
    }
    summary = build_dry_run_report(
        ready + deferred, session="current", candidates_file=Path("queue.jsonl"),
        canon_glob="tiddlers_*.jsonl", persistent_human_decisions=decisions,
    )["summary"]
    assert summary["approved_for_admission"] == 140
    assert summary["human_deferred"] == 17
    assert summary["admission_ready_dry_run"] == 140
    assert summary["technically_invalid"] == 0
    assert summary["awaiting_human_review"] == 0


def _report_result(candidate_id: str, *, gate_status: str = BLOCKED,
                   decision: str = "blocked_missing_human_review") -> dict:
    return {
        "candidate_id": candidate_id,
        "gate_status": gate_status,
        "decision": decision,
        "relation_type": "depende_de",
        "blocking_reasons": [],
        "ok_reasons": [],
        "human_review_status": "(absent)",
    }


def _scoped_report(results: list[dict], decisions: dict[str, dict]) -> dict:
    return build_dry_run_report(
        results,
        session="current",
        candidates_file=Path("queue.jsonl"),
        canon_glob="tiddlers_*.jsonl",
        persistent_human_decisions=decisions,
    )


def test_report_scopes_persistent_decisions_to_evaluated_candidates() -> None:
    results = [_report_result("A"), _report_result("B")]
    persistent = {
        "A": {"human_review_decision": "approved_for_admission"},
        "B": {"human_review_decision": "deferred"},
        "X": {"human_review_decision": "approved_for_admission"},
    }

    report = _scoped_report(results, persistent)
    summary = report["summary"]

    assert persistent["X"]["human_review_decision"] == "approved_for_admission"
    assert summary["evaluated"] == 2
    assert summary["approved_for_admission"] == 1
    assert summary["human_deferred"] == 1
    assert summary["human_rejected"] == 0
    assert summary["awaiting_human_review"] == 0
    assert summary["admission_ready"] == 0


def test_report_human_dispositions_partition_current_results_and_ignore_external_rejections() -> None:
    results = [_report_result(candidate_id) for candidate_id in ("A", "B", "C", "D")]
    persistent = {
        "A": {"human_review_decision": "approved_for_admission"},
        "B": {"human_review_decision": "deferred"},
        "C": {"human_review_decision": "rejected"},
        "external-rejected": {"human_review_decision": "rejected"},
    }

    summary = _scoped_report(results, persistent)["summary"]

    assert summary["approved_for_admission"] == 1
    assert summary["human_deferred"] == 1
    assert summary["human_rejected"] == 1
    assert summary["awaiting_human_review"] == 1
    assert (
        summary["approved_for_admission"]
        + summary["human_deferred"]
        + summary["human_rejected"]
        + summary["awaiting_human_review"]
        == summary["evaluated"]
    )


def test_report_is_order_independent_and_external_decisions_do_not_change_verdict_inputs() -> None:
    results = [
        _report_result("A", gate_status=ADMISSION_READY, decision=ADMISSION_READY),
        _report_result("B"),
    ]
    current = {
        "A": {"human_review_decision": "approved_for_admission"},
        "B": {"human_review_decision": "deferred"},
    }
    with_external = {
        "external": {"human_review_decision": "approved_for_admission"},
        **current,
    }

    baseline = _scoped_report(results, current)["summary"]
    reordered = _scoped_report(list(reversed(results)), dict(reversed(list(with_external.items()))))["summary"]

    assert reordered == baseline


def test_report_all_external_decisions_leave_current_candidates_awaiting_and_is_idempotent() -> None:
    results = [_report_result("A"), _report_result("B")]
    persistent = {
        "X": {"human_review_decision": "approved_for_admission"},
        "Y": {"human_review_decision": "deferred"},
        "Z": {"human_review_decision": "rejected"},
    }

    first = _scoped_report(results, persistent)["summary"]
    second = _scoped_report(results, persistent)["summary"]

    assert first == second
    assert first["approved_for_admission"] == 0
    assert first["human_deferred"] == 0
    assert first["human_rejected"] == 0
    assert first["awaiting_human_review"] == 2
    assert persistent == {
        "X": {"human_review_decision": "approved_for_admission"},
        "Y": {"human_review_decision": "deferred"},
        "Z": {"human_review_decision": "rejected"},
    }


def test_report_rejects_duplicate_evaluated_candidate_ids() -> None:
    with pytest.raises(ValueError, match="duplicate candidate_id"):
        _scoped_report([_report_result("A"), _report_result("A")], {})


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
        "human_review_reason_code": "EXPLICIT_REFERENCE_CONFIRMED",
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
    if "human_review_reason_code" not in overrides:
        cand["human_review_reason_code"] = {
            "approved_for_admission": "EXPLICIT_REFERENCE_CONFIRMED",
            "rejected": "OUT_OF_SCOPE",
            "deferred": "INSUFFICIENT_CONTEXT",
        }.get(cand.get("human_review_decision"), cand.get("human_review_reason_code"))
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
        reason_by_decision = {
            "approved_for_admission": "EVIDENCE_AND_ENDPOINTS_VERIFIED",
            "rejected": "OUT_OF_SCOPE",
            "deferred": "INSUFFICIENT_CONTEXT",
        }
        normalized = []
        for source in records:
            record = dict(source)
            record.setdefault("schema_version", "relation-human-review-decision/v2")
            record.setdefault(
                "human_review_reason_code",
                reason_by_decision.get(record.get("human_review_decision"), "INSUFFICIENT_CONTEXT"),
            )
            record.setdefault("human_review_note", None)
            record.setdefault("decision_mode", "individual")
            record.setdefault("decision_batch_id", None)
            record.setdefault("supersedes_decision_hash", None)
            record.setdefault("canon_hash", "1" * 64)
            record.setdefault("candidate_manifest_hash", "2" * 64)
            record.setdefault("reconciliation_manifest_hash", "3" * 64)
            normalized.append(record)
        path.write_text(
            "\n".join(json.dumps(record) for record in normalized) + "\n",
            encoding="utf-8",
        )
        return path

    def test_safety_verification_accepts_convergent_noop(
        self, tmp_path: Path,
    ):
        candidate = _technical_candidate()
        candidate_id = str(candidate["candidate_id"])
        source_id = relation_gate.endpoint_id(candidate.get("source") or {})
        target_id = relation_gate.endpoint_id(candidate.get("target") or {})
        relation_type = relation_gate.relation_type_for(candidate)

        canon_dir = tmp_path / "canon"
        canon_dir.mkdir()
        canon_path = canon_dir / "tiddlers_1.jsonl"
        canon_path.write_text(
            json.dumps({
                "id": source_id,
                "relations": [{
                    "relation_schema_version": "canonical-relation/v1",
                    "relation_id": "cr1_existing_fixture",
                    "source_id": source_id,
                    "target_id": target_id,
                    "relation_type": relation_type,
                }],
            }) + "\n",
            encoding="utf-8",
        )
        canon_before = canon_path.read_bytes()

        candidates_file = self._write_candidates(tmp_path, [candidate])
        dry_run = self._write_dry_run_report(
            tmp_path,
            [{
                "candidate_id": candidate_id,
                "gate_status": "admission_ready_dry_run",
                "admission_ready_dry_run": True,
                "blocking_reasons": [],
                "all_block_reasons": [],
            }],
            ready=1,
        )
        review_file = self._write_review(
            tmp_path,
            [{
                "candidate_id": candidate_id,
                "human_review_decision": "approved_for_admission",
                "human_review_actor": "operator",
                "human_review_timestamp": "2026-08-23T00:00:00+00:00",
                "approval_scope": "canonical_admission",
                "reviewed_evidence_paths": [],
                "session_id": "S0184",
            }],
        )

        report = relation_gate.verify_apply_safety_on_temp_copy(
            source_canon_glob=str(canon_dir / "tiddlers_*.jsonl"),
            temp_work_root=tmp_path / "safety-work",
            candidates_file=candidates_file,
            human_review_decisions_file=review_file,
            dry_run_report_path=dry_run,
            binding_paths={},
            report_path=tmp_path / "safety-report.json",
        )

        assert report["passed"] is True
        assert report["verification_mode"] == "convergent_noop"

        positive = report["positive_apply"]
        assert positive["would_apply_count"] == 1
        assert positive["applied_count"] == 0
        assert positive["omitted_existing_count"] == 1
        assert positive["failed_count"] == 0
        assert positive["apply_executed"] is False
        assert positive["canon_modified"] is False

        retry = report["second_apply"]
        assert retry["status"] == "applied"
        assert retry["applied_count"] == 0
        assert retry["omitted_existing_count"] == 1
        assert retry["failed_count"] == 0
        assert retry["canon_modified"] is False

        failure = report["injected_failure"]
        assert failure["applicable"] is False
        assert failure["status"] == "applied"
        assert failure["applied_count"] == 0
        assert failure["omitted_existing_count"] == 1
        assert failure["failed_count"] == 0
        assert failure["canon_modified"] is False
        assert failure["restored_exactly"] is True

        assert report["rollback"]["status"] == "already_restored"
        assert report["rollback"]["byte_exact"] is True
        assert report["repeated_rollback"]["status"] == "already_restored"
        assert report["repeated_rollback"]["byte_exact"] is True
        assert report["success_copy_restored_exactly"] is True
        assert report["production_canon_unchanged"] is True
        assert canon_path.read_bytes() == canon_before

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
            "schema_version": "relation-human-review-decision/v2",
            "candidate_id": "rc1_c1c2c3c4c5c6c7c8",
            "human_review_decision": "approved_for_admission",
            "human_review_reason_code": "EVIDENCE_AND_ENDPOINTS_VERIFIED",
            "human_review_note": None,
            "decision_mode": "individual",
            "decision_batch_id": None,
            "supersedes_decision_hash": None,
            "human_review_actor": "operator",
            "human_review_timestamp": "2026-07-08T00:00:00Z",
            "approval_scope": "canonical_admission",
            "reviewed_evidence_paths": ["data/out/local/pipeline/relation_candidates/current/review_queue.jsonl"],
            "session_id": "S0165",
            "canon_hash": "1" * 64,
            "candidate_manifest_hash": "2" * 64,
            "reconciliation_manifest_hash": "3" * 64,
        }
        assert validate_human_review_decision_record(valid) == []

    def test_admitted_relation_schema_minimal_fields(self):
        cand = _technical_candidate()
        review = {
            "human_review_actor": "operator",
            "session_id": "S0165",
            "human_review_decision": "approved_for_admission",
            "human_review_reason_code": "EVIDENCE_AND_ENDPOINTS_VERIFIED",
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
            "relations": [{
                "type": "references",
                "target_id": "tgt-002",
                "relation_schema": "legacy/pre-v1",
            }],
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
        original_canon = canon_path.read_bytes()

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
        assert (audit_dir / "relation_apply_receipt.json").exists()
        assert Path(report["rollback_snapshot"]).exists()

        records = [
            json.loads(line)
            for line in canon_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(records) == 2
        relation = records[0]["relations"][-1]
        assert validate_admitted_relation_schema(relation) == []
        assert relation["relation_schema_version"] == "canonical-relation/v1"
        assert relation["artifact_family"] == "canonical_relation"
        assert relation["relation_id"]
        assert relation["source_id"] == "src-001"
        assert relation["target_id"] == "tgt-002"
        assert relation["relation_type"] == "references"
        assert relation["authority"]["human_review_decision"] == "approved_for_admission"
        assert relation["authority"]["human_review_reason_code"] == "EVIDENCE_AND_ENDPOINTS_VERIFIED"
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
        assert len(retry_records[0]["relations"]) == 2

        rollback = rollback_relational_apply(
            snapshot_manifest_path=Path(report["rollback_snapshot"]),
            out_dir=audit_dir,
        )
        assert rollback["status"] == "restored"
        assert rollback["byte_exact"] is True
        assert canon_path.read_bytes() == original_canon
        repeated = rollback_relational_apply(
            snapshot_manifest_path=Path(report["rollback_snapshot"]),
            out_dir=audit_dir,
        )
        assert repeated["status"] == "already_restored"
        assert canon_path.read_bytes() == original_canon

    def test_productive_apply_reuses_exact_plan_and_consumes_authorization_once(
        self, tmp_path: Path,
    ):
        canon_dir = tmp_path / "canon"
        inputs_dir = tmp_path / "inputs"
        audit_dir = tmp_path / "audit"
        canon_dir.mkdir()
        inputs_dir.mkdir()
        canon_path = canon_dir / "tiddlers_1.jsonl"
        canon_path.write_text(
            json.dumps({"id": "src-001", "relations": []}) + "\n"
            + json.dumps({"id": "tgt-002", "relations": []}) + "\n",
            encoding="utf-8",
        )
        candidate = _technical_candidate(
            source={"canonical_id": "src-001", "repo_path": "source.py"},
            target={"canonical_id": "tgt-002", "repo_path": "target.py"},
            policy={"human_review_required": True, "canonical_admission_allowed": True},
            session_resolution={"classification": "resolved_for_human_review"},
        )
        candidates_file = self._write_candidates(inputs_dir, [candidate])
        review_file = self._write_review(inputs_dir, [{
            "candidate_id": candidate["candidate_id"],
            "human_review_decision": "approved_for_admission",
            "human_review_actor": "operator",
            "human_review_timestamp": "2026-07-28T00:00:00Z",
            "approval_scope": "canonical_admission",
            "reviewed_evidence_paths": [],
            "session_id": "S0183",
        }])
        dry_run = self._write_dry_run_report(
            inputs_dir,
            [{
                "candidate_id": candidate["candidate_id"],
                "gate_status": "admission_ready_dry_run",
                "all_block_reasons": [],
            }],
            ready=1,
        )
        decisions, errors = relation_gate.load_persistent_human_review_decisions(review_file)
        assert errors == []
        plan = relation_gate.build_apply_plan(
            candidates=[candidate],
            canon_glob=str(canon_dir / "tiddlers_*.jsonl"),
            human_review_decisions=decisions,
            dry_run_report=relation_gate.load_dry_run_report(dry_run),
            dry_run_report_path=dry_run,
            dry_run_recent=True,
            binding_paths={},
        )
        authorized_plan_path = inputs_dir / "authorized_plan.json"
        authorized_plan_path.write_text(
            json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        authorization_path = inputs_dir / "authorization.json"
        authorization_path.write_text(json.dumps({
            "schema_version": "gate-g-authorization/v1",
            "authorization_id": "auth_fixture",
            "decision": "authorized",
            "authorized_operation": "APPLY RELATIONS",
            "single_use": True,
            "consumed": False,
            "superseded": False,
            "authorization_current": True,
            "bindings": {
                "apply_plan_id": plan["apply_plan_id"],
                "apply_plan_hash": relation_gate.sha256_path(authorized_plan_path),
            },
        }) + "\n", encoding="utf-8")
        authorized_bytes = authorized_plan_path.read_bytes()

        code, report = guarded_apply_relations(
            candidates_file=candidates_file,
            canon_glob=str(canon_dir / "tiddlers_*.jsonl"),
            human_review_decisions_file=review_file,
            dry_run_report_path=dry_run,
            out_dir=audit_dir,
            terminal_confirmation="APPLY RELATIONS",
            perform_write=True,
            target_scope="production_path",
            authorization_path=authorization_path,
            authorized_plan_path=authorized_plan_path,
        )

        assert code == 0
        assert report["exact_authorized_plan_reused"] is True
        assert (audit_dir / "relation_apply_plan.json").read_bytes() == authorized_bytes
        assert report["apply_id"].startswith("apply_exec_")
        receipt = json.loads((audit_dir / "relation_apply_receipt.json").read_text())
        snapshot = json.loads(Path(report["rollback_snapshot"]).read_text())
        journal = [
            json.loads(line)
            for line in (audit_dir / "relation_apply_journal.jsonl").read_text().splitlines()
        ]
        consumed = json.loads(authorization_path.read_text())
        assert receipt["apply_id"] == report["apply_id"] == snapshot["apply_id"]
        assert receipt["authorization_id"] == "auth_fixture"
        assert receipt["exact_authorized_plan_reused"] is True
        assert [row["candidate_id"] for row in journal if row.get("result") == "written"] == [
            candidate["candidate_id"]
        ]
        assert all(row.get("apply_id") == report["apply_id"] for row in journal)
        assert consumed["consumed"] is True
        assert consumed["consumed_once"] is True
        assert consumed["consumed_by_apply_id"] == report["apply_id"]

        retry_code, retry = guarded_apply_relations(
            candidates_file=candidates_file,
            canon_glob=str(canon_dir / "tiddlers_*.jsonl"),
            human_review_decisions_file=review_file,
            dry_run_report_path=dry_run,
            out_dir=tmp_path / "retry",
            terminal_confirmation="APPLY RELATIONS",
            perform_write=True,
            target_scope="production_path",
            authorization_path=authorization_path,
            authorized_plan_path=authorized_plan_path,
        )
        assert retry_code == 1
        assert "authorization_already_consumed" in retry["apply_plan"]["block_reasons"]

    def test_prevalidated_plan_is_blocked_outside_current_relational_bundle(
        self, tmp_path: Path,
    ):
        canon_dir = tmp_path / "canon"
        inputs_dir = tmp_path / "inputs"
        audit_dir = tmp_path / "audit"
        canon_dir.mkdir()
        inputs_dir.mkdir()

        canon_path = canon_dir / "tiddlers_1.jsonl"
        canon_path.write_text(
            json.dumps({"id": "src-001", "relations": []}) + "\n"
            + json.dumps({"id": "tgt-002", "relations": []}) + "\n",
            encoding="utf-8",
        )
        canon_before = canon_path.read_bytes()

        candidate = _technical_candidate(
            source={"canonical_id": "src-001", "repo_path": "source.py"},
            target={"canonical_id": "tgt-002", "repo_path": "target.py"},
            policy={
                "human_review_required": True,
                "canonical_admission_allowed": True,
            },
            session_resolution={"classification": "resolved_for_human_review"},
        )
        candidates_file = self._write_candidates(inputs_dir, [candidate])
        review_file = self._write_review(inputs_dir, [{
            "candidate_id": candidate["candidate_id"],
            "human_review_decision": "approved_for_admission",
            "human_review_actor": "operator",
            "human_review_timestamp": "2026-07-28T00:00:00Z",
            "approval_scope": "canonical_admission",
            "reviewed_evidence_paths": [],
            "session_id": "S0183",
        }])
        dry_run = self._write_dry_run_report(
            inputs_dir,
            [{
                "candidate_id": candidate["candidate_id"],
                "gate_status": "admission_ready_dry_run",
                "all_block_reasons": [],
            }],
            ready=1,
        )

        decisions, errors = relation_gate.load_persistent_human_review_decisions(
            review_file
        )
        assert errors == []

        plan = relation_gate.build_apply_plan(
            candidates=[candidate],
            canon_glob=str(canon_dir / "tiddlers_*.jsonl"),
            human_review_decisions=decisions,
            dry_run_report=relation_gate.load_dry_run_report(dry_run),
            dry_run_report_path=dry_run,
            dry_run_recent=True,
            binding_paths={},
        )
        plan["apply_plan_id"] = relation_gate.semantic_apply_plan_id(plan)

        sealed_plan = inputs_dir / "sealed_current_plan.json"
        sealed_plan.write_text(
            json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        code, report = guarded_apply_relations(
            candidates_file=candidates_file,
            canon_glob=str(canon_dir / "tiddlers_*.jsonl"),
            human_review_decisions_file=review_file,
            dry_run_report_path=dry_run,
            out_dir=audit_dir,
            terminal_confirmation="APPLY RELATIONS",
            perform_write=True,
            target_scope="production_path",
            prevalidated_plan_path=sealed_plan,
        )

        assert code == 1
        assert report["status"] == "blocked"
        assert report["exact_authorized_plan_reused"] is False
        assert (
            "prevalidated_plan_scope_invalid"
            in report["apply_plan"]["block_reasons"]
        )
        assert canon_path.read_bytes() == canon_before

    def test_transaction_failure_between_shards_rolls_back_exactly(self, tmp_path: Path):
        canon_dir = tmp_path / "canon"
        audit_dir = tmp_path / "audit"
        canon_dir.mkdir()
        audit_dir.mkdir()
        first = canon_dir / "tiddlers_1.jsonl"
        second = canon_dir / "tiddlers_2.jsonl"
        first.write_text(json.dumps({"id": "src", "relations": []}) + "\n", encoding="utf-8")
        second.write_text(json.dumps({"id": "other", "relations": []}) + "\n", encoding="utf-8")
        before = {path: path.read_bytes() for path in (first, second)}
        plan = {
            "apply_plan_id": "apply_" + "a" * 16,
            "canon_before_hash": relation_gate.aggregate_canon_hash(str(canon_dir / "tiddlers_*.jsonl")),
            "canon_before_count": 2,
            "exact_bindings": {},
        }
        plan_path = audit_dir / "relation_apply_plan.json"
        plan_path.write_text(json.dumps(plan) + "\n", encoding="utf-8")
        relation = {
            "source_id": "src",
            "target_id": "other",
            "relation_type": "references",
            "relation_schema_version": "canonical-relation/v1",
            "relation_id": "cr1_fixture",
            "evidence": {"candidate_id": "rc_fixture"},
        }
        with pytest.raises(RuntimeError, match="injected failure"):
            relation_gate._transactional_apply(
                canon_glob=str(canon_dir / "tiddlers_*.jsonl"),
                selected_by_source={"src": [relation]},
                plan=plan,
                plan_path=plan_path,
                out_dir=audit_dir,
                target_scope="tmp_path",
                inject_failure_after_shards=1,
                apply_id="apply_exec_fixture",
            )
        assert all(path.read_bytes() == payload for path, payload in before.items())
        rollback = json.loads((audit_dir / "rollback_report.json").read_text(encoding="utf-8"))
        assert rollback["byte_exact"] is True
        journal = (audit_dir / "relation_apply_journal.jsonl").read_text(encoding="utf-8")
        assert "transaction_failed" in journal
        assert "rollback_completed" in journal

    def test_failed_authorization_attempt_is_exhausted_without_false_consumption(
        self, tmp_path: Path,
    ):
        authorization_path = tmp_path / "authorization.json"
        authorization = {
            "schema_version": "gate-g-authorization/v1",
            "authorization_id": "auth_failure_fixture",
            "decision": "authorized",
            "authorized_operation": "APPLY RELATIONS",
            "single_use": True,
            "consumed": False,
            "authorization_current": True,
        }
        authorization_path.write_text(json.dumps(authorization) + "\n", encoding="utf-8")

        relation_gate._mark_authorization_in_progress(
            authorization_path,
            authorization,
            apply_id="apply_exec_failed_fixture",
            apply_plan_id="apply_fixture",
            started_at="2026-07-28T00:00:00Z",
        )
        relation_gate._mark_authorization_failed(
            authorization_path,
            apply_id="apply_exec_failed_fixture",
            failure="injected failure",
        )

        failed = json.loads(authorization_path.read_text())
        assert failed["consumed"] is False
        assert failed["single_use_exhausted"] is True
        assert failed["authorization_current"] is False
        assert failed["production_apply_executed"] is False
        assert failed["consumption_state"] == "failed_rolled_back_requires_reauthorization"
