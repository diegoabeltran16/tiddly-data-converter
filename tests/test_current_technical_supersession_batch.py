"""Regression tests for the governed CURRENT technical-supersession batch:
one human confirmation superseding every CURRENT approved_for_admission
candidate blocked exclusively by the GATE-020 (repo lifecycle metadata)
family, to a uniform deferred/LIFECYCLE_UNRESOLVED decision.

Fixtures/TMP only; never CURRENT productivo, never Canon, never a
regenerated candidate batch.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "src" / "python_scripts"
sys.path.insert(0, str(SCRIPTS))

import current_relation_human_review as human_review  # noqa: E402
import relation_admission_gate as gate  # noqa: E402


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _candidate(candidate_id: str, *, source_id: str, target_id: str) -> dict:
    return {
        "candidate_id": candidate_id,
        "candidate_schema_version": "technical-relation-candidates/v1",
        "session_origin": "CURRENT",
        "relation_type": "depende_de",
        "source": {"canonical_id": source_id, "repo_path": f"src/{source_id}.py"},
        "target": {"canonical_id": target_id, "repo_path": f"src/{target_id}.py"},
        "evidence": {
            "evidence_kind": "content_embedded",
            "raw_observation": f"{candidate_id} evidence",
            "file": f"src/{source_id}.py",
            "line": 1,
        },
    }


def _gate_item(candidate_id: str, *, ready: bool, reasons: list[str]) -> dict:
    return {
        "candidate_id": candidate_id,
        "gate_status": gate.ADMISSION_READY if ready else "blocked",
        "admission_ready_dry_run": ready,
        "all_block_reasons": reasons,
    }


def _build_fixture(
    tmp_path: Path, *, candidates: list[dict], decisions_spec: dict[str, dict], gate_items: list[dict],
) -> tuple[Path, Path, Path]:
    """decisions_spec: candidate_id -> {"decision": ..., "reason_code": ...} (omit to leave undecided)."""
    current_dir = tmp_path / "current"
    canon_root = tmp_path / "canon"
    canon_root.mkdir(parents=True)
    (canon_root / "tiddlers_1.jsonl").write_text('{"id":"x"}\n', encoding="utf-8")
    _write_jsonl(current_dir / human_review.QUEUE_FILE, candidates)
    (current_dir / "current_candidate_manifest.json").write_text("{}", encoding="utf-8")
    (current_dir / "reconciliation_manifest.json").write_text("{}", encoding="utf-8")
    bindings = human_review.current_bindings(current_dir, canon_root)
    candidates_by_id = {c["candidate_id"]: c for c in candidates}
    decisions = {}
    for candidate_id, spec in decisions_spec.items():
        decisions[candidate_id] = human_review.build_decision_record(
            candidates_by_id[candidate_id],
            decision=spec["decision"],
            reason_code=spec["reason_code"],
            actor="fixture-reviewer",
            bindings=bindings,
            note="fixture original decision",
            decision_mode="individual",
            reviewed_at="2026-09-04T00:00:00+00:00",
        )
    human_review.atomic_write_jsonl(current_dir / human_review.EFFECTIVE_DECISIONS_FILE, decisions)
    gate_report_path = tmp_path / "admission_gate_dry_run.json"
    gate_report_path.write_text(
        json.dumps({"items": gate_items}, ensure_ascii=False), encoding="utf-8",
    )
    return current_dir, canon_root, gate_report_path


GATE_020_SOURCE = "GATE-020: source.lifecycle_state ausente."
GATE_020_TARGET = "GATE-020: target.lifecycle_state ausente."
GATE_016_OTHER = "GATE-016: human_review_decision != approved_for_admission; encontrado='deferred'."


def _three_eligible_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    candidates = [
        _candidate("rc_current_" + "1" * 24, source_id="s1", target_id="t1"),
        _candidate("rc_current_" + "2" * 24, source_id="s2", target_id="t2"),
        _candidate("rc_current_" + "3" * 24, source_id="s3", target_id="t3"),
    ]
    decisions_spec = {
        c["candidate_id"]: {"decision": "approved_for_admission", "reason_code": "DIRECT_CODE_DEPENDENCY_CONFIRMED"}
        for c in candidates
    }
    gate_items = [
        _gate_item(candidates[0]["candidate_id"], ready=False, reasons=[GATE_020_SOURCE]),
        _gate_item(candidates[1]["candidate_id"], ready=False, reasons=[GATE_020_TARGET]),
        _gate_item(candidates[2]["candidate_id"], ready=False, reasons=[GATE_020_SOURCE, GATE_020_TARGET]),
    ]
    return _build_fixture(tmp_path, candidates=candidates, decisions_spec=decisions_spec, gate_items=gate_items)


# --- A: 3 eligible candidates -> preview 3 -> one confirmation -> 3 records ---

def test_batch_supersedes_all_eligible_candidates_with_one_confirmation(tmp_path: Path) -> None:
    current_dir, canon_root, gate_report = _three_eligible_fixture(tmp_path)

    original_decisions = dict(
        gate.load_persistent_human_review_decisions(
            current_dir / human_review.EFFECTIVE_DECISIONS_FILE
        )[0]
    )

    preview = human_review.build_current_technical_supersession_preview(
        current_dir, canon_root, gate_report, note="Diferidas por GATE-020: lifecycle_state ausente.",
    )
    assert preview["candidate_count"] == 3
    assert set(preview["candidate_ids"]) == {
        "rc_current_" + "1" * 24, "rc_current_" + "2" * 24, "rc_current_" + "3" * 24,
    }
    assert preview["proposed_decision"] == "deferred"
    assert preview["proposed_reason_code"] == "LIFECYCLE_UNRESOLVED"
    assert preview["confirmation_required"] == f"CONFIRM CURRENT TECHNICAL SUPERSESSION {preview['batch_id']}"

    receipt = human_review.persist_current_technical_supersession(
        current_dir, canon_root, gate_report,
        preview=preview, actor="Naveen", confirmation=preview["confirmation_required"],
    )
    assert receipt["decisions_written"] == 3
    assert receipt["failures"] == 0
    assert receipt["eligible_count"] == 3

    final_decisions, errors = gate.load_persistent_human_review_decisions(
        current_dir / human_review.EFFECTIVE_DECISIONS_FILE
    )
    assert not errors
    operation_ids = set()
    for candidate_id in preview["candidate_ids"]:
        record = final_decisions[candidate_id]
        assert record["human_review_decision"] == "deferred"
        assert record["human_review_reason_code"] == "LIFECYCLE_UNRESOLVED"
        assert record["decision_mode"] == "batch"
        assert record["decision_batch_id"] == preview["batch_id"]
        operation_ids.add(record["multi_review_operation_id"])
        expected_hash = human_review.decision_hash(original_decisions[candidate_id])
        assert record["supersedes_decision_hash"] == expected_hash
    assert operation_ids == {preview["operation_id"]}


# --- B: an already-deferred candidate is excluded ---

def test_already_deferred_candidate_is_excluded(tmp_path: Path) -> None:
    candidates = [
        _candidate("rc_current_" + "1" * 24, source_id="s1", target_id="t1"),
        _candidate("rc_current_" + "4" * 24, source_id="s4", target_id="t4"),
    ]
    decisions_spec = {
        candidates[0]["candidate_id"]: {"decision": "approved_for_admission", "reason_code": "DIRECT_CODE_DEPENDENCY_CONFIRMED"},
        candidates[1]["candidate_id"]: {"decision": "deferred", "reason_code": "INSUFFICIENT_CONTEXT"},
    }
    gate_items = [
        _gate_item(candidates[0]["candidate_id"], ready=False, reasons=[GATE_020_SOURCE]),
        _gate_item(candidates[1]["candidate_id"], ready=False, reasons=[GATE_020_SOURCE]),
    ]
    current_dir, canon_root, gate_report = _build_fixture(
        tmp_path, candidates=candidates, decisions_spec=decisions_spec, gate_items=gate_items,
    )
    preview = human_review.build_current_technical_supersession_preview(
        current_dir, canon_root, gate_report, note="Diferidas por GATE-020.",
    )
    assert preview["candidate_ids"] == [candidates[0]["candidate_id"]]


# --- C: a candidate with GATE-020 + a non-permitted gate reason is excluded,
#         and a tampered preview including it fails closed at persist time ---

def test_mixed_gate_reason_candidate_excluded_and_fails_closed_if_injected(tmp_path: Path) -> None:
    candidates = [
        _candidate("rc_current_" + "1" * 24, source_id="s1", target_id="t1"),
        _candidate("rc_current_" + "5" * 24, source_id="s5", target_id="t5"),
    ]
    decisions_spec = {
        candidates[0]["candidate_id"]: {"decision": "approved_for_admission", "reason_code": "DIRECT_CODE_DEPENDENCY_CONFIRMED"},
        candidates[1]["candidate_id"]: {"decision": "approved_for_admission", "reason_code": "DIRECT_CODE_DEPENDENCY_CONFIRMED"},
    }
    gate_items = [
        _gate_item(candidates[0]["candidate_id"], ready=False, reasons=[GATE_020_SOURCE]),
        _gate_item(candidates[1]["candidate_id"], ready=False, reasons=[GATE_020_SOURCE, GATE_016_OTHER]),
    ]
    current_dir, canon_root, gate_report = _build_fixture(
        tmp_path, candidates=candidates, decisions_spec=decisions_spec, gate_items=gate_items,
    )
    preview = human_review.build_current_technical_supersession_preview(
        current_dir, canon_root, gate_report, note="Diferidas por GATE-020.",
    )
    # Automatic exclusion: the mixed-reason candidate never enters the batch.
    assert preview["candidate_ids"] == [candidates[0]["candidate_id"]]

    # Now simulate a tampered preview that injects the ineligible candidate
    # (and a forged, internally-"consistent" hash for the tampered set) --
    # persistence must still fail closed because it recomputes the eligible
    # universe fresh rather than trusting the preview's own declared hash.
    tampered = dict(preview)
    tampered_ids = sorted(preview["candidate_ids"] + [candidates[1]["candidate_id"]])
    tampered["candidate_ids"] = tampered_ids
    tampered["candidate_count"] = len(tampered_ids)
    tampered["candidate_set_hash"] = human_review.technical_supersession_candidate_set_hash(
        tampered_ids, tampered["proposed_decision"], tampered["proposed_reason_code"], tampered["proposed_note"],
    )
    tampered["batch_id"] = "hrb_" + tampered["candidate_set_hash"][:24]
    tampered["confirmation_required"] = (
        f"CONFIRM CURRENT TECHNICAL SUPERSESSION {tampered['batch_id']}"
    )

    before = gate.load_persistent_human_review_decisions(
        current_dir / human_review.EFFECTIVE_DECISIONS_FILE
    )[0]
    with pytest.raises(ValueError):
        human_review.persist_current_technical_supersession(
            current_dir, canon_root, gate_report,
            preview=tampered, actor="Naveen", confirmation=tampered["confirmation_required"],
        )
    after = gate.load_persistent_human_review_decisions(
        current_dir / human_review.EFFECTIVE_DECISIONS_FILE
    )[0]
    assert before == after


# --- D: CURRENT generation changes between preview and confirmation ---

def test_generation_change_between_preview_and_confirmation_fails_closed(tmp_path: Path) -> None:
    current_dir, canon_root, gate_report = _three_eligible_fixture(tmp_path)
    preview = human_review.build_current_technical_supersession_preview(
        current_dir, canon_root, gate_report, note="Diferidas por GATE-020.",
    )
    # A later, unrelated candidate-manifest change (e.g. a technical rebuild)
    # changes CURRENT's own bindings between preview and confirmation.
    (current_dir / "current_candidate_manifest.json").write_text(
        json.dumps({"changed": True}), encoding="utf-8",
    )
    before = gate.load_persistent_human_review_decisions(
        current_dir / human_review.EFFECTIVE_DECISIONS_FILE
    )[0]
    with pytest.raises(ValueError):
        human_review.persist_current_technical_supersession(
            current_dir, canon_root, gate_report,
            preview=preview, actor="Naveen", confirmation=preview["confirmation_required"],
        )
    after = gate.load_persistent_human_review_decisions(
        current_dir / human_review.EFFECTIVE_DECISIONS_FILE
    )[0]
    assert before == after


# --- E: the authoritative write itself fails -> nothing is silently accepted ---

def test_write_failure_leaves_no_partial_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    current_dir, canon_root, gate_report = _three_eligible_fixture(tmp_path)
    preview = human_review.build_current_technical_supersession_preview(
        current_dir, canon_root, gate_report, note="Diferidas por GATE-020.",
    )
    before = gate.load_persistent_human_review_decisions(
        current_dir / human_review.EFFECTIVE_DECISIONS_FILE
    )[0]

    def _boom(path, decisions):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(human_review, "atomic_write_jsonl", _boom)
    with pytest.raises(OSError):
        human_review.persist_current_technical_supersession(
            current_dir, canon_root, gate_report,
            preview=preview, actor="Naveen", confirmation=preview["confirmation_required"],
        )
    after = gate.load_persistent_human_review_decisions(
        current_dir / human_review.EFFECTIVE_DECISIONS_FILE
    )[0]
    assert before == after
    assert not (current_dir / human_review.TECHNICAL_SUPERSESSION_RECEIPTS_FILE).exists()


# --- F: Canon before/after identical ---

def test_canon_untouched_by_batch_supersession(tmp_path: Path) -> None:
    current_dir, canon_root, gate_report = _three_eligible_fixture(tmp_path)
    canon_before = (canon_root / "tiddlers_1.jsonl").read_bytes()
    preview = human_review.build_current_technical_supersession_preview(
        current_dir, canon_root, gate_report, note="Diferidas por GATE-020.",
    )
    human_review.persist_current_technical_supersession(
        current_dir, canon_root, gate_report,
        preview=preview, actor="Naveen", confirmation=preview["confirmation_required"],
    )
    canon_after = (canon_root / "tiddlers_1.jsonl").read_bytes()
    assert canon_before == canon_after


# --- G: original decisions remain present/auditable ---

def test_original_decisions_remain_auditable_after_supersession(tmp_path: Path) -> None:
    current_dir, canon_root, gate_report = _three_eligible_fixture(tmp_path)
    original_decisions = dict(
        gate.load_persistent_human_review_decisions(
            current_dir / human_review.EFFECTIVE_DECISIONS_FILE
        )[0]
    )
    preview = human_review.build_current_technical_supersession_preview(
        current_dir, canon_root, gate_report, note="Diferidas por GATE-020.",
    )
    human_review.persist_current_technical_supersession(
        current_dir, canon_root, gate_report,
        preview=preview, actor="Naveen", confirmation=preview["confirmation_required"],
    )
    audit_rows = human_review.load_jsonl(current_dir / human_review.AUDIT_FILE)
    audited_by_id = {row["candidate_id"]: row for row in audit_rows}
    for candidate_id in preview["candidate_ids"]:
        entry = audited_by_id[candidate_id]
        assert entry["action"] == "decision_superseded"
        assert entry["previous_decision"] == original_decisions[candidate_id]
        assert entry["previous_decision_hash"] == human_review.decision_hash(
            original_decisions[candidate_id]
        )
