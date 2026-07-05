"""S0141 tests for operational human_review menu flow."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

import relation_review_menu as rrm  # noqa: E402


CID = "rc1_a1b2c3d4e5f6a7b8"


def _queue_item() -> dict:
    return {
        "candidate_id": CID,
        "source_id": "src-001",
        "source_title": "Source",
        "target_id": "tgt-002",
        "target_title": "Target",
        "relation_type": "referencia_a",
        "confidence_score": 0.92,
        "evidence_kind": "explicit_reference",
        "evidence_excerpt": "approved excerpt present",
        "current_decision": "review_required",
        "risk_level": "low",
        "review_prompt": "Review test candidate.",
        "source_report": "test-admissibility.json",
    }


def _candidate() -> dict:
    return {
        "candidate_id": CID,
        "schema_version": "relations-candidate/v1",
        "status": "candidate",
        "source": {"tiddler_id": "src-001", "title": "Source"},
        "target": {
            "tiddler_id": "tgt-002",
            "title": "Target",
            "resolution_status": "resolved",
        },
        "relation": {"type": "referencia_a", "direction": "source_to_target"},
        "evidence": {"kind": "explicit_reference", "excerpt": "approved excerpt present"},
        "confidence": {"score": 0.92, "method": "rule_based", "risk_flags": []},
        "provenance": {"source_path": "tmp/tiddlers_1.jsonl"},
    }


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _fixture(tmp_path: Path) -> dict[str, Path]:
    review_dir = tmp_path / "relation_review" / "s0141"
    admission_dir = tmp_path / "relation_admission" / "s0141"
    canon_dir = tmp_path / "canon"
    type_policy_dir = tmp_path / "type_policy"
    candidates_file = tmp_path / "valid_candidates.jsonl"
    admissibility_report = tmp_path / "admissibility.json"

    _write_jsonl(review_dir / "human_review_queue.jsonl", [_queue_item()])
    _write_jsonl(candidates_file, [_candidate()])
    _write_jsonl(
        canon_dir / "tiddlers_1.jsonl",
        [
            {
                "id": "src-001",
                "title": "Source",
                "text": "approved excerpt present",
                "relations": [],
            },
            {"id": "tgt-002", "title": "Target", "text": "Target text", "relations": []},
        ],
    )
    type_policy_dir.mkdir(parents=True)
    (type_policy_dir / "s0139_historical_relation_type_decisions.json").write_text(
        json.dumps({"decisions_by_type": {}}, ensure_ascii=False),
        encoding="utf-8",
    )
    admissibility_report.write_text(
        json.dumps({"results": [{"decision": "review_required", **_queue_item()}]}),
        encoding="utf-8",
    )
    rrm.ensure_s0141_review_artifacts(review_dir)
    return {
        "review_dir": review_dir,
        "admission_dir": admission_dir,
        "canon_glob": canon_dir / "tiddlers_*.jsonl",
        "canon_file": canon_dir / "tiddlers_1.jsonl",
        "type_policy_dir": type_policy_dir,
        "candidates_file": candidates_file,
        "admissibility_report": admissibility_report,
    }


def _decisions(review_dir: Path) -> dict:
    return json.loads((review_dir / "human_review_decisions.json").read_text(encoding="utf-8"))


def _decision_value(review_dir: Path) -> str:
    return _decisions(review_dir)["decisions"][0]["decision"]


def _audit_actions(review_dir: Path) -> list[str]:
    path = review_dir / "human_review_audit_log.jsonl"
    return [json.loads(line)["action"] for line in path.read_text(encoding="utf-8").splitlines() if line]


def _run_gate(fixture: dict[str, Path]) -> int:
    return rrm.run_relation_admission_gate_dry_run(
        review_dir=fixture["review_dir"],
        admission_dir=fixture["admission_dir"],
        candidates_file=fixture["candidates_file"],
        canon_glob=str(fixture["canon_glob"]),
        type_policy_dir=fixture["type_policy_dir"],
        admissibility_report=fixture["admissibility_report"],
    )


def test_menu_can_load_s0141_queue(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)

    queue = rrm.load_human_review_queue(fixture["review_dir"])

    assert len(queue) == 1
    assert queue[0]["candidate_id"] == CID


def test_menu_shows_pending_candidates(tmp_path: Path, capsys) -> None:
    fixture = _fixture(tmp_path)

    rrm.show_human_review_queue(fixture["review_dir"])

    out = capsys.readouterr().out
    assert "Human Review Queue" in out
    assert CID in out
    assert "Diferidos: 1" in out


def test_approve_requires_explicit_confirmation(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)

    approved = rrm.approve_candidate_for_dry_run(CID, confirmation="n", review_dir=fixture["review_dir"])

    assert approved is False
    assert _decision_value(fixture["review_dir"]) == "deferred"


def test_non_yes_response_does_not_approve(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)

    rrm.approve_candidate_for_dry_run(CID, confirmation="", review_dir=fixture["review_dir"])

    assert _decision_value(fixture["review_dir"]) != "approved_for_dry_run"


def test_approve_candidate_writes_approved_for_dry_run(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)

    assert rrm.approve_candidate_for_dry_run(CID, confirmation="yes", review_dir=fixture["review_dir"])

    decision = _decisions(fixture["review_dir"])["decisions"][0]
    assert decision["decision"] == "approved_for_dry_run"
    assert all(decision["checks"].values())


def test_reject_candidate_writes_rejected_by_human(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)

    rrm.reject_candidate_by_human(CID, review_dir=fixture["review_dir"])

    assert _decision_value(fixture["review_dir"]) == "rejected_by_human"


def test_defer_candidate_writes_deferred(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    rrm.approve_candidate_for_dry_run(CID, confirmation="y", review_dir=fixture["review_dir"])

    rrm.defer_candidate(CID, review_dir=fixture["review_dir"])

    assert _decision_value(fixture["review_dir"]) == "deferred"


def test_each_decision_action_writes_audit_log(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)

    rrm.approve_candidate_for_dry_run(CID, confirmation="y", review_dir=fixture["review_dir"])
    rrm.reject_candidate_by_human(CID, review_dir=fixture["review_dir"])
    rrm.defer_candidate(CID, review_dir=fixture["review_dir"])

    actions = _audit_actions(fixture["review_dir"])
    assert "approved_for_dry_run" in actions
    assert "rejected_by_human" in actions
    assert "deferred" in actions


def test_gate_with_approved_candidate_generates_admission_ready(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    rrm.approve_candidate_for_dry_run(CID, confirmation="y", review_dir=fixture["review_dir"])

    assert _run_gate(fixture) == 0

    ready = json.loads((fixture["admission_dir"] / "admission_ready_dry_run.json").read_text())
    assert ready["summary"]["total"] == 1
    assert ready["items"][0]["decision"] == "admission_ready_dry_run"


def test_gate_with_deferred_candidate_blocks_missing_human_review(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)

    assert _run_gate(fixture) == 0

    blocked = json.loads((fixture["admission_dir"] / "admission_blocked.json").read_text())
    assert blocked["summary"]["by_decision"] == {"blocked_missing_human_review": 1}


def test_gate_with_rejected_candidate_produces_rejected_by_human(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    rrm.reject_candidate_by_human(CID, review_dir=fixture["review_dir"])

    assert _run_gate(fixture) == 0

    blocked = json.loads((fixture["admission_dir"] / "admission_blocked.json").read_text())
    assert blocked["summary"]["by_decision"] == {"rejected_by_human": 1}


def test_patch_preview_declares_not_applied(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    rrm.approve_candidate_for_dry_run(CID, confirmation="y", review_dir=fixture["review_dir"])
    _run_gate(fixture)

    preview = json.loads((fixture["admission_dir"] / "admission_patch_preview.json").read_text())
    assert preview["applied_to_canon"] is False
    assert preview["canon_modified"] is False
    assert preview["applicable"] is False


def test_no_tiddlers_jsonl_changes(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    before = hashlib.sha256(fixture["canon_file"].read_bytes()).hexdigest()
    rrm.approve_candidate_for_dry_run(CID, confirmation="y", review_dir=fixture["review_dir"])

    _run_gate(fixture)

    after = hashlib.sha256(fixture["canon_file"].read_bytes()).hexdigest()
    assert after == before


def test_menu_keeps_canonical_admission_block_visible() -> None:
    assert "Admisión canónica relacional" in rrm._MENU_HEADER
    assert "BLOQUEADA" in rrm._MENU_HEADER
    assert "dry-run" in rrm._MENU_HEADER


def test_gate_report_contains_counts_by_decision(tmp_path: Path, capsys) -> None:
    fixture = _fixture(tmp_path)
    rrm.reject_candidate_by_human(CID, review_dir=fixture["review_dir"])
    _run_gate(fixture)

    rrm.show_admission_gate_report(fixture["admission_dir"], review_dir=fixture["review_dir"])

    out = capsys.readouterr().out
    assert "rejected_by_human: 1" in out
    assert "applied_to_canon: false" in out
