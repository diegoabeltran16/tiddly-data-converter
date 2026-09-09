"""S0149/S0150/S0151 tests for metadata menu integration."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

import repo_metadata_review_menu as metadata_menu  # noqa: E402
import repo_metadata_admission_gate as metadata_gate  # noqa: E402
import repo_metadata_refresh_patch as metadata_refresh  # noqa: E402


def test_tdc_menu_keeps_critical_access_after_top_level_migration() -> None:
    # S0186 Unit H (final intervention, top-level UX migration):
    # "Revisión / admisión gobernada" no longer exists as an independent
    # top-level entry (OLD_NAVIGATION_CONTRACT_MIGRATED) -- metadata técnica
    # is now reachable via "4) Sincronizar artefactos al canon" -> 2, proven
    # separately below.
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
    assert "3) Exportador de repositorio" in result.stdout
    assert "9) Configurar MCP / mirror remoto" in result.stdout
    assert "4) Sincronizar artefactos al canon" in result.stdout


def test_metadata_tecnica_reachable_from_sync_governance_menu() -> None:
    result = subprocess.run(
        [str(REPO_ROOT / "src" / "shell_scripts" / "tdc.sh")],
        cwd=REPO_ROOT,
        input="4\n2\n0\n0\n0\n",
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Metadata técnica" in result.stdout
    assert "Canon: PROTEGIDO" in result.stdout


def test_metadata_submenu_header_declares_s0151_guided_policy() -> None:
    assert callable(metadata_menu.option_repo_metadata_admission_menu)
    header = metadata_menu.S0151_MENU_HEADER
    assert "Metadata técnica" in header
    assert "Canon: PROTEGIDO" in header
    assert "Modo normal: guiado" in header
    assert "IDs y hashes: solo en avanzado" in header


def test_metadata_menu_uses_repo_root_not_src() -> None:
    assert metadata_menu.REPO_ROOT == REPO_ROOT
    assert metadata_gate.REPO_ROOT == REPO_ROOT
    assert metadata_refresh.REPO_ROOT == REPO_ROOT
    assert "/src/data/out/local/" not in str(metadata_menu.DEFAULT_LATEST_METADATA_PATCH_MANIFEST)
    assert "/src/data/out/local/" not in str(metadata_gate.DEFAULT_LATEST_METADATA_PATCH_MANIFEST)


def test_metadata_recommended_selection_without_manifest_is_guided_not_traceback(
    tmp_path: Path,
    capsys,
) -> None:
    code = metadata_menu.select_s0151_recommended(
        manifest=tmp_path / "missing_manifest.json",
        admission_dir=tmp_path / "admission",
    )

    output = capsys.readouterr().out
    assert code == 2
    assert "No hay patch vigente." in output
    assert "patch vigente: no disponible" in output
    assert "acción sugerida: refrescar patch contra canon actual" in output
    assert "Ejecuta opción 6: Refrescar patch contra canon actual." in output
