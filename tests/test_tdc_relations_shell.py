from __future__ import annotations

import subprocess
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
TDC_SH = REPO_ROOT / "src" / "shell_scripts" / "tdc.sh"


def _run_tdc(input_text: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(TDC_SH), *args],
        cwd=REPO_ROOT,
        input=input_text,
        capture_output=True,
        text=True,
        check=False,
    )


def _run_tdc_with_env(
    input_text: str,
    env: dict[str, str],
    *args: str,
) -> subprocess.CompletedProcess[str]:
    merged_env = {**env}
    return subprocess.run(
        ["bash", str(TDC_SH), *args],
        cwd=REPO_ROOT,
        input=input_text,
        capture_output=True,
        text=True,
        check=False,
        env=merged_env,
    )


def test_tdc_relations_submenu_is_visible() -> None:
    result = _run_tdc("0\n", "relations")
    assert result.returncode == 0
    assert "Relaciones canónicas" in result.stdout
    assert "Canon: PROTEGIDO" in result.stdout
    assert "Validar y reconciliar candidatas vigentes" in result.stdout
    assert "Este módulo no contiene apply" in result.stdout
    assert "APPLY RELATIONS al canon" not in result.stdout


def test_tdc_default_opens_single_operator_menu() -> None:
    result = _run_tdc("0\n")

    assert result.returncode == 0
    assert "Tiddly Data Converter - Operador local" in result.stdout
    assert "TDC · Tiddly Data Converter" not in result.stdout
    assert "1) Canon" not in result.stdout
    assert "6) Relaciones canónicas" in result.stdout
    assert "7) Revisión / admisión gobernada" in result.stdout


def test_tdc_main_option_6_opens_canonical_relations() -> None:
    result = _run_tdc("6\n0\n0\n")

    assert result.returncode == 0
    assert "Tiddly Data Converter - Operador local" in result.stdout
    assert "Relaciones canónicas" in result.stdout
    assert "Generar candidatas desde canon vigente" in result.stdout
    assert "Validar y reconciliar candidatas vigentes" in result.stdout
    assert "Ver estado relacional vigente" in result.stdout
    assert "APPLY RELATIONS al canon" not in result.stdout


def test_tdc_governed_admission_bridges_to_canonical_relations_without_duplicate_label() -> None:
    result = _run_tdc("7\n2\n0\n0\n0\n")

    assert result.returncode == 0
    assert "Revisión / admisión gobernada" in result.stdout
    assert "Relaciones canónicas" in result.stdout
    assert "Relaciones candidatas" not in result.stdout
    assert "Revisión humana / admisión relacional" in result.stdout
    assert "Ejecutar admission gate dry-run" in result.stdout


def test_tdc_relations_summary_uses_current_operational_state() -> None:
    result = _run_tdc("3\n0\n", "relations")

    assert result.returncode == 0
    assert '"schema_version": "relational-operational-state/v1"' in result.stdout
    assert '"candidate_generation"' in result.stdout
    assert "S0167 repaired queue" not in result.stdout


def test_tdc_relations_apply_cancel_does_not_modify_canon() -> None:
    before = {
        path: path.stat().st_mtime
        for path in sorted((REPO_ROOT / "data" / "out" / "local").glob("tiddlers_*.jsonl"))
    }
    result = _run_tdc("5\nNO\n0\n", "relations-admission")
    after = {path: path.stat().st_mtime for path in before}

    assert result.returncode == 0
    assert "ATENCIÓN:" in result.stdout
    assert "Operación cancelada. No se modificó el canon." in result.stdout
    assert after == before


def test_tdc_relations_apply_exact_confirmation_blocks_without_ready_candidates(tmp_path: Path) -> None:
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    candidate_file = tmp_path / "candidates.jsonl"
    candidate_file.write_text("", encoding="utf-8")
    (audit_dir / "admission_gate_dry_run.json").write_text(
        json.dumps({
            "summary": {
                "admission_ready_dry_run": 0,
                "blocked": 1,
                "canon_modified": False,
                "dry_run": True,
            },
            "items": [],
        }),
        encoding="utf-8",
    )

    result = _run_tdc_with_env(
        "5\nAPPLY RELATIONS\n0\n",
        {
            "AUDIT_DIR": str(audit_dir),
            "RELATION_CANDIDATE_FILE": str(candidate_file),
            "RELATION_HUMAN_REVIEW_DECISIONS": str(tmp_path / "missing-review.jsonl"),
            "PATH": "/usr/bin:/bin",
        },
        "relations-admission",
    )

    assert result.returncode == 1
    assert "APPLY RELATIONS bloqueado." in result.stdout
    assert "Motivo: no existe human_review_decision=approved_for_admission." in result.stdout
    assert "No se modificó el canon." in result.stdout


def test_tdc_relations_apply_routes_to_safe_engine_and_blocks_missing_review(tmp_path: Path) -> None:
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    candidate_file = tmp_path / "candidates.jsonl"
    candidate_file.write_text("", encoding="utf-8")
    (audit_dir / "admission_gate_dry_run.json").write_text(
        json.dumps({
            "summary": {
                "admission_ready_dry_run": 1,
                "blocked": 0,
                "canon_modified": False,
                "dry_run": True,
            },
            "items": [
                {
                    "gate_status": "admission_ready_dry_run",
                    "human_review_decision": "approved_for_admission",
                    "all_block_reasons": [],
                }
            ],
        }),
        encoding="utf-8",
    )

    result = _run_tdc_with_env(
        "5\nAPPLY RELATIONS\n0\n",
        {
            "AUDIT_DIR": str(audit_dir),
            "RELATION_CANDIDATE_FILE": str(candidate_file),
            "RELATION_HUMAN_REVIEW_DECISIONS": str(tmp_path / "missing-review.jsonl"),
            "PATH": "/usr/bin:/bin",
        },
        "relations-admission",
    )

    assert result.returncode == 1
    assert "APPLY RELATIONS bloqueado." in result.stdout
    assert "Motivo: no existe human_review_decision=approved_for_admission." in result.stdout
    assert (audit_dir / "relation_apply_plan.json").exists()
