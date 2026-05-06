#!/usr/bin/env python3
"""Diagnostic artifact governance tests — S101.

Validates that the system correctly:
1. Accepts valid session artifacts (unchanged behavior).
2. Accepts valid diagnostic artifacts by family.
3. Rejects diagnostics placed in the wrong subfolder.
4. Rejects path traversal attempts.
5. Rejects files with invalid extensions.
6. Rejects names that don't match any known diagnostic family.
7. Distinguishes session vs diagnostic artifacts in the pull allowlist.
8. The pull allowlist (remote_pull_sessions._is_allowed_outbox_file) accepts both families.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = REPO_ROOT / "python_scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import diagnostic_governance as dg
import remote_pull_sessions as rps


SESSIONS_ROOT = REPO_ROOT / "data" / "out" / "local" / "sessions"


# ---------------------------------------------------------------------------
# 11.1  Session normal válida — el allowlist de pull sigue aceptándola
# ---------------------------------------------------------------------------

class TestSessionArtifactAccepted:

    @pytest.mark.parametrize("filename", [
        "m04-s101-gobernanza-admision-diagnosticos-no-sesionales-local.md.json",
        "m04-s055-algo-de-prueba.md.json",
        "m03-s012a-variant.md.json",
    ])
    def test_pull_allowlist_accepts_session_artifact(self, filename):
        allowed, reason = rps._is_allowed_outbox_file(filename)
        assert allowed, f"Expected session artifact to be allowed; reason={reason}"
        assert reason == ""

    def test_classify_returns_session_artifact(self):
        artifact_type, family = dg.classify_artifact(
            "m04-s101-gobernanza-admision-diagnosticos.md.json"
        )
        assert artifact_type == "session_artifact"
        assert family == ""


# ---------------------------------------------------------------------------
# 11.2  Diagnóstico temático válido
# ---------------------------------------------------------------------------

class TestDiagnosticoTematicoValido:

    FILENAME = "diagnostico-tematico-08-chunks-ai-estructurados-relacion-propagada-a-chunks.md.json"

    def test_pull_allowlist_accepts_diagnostico_tematico(self):
        allowed, reason = rps._is_allowed_outbox_file(self.FILENAME)
        assert allowed, f"Diagnostic tema should be allowed; reason={reason}"

    def test_is_diagnostic_artifact(self):
        assert dg.is_diagnostic_artifact(self.FILENAME)

    def test_detect_family_tema(self):
        assert dg.detect_family(self.FILENAME) == "tema"

    def test_expected_subfolder_tema(self):
        assert dg.expected_subfolder(self.FILENAME) == "tema"

    def test_validate_path_valid(self):
        valid, reason = dg.validate_diagnostic_artifact_path(self.FILENAME, "tema")
        assert valid, f"Expected valid; reason={reason}"

    def test_classify_returns_diagnostic_artifact(self):
        artifact_type, family = dg.classify_artifact(self.FILENAME)
        assert artifact_type == "diagnostic_artifact"
        assert family == "tema"

    def test_full_path_validation(self):
        full_path = str(
            SESSIONS_ROOT / "06_diagnoses" / "tema" / self.FILENAME
        )
        valid, reason = dg.validate_full_path(full_path, SESSIONS_ROOT)
        assert valid, f"Expected valid full path; reason={reason}"


# ---------------------------------------------------------------------------
# 11.3  Diagnóstico de microciclo válido
# ---------------------------------------------------------------------------

class TestDiagnosticoMicrocicloValido:

    FILENAME = "m04-micro-ciclo-s055-s064-diagnostico.md.json"

    def test_pull_allowlist_accepts_micro_ciclo(self):
        allowed, reason = rps._is_allowed_outbox_file(self.FILENAME)
        assert allowed, f"Diagnostic micro-ciclo should be allowed; reason={reason}"

    def test_is_diagnostic_artifact(self):
        assert dg.is_diagnostic_artifact(self.FILENAME)

    def test_detect_family_micro_ciclo(self):
        assert dg.detect_family(self.FILENAME) == "micro_ciclo"

    def test_expected_subfolder_micro_ciclo(self):
        assert dg.expected_subfolder(self.FILENAME) == "micro-ciclo"

    def test_validate_path_valid(self):
        valid, reason = dg.validate_diagnostic_artifact_path(self.FILENAME, "micro-ciclo")
        assert valid, f"Expected valid; reason={reason}"

    def test_full_path_validation(self):
        full_path = str(
            SESSIONS_ROOT / "06_diagnoses" / "micro-ciclo" / self.FILENAME
        )
        valid, reason = dg.validate_full_path(full_path, SESSIONS_ROOT)
        assert valid, f"Expected valid full path; reason={reason}"


# ---------------------------------------------------------------------------
# 11.4  Diagnóstico de mesociclo válido
# ---------------------------------------------------------------------------

class TestDiagnosticoMesocicloValido:

    FILENAME = "m04-meso-ciclo-s065-s094-diagnostico.md.json"

    def test_pull_allowlist_accepts_meso_ciclo(self):
        allowed, reason = rps._is_allowed_outbox_file(self.FILENAME)
        assert allowed, f"Diagnostic meso-ciclo should be allowed; reason={reason}"

    def test_is_diagnostic_artifact(self):
        assert dg.is_diagnostic_artifact(self.FILENAME)

    def test_detect_family_meso_ciclo(self):
        assert dg.detect_family(self.FILENAME) == "meso_ciclo"

    def test_expected_subfolder_meso_ciclo(self):
        assert dg.expected_subfolder(self.FILENAME) == "meso-ciclo"

    def test_validate_path_valid(self):
        valid, reason = dg.validate_diagnostic_artifact_path(self.FILENAME, "meso-ciclo")
        assert valid, f"Expected valid; reason={reason}"

    def test_full_path_validation(self):
        full_path = str(
            SESSIONS_ROOT / "06_diagnoses" / "meso-ciclo" / self.FILENAME
        )
        valid, reason = dg.validate_full_path(full_path, SESSIONS_ROOT)
        assert valid, f"Expected valid full path; reason={reason}"


# ---------------------------------------------------------------------------
# Additional: Diagnóstico de proyecto y sesión
# ---------------------------------------------------------------------------

class TestDiagnosticoProyectoYSesion:

    @pytest.mark.parametrize("filename,subfolder,family", [
        (
            "diagnostico-proyecto-01-alineacion-canon-reverse.md.json",
            "proyecto",
            "proyecto",
        ),
        (
            "m04-diagnostico-proyecto-alineacion-canon.md.json",
            "proyecto",
            "proyecto",
        ),
        (
            "diagnostico-sesion-s098-propagacion-relacional-chunks-ai.md.json",
            "sesion",
            "sesion",
        ),
    ])
    def test_pull_allowlist_accepts_artifact(self, filename, subfolder, family):
        allowed, reason = rps._is_allowed_outbox_file(filename)
        assert allowed, f"{filename}: should be allowed; reason={reason}"

    @pytest.mark.parametrize("filename,subfolder,family", [
        (
            "diagnostico-proyecto-01-alineacion-canon-reverse.md.json",
            "proyecto",
            "proyecto",
        ),
        (
            "m04-diagnostico-proyecto-alineacion-canon.md.json",
            "proyecto",
            "proyecto",
        ),
        (
            "diagnostico-sesion-s098-propagacion-relacional-chunks-ai.md.json",
            "sesion",
            "sesion",
        ),
    ])
    def test_validate_path_valid(self, filename, subfolder, family):
        valid, reason = dg.validate_diagnostic_artifact_path(filename, subfolder)
        assert valid, f"{filename}: expected valid in {subfolder}; reason={reason}"
        assert dg.detect_family(filename) == family


# ---------------------------------------------------------------------------
# 11.5  Diagnóstico en carpeta incorrecta debe ser rechazado
# ---------------------------------------------------------------------------

class TestDiagnosticoEnCarpetaIncorrecta:

    def test_meso_ciclo_in_tema_folder_rejected(self):
        filename = "m04-meso-ciclo-s065-s094-diagnostico.md.json"
        valid, reason = dg.validate_diagnostic_artifact_path(filename, "tema")
        assert not valid
        assert "wrong_subfolder" in reason
        assert "meso-ciclo" in reason

    def test_micro_ciclo_in_sesion_folder_rejected(self):
        filename = "m04-micro-ciclo-s055-s064-diagnostico.md.json"
        valid, reason = dg.validate_diagnostic_artifact_path(filename, "sesion")
        assert not valid
        assert "wrong_subfolder" in reason

    def test_tema_in_micro_ciclo_folder_rejected(self):
        filename = "diagnostico-tematico-08-chunks-ai.md.json"
        valid, reason = dg.validate_diagnostic_artifact_path(filename, "micro-ciclo")
        assert not valid
        assert "wrong_subfolder" in reason

    def test_full_path_meso_in_tema_rejected(self):
        filename = "m04-meso-ciclo-s065-s094-diagnostico.md.json"
        full_path = str(SESSIONS_ROOT / "06_diagnoses" / "tema" / filename)
        valid, reason = dg.validate_full_path(full_path, SESSIONS_ROOT)
        assert not valid
        assert "wrong_subfolder" in reason


# ---------------------------------------------------------------------------
# 11.6  Escape de ruta debe ser rechazado
# ---------------------------------------------------------------------------

class TestPathTraversalRejected:

    def test_path_traversal_in_full_path(self):
        traversal_path = str(
            SESSIONS_ROOT / "06_diagnoses" / "tema" / ".." / ".." / "secret.md.json"
        )
        valid, reason = dg.validate_full_path(traversal_path, SESSIONS_ROOT)
        assert not valid

    def test_is_safe_path_rejects_dotdot(self):
        safe, reason = dg.is_safe_path("data/out/local/sessions/06_diagnoses/tema/../../secret.md.json")
        assert not safe
        assert reason == "path_traversal"

    def test_is_safe_path_rejects_absolute(self):
        safe, reason = dg.is_safe_path("/etc/passwd")
        assert not safe
        assert reason == "absolute_path"

    def test_is_safe_path_accepts_relative(self):
        safe, reason = dg.is_safe_path(
            "data/out/local/sessions/06_diagnoses/tema/diagnostico-tematico-08-foo.md.json"
        )
        assert safe
        assert reason == ""

    def test_pull_allowlist_rejects_windows_ads(self):
        allowed, reason = rps._is_allowed_outbox_file("diagnostico-tematico-08-foo.md.json:Zone.Identifier")
        assert not allowed
        assert reason == "denylist_ads_zone_identifier"


# ---------------------------------------------------------------------------
# 11.7  Extensión inválida debe ser rechazada
# ---------------------------------------------------------------------------

class TestExtensionInvalida:

    @pytest.mark.parametrize("filename", [
        "diagnostico-tematico-08-algo.json",
        "diagnostico-tematico-08-algo.md",
        "diagnostico-tematico-08-algo.txt",
        "diagnostico-tematico-08-algo",
        "m04-meso-ciclo-s065-s094-diagnostico.json",
        "m04-micro-ciclo-s055-s064-diagnostico.md",
    ])
    def test_invalid_extension_not_diagnostic(self, filename):
        assert not dg.is_diagnostic_artifact(filename), (
            f"{filename} should not be recognized as a diagnostic artifact (wrong extension)"
        )

    @pytest.mark.parametrize("filename", [
        "diagnostico-tematico-08-algo.json",
        "diagnostico-tematico-08-algo.md",
        "diagnostico-tematico-08-algo.txt",
    ])
    def test_validate_path_rejects_invalid_extension(self, filename):
        valid, reason = dg.validate_diagnostic_artifact_path(filename, "tema")
        assert not valid
        assert reason == "invalid_extension"

    @pytest.mark.parametrize("filename", [
        "diagnostico-tematico-08-algo.json",
        "diagnostico-tematico-08-algo.md",
        "diagnostico-tematico-08-algo.txt",
    ])
    def test_pull_allowlist_rejects_wrong_extension(self, filename):
        allowed, reason = rps._is_allowed_outbox_file(filename)
        assert not allowed

    def test_has_valid_extension_checks_double_extension(self):
        assert dg.has_valid_extension("diagnostico-tematico-08-foo.md.json")
        assert not dg.has_valid_extension("diagnostico-tematico-08-foo.json")
        assert not dg.has_valid_extension("diagnostico-tematico-08-foo.md")
        assert not dg.has_valid_extension(".md.json")


# ---------------------------------------------------------------------------
# 11.8  Nombre ambiguo debe ser rechazado
# ---------------------------------------------------------------------------

class TestNombreAmbiguo:

    @pytest.mark.parametrize("filename", [
        "informe-08-algo.md.json",
        "algo-random.md.json",
        "session-08.md.json",
        "diagnostico-08.md.json",
        "diagnostico.md.json",
        "report.md.json",
        "tiddlers_001.jsonl",
        "diagnostico-ciclo-s055-s064.md.json",
    ])
    def test_ambiguous_names_not_diagnostic(self, filename):
        assert not dg.is_diagnostic_artifact(filename), (
            f"{filename} should not be recognized as a diagnostic artifact"
        )

    @pytest.mark.parametrize("filename", [
        "informe-08-algo.md.json",
        "algo-random.md.json",
        "diagnostico-08.md.json",
    ])
    def test_ambiguous_names_classified_unknown(self, filename):
        artifact_type, _ = dg.classify_artifact(filename)
        assert artifact_type == "unknown"

    @pytest.mark.parametrize("filename", [
        "informe-08-algo.md.json",
        "diagnostico-08.md.json",
    ])
    def test_pull_allowlist_rejects_ambiguous(self, filename):
        allowed, reason = rps._is_allowed_outbox_file(filename)
        assert not allowed
        assert "allowlist" in reason


# ---------------------------------------------------------------------------
# Pull allowlist — denylist still works
# ---------------------------------------------------------------------------

class TestPullAllowlistDenylist:

    def test_canon_shard_rejected(self):
        allowed, reason = rps._is_allowed_outbox_file("tiddlers_001.jsonl")
        assert not allowed
        assert reason == "denylist_canon_shard"

    def test_env_file_rejected(self):
        allowed, reason = rps._is_allowed_outbox_file(".env")
        assert not allowed
        assert reason == "denylist_credentials"

    def test_env_prefix_rejected(self):
        allowed, reason = rps._is_allowed_outbox_file(".env.production")
        assert not allowed
        assert reason == "denylist_credentials"


# ---------------------------------------------------------------------------
# Valid diagnosis subfolders
# ---------------------------------------------------------------------------

class TestValidDiagnosisSubfolders:

    def test_all_five_families_have_valid_subfolders(self):
        expected = {"tema", "micro-ciclo", "meso-ciclo", "proyecto", "sesion"}
        assert dg.VALID_DIAGNOSIS_SUBFOLDERS == expected

    def test_invalid_subfolder_not_in_valid_set(self):
        assert "canon" not in dg.VALID_DIAGNOSIS_SUBFOLDERS
        assert "module" not in dg.VALID_DIAGNOSIS_SUBFOLDERS
        assert "reverse" not in dg.VALID_DIAGNOSIS_SUBFOLDERS
        assert "00_contratos" not in dg.VALID_DIAGNOSIS_SUBFOLDERS
