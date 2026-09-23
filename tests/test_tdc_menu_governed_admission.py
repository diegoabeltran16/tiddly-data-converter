"""S0150 tests for centralized TDC operator menu."""

from __future__ import annotations

import subprocess
import sys
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

import tdc_menu_registry as registry  # noqa: E402
import operator_menu as menu  # noqa: E402


def test_main_menu_reflects_s0186_top_level_migration() -> None:
    # S0186 Unit H (final intervention, top-level UX migration): the visible
    # menu was fully renumbered per the mandate's required 12-item layout;
    # "Revisión / admisión gobernada" no longer exists as an independent
    # top-level entry (OLD_NAVIGATION_CONTRACT_MIGRATED).
    text = registry.menu_text()

    assert "1) Preparación / preflight" in text
    assert "2) Construir o importar canon" in text
    assert "3) Inventario material / repositorio" in text
    assert "4) Sincronizar artefactos al canon" in text
    assert "5) Exportar / consultar canon" in text
    assert "6) Relaciones canónicas" in text
    assert "7) Reportes / métricas / auditoría" in text
    assert "8) Derivados / RAG" in text
    assert "9) Configurar MCP / mirror remoto" in text
    assert "10) Rollback" in text
    assert "11) Temporales / quiescencia" in text
    assert "12) Avanzado / mantenimiento" in text
    assert "Revisión / admisión gobernada" not in text


def test_tdc_shows_simplified_menu() -> None:
    result = subprocess.run(
        [str(REPO_ROOT / "src" / "shell_scripts" / "tdc.sh")],
        cwd=REPO_ROOT,
        input="0\n",
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Tiddly Data Converter - Operador local" in result.stdout
    assert "TDC · Tiddly Data Converter" not in result.stdout
    assert "6) Relaciones canónicas" in result.stdout
    assert "Revisión / admisión gobernada" not in result.stdout
    assert "Inventario material / repositorio" in result.stdout
    assert "Configurar MCP / mirror remoto" in result.stdout
    assert "Avanzado / mantenimiento" in result.stdout
    assert "Temporales / quiescencia" in result.stdout


def test_governed_admission_status_is_operator_facing() -> None:
    # S0186 Unit H (final intervention, top-level UX migration): "Estado de
    # compuertas" now lives inside "4) Sincronizar artefactos al canon" (item
    # 3), not under the retired "Revisión / admisión gobernada" entry
    # (OLD_NAVIGATION_CONTRACT_MIGRATED) -- the underlying handler
    # (print_governed_gate_status) is unchanged.
    result = subprocess.run(
        [str(REPO_ROOT / "src" / "shell_scripts" / "tdc.sh")],
        cwd=REPO_ROOT,
        input="4\n3\n0\n0\n",
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Estado de compuertas" in result.stdout
    assert "Contratos: separados" in result.stdout
    assert "Relaciones current:" in result.stdout
    assert "veredicto=" in result.stdout
    assert "siguiente=" in result.stdout
    assert "Relaciones S0167:" not in result.stdout


def _stub_relational_state_command(monkeypatch, *, returncode: int = 0, stdout: str = "{}") -> None:
    monkeypatch.setattr(
        menu,
        "run_command",
        lambda *_args, **_kwargs: menu.CommandResult([], REPO_ROOT, returncode, stdout, ""),
    )


def test_gate_status_reports_unavailable_when_state_command_fails(monkeypatch, tmp_path, capsys) -> None:
    # S0186 Unit H (operator relational-state fragmentation fix): the gate
    # status must resolve CURRENT from the SAME live resolver TDC->6 and
    # TDC->8->2 consult (relation_admission_state.py's own "state" stdout),
    # not a separately-produced "audit" snapshot file that can be absent even
    # when the live authority is perfectly current.
    _stub_relational_state_command(monkeypatch, returncode=2, stdout="")
    monkeypatch.setattr(menu, "REPO_ROOT", tmp_path)

    menu.print_governed_gate_status()

    out = capsys.readouterr().out
    assert "estado no disponible" in out
    assert "veredicto=RELATIONAL_STATE_UNAVAILABLE" in out
    assert "siguiente=" in out


def test_gate_status_reports_malformed_when_state_stdout_is_not_json(monkeypatch, tmp_path, capsys) -> None:
    _stub_relational_state_command(monkeypatch, returncode=0, stdout="{not-json")
    monkeypatch.setattr(menu, "REPO_ROOT", tmp_path)

    menu.print_governed_gate_status()

    out = capsys.readouterr().out
    assert "estado persistido malformado" in out
    assert "veredicto=RELATIONAL_STATE_MALFORMED" in out
    assert "siguiente=" in out


def test_gate_status_reports_live_state_from_resolver_stdout(monkeypatch, tmp_path, capsys) -> None:
    _stub_relational_state_command(monkeypatch, returncode=0, stdout=json.dumps({
        "candidate_generation": {"total": 2},
        "reconciliation": {"ready_for_review": 1, "blocked": 0},
        "human_review": {"total": 1},
        "verdict": "READY",
        "next_action": "review",
    }))
    monkeypatch.setattr(menu, "REPO_ROOT", tmp_path)

    menu.print_governed_gate_status()

    out = capsys.readouterr().out
    assert "veredicto=READY" in out
    assert "siguiente=review" in out


def test_gate_status_agrees_with_live_resolver_without_any_persisted_snapshot(monkeypatch, tmp_path, capsys) -> None:
    """Same invariant the mandate names explicitly: same logical CURRENT ->
    same authority resolver -> same operator verdict. No
    relational_operational_state.json is written anywhere in this test --
    the gate status must still report the live state correctly."""
    _stub_relational_state_command(monkeypatch, returncode=0, stdout=json.dumps({
        "candidate_generation": {"total": 533},
        "reconciliation": {"ready_for_review": 498, "blocked": 35},
        "human_review": {"total": 498},
        "verdict": "RELATIONAL_ADMISSION_PARTIALLY_READY",
        "next_action": "RESOLVE_OR_DEFER_TECHNICALLY_INVALID_APPROVALS",
    }))
    monkeypatch.setattr(menu, "REPO_ROOT", tmp_path)
    snapshot_path = tmp_path / "data/out/local/audit/relation_admission/current/relational_operational_state.json"
    assert not snapshot_path.exists()

    menu.print_governed_gate_status()

    out = capsys.readouterr().out
    assert "veredicto=RELATIONAL_ADMISSION_PARTIALLY_READY" in out
    assert "RELATIONAL_STATE_UNAVAILABLE" not in out


def test_tmp_menu_is_reachable_read_only_and_advanced_hides_visible_aliases() -> None:
    result = subprocess.run(
        [str(REPO_ROOT / "src" / "shell_scripts" / "tdc.sh")],
        cwd=REPO_ROOT,
        input="13\n2\n0\n12\n0\n0\n",
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Temporales / quiescencia" in result.stdout
    assert "Entradas observadas:" in result.stdout
    advanced = result.stdout.split("Avanzado / mantenimiento", 1)[1].split("\n>  /\\_", 1)[0]
    assert "Configurar MCP / mirror remoto" not in advanced
    assert "Relaciones canónicas [alias histórico 16]" not in advanced


def test_menu_mapping_declares_metadata_and_relation_access() -> None:
    # S0186 Unit H (final intervention, top-level UX migration): positions
    # updated to match the new 12-item top-level menu
    # (OLD_NAVIGATION_CONTRACT_MIGRATED).
    mapping = registry.menu_mapping()

    assert mapping["critical_functions_preserved"]["canonical_relations"] == "6 and alias 16"
    assert mapping["critical_functions_preserved"]["metadata_admission"] == "4.2 and alias 18"
    assert mapping["critical_functions_preserved"]["repository_exporter"] == "3 and alias 17"
    assert mapping["relational_operation"]["state_engine"] == "src/python_scripts/relation_admission_state.py"

def _rag_staging_flag(cmd: list[str], name: str) -> str:
    return cmd[cmd.index(name) + 1]


def test_rag_admission_staging_gate_report_md_is_explicit_twin() -> None:
    cmd = menu._rag_admission_staging_command()
    assert "--gate-report-md" in cmd
    assert _rag_staging_flag(cmd, "--gate-report") == str(menu.RAG_ADMISSION_TECHNICAL_GATE)
    assert _rag_staging_flag(cmd, "--gate-report-md") == str(
        menu.RAG_ADMISSION_TECHNICAL_GATE.with_suffix(".md")
    )
    assert _rag_staging_flag(cmd, "--gate-report-md").endswith(
        "audit/rag_admission/technical_gate_report.md"
    )


def test_rag_admission_staging_does_not_target_s0172_report() -> None:
    cmd = menu._rag_admission_staging_command()
    for value in cmd:
        assert "rag_derivation/s0172/rag_gate_report" not in value
    assert _rag_staging_flag(cmd, "--gate-report-md") != str(
        menu.RAG_DERIVATION_GATE_REPORT_MD
    )


def test_rag_admission_staging_preserves_other_operator_flags() -> None:
    cmd = menu._rag_admission_staging_command()
    for name in (
        "--input-dir",
        "--out-dir",
        "--profile",
        "--metadata-candidates",
        "--tag-inventory",
        "--preview-manifest",
        "--plan-out",
    ):
        assert name in cmd
    assert _rag_staging_flag(cmd, "--mode") == "staging"
    assert "--dry-run" in cmd
