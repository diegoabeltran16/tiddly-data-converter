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


def test_tdc_relations_summary_uses_current_operational_state(
    tmp_path: Path,
) -> None:
    local = tmp_path / "local"
    local.mkdir()
    (local / "tiddlers_1.jsonl").write_text(
        '{"id":"fixture","relations":[]}\n', encoding="utf-8",
    )
    result = _run_tdc_with_env(
        "3\n0\n",
        {"CANON_DIR": str(local), "PATH": "/usr/bin:/bin"},
        "relations",
    )

    assert result.returncode == 0
    assert '"schema_version": "relational-operational-state/v1"' in result.stdout
    assert '"candidate_generation"' in result.stdout
    assert "S0167 repaired queue" not in result.stdout
    assert not (
        local
        / "audit/relation_admission/current/relational_operational_state.json"
    ).is_file()


def test_tdc_relations_review_queue_distinguishes_technical_and_effective_state() -> None:
    result = _run_tdc("4\n\n0\n", "relations")

    assert result.returncode == 0
    assert "Cola técnica reviewable:" in result.stdout
    assert "Cobertura efectiva de decisiones:" in result.stdout
    assert "Delta humano efectivo pendiente:" in result.stdout
    assert "Autoridad generacional current:" in result.stdout
    assert "Estado operacional:" in result.stdout
    assert "Siguiente acción:" in result.stdout
    assert "revisión humana no ejecutada" not in result.stdout


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
    executable.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@" >> "$TDC_TEST_ARGS"\n', encoding="utf-8")
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


def test_single_batch_menu_routes_to_current_writer_and_returns_to_relational_submenu(tmp_path: Path) -> None:
    bin_dir, args_file = _fake_python(tmp_path)
    result = _run_tdc_with_env("8\n\n0\n", {
        "PATH": f"{bin_dir}:/usr/bin:/bin", "TDC_TEST_ARGS": str(args_file),
        "RELATION_OUT_DIR": str(tmp_path / "current"), "CANON_DIR": str(tmp_path / "local"),
        "AUDIT_DIR": str(tmp_path / "audit"),
    }, "relations-admission")
    assert result.returncode == 0
    args = args_file.read_text(encoding="utf-8").splitlines()
    assert "--review-batches" in args
    assert "--review-multiple-batches" not in args
    assert result.stdout.count("Revisión humana / admisión relacional") >= 2


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


def test_prepare_current_generation_menu_is_option_12_and_requests_no_identity(tmp_path: Path) -> None:
    bin_dir, args_file = _fake_python(tmp_path)
    result = _run_tdc_with_env("12\n0\n", {
        "PATH": f"{bin_dir}:/usr/bin:/bin", "TDC_TEST_ARGS": str(args_file),
        "RELATION_OUT_DIR": str(tmp_path / "current"), "CANON_DIR": str(tmp_path / "local"),
        "AUDIT_DIR": str(tmp_path / "audit"),
    }, "relations-admission")

    assert result.returncode == 0
    assert "12) Preparar generación relacional current" in result.stdout
    assert "Identidad" not in result.stdout
    args = args_file.read_text(encoding="utf-8").splitlines()
    assert "src/python_scripts/prepare_current_relational_generation.py" in args
    assert "--status" in args
    assert "--dry-run" in args
    assert "--execute" in args
    assert "--compact" in args


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


def test_legacy_supersession_menu_blocks_before_confirmation_when_migration_preflight_fails(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    args_file = tmp_path / "python-args.txt"
    executable = bin_dir / "python3"
    executable.write_text(
        "#!/usr/bin/env bash\n"
        'printf "%s\\n" "$*" >> "$TDC_TEST_ARGS"\n'
        'if [[ "$*" == *"--migrate-equivalent"* ]]; then\n'
        '  printf "HUMAN_DECISION_MIGRATION_BLOCKED\\n"\n'
        '  printf "many_to_one_current_id_collision\\n"\n'
        "  exit 2\n"
        "fi\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)

    result = _run_tdc_with_env("9\n0\n", {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "TDC_TEST_ARGS": str(args_file),
        "RELATION_OUT_DIR": str(tmp_path / "current"),
        "CANON_DIR": str(tmp_path / "local"),
        "AUDIT_DIR": str(tmp_path / "audit"),
        "RELATION_MIGRATION_SOURCE_DECISIONS": str(tmp_path / "historical.jsonl"),
        "RELATION_MIGRATION_CROSS_BATCH_MANIFEST": str(tmp_path / "cross.json"),
    }, "relations-admission")

    args = args_file.read_text(encoding="utf-8")
    assert result.returncode == 1
    assert "--migrate-equivalent" in args
    assert "--supersede-current" not in args
    assert "HUMAN_DECISION_MIGRATION_BLOCKED" in result.stdout
    assert "Supersesión bloqueada por el preflight" in result.stdout
    assert "Identidad del revisor humano" not in result.stdout


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


def test_tdc_relations_apply_requires_a_current_self_contained_bundle() -> None:
    before = {
        path: path.stat().st_mtime
        for path in sorted((REPO_ROOT / "data" / "out" / "local").glob("tiddlers_*.jsonl"))
    }
    result = _run_tdc("5\n0\n", "relations-admission")
    after = {path: path.stat().st_mtime for path in before}

    assert result.returncode == 1
    assert "RELATION_APPLY_PREFLIGHT_BLOCKED" in result.stdout
    assert "current_bundle_" in result.stdout
    assert after == before


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
