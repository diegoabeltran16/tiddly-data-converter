"""
tests/test_relation_review_menu.py — S0127

Tests del módulo auxiliar de revisión relacional experimental.

Cobertura requerida por S0127:
  1. La sección experimental aparece en el menú principal (opción 16).
  2. El texto del submenú incluye EXPERIMENTAL, dry-run,
     generación bloqueada y admisión bloqueada.
  3. La opción invoca el validador con --dry-run.
  4. La opción NO invoca --apply.
  5. La opción NO modifica data/out/local/tiddlers_*.jsonl.
  6. Si no hay candidatos, la salida es legible y no genera nuevos.
  7. El reporte humano puede mostrarse o referenciarse sin alterar archivos.
  8. El submenú es accesible desde el menú principal como opción 16.
  9. El submenú cierra limpiamente con opción 0.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

# ---------------------------------------------------------------------------
# Constantes de repositorio
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
MENU_SCRIPT = REPO_ROOT / "python_scripts" / "operator_menu.py"
REVIEW_MODULE = REPO_ROOT / "python_scripts" / "relation_review_menu.py"
CANON_DIR = REPO_ROOT / "data" / "out" / "local"
RELATIONS_DIR = CANON_DIR / "pipeline" / "relations_candidates"
DEFAULT_CANDIDATES_INPUT = RELATIONS_DIR / "relations_candidates.sample.jsonl"
DEFAULT_HUMAN_REVIEW = RELATIONS_DIR / "relations_candidates.human_review.md"
DEFAULT_VALIDATION_REPORT = RELATIONS_DIR / "relations_candidates.validation_report.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Importar el módulo bajo test
# ---------------------------------------------------------------------------

sys.path.insert(0, str(REPO_ROOT / "python_scripts"))
import relation_review_menu as rrm  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_relations_dir(tmp_path):
    """Directorio temporal con un archivo de candidatos de muestra."""
    relations = tmp_path / "pipeline" / "relations_candidates"
    relations.mkdir(parents=True)
    input_file = relations / "relations_candidates.sample.jsonl"
    # Línea mínima con los campos requeridos para superar la guardia de existencia
    input_file.write_text(
        '{"candidate_id":"rc1_aabb1122334455667788","status":"candidate"}\n',
        encoding="utf-8",
    )
    report = relations / "relations_candidates.validation_report.json"
    human = relations / "relations_candidates.human_review.md"
    return {
        "dir": relations,
        "input": input_file,
        "report": report,
        "human": human,
    }


# ===========================================================================
# Clase 1: Existencia y estructura del módulo
# ===========================================================================


class TestModuleExists:
    def test_module_file_exists(self):
        assert REVIEW_MODULE.exists(), f"relation_review_menu.py no encontrado: {REVIEW_MODULE}"

    def test_module_exports_option_relation_review_menu(self):
        assert callable(rrm.option_relation_review_menu)

    def test_module_exports_option_validate_candidates(self):
        assert callable(rrm.option_validate_candidates)

    def test_module_exports_option_view_human_report(self):
        assert callable(rrm.option_view_human_report)

    def test_module_exports_show_block_status(self):
        assert callable(rrm.show_block_status)

    def test_block_status_lines_contains_experimental(self):
        joined = " ".join(rrm.BLOCK_STATUS_LINES)
        assert "EXPERIMENTAL" in joined

    def test_block_status_lines_contains_bloqueada(self):
        joined = " ".join(rrm.BLOCK_STATUS_LINES)
        assert "BLOQUEADA" in joined

    def test_block_status_lines_contains_dry_run(self):
        joined = " ".join(rrm.BLOCK_STATUS_LINES)
        assert "dry-run" in joined


# ===========================================================================
# Clase 2: Contenido del menú header / textos de bloqueo
# ===========================================================================


class TestMenuHeaderContent:
    """El header del submenú debe incluir los mensajes de bloqueo requeridos."""

    def test_menu_header_contains_experimental(self):
        assert "EXPERIMENTAL" in rrm._MENU_HEADER

    def test_menu_header_contains_bloqueada(self):
        assert "BLOQUEADA" in rrm._MENU_HEADER

    def test_menu_header_contains_dry_run(self):
        assert "dry-run" in rrm._MENU_HEADER

    def test_menu_header_contains_admision(self):
        assert "Admisión" in rrm._MENU_HEADER or "Admision" in rrm._MENU_HEADER

    def test_menu_header_contains_generacion(self):
        assert "Generación" in rrm._MENU_HEADER or "Generacion" in rrm._MENU_HEADER

    def test_menu_header_contains_validate_option(self):
        assert "Validar relaciones candidatas" in rrm._MENU_HEADER

    def test_show_block_status_output(self, capsys):
        rrm.show_block_status()
        captured = capsys.readouterr()
        assert "EXPERIMENTAL" in captured.out
        assert "BLOQUEADA" in captured.out
        assert "dry-run" in captured.out
        assert "Reporte JSON" in captured.out
        assert "Reporte humano" in captured.out


# ===========================================================================
# Clase 3: option_validate_candidates — comando generado
# ===========================================================================


class TestValidateCandidatesCommand:
    """Verifica que el validador se invoca correctamente con --dry-run y sin --apply."""

    def test_dry_run_flag_is_in_command(self, fake_relations_dir):
        """--dry-run debe estar en el comando cuando el fichero existe."""
        f = fake_relations_dir
        with (
            mock.patch("relation_review_menu.RELATIONS_DIR", f["dir"]),
            mock.patch("relation_review_menu.DEFAULT_CANDIDATES_INPUT", f["input"]),
            mock.patch("relation_review_menu.DEFAULT_VALIDATION_REPORT", f["report"]),
            mock.patch("relation_review_menu.DEFAULT_HUMAN_REVIEW", f["human"]),
            mock.patch(
                "relation_review_menu.subprocess.run",
                return_value=mock.Mock(returncode=0, stdout="", stderr=""),
            ) as mock_run,
        ):
            rrm.option_validate_candidates()
            assert mock_run.called, "subprocess.run no fue llamado"
            cmd = mock_run.call_args[0][0]
            assert "--dry-run" in cmd, f"--dry-run no está en el comando: {cmd}"

    def test_apply_flag_is_never_in_command(self, fake_relations_dir):
        """--apply NUNCA debe aparecer en el comando generado (S0127)."""
        f = fake_relations_dir
        with (
            mock.patch("relation_review_menu.RELATIONS_DIR", f["dir"]),
            mock.patch("relation_review_menu.DEFAULT_CANDIDATES_INPUT", f["input"]),
            mock.patch("relation_review_menu.DEFAULT_VALIDATION_REPORT", f["report"]),
            mock.patch("relation_review_menu.DEFAULT_HUMAN_REVIEW", f["human"]),
            mock.patch(
                "relation_review_menu.subprocess.run",
                return_value=mock.Mock(returncode=0, stdout="", stderr=""),
            ) as mock_run,
        ):
            rrm.option_validate_candidates()
            cmd = mock_run.call_args[0][0]
            assert "--apply" not in cmd, (
                f"--apply apareció en el comando — PROHIBIDO en S0127: {cmd}"
            )

    def test_command_contains_input_flag(self, fake_relations_dir):
        f = fake_relations_dir
        with (
            mock.patch("relation_review_menu.RELATIONS_DIR", f["dir"]),
            mock.patch("relation_review_menu.DEFAULT_CANDIDATES_INPUT", f["input"]),
            mock.patch("relation_review_menu.DEFAULT_VALIDATION_REPORT", f["report"]),
            mock.patch("relation_review_menu.DEFAULT_HUMAN_REVIEW", f["human"]),
            mock.patch(
                "relation_review_menu.subprocess.run",
                return_value=mock.Mock(returncode=0, stdout="", stderr=""),
            ) as mock_run,
        ):
            rrm.option_validate_candidates()
            cmd = mock_run.call_args[0][0]
            assert "--input" in cmd

    def test_command_contains_canon_root_flag(self, fake_relations_dir):
        f = fake_relations_dir
        with (
            mock.patch("relation_review_menu.RELATIONS_DIR", f["dir"]),
            mock.patch("relation_review_menu.DEFAULT_CANDIDATES_INPUT", f["input"]),
            mock.patch("relation_review_menu.DEFAULT_VALIDATION_REPORT", f["report"]),
            mock.patch("relation_review_menu.DEFAULT_HUMAN_REVIEW", f["human"]),
            mock.patch(
                "relation_review_menu.subprocess.run",
                return_value=mock.Mock(returncode=0, stdout="", stderr=""),
            ) as mock_run,
        ):
            rrm.option_validate_candidates()
            cmd = mock_run.call_args[0][0]
            assert "--canon-root" in cmd

    def test_validator_script_is_validate_relation_candidates(self, fake_relations_dir):
        f = fake_relations_dir
        with (
            mock.patch("relation_review_menu.RELATIONS_DIR", f["dir"]),
            mock.patch("relation_review_menu.DEFAULT_CANDIDATES_INPUT", f["input"]),
            mock.patch("relation_review_menu.DEFAULT_VALIDATION_REPORT", f["report"]),
            mock.patch("relation_review_menu.DEFAULT_HUMAN_REVIEW", f["human"]),
            mock.patch(
                "relation_review_menu.subprocess.run",
                return_value=mock.Mock(returncode=0, stdout="", stderr=""),
            ) as mock_run,
        ):
            rrm.option_validate_candidates()
            cmd = mock_run.call_args[0][0]
            scripts = [c for c in cmd if "validate_relation_candidates" in str(c)]
            assert scripts, f"validate_relation_candidates.py no en el comando: {cmd}"


# ===========================================================================
# Clase 4: option_validate_candidates — casos sin candidatos
# ===========================================================================


class TestValidateCandidatesMissingFiles:
    """Manejo gracioso cuando no existen candidatos o directorio."""

    def test_missing_directory_no_crash(self, capsys, tmp_path):
        """Si el directorio no existe, se reporta sin excepción."""
        absent_dir = tmp_path / "absent_relations"
        with mock.patch("relation_review_menu.RELATIONS_DIR", absent_dir):
            rc = rrm.option_validate_candidates()
        captured = capsys.readouterr()
        # Debe haber mensaje informativo
        assert rc != 0

    def test_missing_directory_output_mentions_no_generation(self, capsys, tmp_path):
        """La salida menciona que no se generan candidatos nuevos en S0127."""
        absent_dir = tmp_path / "absent_relations"
        with mock.patch("relation_review_menu.RELATIONS_DIR", absent_dir):
            rrm.option_validate_candidates()
        captured = capsys.readouterr()
        assert "S0127" in captured.out or "no genera candidatos" in captured.out, (
            f"Mensaje de no-generación no encontrado:\n{captured.out}"
        )

    def test_missing_input_file_no_crash(self, capsys, tmp_path):
        """Si el directorio existe pero no el archivo, se reporta limpiamente."""
        existing_dir = tmp_path / "relations"
        existing_dir.mkdir()
        absent_input = existing_dir / "relations_candidates.sample.jsonl"
        # El archivo no es creado → no existe
        with (
            mock.patch("relation_review_menu.RELATIONS_DIR", existing_dir),
            mock.patch("relation_review_menu.DEFAULT_CANDIDATES_INPUT", absent_input),
        ):
            rc = rrm.option_validate_candidates()
        captured = capsys.readouterr()
        assert "No se encontraron" in captured.out

    def test_missing_input_file_does_not_call_subprocess(self, tmp_path):
        """Si no hay archivo de candidatos, subprocess.run NO debe ser llamado."""
        existing_dir = tmp_path / "relations"
        existing_dir.mkdir()
        absent_input = existing_dir / "relations_candidates.sample.jsonl"
        with (
            mock.patch("relation_review_menu.RELATIONS_DIR", existing_dir),
            mock.patch("relation_review_menu.DEFAULT_CANDIDATES_INPUT", absent_input),
            mock.patch("relation_review_menu.subprocess.run") as mock_run,
        ):
            rrm.option_validate_candidates()
            assert not mock_run.called

    def test_missing_dir_does_not_call_subprocess(self, tmp_path):
        """Si no existe el directorio, subprocess.run NO debe ser llamado."""
        absent_dir = tmp_path / "absent_relations"
        with (
            mock.patch("relation_review_menu.RELATIONS_DIR", absent_dir),
            mock.patch("relation_review_menu.subprocess.run") as mock_run,
        ):
            rrm.option_validate_candidates()
            assert not mock_run.called


# ===========================================================================
# Clase 5: Canon intacto después de ejecutar la opción
# ===========================================================================


class TestCanonIntacto:
    """Verificación de que tiddlers_*.jsonl no se modifica."""

    def test_validate_candidates_real_run_does_not_modify_canon(self):
        """
        Ejecuta el validador dry-run real con los candidatos existentes
        y verifica que el canon no cambió.
        """
        hashes_before = _canon_shard_hashes()
        if DEFAULT_CANDIDATES_INPUT.exists():
            rrm.option_validate_candidates()
        hashes_after = _canon_shard_hashes()
        assert hashes_before == hashes_after, (
            "¡Canon modificado por option_validate_candidates! BLOQUEO CRÍTICO S0127\n"
            + "\n".join(
                f"  {k}: CAMBIÓ"
                for k in hashes_before
                if hashes_before.get(k) != hashes_after.get(k)
            )
        )

    def test_view_human_report_does_not_modify_canon(self):
        """Ver el reporte humano no modifica el canon."""
        hashes_before = _canon_shard_hashes()
        rrm.option_view_human_report()
        hashes_after = _canon_shard_hashes()
        assert hashes_before == hashes_after

    def test_show_block_status_does_not_modify_canon(self):
        hashes_before = _canon_shard_hashes()
        rrm.show_block_status()
        hashes_after = _canon_shard_hashes()
        assert hashes_before == hashes_after


# ===========================================================================
# Clase 6: option_view_human_report
# ===========================================================================


class TestViewHumanReport:
    def test_view_report_no_file_outputs_instruction(self, capsys, tmp_path):
        """Si el reporte no existe, indica ejecutar la validación primero."""
        absent = tmp_path / "human_review.md"
        with mock.patch("relation_review_menu.DEFAULT_HUMAN_REVIEW", absent):
            rrm.option_view_human_report()
        captured = capsys.readouterr()
        assert "No hay reporte" in captured.out or "dry-run" in captured.out

    def test_view_report_no_file_does_not_crash(self, tmp_path):
        absent = tmp_path / "human_review.md"
        with mock.patch("relation_review_menu.DEFAULT_HUMAN_REVIEW", absent):
            rrm.option_view_human_report()  # no debe lanzar excepción

    def test_view_report_existing_file_reads_content(self, capsys, tmp_path):
        """Si el reporte existe, su contenido es mostrado."""
        fake_report = tmp_path / "human_review.md"
        fake_report.write_text("# Test reporte\n- Línea 1\n- Línea 2\n", encoding="utf-8")
        with mock.patch("relation_review_menu.DEFAULT_HUMAN_REVIEW", fake_report):
            rrm.option_view_human_report()
        captured = capsys.readouterr()
        assert "Test reporte" in captured.out

    def test_view_report_does_not_create_new_files(self, tmp_path):
        """Ver el reporte humano no crea archivos adicionales."""
        fake_report = tmp_path / "human_review.md"
        fake_report.write_text("# Contenido\n", encoding="utf-8")
        files_before = {p.name for p in tmp_path.iterdir()}
        with mock.patch("relation_review_menu.DEFAULT_HUMAN_REVIEW", fake_report):
            rrm.option_view_human_report()
        files_after = {p.name for p in tmp_path.iterdir()}
        assert files_before == files_after, (
            f"Se crearon archivos inesperados al ver el reporte humano: {files_after - files_before}"
        )


# ===========================================================================
# Clase 7: Integración con el menú principal (operator_menu.py)
# ===========================================================================


class TestMainMenuIntegration:
    """Verifica que la opción 16 está integrada en el menú principal."""

    def test_main_menu_shows_revision_relacional_experimental(self):
        """El menú principal muestra la opción de revisión relacional experimental."""
        result = _run_menu("0\n")
        assert result.returncode == 0
        assert (
            "Revision relacional" in result.stdout
            or "EXPERIMENTAL" in result.stdout
        ), f"Opción experimental no encontrada:\n{result.stdout[:600]}"

    def test_main_menu_shows_option_16(self):
        result = _run_menu("0\n")
        assert "16)" in result.stdout, (
            f"Opción 16 no encontrada en el menú:\n{result.stdout[:600]}"
        )

    def test_experimental_submenu_reachable_from_main(self):
        """La opción 16 abre el submenú experimental y permite volver con 0."""
        result = _run_menu("16\n0\n0\n", timeout=30)
        assert result.returncode == 0, (
            f"returncode={result.returncode}\nstderr:{result.stderr[:300]}"
        )

    def test_experimental_submenu_shows_experimental_text(self):
        """Al abrir el submenú (opción 16), el output contiene 'EXPERIMENTAL'."""
        result = _run_menu("16\n0\n0\n", timeout=30)
        assert "EXPERIMENTAL" in result.stdout, (
            f"'EXPERIMENTAL' no encontrado:\n{result.stdout[:800]}"
        )

    def test_experimental_submenu_shows_bloqueada(self):
        """Al abrir el submenú (opción 16), el output contiene 'BLOQUEADA'."""
        result = _run_menu("16\n0\n0\n", timeout=30)
        assert "BLOQUEADA" in result.stdout, (
            f"'BLOQUEADA' no encontrado:\n{result.stdout[:800]}"
        )

    def test_experimental_submenu_shows_dry_run(self):
        """Al abrir el submenú (opción 16), el output contiene 'dry-run'."""
        result = _run_menu("16\n0\n0\n", timeout=30)
        assert "dry-run" in result.stdout, (
            f"'dry-run' no encontrado:\n{result.stdout[:800]}"
        )

    def test_experimental_submenu_does_not_modify_canon(self):
        """Abrir y cerrar el submenú experimental no modifica el canon."""
        hashes_before = _canon_shard_hashes()
        _run_menu("16\n0\n0\n", timeout=30)
        hashes_after = _canon_shard_hashes()
        assert hashes_before == hashes_after, (
            "Canon modificado al abrir/cerrar el submenú experimental S0127"
        )

    def test_experimental_option_1_with_existing_candidates_does_not_modify_canon(self):
        """
        Ejecutar la opción 1 del submenú con candidatos reales no modifica el canon.
        """
        if not DEFAULT_CANDIDATES_INPUT.exists():
            pytest.skip("No hay archivo de candidatos; test no aplica")
        hashes_before = _canon_shard_hashes()
        _run_menu("16\n1\n0\n0\n", timeout=60)
        hashes_after = _canon_shard_hashes()
        assert hashes_before == hashes_after, (
            "Canon modificado por la validación dry-run experimental S0127\n"
            + "\n".join(
                f"  {k}: CAMBIÓ"
                for k in hashes_before
                if hashes_before.get(k) != hashes_after.get(k)
            )
        )

    def test_experimental_option_1_output_does_not_contain_apply(self):
        """
        La salida de la opción 1 NO debe contener '--apply'.
        """
        if not DEFAULT_CANDIDATES_INPUT.exists():
            pytest.skip("No hay archivo de candidatos; test no aplica")
        result = _run_menu("16\n1\n0\n0\n", timeout=60)
        assert "--apply" not in result.stdout, (
            f"'--apply' encontrado en el output — PROHIBIDO en S0127:\n{result.stdout[:800]}"
        )

    def test_experimental_invalid_choice_no_crash(self):
        """Elegir una opción inválida dentro del submenú no crashea el menú."""
        result = _run_menu("16\n99\n0\n0\n", timeout=30)
        assert result.returncode == 0, (
            f"returncode={result.returncode}"
        )

    def test_experimental_option_2_no_report_is_graceful(self):
        """
        La opción 2 del submenú (ver reporte humano) maneja graciosamente
        la ausencia del reporte.
        """
        result = _run_menu("16\n2\n0\n0\n", timeout=30)
        assert result.returncode == 0
        # Si no existe el reporte, debe haber un mensaje claro
        if "No hay reporte" in result.stdout:
            assert "dry-run" in result.stdout or "Ejecute" in result.stdout
