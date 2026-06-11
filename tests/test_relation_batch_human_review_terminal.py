"""S0142 tests for governed terminal batch human-review flow."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "python_scripts"))

import relation_batch_review as batch  # noqa: E402
import relation_review_menu as menu  # noqa: E402
from relation_admission_gate import main as gate_main  # noqa: E402


CID_READY = "rc1_a1b2c3d4e5f6a7b8"
CID_REVIEW = "rc1_b2c3d4e5f6a7b8c9"
CID_BLOCKED = "rc1_e5f6a7b8c9d0e1f2"


def _candidate(cid: str, *, score: float = 0.92, excerpt: str = "approved excerpt", target_id: str = "tgt-002") -> dict:
    return {
        "candidate_id": cid,
        "schema_version": "relations-candidate/v1",
        "status": "candidate",
        "source": {"tiddler_id": "src-001", "title": "Source"},
        "target": {"tiddler_id": target_id, "title": "Target", "resolution_status": "resolved"},
        "relation": {"type": "referencia_a", "direction": "source_to_target"},
        "evidence": {"kind": "explicit_reference", "excerpt": excerpt},
        "confidence": {"score": score, "method": "rule_based", "risk_flags": []},
        "provenance": {"source_path": "tmp/tiddlers_1.jsonl"},
    }


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _fixture(tmp_path: Path) -> dict[str, Path]:
    candidates = [
        _candidate(CID_READY),
        _candidate(CID_REVIEW, score=0.71),
        _candidate(CID_BLOCKED, target_id="missing-target"),
    ]
    candidates_file = tmp_path / "valid_candidates.jsonl"
    canon_dir = tmp_path / "canon"
    type_policy_dir = tmp_path / "type_policy"
    admissibility_report = tmp_path / "admissibility.json"
    review_dir = tmp_path / "relation_review" / "s0142"
    admission_dir = tmp_path / "relation_admission" / "s0142"

    _write_jsonl(candidates_file, candidates)
    _write_jsonl(
        canon_dir / "tiddlers_1.jsonl",
        [
            {
                "id": "src-001",
                "title": "Source",
                "text": "approved excerpt",
                "relations": [],
            },
            {"id": "tgt-002", "title": "Target", "text": "Target", "relations": []},
        ],
    )
    type_policy_dir.mkdir(parents=True)
    (type_policy_dir / "s0139_historical_relation_type_decisions.json").write_text(
        json.dumps({"decisions_by_type": {}}, ensure_ascii=False),
        encoding="utf-8",
    )
    admissibility_report.write_text(
        json.dumps({
            "results": [
                {"candidate_id": CID_READY, "risk_level": "low", "decision": "review_required"},
                {"candidate_id": CID_REVIEW, "risk_level": "high", "decision": "review_required"},
                {"candidate_id": CID_BLOCKED, "risk_level": "medium", "decision": "review_required"},
            ]
        }),
        encoding="utf-8",
    )
    return {
        "candidates_file": candidates_file,
        "canon_glob": canon_dir / "tiddlers_*.jsonl",
        "canon_file": canon_dir / "tiddlers_1.jsonl",
        "type_policy_dir": type_policy_dir,
        "admissibility_report": admissibility_report,
        "review_dir": review_dir,
        "admission_dir": admission_dir,
    }


def _summary(fixture: dict[str, Path]) -> dict:
    return menu.build_s0142_batch_summary(
        review_dir=fixture["review_dir"],
        candidates_file=fixture["candidates_file"],
        canon_glob=str(fixture["canon_glob"]),
        type_policy_dir=fixture["type_policy_dir"],
        admissibility_report=fixture["admissibility_report"],
    )


def _approve_batch(fixture: dict[str, Path]) -> None:
    summary = _summary(fixture)
    paths = menu._batch_paths(fixture["review_dir"])
    assert batch.persist_batch_decision(
        summary,
        decisions_path=paths["decisions"],
        audit_path=paths["audit"],
        confirmation=batch.CONFIRMATION_TOKEN,
    )


def _run_gate(fixture: dict[str, Path], *, individual: Path | None = None) -> int:
    args = [
        "--candidates-file",
        str(fixture["candidates_file"]),
        "--canon-glob",
        str(fixture["canon_glob"]),
        "--human-review-batch",
        str(menu._batch_paths(fixture["review_dir"])["decisions"]),
        "--type-policy-dir",
        str(fixture["type_policy_dir"]),
        "--admissibility-report",
        str(fixture["admissibility_report"]),
        "--out-dir",
        str(fixture["admission_dir"]),
        "--session",
        "s0142",
        "--dry-run",
    ]
    if individual is not None:
        args.extend(["--human-review", str(individual)])
    return gate_main(args)


def test_classifies_candidates_into_batch_ready_individual_and_blocked(tmp_path: Path) -> None:
    summary = _summary(_fixture(tmp_path))

    assert summary["summary"]["batch_ready"] == 1
    assert summary["summary"]["individual_review_required"] == 1
    assert summary["summary"]["blocked"] == 1


def test_only_batch_ready_candidates_enter_approvable_batch(tmp_path: Path) -> None:
    summary = _summary(_fixture(tmp_path))

    assert summary["batch_ready_candidate_ids"] == [CID_READY]


def test_blocked_candidates_never_enter_batch(tmp_path: Path) -> None:
    summary = _summary(_fixture(tmp_path))

    assert CID_BLOCKED not in summary["batch_ready_candidate_ids"]


def test_individual_review_candidates_never_enter_batch(tmp_path: Path) -> None:
    summary = _summary(_fixture(tmp_path))

    assert CID_REVIEW not in summary["batch_ready_candidate_ids"]


def test_batch_hash_is_stable(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)

    assert _summary(fixture)["batch_sha256"] == _summary(fixture)["batch_sha256"]


def test_changing_candidate_id_changes_hash(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    original = _summary(fixture)["batch_sha256"]
    _write_jsonl(fixture["candidates_file"], [_candidate("rc1_ffffffffffffffff")])

    changed = _summary(fixture)["batch_sha256"]

    assert changed != original


def test_changing_evidence_excerpt_changes_hash(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    original = _summary(fixture)["batch_sha256"]
    _write_jsonl(fixture["candidates_file"], [_candidate(CID_READY, excerpt="changed excerpt")])

    changed = _summary(fixture)["batch_sha256"]

    assert changed != original


def test_wrong_confirmation_does_not_persist_approval(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    summary = _summary(fixture)
    paths = menu._batch_paths(fixture["review_dir"])

    ok = batch.persist_batch_decision(summary, decisions_path=paths["decisions"], audit_path=paths["audit"], confirmation="NO")

    assert ok is False
    assert batch.approved_batch_decision(batch.load_json(paths["decisions"], batch.empty_batch_decisions_doc())) is None


def test_exact_confirmation_persists_approval(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)

    _approve_batch(fixture)

    decision = batch.approved_batch_decision(batch.load_json(menu._batch_paths(fixture["review_dir"])["decisions"], {}))
    assert decision is not None
    assert decision["confirmation_token"] == batch.CONFIRMATION_TOKEN


def test_batch_decision_includes_candidate_ids(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    _approve_batch(fixture)

    decision = batch.approved_batch_decision(batch.load_json(menu._batch_paths(fixture["review_dir"])["decisions"], {}))
    assert decision["candidate_ids"] == [CID_READY]


def test_batch_decision_includes_batch_sha256(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    expected = _summary(fixture)["batch_sha256"]
    _approve_batch(fixture)

    decision = batch.approved_batch_decision(batch.load_json(menu._batch_paths(fixture["review_dir"])["decisions"], {}))
    assert decision["batch_sha256"] == expected


def test_gate_accepts_approved_batch_with_matching_hash(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    _approve_batch(fixture)

    assert _run_gate(fixture) == 0

    ready = json.loads((fixture["admission_dir"] / "admission_ready_dry_run.json").read_text())
    assert ready["summary"]["total"] == 1
    assert ready["items"][0]["candidate_id"] == CID_READY


def test_gate_blocks_batch_hash_mismatch(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    _approve_batch(fixture)
    _write_jsonl(fixture["candidates_file"], [_candidate(CID_READY, excerpt="changed excerpt")])

    assert _run_gate(fixture) == 0

    blocked = json.loads((fixture["admission_dir"] / "admission_blocked.json").read_text())
    assert blocked["summary"]["by_decision"] == {"blocked_batch_hash_mismatch": 1}


def test_individual_rejection_overrides_batch_approval(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    _approve_batch(fixture)
    individual = fixture["review_dir"] / "individual.json"
    individual.write_text(
        json.dumps({
            "schema": "relation-human-review-decisions/v1",
            "session": "S0142",
            "dry_run": True,
            "applied_to_canon": False,
            "reviewer": {"reviewer_id": "local-operator", "reviewer_role": "human_operator"},
            "decisions": [
                {
                    "candidate_id": CID_READY,
                    "decision": "rejected_by_human",
                    "reviewed_at": "2026-06-11T00:00:00Z",
                    "rationale": "Rejected in individual review.",
                    "checks": {
                        "source_verified": False,
                        "target_verified": False,
                        "evidence_excerpt_verified": False,
                        "relation_type_checked_against_s0139": False,
                        "not_duplicate_of_existing_relation": False,
                        "no_canonical_write_requested": True,
                    },
                }
            ],
        }),
        encoding="utf-8",
    )

    assert _run_gate(fixture, individual=individual) == 0

    blocked = json.loads((fixture["admission_dir"] / "admission_blocked.json").read_text())
    assert blocked["summary"]["by_decision"]["rejected_by_human"] == 1


def test_patch_preview_declares_not_applied(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    _approve_batch(fixture)
    _run_gate(fixture)

    preview = json.loads((fixture["admission_dir"] / "admission_patch_preview.json").read_text())
    assert preview["applied_to_canon"] is False
    assert preview["canon_modified"] is False
    assert preview["applicable"] is False


def test_no_tiddlers_jsonl_changes(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    before = hashlib.sha256(fixture["canon_file"].read_bytes()).hexdigest()
    _approve_batch(fixture)

    _run_gate(fixture)

    after = hashlib.sha256(fixture["canon_file"].read_bytes()).hexdigest()
    assert after == before


def test_terminal_report_includes_category_counts(tmp_path: Path) -> None:
    report = batch.render_terminal_batch_report(_summary(_fixture(tmp_path)), sample_size=0)

    assert "BATCH READY:" in report
    assert "REQUIEREN REVISION INDIVIDUAL:" in report
    assert "BLOQUEADOS:" in report
    assert "Batch SHA256:" in report


def test_menu_keeps_canonical_admission_block_visible() -> None:
    assert "Admisión canónica relacional" in menu._MENU_HEADER
    assert "BLOQUEADA" in menu._MENU_HEADER
    assert "Revisar lote batch" in menu._MENU_HEADER
    assert "Generar reporte batch técnico" in menu._ADVANCED_MENU_HEADER
