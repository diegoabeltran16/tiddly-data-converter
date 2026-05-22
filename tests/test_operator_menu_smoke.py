"""
Smoke tests dry-run del menú local — S0116.

Verifica que el menú local puede ejecutarse en modo seguro sin escribir
al canon ni crear rutas prohibidas.

Contrato verificado:
  - El menú muestra todas las opciones esperadas
  - El menú termina con exit code 0 al seleccionar Salir
  - No se crean sesiones/ en raíz ni data/sessions/
  - Los shards del canon local no son modificados
  - tdc.sh existe y es ejecutable
  - La opción de Preparación termina sin error

Para ejecutar en aislamiento:
    pytest tests/test_operator_menu_smoke.py -v
"""
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MENU_SCRIPT = REPO_ROOT / "python_scripts" / "operator_menu.py"
TDC_SH = REPO_ROOT / "shell_scripts" / "tdc.sh"
CANON_DIR = REPO_ROOT / "data" / "out" / "local"


def _run_menu(input_seq: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MENU_SCRIPT)],
        input=input_seq,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=timeout,
    )


def _canon_shard_hashes() -> dict[str, str]:
    result = {}
    for p in sorted(CANON_DIR.glob("tiddlers_*.jsonl")):
        result[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
    return result


# ── Existencia de artefactos operativos ──────────────────────────────────────

class TestMenuArtifactsExist:
    def test_menu_script_exists(self):
        assert MENU_SCRIPT.exists(), f"operator_menu.py not found: {MENU_SCRIPT}"

    def test_tdc_sh_exists(self):
        assert TDC_SH.exists(), f"tdc.sh not found: {TDC_SH}"

    def test_tdc_sh_is_executable(self):
        assert os.access(TDC_SH, os.X_OK), f"tdc.sh is not executable: {TDC_SH}"

    def test_canon_dir_exists(self):
        assert CANON_DIR.exists(), f"Canon dir missing: {CANON_DIR}"


# ── Smoke: salida limpia ──────────────────────────────────────────────────────

class TestMenuExitsCleanly:
    def test_exit_option_returns_zero(self):
        result = _run_menu("0\n")
        assert result.returncode == 0, (
            f"Menu exited with code {result.returncode}\nstdout: {result.stdout[:300]}\nstderr: {result.stderr[:300]}"
        )

    def test_menu_shows_salir_option(self):
        result = _run_menu("0\n")
        assert "0)" in result.stdout and "Salir" in result.stdout, (
            f"'0) Salir' not found in menu output:\n{result.stdout[:500]}"
        )

    def test_menu_shows_critical_options(self):
        result = _run_menu("0\n")
        stdout = result.stdout
        expected_fragments = [
            "Preparacion",
            "Validar canon",
            "Sincronizar entregables",
            "Generar derivados",
            "Ejecutar reverse",
        ]
        missing = [f for f in expected_fragments if f not in stdout]
        assert not missing, (
            f"Menu missing options: {missing}\nGot:\n{stdout[:600]}"
        )

    def test_menu_shows_saneamiento_del_canon(self):
        """S0121: menu must show 'Saneamiento del canon' option."""
        result = _run_menu("0\n")
        assert "Saneamiento del canon" in result.stdout, (
            f"'Saneamiento del canon' not found in menu output:\n{result.stdout[:600]}"
        )

    def test_menu_does_not_crash_on_invalid_option(self):
        # Feed an invalid option then exit
        result = _run_menu("999\n0\n")
        assert result.returncode == 0, (
            f"Menu crashed on invalid option\nreturncode={result.returncode}\nstderr: {result.stderr[:300]}"
        )


# ── Smoke: opción de Preparación ─────────────────────────────────────────────

class TestMenuPreparationOption:
    def test_preparation_option_exits_zero(self):
        # Select Preparación (1) then Salir (0)
        result = _run_menu("1\n0\n", timeout=30)
        assert result.returncode == 0, (
            f"Preparation option failed\nreturncode={result.returncode}\nstderr: {result.stderr[:300]}"
        )

    def test_preparation_does_not_write_to_canon(self):
        hashes_before = _canon_shard_hashes()
        _run_menu("1\n0\n", timeout=30)
        hashes_after = _canon_shard_hashes()
        assert hashes_before == hashes_after, (
            "Canon shards were modified by Preparation option\n"
            + "\n".join(
                f"  {k}: {hashes_before[k][:12]}… → {hashes_after[k][:12]}…"
                for k in hashes_before
                if hashes_before[k] != hashes_after.get(k)
            )
        )


# ── Smoke: rutas prohibidas no creadas ───────────────────────────────────────

class TestMenuForbiddenPaths:
    def test_exit_does_not_create_sessions_in_root(self):
        _run_menu("0\n")
        assert not (REPO_ROOT / "sessions").exists(), "Forbidden path 'sessions/' was created"

    def test_exit_does_not_create_data_sessions(self):
        _run_menu("0\n")
        assert not (REPO_ROOT / "data" / "sessions").exists(), (
            "Forbidden path 'data/sessions/' was created"
        )

    def test_preparation_does_not_create_forbidden_paths(self):
        _run_menu("1\n0\n", timeout=30)
        assert not (REPO_ROOT / "sessions").exists(), (
            "Forbidden path 'sessions/' was created by Preparation"
        )
        assert not (REPO_ROOT / "data" / "sessions").exists(), (
            "Forbidden path 'data/sessions/' was created by Preparation"
        )


# ── Smoke: no escritura accidental al canon en flujo básico ──────────────────

class TestMenuCanonIntegrity:
    def test_exit_does_not_modify_canon_shards(self):
        hashes_before = _canon_shard_hashes()
        _run_menu("0\n")
        hashes_after = _canon_shard_hashes()
        assert hashes_before == hashes_after, (
            "Canon shards were modified on exit\n"
            + "\n".join(
                f"  {k}: changed"
                for k in hashes_before
                if hashes_before[k] != hashes_after.get(k)
            )
        )

    def test_canon_shards_are_still_present_after_menu(self):
        shards_before = set(p.name for p in CANON_DIR.glob("tiddlers_*.jsonl"))
        _run_menu("0\n")
        shards_after = set(p.name for p in CANON_DIR.glob("tiddlers_*.jsonl"))
        assert shards_before == shards_after, (
            f"Canon shards changed after menu exit\n"
            f"Before: {shards_before}\nAfter: {shards_after}"
        )


# ── Smoke: saneamiento del canon ─────────────────────────────────────────────

class TestMenuCanonSanitation:
    """S0121: verify the Saneamiento del canon submenu is reachable and safe."""

    def test_sanitation_submenu_shows_options(self):
        # Open submenu (15) then exit (0) then exit main (0)
        result = _run_menu("15\n0\n0\n", timeout=30)
        assert result.returncode == 0, (
            f"Menu exited with code {result.returncode}\nstdout: {result.stdout[:400]}\nstderr: {result.stderr[:300]}"
        )
        assert "Saneamiento del canon" in result.stdout, (
            f"Submenu title not found in output:\n{result.stdout[:600]}"
        )

    def test_sanitation_submenu_shows_scan_option(self):
        result = _run_menu("15\n0\n0\n", timeout=30)
        assert "Escanear" in result.stdout, (
            f"'Escanear' option not found:\n{result.stdout[:400]}"
        )

    def test_sanitation_submenu_does_not_modify_canon(self):
        hashes_before = _canon_shard_hashes()
        _run_menu("15\n0\n0\n", timeout=30)
        hashes_after = _canon_shard_hashes()
        assert hashes_before == hashes_after, (
            "Canon shards were modified by opening the Saneamiento submenu"
        )


# ── Smoke: gobernanza de sesiones ─────────────────────────────────────────────

class TestMenuSessionGovernance:
    def test_governed_sessions_path_unchanged(self):
        sessions_dir = CANON_DIR / "sessions"
        existed_before = sessions_dir.exists()
        _run_menu("0\n")
        existed_after = sessions_dir.exists()
        assert existed_before == existed_after, (
            f"Governed sessions dir existence changed: {existed_before} → {existed_after}"
        )
