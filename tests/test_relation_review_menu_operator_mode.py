"""S0143 tests for simplified operator relational menu mode."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

import relation_batch_review as batch  # noqa: E402
import relation_review_menu as menu  # noqa: E402


CID_READY = "rc1_a1b2c3d4e5f6a7b8"
CID_REVIEW = "rc1_b2c3d4e5f6a7b8c9"
CID_BLOCKED = "rc1_e5f6a7b8c9d0e1f2"


def _candidate(
    cid: str,
    *,
    score: float = 0.92,
    excerpt: str = "approved excerpt",
    target_id: str = "tgt-002",
) -> dict:
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
    candidates_file = tmp_path / "valid_candidates.jsonl"
    canon_dir = tmp_path / "canon"
    type_policy_dir = tmp_path / "type_policy"
    admissibility_report = tmp_path / "admissibility.json"
    review_dir = tmp_path / "relation_review" / "s0142"
    admission_dir = tmp_path / "relation_admission" / "s0143"

    _write_jsonl(
        candidates_file,
        [
            _candidate(CID_READY),
            _candidate(CID_REVIEW, score=0.71),
            _candidate(CID_BLOCKED, target_id="missing-target"),
        ],
    )
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
        json.dumps(
            {
                "results": [
                    {"candidate_id": CID_READY, "risk_level": "low", "decision": "review_required"},
                    {"candidate_id": CID_REVIEW, "risk_level": "high", "decision": "review_required"},
                    {"candidate_id": CID_BLOCKED, "risk_level": "medium", "decision": "review_required"},
                ]
            },
            ensure_ascii=False,
        ),
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


def _review_and_approve(fixture: dict[str, Path], confirmation: str) -> bool:
    return menu.review_batch_and_approve_for_dry_run(
        review_dir=fixture["review_dir"],
        confirmation=confirmation,
        candidates_file=fixture["candidates_file"],
        canon_glob=str(fixture["canon_glob"]),
        type_policy_dir=fixture["type_policy_dir"],
        admissibility_report=fixture["admissibility_report"],
    )


def _run_s0143_gate(fixture: dict[str, Path]) -> int:
    return menu.run_s0143_batch_admission_gate_dry_run(
        review_dir=fixture["review_dir"],
        admission_dir=fixture["admission_dir"],
        candidates_file=fixture["candidates_file"],
        canon_glob=str(fixture["canon_glob"]),
        type_policy_dir=fixture["type_policy_dir"],
        admissibility_report=fixture["admissibility_report"],
    )


def _batch_decision(fixture: dict[str, Path]) -> dict | None:
    path = menu._batch_paths(fixture["review_dir"])["decisions"]
    doc = batch.load_json(path, batch.empty_batch_decisions_doc())
    return batch.approved_batch_decision(doc)


def test_main_menu_shows_only_simple_operator_options() -> None:
    assert "1) Revisar lote batch y aprobar para dry-run" in menu._MENU_HEADER
    assert "2) Ejecutar compuerta dry-run con aprobación existente" in menu._MENU_HEADER
    assert "3) Ver último resultado dry-run" in menu._MENU_HEADER
    assert "4) Ver candidatos bloqueados / revisión individual" in menu._MENU_HEADER
    assert "9) Avanzado / mantenimiento" in menu._MENU_HEADER
    assert "5)" not in menu._MENU_HEADER


def test_main_menu_does_not_show_legacy_s0135_directly() -> None:
    assert "S0135" not in menu._MENU_HEADER
    assert "Generar plan" not in menu._MENU_HEADER


def test_main_menu_includes_advanced_maintenance() -> None:
    assert "Avanzado / mantenimiento" in menu._MENU_HEADER


def test_main_menu_keeps_dry_run_visible() -> None:
    assert "DRY-RUN" in menu._MENU_HEADER


def test_main_menu_keeps_canon_protected_visible() -> None:
    assert "Canon: PROTEGIDO" in menu._MENU_HEADER


def test_option_1_does_not_request_manual_candidate_id(tmp_path: Path, capsys) -> None:
    fixture = _fixture(tmp_path)

    _review_and_approve(fixture, confirmation="NO")

    out = capsys.readouterr().out
    assert "Candidate ID" not in out
    assert "candidate_id manual" not in out


def test_option_1_shows_batch_report_in_terminal(tmp_path: Path, capsys) -> None:
    fixture = _fixture(tmp_path)

    _review_and_approve(fixture, confirmation="NO")

    assert "Reporte batch de human_review relacional" in capsys.readouterr().out


def test_option_1_shows_batch_id_and_sha256(tmp_path: Path, capsys) -> None:
    fixture = _fixture(tmp_path)

    _review_and_approve(fixture, confirmation="NO")

    out = capsys.readouterr().out
    assert "batch_id:" in out
    assert "batch_sha256:" in out


def test_option_1_requires_strong_confirmation_token(tmp_path: Path, capsys) -> None:
    fixture = _fixture(tmp_path)

    _review_and_approve(fixture, confirmation="NO")

    assert batch.CONFIRMATION_TOKEN in capsys.readouterr().out


def test_wrong_confirmation_does_not_persist_batch_decision(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)

    assert _review_and_approve(fixture, confirmation="NO") is False

    assert _batch_decision(fixture) is None


def test_correct_confirmation_persists_batch_decision(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)

    assert _review_and_approve(fixture, confirmation=batch.CONFIRMATION_TOKEN)

    decision = _batch_decision(fixture)
    assert decision is not None
    assert decision["confirmation_token"] == batch.CONFIRMATION_TOKEN


def test_option_2_executes_s0143_dry_run_gate(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    _review_and_approve(fixture, confirmation=batch.CONFIRMATION_TOKEN)

    assert _run_s0143_gate(fixture) == 0

    ready = json.loads((fixture["admission_dir"] / "admission_ready_dry_run.json").read_text())
    assert ready["session"] == "S0143"
    assert ready["dry_run"] is True
    assert ready["applied_to_canon"] is False
    assert ready["canon_modified"] is False


def test_option_3_shows_latest_dry_run_result(tmp_path: Path, capsys) -> None:
    fixture = _fixture(tmp_path)
    _review_and_approve(fixture, confirmation=batch.CONFIRMATION_TOKEN)
    _run_s0143_gate(fixture)

    menu.show_latest_dry_run_result(fixture["admission_dir"], review_dir=fixture["review_dir"])

    out = capsys.readouterr().out
    assert "Último resultado dry-run" in out
    assert "admission_ready_dry_run:" in out
    assert "admission_patch_preview.json" in out


def test_option_4_shows_blocked_or_individual_review(tmp_path: Path, capsys) -> None:
    fixture = _fixture(tmp_path)

    menu.show_blocked_or_individual_review_candidates(
        review_dir=fixture["review_dir"],
        candidates_file=fixture["candidates_file"],
        canon_glob=str(fixture["canon_glob"]),
        type_policy_dir=fixture["type_policy_dir"],
        admissibility_report=fixture["admissibility_report"],
    )

    out = capsys.readouterr().out
    assert "individual_review_required" in out
    assert "unverified_evidence" in out
    assert CID_READY not in out


def test_advanced_menu_contains_previous_technical_options() -> None:
    assert "Validar relaciones candidatas existentes" in menu._ADVANCED_MENU_HEADER
    assert "Ver último reporte humano" in menu._ADVANCED_MENU_HEADER
    assert "Ver cola de human_review pendiente" in menu._ADVANCED_MENU_HEADER
    assert "Ejecutar compuerta individual" in menu._ADVANCED_MENU_HEADER
    assert "Generar reporte batch técnico" in menu._ADVANCED_MENU_HEADER


def test_advanced_menu_marks_s0135_as_legacy_or_maintenance() -> None:
    assert "S0135" in menu._ADVANCED_MENU_HEADER
    assert "LEGACY" in menu._ADVANCED_MENU_HEADER
    assert "MANTENIMIENTO" in menu._ADVANCED_MENU_HEADER


def test_main_gate_command_never_uses_apply(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    _review_and_approve(fixture, confirmation=batch.CONFIRMATION_TOKEN)

    completed = mock.Mock(returncode=0, stdout="", stderr="")
    with mock.patch("relation_review_menu.subprocess.run", return_value=completed) as run:
        menu.run_s0143_batch_admission_gate_dry_run(
            review_dir=fixture["review_dir"],
            admission_dir=fixture["admission_dir"],
            candidates_file=fixture["candidates_file"],
            canon_glob=str(fixture["canon_glob"]),
            type_policy_dir=fixture["type_policy_dir"],
            admissibility_report=fixture["admissibility_report"],
        )

    cmd = run.call_args[0][0]
    assert "--dry-run" in cmd
    assert "--apply" not in cmd


def test_operator_flow_does_not_change_tiddlers_jsonl(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    before = hashlib.sha256(fixture["canon_file"].read_bytes()).hexdigest()

    _review_and_approve(fixture, confirmation=batch.CONFIRMATION_TOKEN)
    _run_s0143_gate(fixture)

    after = hashlib.sha256(fixture["canon_file"].read_bytes()).hexdigest()
    assert after == before
