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
    # S0186 Unit H (final intervention, top-level UX migration):
    # "Revisión / admisión gobernada" no longer exists as an independent
    # top-level entry (OLD_NAVIGATION_CONTRACT_MIGRATED).
    result = _run_tdc("0\n")

    assert result.returncode == 0
    assert "Tiddly Data Converter - Operador local" in result.stdout
    assert "TDC · Tiddly Data Converter" not in result.stdout
    assert "1) Canon" not in result.stdout
    assert "6) Relaciones canónicas" in result.stdout
    assert "Revisión / admisión gobernada" not in result.stdout


def test_tdc_main_option_6_opens_canonical_relations() -> None:
    result = _run_tdc("6\n0\n0\n")

    assert result.returncode == 0
    assert "Tiddly Data Converter - Operador local" in result.stdout
    assert "Relaciones canónicas" in result.stdout
    assert "Generar candidatas desde canon vigente" in result.stdout
    assert "Validar y reconciliar candidatas vigentes" in result.stdout
    assert "Ver estado relacional vigente" in result.stdout
    assert "APPLY RELATIONS al canon" not in result.stdout


def test_tdc_relations_menu_bridges_to_review_admission_apply() -> None:
    # S0186 Unit H (operator relational human-lifecycle unification): from
    # inside the technical-preparation menu (option 6, or alias 16), the
    # operator can now reach review/admission/Apply directly (item 6) instead
    # of backing out to the main menu and re-entering via 7->2.
    result = _run_tdc("6\n0\n", "relations")

    assert result.returncode == 0
    assert "Relaciones canónicas — revisión/admisión" in result.stdout
    assert "APPLY RELATIONS protegido" in result.stdout


def test_relations_admission_menu_shows_technically_invalid_review_item() -> None:
    # S0186 Unit H (final closure blocker, TASK B): item 8 exposes the
    # existing supersede_individual_decision() primitive for CURRENT
    # approved_for_admission candidates blocked as technically_invalid --
    # scoped exactly, zero decision writes when the operator declines.
    result = _run_tdc("8\n0\n0\n", "relations-admission")

    assert result.returncode == 0
    assert "8) Revisar aprobadas con bloqueo técnico" in result.stdout
    assert "Revisar aprobadas con bloqueo técnico (CURRENT)" in result.stdout


def test_canonical_relations_shows_review_admission_bridge_label() -> None:
    # S0186 Unit H (final intervention, top-level UX migration): the
    # top-level "Revisión / admisión gobernada" entry that used to host this
    # bridge was retired (OLD_NAVIGATION_CONTRACT_MIGRATED). The same content
    # is now reached entirely from within "6) Relaciones canónicas" -> its
    # own bash-level bridge item 6, added inside tdc_relations_menu().
    # Kept SHALLOW (single python->bash crossing, same depth as the
    # already-stable test_tdc_main_option_6_opens_canonical_relations):
    # deeper multi-level dips through this exact boundary are flaky
    # (Python's buffered input() can consume more of the shared stdin pipe
    # than the subprocess call logically needs -- confirmed empirically
    # here: going one level deeper into the bash-level bridge from behind
    # the python boundary starved the child process's stdin). The actual
    # admission-menu CONTENT reachable via this bridge is proven directly
    # against `relations` (bash-only, no python boundary) in
    # test_tdc_relations_menu_bridges_to_review_admission_apply above.
    result = _run_tdc("6\n0\n0\n")

    assert result.returncode == 0
    assert "Relaciones canónicas" in result.stdout
    assert "Relaciones candidatas" not in result.stdout
    assert "6) Revisión / admisión / Apply protegido" in result.stdout


def test_pending_review_submenu_lists_legacy_batch_capabilities() -> None:
    result = _run_tdc("3\n0\n0\n", "relations-admission")
    assert result.returncode == 0
    assert "Previsualizar lotes homogéneos (no escribe)" in result.stdout
    assert "Revisar y confirmar un lote" in result.stdout
    assert "Revisar múltiples lotes homogéneos" in result.stdout


def test_advanced_submenu_lists_legacy_supersession_and_rollback() -> None:
    result = _run_tdc("9\n0\n0\n", "relations-admission")
    assert result.returncode == 0
    assert "Superseder revisión legacy con respaldo histórico" in result.stdout
    assert "ROLLBACK RELATIONS protegido" in result.stdout


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
        "5\n\n0\n",
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
    result = _run_tdc_with_env("3\n3\n0\n0\n", {
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
    result = _run_tdc_with_env("3\n4\n\n0\n0\n", {
        "PATH": f"{bin_dir}:/usr/bin:/bin", "TDC_TEST_ARGS": str(args_file),
        "RELATION_OUT_DIR": str(tmp_path / "current"), "CANON_DIR": str(tmp_path / "local"),
        "AUDIT_DIR": str(tmp_path / "audit"),
    }, "relations-admission")
    assert result.returncode == 0
    args = args_file.read_text(encoding="utf-8").splitlines()
    assert "--review-batches" in args
    assert "--review-multiple-batches" not in args
    assert result.stdout.count("Relaciones canónicas — revisión/admisión") >= 2


def test_multiple_batch_menu_preserves_a_distinct_governed_route(tmp_path: Path) -> None:
    bin_dir, args_file = _fake_python(tmp_path)
    result = _run_tdc_with_env("3\n5\n0\n0\n", {
        "PATH": f"{bin_dir}:/usr/bin:/bin", "TDC_TEST_ARGS": str(args_file),
        "RELATION_OUT_DIR": str(tmp_path / "current"), "CANON_DIR": str(tmp_path / "local"),
        "AUDIT_DIR": str(tmp_path / "audit"),
    }, "relations-admission")
    assert result.returncode == 0
    args = args_file.read_text(encoding="utf-8").splitlines()
    assert "--review-multiple-batches" in args
    assert "--review-batches" not in args


def test_prepare_current_generation_menu_is_option_2_and_requests_no_identity(tmp_path: Path) -> None:
    bin_dir, args_file = _fake_python(tmp_path)
    result = _run_tdc_with_env("2\n0\n", {
        "PATH": f"{bin_dir}:/usr/bin:/bin", "TDC_TEST_ARGS": str(args_file),
        "RELATION_OUT_DIR": str(tmp_path / "current"), "CANON_DIR": str(tmp_path / "local"),
        "AUDIT_DIR": str(tmp_path / "audit"),
    }, "relations-admission")

    assert result.returncode == 0
    assert "2) Generar / reconciliar CURRENT" in result.stdout
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
        "9\n1\nNaveen\nJustificación libre no auditable.\nSUPERSEDE CURRENT HUMAN REVIEW\n0\n0\n",
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

    result = _run_tdc_with_env("9\n1\n0\n0\n", {
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
    result = _run_tdc_with_env("5\n0\n", {
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
    result = _run_tdc_with_env("5\n0\n", {
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
    result = _run_tdc("6\n0\n", "relations-admission")
    after = {path: path.stat().st_mtime for path in before}

    assert result.returncode == 1
    assert "RELATION_APPLY_PREFLIGHT_BLOCKED" in result.stdout
    assert "current_bundle_" in result.stdout
    assert after == before


def test_tdc_relations_rollback_requires_snapshot_and_exact_confirmation(tmp_path: Path) -> None:
    bin_dir, args_file = _fake_python(tmp_path)
    snapshot = tmp_path / "snapshot_manifest.json"
    snapshot.write_text("{}\n", encoding="utf-8")
    result = _run_tdc_with_env("9\n2\nROLLBACK RELATIONS\n0\n0\n", {
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


# ---------------------------------------------------------------------------
# S0186 Unit H8 — governed policy admission menu surface
#
# The H8 diagnostic session (post-first-authorization) found the primary
# relational menu too cluttered to use and moved policy governance into its
# own submenu (main option 4) rather than six top-level numbers 13-16, per
# the follow-up session brief. Every case below now navigates "4" first.
# ---------------------------------------------------------------------------

def test_relations_admission_menu_lists_simplified_primary_options() -> None:
    result = _run_tdc("0\n", "relations-admission")
    assert result.returncode == 0
    assert "1) Estado actual" in result.stdout
    assert "2) Generar / reconciliar CURRENT" in result.stdout
    assert "3) Revisar relaciones pendientes" in result.stdout
    assert "4) Gobernanza por políticas" in result.stdout
    assert "5) Preparar admisión (dry-run gate)" in result.stdout
    assert "6) APPLY RELATIONS protegido" in result.stdout
    assert "7) Reportes" in result.stdout
    assert "9) Avanzado" in result.stdout


def test_policy_submenu_lists_all_six_governance_options() -> None:
    result = _run_tdc("4\n0\n0\n", "relations-admission")
    assert result.returncode == 0
    assert "1) Resumen de políticas" in result.stdout
    assert "2) Ver detalle / muestra" in result.stdout
    assert "3) Ver excepciones" in result.stdout
    assert "4) Autorizar política CURRENT" in result.stdout
    assert "5) Materializar decisiones autorizadas" in result.stdout
    assert "6) Ver autorizaciones / decisiones (estado detallado)" in result.stdout


def test_policy_preview_menu_routes_to_compact_preview(tmp_path: Path) -> None:
    bin_dir, args_file = _fake_python(tmp_path)
    result = _run_tdc_with_env("4\n1\n0\n0\n", {
        "PATH": f"{bin_dir}:/usr/bin:/bin", "TDC_TEST_ARGS": str(args_file),
        "CANON_DIR": str(tmp_path / "local"),
    }, "relations-admission")

    assert result.returncode == 0
    args = args_file.read_text(encoding="utf-8").splitlines()
    assert "src/python_scripts/governed_relation_admission_policy.py" in args
    assert "--compact" in args
    assert "--local-root" in args
    assert "--authorize" not in args
    assert "--materialize" not in args


def test_policy_detail_menu_forwards_typed_policy_id(tmp_path: Path) -> None:
    bin_dir, args_file = _fake_python(tmp_path)
    result = _run_tdc_with_env("4\n2\nPYTHON_AST_IMPORT_DEPENDENCY_V1\n0\n0\n", {
        "PATH": f"{bin_dir}:/usr/bin:/bin", "TDC_TEST_ARGS": str(args_file),
        "CANON_DIR": str(tmp_path / "local"),
    }, "relations-admission")

    assert result.returncode == 0
    args = args_file.read_text(encoding="utf-8").splitlines()
    assert "--policy" in args
    assert "PYTHON_AST_IMPORT_DEPENDENCY_V1" in args


def test_policy_detail_menu_cancels_cleanly_on_empty_policy_id(tmp_path: Path) -> None:
    bin_dir, args_file = _fake_python(tmp_path)
    result = _run_tdc_with_env("4\n2\n\n0\n0\n", {
        "PATH": f"{bin_dir}:/usr/bin:/bin", "TDC_TEST_ARGS": str(args_file),
        "CANON_DIR": str(tmp_path / "local"),
    }, "relations-admission")

    assert result.returncode == 0
    assert not args_file.exists()


def test_policy_exceptions_menu_routes_to_exceptions_view(tmp_path: Path) -> None:
    bin_dir, args_file = _fake_python(tmp_path)
    result = _run_tdc_with_env("4\n3\n0\n0\n", {
        "PATH": f"{bin_dir}:/usr/bin:/bin", "TDC_TEST_ARGS": str(args_file),
        "CANON_DIR": str(tmp_path / "local"),
    }, "relations-admission")

    assert result.returncode == 0
    args = args_file.read_text(encoding="utf-8").splitlines()
    assert "--exceptions" in args


def test_policy_authorize_menu_requires_typed_confirmation_not_yn(tmp_path: Path) -> None:
    bin_dir, args_file = _fake_python(tmp_path)
    result = _run_tdc_with_env(
        "4\n4\nPYTHON_AST_IMPORT_DEPENDENCY_V1\noperator-1\nAUTHORIZE POLICY PYTHON_AST_IMPORT_DEPENDENCY_V1 FOR CURRENT BATCH\n0\n0\n",
        {
            "PATH": f"{bin_dir}:/usr/bin:/bin", "TDC_TEST_ARGS": str(args_file),
            "CANON_DIR": str(tmp_path / "local"),
        },
        "relations-admission",
    )

    assert result.returncode == 0
    assert "NO aprueba ninguna relación" in result.stdout
    args = args_file.read_text(encoding="utf-8").splitlines()
    # First call previews the policy detail (so the human sees what they are
    # about to authorize); the second call actually authorizes it.
    assert "--policy" in args
    assert "--authorize" in args
    assert "operator-1" in args
    assert "AUTHORIZE POLICY PYTHON_AST_IMPORT_DEPENDENCY_V1 FOR CURRENT BATCH" in args


def test_policy_authorize_menu_cancels_cleanly_on_empty_policy_id(tmp_path: Path) -> None:
    bin_dir, args_file = _fake_python(tmp_path)
    result = _run_tdc_with_env("4\n4\n\n0\n0\n", {
        "PATH": f"{bin_dir}:/usr/bin:/bin", "TDC_TEST_ARGS": str(args_file),
        "CANON_DIR": str(tmp_path / "local"),
    }, "relations-admission")

    assert result.returncode == 0
    assert not args_file.exists()


def test_policy_materialize_menu_forwards_policy_id_and_actor(tmp_path: Path) -> None:
    bin_dir, args_file = _fake_python(tmp_path)
    result = _run_tdc_with_env(
        "4\n5\nPYTHON_AST_IMPORT_DEPENDENCY_V1\noperator-1\n0\n0\n",
        {
            "PATH": f"{bin_dir}:/usr/bin:/bin", "TDC_TEST_ARGS": str(args_file),
            "CANON_DIR": str(tmp_path / "local"),
        },
        "relations-admission",
    )

    assert result.returncode == 0
    assert "SI escribe decisiones" in result.stdout
    args = args_file.read_text(encoding="utf-8").splitlines()
    assert "--materialize" in args
    assert "PYTHON_AST_IMPORT_DEPENDENCY_V1" in args
    assert "--actor" in args
    assert "operator-1" in args
    assert "--authorize" not in args


def test_policy_materialize_menu_cancels_cleanly_on_empty_policy_id(tmp_path: Path) -> None:
    bin_dir, args_file = _fake_python(tmp_path)
    result = _run_tdc_with_env("4\n5\n\n0\n0\n", {
        "PATH": f"{bin_dir}:/usr/bin:/bin", "TDC_TEST_ARGS": str(args_file),
        "CANON_DIR": str(tmp_path / "local"),
    }, "relations-admission")

    assert result.returncode == 0
    assert not args_file.exists()


def test_policy_status_menu_routes_to_status_view(tmp_path: Path) -> None:
    bin_dir, args_file = _fake_python(tmp_path)
    result = _run_tdc_with_env("4\n6\n0\n0\n", {
        "PATH": f"{bin_dir}:/usr/bin:/bin", "TDC_TEST_ARGS": str(args_file),
        "CANON_DIR": str(tmp_path / "local"),
    }, "relations-admission")

    assert result.returncode == 0
    args = args_file.read_text(encoding="utf-8").splitlines()
    assert "--status" in args
    assert "--authorize" not in args
    assert "--materialize" not in args


# ---------------------------------------------------------------------------
# S0186 Unit H8 (second diagnostic pass) -- end-to-end: menu materialization
# must actually change what the menu dry-run gate reports, using the real
# productive surfaces (no _fake_python -- these must be the real Python
# owners), against an isolated fixture. No Canon write; no Apply.
# ---------------------------------------------------------------------------

def _write_fixture_canon(local_root: Path) -> None:
    records = [
        {
            "id": "src-a", "title": "src/python_scripts/a.py", "key": "src/python_scripts/a.py",
            "text": "import b\n", "relations": [],
            "source_fields": {
                "repo_path": "src/python_scripts/a.py", "artifact_family": "python_script",
                "authority_level": "current_verified", "repo_lifecycle_state": "historical_snapshot",
            },
        },
        {
            "id": "tgt-b", "title": "src/python_scripts/b.py", "key": "src/python_scripts/b.py",
            "text": "VALUE = 1\n", "relations": [],
            "source_fields": {
                "repo_path": "src/python_scripts/b.py", "artifact_family": "python_script",
                "authority_level": "current_verified", "repo_lifecycle_state": "historical_snapshot",
            },
        },
    ]
    local_root.mkdir(parents=True, exist_ok=True)
    (local_root / "tiddlers_1.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8",
    )


def _write_fixture_current_bundle(local_root: Path, current_dir: Path, candidate_id: str) -> None:
    candidate = {
        "candidate_id": candidate_id,
        "candidate_schema_version": "technical-relation-candidates/v1",
        "technical_relation_kind": "python_ast_import",
        "relation_type": "depende_de",
        "source": {"canonical_id": "src-a", "repo_path": "src/python_scripts/a.py"},
        "target": {"canonical_id": "tgt-b", "repo_path": "src/python_scripts/b.py"},
        "evidence": {
            "evidence_kind": "content_embedded", "technical_evidence_kind": "ast_import",
            "parser": "python_ast", "raw_observation": "import b", "confidence": "high",
        },
    }
    current_dir.mkdir(parents=True, exist_ok=True)
    (current_dir / "ready_for_human_review.jsonl").write_text(json.dumps(candidate) + "\n", encoding="utf-8")
    (current_dir / "human_review_decisions.jsonl").write_text("", encoding="utf-8")
    (current_dir / "current_candidate_manifest.json").write_text('{"schema":"x"}', encoding="utf-8")
    (current_dir / "reconciliation_manifest.json").write_text('{"schema":"y"}', encoding="utf-8")

    audit_dir = local_root / "audit" / "relation_admission"
    bundle_dir = audit_dir / "generations" / "rg_test" / "rv_test" / "human_delta"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "current_human_delta_manifest.json").write_text(json.dumps({
        "review_candidates": [{"candidate_id": candidate_id, "review_reason": "reconciliation_new"}],
    }), encoding="utf-8")
    (audit_dir / "current_generation.json").write_text(json.dumps({"bundle_path": str(bundle_dir)}), encoding="utf-8")


def test_menu_materialization_changes_the_menu_dry_run_gate_outcome(tmp_path: Path) -> None:
    local_root = tmp_path / "local"
    current_dir = local_root / "pipeline" / "relation_candidates" / "current"
    audit_dir = local_root / "audit" / "relation_admission" / "current"
    candidate_id = "rc_current_" + "1" * 24

    _write_fixture_canon(local_root)
    _write_fixture_current_bundle(local_root, current_dir, candidate_id)
    canon_before = (local_root / "tiddlers_1.jsonl").read_bytes()

    env = {
        "CANON_DIR": str(local_root),
        "RELATION_OUT_DIR": str(current_dir),
        "AUDIT_DIR": str(audit_dir),
    }
    phrase = "AUTHORIZE POLICY PYTHON_AST_IMPORT_DEPENDENCY_V1 FOR CURRENT BATCH"

    # 4 -> 4 authorizes; 4 -> 5 materializes; both against the real backend.
    authorize_result = _run_tdc_with_env(
        f"4\n4\nPYTHON_AST_IMPORT_DEPENDENCY_V1\ntester\n{phrase}\n0\n0\n", env, "relations-admission",
    )
    assert authorize_result.returncode == 0
    assert "Autorización escrita" in authorize_result.stdout

    materialize_result = _run_tdc_with_env(
        "4\n5\nPYTHON_AST_IMPORT_DEPENDENCY_V1\ntester\n0\n0\n", env, "relations-admission",
    )
    assert materialize_result.returncode == 0
    assert "Decisiones materializadas: 1" in materialize_result.stdout

    # The decision must be readable straight back out of whichever file
    # decision_authority_path() resolves to (this minimal fixture never ran
    # PREPARE, so no effective_human_review_decisions.jsonl exists yet and
    # the write correctly falls back to the raw ledger) -- not just claimed
    # by the CLI's own stdout.
    import sys
    sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))
    import current_relation_human_review as human_review  # noqa: E402
    effective_path = human_review.decision_authority_path(current_dir)
    decisions = [json.loads(line) for line in effective_path.read_text().splitlines() if line.strip()]
    assert len(decisions) == 1
    assert decisions[0]["candidate_id"] == candidate_id
    assert decisions[0]["decision_mode"] == "policy_derived"
    assert decisions[0]["human_review_decision"] == "approved_for_admission"

    # BEFORE this session's fix, the dry-run gate ignored the effective file
    # entirely (RELATION_HUMAN_REVIEW_DECISIONS defaulted to the raw,
    # never-written-to file) and would still report this candidate as
    # awaiting_human_review here.
    dry_run_result = _run_tdc_with_env("5\n0\n", env, "relations-admission")
    assert dry_run_result.returncode == 0
    assert "awaiting_human_review    : 0" in dry_run_result.stdout
    assert "admission_ready_dry_run  : 1" in dry_run_result.stdout

    assert (local_root / "tiddlers_1.jsonl").read_bytes() == canon_before

    # Rematerializing the same, now-consumed authorization must not duplicate
    # the decision or silently succeed again.
    remateralize_result = _run_tdc_with_env(
        "4\n5\nPYTHON_AST_IMPORT_DEPENDENCY_V1\ntester\n0\n0\n", env, "relations-admission",
    )
    assert remateralize_result.returncode == 1
    # The authorization is now consumed, so the CLI refuses before even
    # attempting materialization -- a different (but still fail-closed)
    # message than a mid-flight staleness block.
    assert "No existe una autorización vigente" in remateralize_result.stdout
    decisions_after = [
        json.loads(line) for line in effective_path.read_text().splitlines() if line.strip()
    ]
    assert len(decisions_after) == 1


def test_materialized_decision_recovers_correctly_after_process_restart(tmp_path: Path) -> None:
    # Simulates "existing state after restart": build the fixture already in
    # the post-materialization state (as if a prior process had run and
    # exited) and confirm status/gate both read it correctly cold, without
    # any of this test's code path having executed the materialization.
    local_root = tmp_path / "local"
    current_dir = local_root / "pipeline" / "relation_candidates" / "current"
    audit_dir = local_root / "audit" / "relation_admission" / "current"
    candidate_id = "rc_current_" + "2" * 24

    _write_fixture_canon(local_root)
    _write_fixture_current_bundle(local_root, current_dir, candidate_id)

    import sys
    sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))
    import governed_relation_admission_policy as gpol  # noqa: E402
    import current_relation_human_review as human_review  # noqa: E402

    policy = next(p for p in gpol.build_policy_registry() if p.policy_id == "PYTHON_AST_IMPORT_DEPENDENCY_V1")
    state = gpol.load_current_pending(local_root)
    partition = gpol.partition_pending_candidates(
        gpol.build_policy_registry(), state["pending_ids"], state["by_id"], state["review_reason_by_id"],
    )
    eligible_ids = partition["by_policy"]["PYTHON_AST_IMPORT_DEPENDENCY_V1"]
    authorization = gpol.write_policy_authorization(
        policy, eligible_ids, state["bindings"], actor="tester",
        confirmation=gpol.authorization_confirmation_phrase(policy.policy_id),
        authorizations_dir=audit_dir / "policy_authorizations",
    )
    gpol.materialize_authorized_policy(
        local_root, policy_id="PYTHON_AST_IMPORT_DEPENDENCY_V1", authorization=authorization, actor="tester",
    )

    env = {"CANON_DIR": str(local_root), "RELATION_OUT_DIR": str(current_dir), "AUDIT_DIR": str(audit_dir)}
    status_result = _run_tdc_with_env("4\n6\n0\n0\n", env, "relations-admission")
    assert '"materialized": 1' in status_result.stdout
    assert '"status": "MATERIALIZED"' in status_result.stdout
    assert '"consumed_authorizations": 1' in status_result.stdout
    assert '"stale_authorizations": 0' in status_result.stdout

    dry_run_result = _run_tdc_with_env("5\n0\n", env, "relations-admission")
    assert "admission_ready_dry_run  : 1" in dry_run_result.stdout


# ---------------------------------------------------------------------------
# S0186 Unit H (GATE-020 remediation) -- Reportes gained a submenu with the
# repo_lifecycle_state authority audit, without adding a new top-level number.
# ---------------------------------------------------------------------------

def test_reports_menu_lists_file_listing_and_lifecycle_authority_options() -> None:
    result = _run_tdc("7\n0\n0\n", "relations-admission")
    assert result.returncode == 0
    assert "1) Listado de archivos (candidatas / auditoría)" in result.stdout
    assert "2) Auditoría de autoridad de repo_lifecycle_state (solo lectura)" in result.stdout


def test_reports_menu_file_listing_still_works(tmp_path: Path) -> None:
    current = tmp_path / "current"
    audit = tmp_path / "audit"
    current.mkdir()
    audit.mkdir()
    (current / "marker.jsonl").write_text("{}\n", encoding="utf-8")
    result = _run_tdc_with_env("7\n1\n0\n0\n", {
        "RELATION_OUT_DIR": str(current), "AUDIT_DIR": str(audit),
    }, "relations-admission")
    assert result.returncode == 0
    assert "marker.jsonl" in result.stdout


def test_reports_menu_lifecycle_authority_routes_to_the_real_diagnostic(tmp_path: Path) -> None:
    bin_dir, args_file = _fake_python(tmp_path)
    result = _run_tdc_with_env("7\n2\n0\n0\n", {
        "PATH": f"{bin_dir}:/usr/bin:/bin", "TDC_TEST_ARGS": str(args_file),
        "CANON_DIR": str(tmp_path / "local"),
    }, "relations-admission")

    assert result.returncode == 0
    args = args_file.read_text(encoding="utf-8").splitlines()
    assert "src/python_scripts/audit_repo_lifecycle_authority.py" in args
    assert "--compact" in args
