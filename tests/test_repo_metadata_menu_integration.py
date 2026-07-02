"""S0149/S0150/S0151 tests for metadata menu integration."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "python_scripts"))

import repo_metadata_review_menu as metadata_menu  # noqa: E402


def test_tdc_menu_exposes_governed_admission_and_keeps_critical_access() -> None:
    result = subprocess.run(
        [str(REPO_ROOT / "shell_scripts" / "tdc.sh")],
        cwd=REPO_ROOT,
        input="0\n",
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "6) Revisión / admisión gobernada" in result.stdout
    assert "9) Exportador de repositorio" in result.stdout
    assert "10) Configurar MCP / mirror remoto" in result.stdout


def test_metadata_submenu_header_declares_s0151_guided_policy() -> None:
    assert callable(metadata_menu.option_repo_metadata_admission_menu)
    header = metadata_menu.S0151_MENU_HEADER
    assert "Metadata técnica" in header
    assert "Canon: PROTEGIDO" in header
    assert "Modo normal: guiado" in header
    assert "IDs y hashes: solo en avanzado" in header
