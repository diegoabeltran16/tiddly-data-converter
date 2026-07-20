"""S0150 tests for centralized TDC operator menu."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

import tdc_menu_registry as registry  # noqa: E402


def test_main_menu_contains_governed_admission_and_critical_functions() -> None:
    text = registry.menu_text()

    assert "6) Relaciones canónicas" in text
    assert "7) Revisión / admisión gobernada" in text
    assert "10) Exportador de repositorio" in text
    assert "11) Configurar MCP / mirror remoto" in text
    assert "12) Avanzado / mantenimiento" in text


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
    assert "Revisión / admisión gobernada" in result.stdout
    assert "Exportador de repositorio" in result.stdout
    assert "Configurar MCP / mirror remoto" in result.stdout
    assert "Avanzado / mantenimiento" in result.stdout


def test_governed_admission_status_is_operator_facing() -> None:
    result = subprocess.run(
        [str(REPO_ROOT / "src" / "shell_scripts" / "tdc.sh")],
        cwd=REPO_ROOT,
        input="7\n4\n0\n0\n",
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


def test_menu_mapping_declares_metadata_and_relation_access() -> None:
    mapping = registry.menu_mapping()

    assert mapping["critical_functions_preserved"]["canonical_relations"] == "6 and alias 16"
    assert mapping["critical_functions_preserved"]["metadata_admission"] == "7.1 and alias 18"
    assert mapping["critical_functions_preserved"]["repository_exporter"] == "10"
    assert mapping["relational_operation"]["state_engine"] == "src/python_scripts/relation_admission_state.py"
