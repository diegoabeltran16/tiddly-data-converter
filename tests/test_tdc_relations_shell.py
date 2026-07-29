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
    assert "Previsualizar lotes homogéneos v2" in result.stdout
    assert "Superseder revisión legacy con respaldo histórico" in result.stdout
    assert "Revisar múltiples lotes homogéneos v2" in result.stdout


def test_tdc_relations_summary_uses_current_operational_state() -> None:
    result = _run_tdc("3\n0\n", "relations")

    assert result.returncode == 0
    assert '"schema_version": "relational-operational-state/v1"' in result.stdout
    assert '"candidate_generation"' in result.stdout
    assert "S0167 repaired queue" not in result.stdout


def test_tdc_relations_dry_run_missing_reviewable_queue_gives_exact_guidance(tmp_path: Path) -> None:
    missing_queue = tmp_path / "ready_for_human_review.jsonl"

    result = _run_tdc_with_env(
        "3\n\n0\n",
        {"RELATION_REVIEWABLE_FILE": str(missing_queue), "PATH": "/usr/bin:/bin"},
        "relations-admission",
    )

    assert result.returncode == 1
    assert f"No existe la cola reviewable vigente: {missing_queue}." in result.stdout
    assert "Ejecute primero “Validar y reconciliar candidatas vigentes” (opción 2)" in result.stdout
    assert "o defina RELATION_REVIEWABLE_FILE." in result.stdout
    assert "RELATION_CANDIDATE_FILE" not in result.stdout


def _fake_python(tmp_path: Path) -> tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    args_file = tmp_path / "python-args.txt"
    executable = bin_dir / "python3"
    executable.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "$TDC_TEST_ARGS"\n', encoding="utf-8")
    executable.chmod(0o755)
    return bin_dir, args_file


def test_batch_preview_menu_routes_to_non_writing_v2_surface(tmp_path: Path) -> None:
    bin_dir, args_file = _fake_python(tmp_path)
    result = _run_tdc_with_env("7\n0\n", {
        "PATH": f"{bin_dir}:/usr/bin:/bin", "TDC_TEST_ARGS": str(args_file),
        "RELATION_OUT_DIR": str(tmp_path / "current"), "CANON_DIR": str(tmp_path / "local"),
        "AUDIT_DIR": str(tmp_path / "audit"),
    }, "relations-admission")
    assert result.returncode == 0
    args = args_file.read_text(encoding="utf-8").splitlines()
    assert "--preview-batches" in args
    assert "--review-batches" not in args


def test_multiple_batch_menu_preserves_a_distinct_governed_route(tmp_path: Path) -> None:
    bin_dir, args_file = _fake_python(tmp_path)
    result = _run_tdc_with_env("10\n0\n", {
        "PATH": f"{bin_dir}:/usr/bin:/bin", "TDC_TEST_ARGS": str(args_file),
        "RELATION_OUT_DIR": str(tmp_path / "current"), "CANON_DIR": str(tmp_path / "local"),
        "AUDIT_DIR": str(tmp_path / "audit"),
    }, "relations-admission")
    assert result.returncode == 0
    args = args_file.read_text(encoding="utf-8").splitlines()
    assert "--review-multiple-batches" in args
    assert "--review-batches" not in args


def test_legacy_supersession_menu_forwards_explicit_actor_note_and_token(tmp_path: Path) -> None:
    bin_dir, args_file = _fake_python(tmp_path)
    result = _run_tdc_with_env(
        "9\nNaveen\nJustificación libre no auditable.\nSUPERSEDE CURRENT HUMAN REVIEW\n0\n",
        {
            "PATH": f"{bin_dir}:/usr/bin:/bin", "TDC_TEST_ARGS": str(args_file),
            "RELATION_OUT_DIR": str(tmp_path / "current"), "CANON_DIR": str(tmp_path / "local"),
            "AUDIT_DIR": str(tmp_path / "audit"),
        },
        "relations-admission",
    )
    assert result.returncode == 0
    args = args_file.read_text(encoding="utf-8").splitlines()
    assert "--supersede-current" in args
    assert "Naveen" in args
    assert "SUPERSEDE CURRENT HUMAN REVIEW" in args


def _fake_python_preflight(tmp_path: Path, *, allowed: bool) -> tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    args_file = tmp_path / "python-args.txt"
    executable = bin_dir / "python3"
    exit_code = 0 if allowed else 2
    executable.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "${1:-}" == "-" ]]; then\n'
        '  exec /usr/bin/python3 "$@"\n'
        "fi\n"
        'printf "%s\\n" "$*" >> "$TDC_TEST_ARGS"\n'
        'if [[ "$*" == *"relation_admission_state.py apply-preflight"* ]]; then\n'
        f'  printf \'{{"allowed": {str(allowed).lower()}, "reasons": ["stale"]}}\\n\'\n'
        f"  exit {exit_code}\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return bin_dir, args_file


def test_dry_run_omits_empty_human_decisions_flag(tmp_path: Path) -> None:
    bin_dir, args_file = _fake_python(tmp_path)
    current = tmp_path / "current"
    current.mkdir()
    (current / "ready_for_human_review.jsonl").write_text("", encoding="utf-8")
    decisions = current / "human_review_decisions.jsonl"
    decisions.write_text("", encoding="utf-8")
    result = _run_tdc_with_env("3\n0\n", {
        "PATH": f"{bin_dir}:/usr/bin:/bin", "TDC_TEST_ARGS": str(args_file),
        "RELATION_OUT_DIR": str(current), "RELATION_HUMAN_REVIEW_DECISIONS": str(decisions),
        "AUDIT_DIR": str(tmp_path / "audit"), "CANON_DIR": str(tmp_path / "local"),
    }, "relations-admission")
    assert result.returncode == 0
    assert "--human-review-decisions" not in args_file.read_text(encoding="utf-8")


def test_dry_run_passes_nonempty_human_decisions_flag(tmp_path: Path) -> None:
    bin_dir, args_file = _fake_python(tmp_path)
    current = tmp_path / "current"
    current.mkdir()
    (current / "ready_for_human_review.jsonl").write_text("{}\n", encoding="utf-8")
    decisions = current / "human_review_decisions.jsonl"
    decisions.write_text("{}\n", encoding="utf-8")
    result = _run_tdc_with_env("3\n0\n", {
        "PATH": f"{bin_dir}:/usr/bin:/bin", "TDC_TEST_ARGS": str(args_file),
        "RELATION_OUT_DIR": str(current), "RELATION_HUMAN_REVIEW_DECISIONS": str(decisions),
        "AUDIT_DIR": str(tmp_path / "audit"), "CANON_DIR": str(tmp_path / "local"),
    }, "relations-admission")
    assert result.returncode == 0
    args = args_file.read_text(encoding="utf-8").splitlines()
    assert "--human-review-decisions" in args
    assert str(decisions) in args


def test_tdc_relations_apply_cancel_does_not_modify_canon() -> None:
    before = {
        path: path.stat().st_mtime
        for path in sorted((REPO_ROOT / "data" / "out" / "local").glob("tiddlers_*.jsonl"))
    }
    result = _run_tdc("5\nNO\n0\n", "relations-admission")
    after = {path: path.stat().st_mtime for path in before}

    assert result.returncode == 1
    assert "RELATION_APPLY_PREFLIGHT_BLOCKED" in result.stdout
    assert "Escribe exactamente:" not in result.stdout
    assert "No se modificó el canon." in result.stdout
    assert after == before


def test_tdc_relations_apply_zero_ready_does_not_request_confirmation(tmp_path: Path) -> None:
    bin_dir, _ = _fake_python_preflight(tmp_path, allowed=True)
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    candidate_file = tmp_path / "candidates.jsonl"
    candidate_file.write_text("", encoding="utf-8")
    (audit_dir / "admission_gate_dry_run.json").write_text(
        json.dumps({
            "summary": {
                "total_evaluated": 0,
                "evaluated": 0,
                "awaiting_human_review": 0,
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
                "PATH": f"{bin_dir}:/usr/bin:/bin",
        },
        "relations-admission",
    )

    assert result.returncode == 1
    assert "NO_ADMISSION_READY_CANDIDATES" in result.stdout
    assert "Apply bloqueado: no existen candidatas admission-ready." in result.stdout
    assert "Escribe exactamente:" not in result.stdout
    assert "No se solicitará confirmación y no se modificó el canon." in result.stdout
    assert not (audit_dir / "relation_apply_plan.json").exists()


def test_tdc_relations_apply_blocks_incomplete_review_before_safe_engine(tmp_path: Path) -> None:
    bin_dir, _ = _fake_python_preflight(tmp_path, allowed=True)
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    candidate_file = tmp_path / "candidates.jsonl"
    candidate_file.write_text("", encoding="utf-8")
    (audit_dir / "admission_gate_dry_run.json").write_text(
        json.dumps({
            "summary": {
                "total_evaluated": 1,
                "evaluated": 1,
                "awaiting_human_review": 1,
                "admission_ready_dry_run": 0,
                "blocked": 1,
                "canon_modified": False,
                "dry_run": True,
            },
            "items": [
                {
                    "gate_status": "blocked",
                    "human_review_decision": "",
                    "all_block_reasons": ["GATE-008: falta revisión humana"],
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
                "PATH": f"{bin_dir}:/usr/bin:/bin",
        },
        "relations-admission",
    )

    assert result.returncode == 1
    assert "HUMAN_REVIEW_INCOMPLETE" in result.stdout
    assert "Apply bloqueado: la revisión humana del lote current está incompleta." in result.stdout
    assert "Resuelva las candidatas awaiting antes de preparar una admisión." in result.stdout
    assert "Escribe exactamente:" not in result.stdout
    assert "No se solicitará confirmación y no se modificó el canon." in result.stdout
    assert not (audit_dir / "relation_apply_plan.json").exists()


def test_tdc_relations_apply_stale_gate_does_not_request_confirmation(tmp_path: Path) -> None:
    bin_dir, args_file = _fake_python_preflight(tmp_path, allowed=False)
    result = _run_tdc_with_env("5\nAPPLY RELATIONS\n", {
        "PATH": f"{bin_dir}:/usr/bin:/bin", "TDC_TEST_ARGS": str(args_file),
        "CANON_DIR": str(tmp_path / "local"),
    }, "relations-admission")
    assert result.returncode == 1
    assert '"allowed": false' in result.stdout
    assert "APPLY RELATIONS bloqueado antes de solicitar confirmación." in result.stdout
    assert "Escribe exactamente:" not in result.stdout


def test_tdc_relations_apply_current_ready_state_preserves_exact_prompt(tmp_path: Path) -> None:
    bin_dir, args_file = _fake_python_preflight(tmp_path, allowed=True)
    current = tmp_path / "current"
    current.mkdir()
    (current / "ready_for_human_review.jsonl").write_text("{}\n", encoding="utf-8")
    decisions = current / "human_review_decisions.jsonl"
    decisions.write_text("{}\n", encoding="utf-8")
    audit = tmp_path / "audit"
    audit.mkdir()
    (audit / "admission_gate_dry_run.json").write_text(
        json.dumps({
            "summary": {
                "total_evaluated": 1,
                "awaiting_human_review": 0,
                "admission_ready_dry_run": 1,
                "canon_modified": False,
                "dry_run": True,
            },
            "items": [{"human_review_decision": "approved_for_admission"}],
        }),
        encoding="utf-8",
    )
    result = _run_tdc_with_env("5\nNO\n0\n", {
        "PATH": f"{bin_dir}:/usr/bin:/bin", "TDC_TEST_ARGS": str(args_file),
        "CANON_DIR": str(tmp_path / "local"), "RELATION_OUT_DIR": str(current),
        "RELATION_HUMAN_REVIEW_DECISIONS": str(decisions),
        "AUDIT_DIR": str(audit),
    }, "relations-admission")
    assert result.returncode == 1
    assert '"allowed": true' in result.stdout
    assert "Escribe exactamente:\nAPPLY RELATIONS\npara continuar." in result.stdout
    assert "RELATION_APPLY_CANCELLED" in result.stdout
    assert "Apply cancelado: no se recibió la confirmación exacta requerida." in result.stdout


def test_tdc_relations_apply_exact_confirmation_invokes_safe_engine_on_fixture(tmp_path: Path) -> None:
    bin_dir, args_file = _fake_python_preflight(tmp_path, allowed=True)
    current = tmp_path / "current"
    current.mkdir()
    (current / "ready_for_human_review.jsonl").write_text("{}\n", encoding="utf-8")
    decisions = current / "human_review_decisions.jsonl"
    decisions.write_text("{}\n", encoding="utf-8")
    audit = tmp_path / "audit"
    audit.mkdir()
    (audit / "admission_gate_dry_run.json").write_text(
        json.dumps({
            "summary": {
                "total_evaluated": 1,
                "awaiting_human_review": 0,
                "admission_ready_dry_run": 1,
                "canon_modified": False,
                "dry_run": True,
            },
            "items": [{"human_review_decision": "approved_for_admission"}],
        }),
        encoding="utf-8",
    )

    result = _run_tdc_with_env("5\nAPPLY RELATIONS\n0\n", {
        "PATH": f"{bin_dir}:/usr/bin:/bin", "TDC_TEST_ARGS": str(args_file),
        "CANON_DIR": str(tmp_path / "local"), "RELATION_OUT_DIR": str(current),
        "RELATION_HUMAN_REVIEW_DECISIONS": str(decisions),
        "AUDIT_DIR": str(audit),
    }, "relations-admission")

    assert result.returncode == 0
    calls = args_file.read_text(encoding="utf-8")
    assert "relation_admission_gate.py" in calls
    assert "--terminal-confirmation APPLY RELATIONS" in calls
    assert "--authorization-file data/out/local/audit/s0183/gate-g/gate_g_authorization.json" in calls
    assert "--authorized-plan data/out/local/audit/s0183/gate-g/relation_apply_plan.json" in calls
    assert "--apply" in calls


def test_tdc_relations_rollback_requires_snapshot_and_exact_confirmation(tmp_path: Path) -> None:
    bin_dir, args_file = _fake_python(tmp_path)
    snapshot = tmp_path / "snapshot_manifest.json"
    snapshot.write_text("{}\n", encoding="utf-8")
    result = _run_tdc_with_env("11\nROLLBACK RELATIONS\n0\n", {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "TDC_TEST_ARGS": str(args_file),
        "RELATION_ROLLBACK_SNAPSHOT": str(snapshot),
        "AUDIT_DIR": str(tmp_path / "audit"),
    }, "relations-admission")
    assert result.returncode == 0
    args = args_file.read_text(encoding="utf-8").splitlines()
    assert "--rollback-snapshot" in args
    assert str(snapshot) in args
    assert "--rollback-confirmation" in args
    assert "ROLLBACK RELATIONS" in args
