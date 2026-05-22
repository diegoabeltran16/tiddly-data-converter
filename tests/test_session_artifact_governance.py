"""Tests for session_artifact_governance.py — S0121.

Verifies family classification, session ID extraction, tag generation, and
canonizability validation for all registered artifact families including
thematic diagnostics, micro-ciclo diagnostics, balance, propuesta, and standard
session artifacts.

Para ejecutar en aislamiento:
    pytest tests/test_session_artifact_governance.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "python_scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from session_artifact_governance import (  # noqa: E402
    FAMILY_BY_RELATIVE_ROOT,
    ArtifactFamilySpec,
    CanonizabilityResult,
    build_session_tags,
    check_canonizable,
    classify_artifact_family,
    describe_family,
    extract_session_id,
    known_families,
    parse_session_parts,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _write_md_json(path: Path, title: str = "Test", text: str = "contenido") -> Path:
    """Write a minimal valid .md.json tiddler to path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([{
            "title": title,
            "text": text,
            "type": "text/markdown",
            "created": "20260101000000000",
            "modified": "20260101000000000",
        }]),
        encoding="utf-8",
    )
    return path


def _sessions_dir(tmp_path: Path) -> Path:
    d = tmp_path / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── TestFamilyRegistry ────────────────────────────────────────────────────────

class TestFamilyRegistry:
    def test_all_expected_families_registered(self):
        families = {spec["family"] for spec in FAMILY_BY_RELATIVE_ROOT.values()}
        expected = {
            "contrato_de_sesion",
            "procedencia_de_sesion",
            "detalles_de_sesion",
            "hipotesis_de_sesion",
            "balance_de_sesion",
            "propuesta_de_sesion",
            "diagnostico_de_sesion",
            "diagnostico_tematico",
            "diagnostico_de_modulo",
            "diagnostico_de_micro_ciclo",
            "diagnostico_de_meso_ciclo",
            "diagnostico_de_proyecto",
        }
        assert expected <= families

    def test_known_families_returns_list(self):
        families = known_families()
        assert isinstance(families, list)
        assert len(families) >= 12

    def test_tema_maps_to_diagnostico_tematico(self):
        spec = FAMILY_BY_RELATIVE_ROOT[("06_diagnoses", "tema")]
        assert spec["family"] == "diagnostico_tematico"

    def test_micro_ciclo_folder_uses_hyphen(self):
        assert ("06_diagnoses", "micro-ciclo") in FAMILY_BY_RELATIVE_ROOT

    def test_meso_ciclo_folder_uses_hyphen(self):
        assert ("06_diagnoses", "meso-ciclo") in FAMILY_BY_RELATIVE_ROOT


# ── TestClassifyArtifactFamily ─────────────────────────────────────────────────

class TestClassifyArtifactFamily:
    def test_contrato_folder(self, tmp_path):
        sessions = _sessions_dir(tmp_path)
        path = sessions / "00_contratos" / "m04-s0121-contrato.md.json"
        spec = classify_artifact_family(path, sessions)
        assert spec is not None
        assert spec.family == "contrato_de_sesion"

    def test_balance_folder(self, tmp_path):
        sessions = _sessions_dir(tmp_path)
        path = sessions / "04_balance_de_sesion" / "m04-s0121-balance.md.json"
        spec = classify_artifact_family(path, sessions)
        assert spec is not None
        assert spec.family == "balance_de_sesion"

    def test_propuesta_folder(self, tmp_path):
        sessions = _sessions_dir(tmp_path)
        path = sessions / "05_propuesta_de_sesion" / "m04-s0121-propuesta.md.json"
        spec = classify_artifact_family(path, sessions)
        assert spec is not None
        assert spec.family == "propuesta_de_sesion"

    def test_diagnostico_tematico_folder(self, tmp_path):
        """Thematic diagnostics in 06_diagnoses/tema/ are recognized by folder."""
        sessions = _sessions_dir(tmp_path)
        # Non-standard filename — no mXX-sNNN prefix required
        path = sessions / "06_diagnoses" / "tema" / (
            "diagnostico-tematico-033-frontera-canon-archivo-diagnosticos-"
            "tematicos-admision-gobernada.md.json"
        )
        spec = classify_artifact_family(path, sessions)
        assert spec is not None
        assert spec.family == "diagnostico_tematico"

    def test_micro_ciclo_folder(self, tmp_path):
        sessions = _sessions_dir(tmp_path)
        path = sessions / "06_diagnoses" / "micro-ciclo" / (
            "m04-micro-ciclo-s095-s104-diagnostico.md.json"
        )
        spec = classify_artifact_family(path, sessions)
        assert spec is not None
        assert spec.family == "diagnostico_de_micro_ciclo"

    def test_meso_ciclo_folder(self, tmp_path):
        sessions = _sessions_dir(tmp_path)
        path = sessions / "06_diagnoses" / "meso-ciclo" / "some-meso.md.json"
        spec = classify_artifact_family(path, sessions)
        assert spec is not None
        assert spec.family == "diagnostico_de_meso_ciclo"

    def test_unknown_folder_returns_none(self, tmp_path):
        sessions = _sessions_dir(tmp_path)
        path = sessions / "07_unknown" / "something.md.json"
        spec = classify_artifact_family(path, sessions)
        assert spec is None

    def test_outside_sessions_returns_none(self, tmp_path):
        sessions = _sessions_dir(tmp_path)
        path = tmp_path / "outside" / "file.md.json"
        spec = classify_artifact_family(path, sessions)
        assert spec is None

    def test_returns_artifact_family_spec_instance(self, tmp_path):
        sessions = _sessions_dir(tmp_path)
        path = sessions / "00_contratos" / "m04-s0121-contrato.md.json"
        spec = classify_artifact_family(path, sessions)
        assert isinstance(spec, ArtifactFamilySpec)
        assert spec.role_primary == "policy"
        assert spec.order == 1


# ── TestExtractSessionId ──────────────────────────────────────────────────────

class TestExtractSessionId:
    def test_standard_session_id(self):
        path = Path("m04-s0121-contrato-de-sesion.md.json")
        assert extract_session_id(path) == "m04-s0121-contrato-de-sesion"

    def test_thematic_diagnostic_id_preserved(self):
        """Non-standard filenames are returned as-is without renaming."""
        name = (
            "diagnostico-tematico-033-frontera-canon-archivo-"
            "diagnosticos-tematicos-admision-gobernada.md.json"
        )
        path = Path(name)
        result = extract_session_id(path)
        assert result == name[: -len(".md.json")]
        assert result.startswith("diagnostico-tematico-033")

    def test_micro_ciclo_id_preserved(self):
        path = Path("m04-micro-ciclo-s095-s104-diagnostico.md.json")
        assert extract_session_id(path) == "m04-micro-ciclo-s095-s104-diagnostico"

    def test_non_md_json_extension_uses_stem(self):
        path = Path("some-file.json")
        assert extract_session_id(path) == "some-file"


# ── TestParseSessionParts ─────────────────────────────────────────────────────

class TestParseSessionParts:
    def test_standard_session_id(self):
        m, n, s = parse_session_parts("m04-s0121-contrato-de-sesion")
        assert m == "m04"
        assert n == "0121"
        assert s == "contrato-de-sesion"

    def test_session_prefix_stripped(self):
        _, _, slug = parse_session_parts("m04-s0121-session-contrato")
        assert slug == "contrato"

    def test_non_standard_returns_empty_milestone(self):
        m, n, s = parse_session_parts("diagnostico-tematico-033-frontera")
        assert m == ""
        assert n == ""
        assert s == "diagnostico-tematico-033-frontera"

    def test_micro_ciclo_name_non_standard(self):
        m, n, s = parse_session_parts("m04-micro-ciclo-s095-s104-diagnostico")
        # Does not match SESSION_RE  (no -sNNN- right after m04-)
        assert m == ""
        assert n == ""

    def test_suffix_letter_variant(self):
        m, n, s = parse_session_parts("m04-s0121a-contrato")
        assert m == "m04"
        assert n == "0121a"
        assert s == "contrato"


# ── TestBuildSessionTags ──────────────────────────────────────────────────────

class TestBuildSessionTags:
    def test_standard_session_tags(self):
        tags = build_session_tags("m04-s0121-contrato", "contrato_de_sesion")
        assert "session:m04-s0121" in tags
        assert "milestone:m04" in tags
        assert "artifact:contrato_de_sesion" in tags
        assert "status:candidate" in tags
        assert "layer:session" in tags

    def test_thematic_diagnostic_tags(self):
        """Non-standard session ID generates session:<full-id> tag."""
        session_id = "diagnostico-tematico-033-frontera"
        tags = build_session_tags(session_id, "diagnostico_tematico")
        assert f"session:{session_id}" in tags
        assert "artifact:diagnostico_tematico" in tags
        assert "status:candidate" in tags
        # No milestone tag for non-standard IDs
        assert not any(t.startswith("milestone:") for t in tags)

    def test_no_duplicate_tags(self):
        tags = build_session_tags("m04-s0121-contrato", "contrato_de_sesion")
        assert len(tags) == len(set(tags))

    def test_micro_ciclo_tags(self):
        tags = build_session_tags("m04-micro-ciclo-s095-s104-diagnostico", "diagnostico_de_micro_ciclo")
        assert "artifact:diagnostico_de_micro_ciclo" in tags
        assert "status:candidate" in tags


# ── TestDescribeFamily ────────────────────────────────────────────────────────

class TestDescribeFamily:
    def test_known_family_returns_label(self):
        label = describe_family("diagnostico_tematico")
        assert "temático" in label.lower() or "tematico" in label.lower()

    def test_unknown_family_returns_family_name(self):
        assert describe_family("unknown_family") == "unknown_family"

    def test_none_returns_desconocida(self):
        assert describe_family(None) == "desconocida"


# ── TestCheckCanonizable ──────────────────────────────────────────────────────

class TestCheckCanonizable:
    def test_valid_contrato_artifact(self, tmp_path):
        sessions = _sessions_dir(tmp_path)
        path = _write_md_json(
            sessions / "00_contratos" / "m04-s0121-contrato.md.json",
            title="Contrato de sesión 0121",
            text="Texto del contrato.",
        )
        result = check_canonizable(path, sessions)
        assert isinstance(result, CanonizabilityResult)
        assert result.is_canonizable, f"Errors: {result.errors}"
        assert result.family_spec is not None
        assert result.family_spec.family == "contrato_de_sesion"
        assert result.session_id == "m04-s0121-contrato"
        assert result.errors == []

    def test_valid_thematic_diagnostic(self, tmp_path):
        """Thematic diagnostics are canonizable without standard naming."""
        sessions = _sessions_dir(tmp_path)
        name = (
            "diagnostico-tematico-033-frontera-canon-archivo-"
            "diagnosticos-tematicos-admision-gobernada.md.json"
        )
        path = _write_md_json(
            sessions / "06_diagnoses" / "tema" / name,
            title="Diagnóstico temático 033",
            text="Análisis temático.",
        )
        result = check_canonizable(path, sessions)
        assert result.is_canonizable, f"Errors: {result.errors}"
        assert result.family_spec.family == "diagnostico_tematico"  # type: ignore[union-attr]
        assert "033" in result.session_id

    def test_valid_micro_ciclo(self, tmp_path):
        sessions = _sessions_dir(tmp_path)
        path = _write_md_json(
            sessions / "06_diagnoses" / "micro-ciclo" / "m04-micro-ciclo-s095-s104-diagnostico.md.json",
            title="Diagnóstico micro-ciclo s095-s104",
            text="Contenido del diagnóstico.",
        )
        result = check_canonizable(path, sessions)
        assert result.is_canonizable, f"Errors: {result.errors}"
        assert result.family_spec.family == "diagnostico_de_micro_ciclo"  # type: ignore[union-attr]

    def test_valid_balance(self, tmp_path):
        sessions = _sessions_dir(tmp_path)
        path = _write_md_json(
            sessions / "04_balance_de_sesion" / "m04-s0120-balance.md.json",
            title="Balance de sesión 0120",
            text="Balance.",
        )
        result = check_canonizable(path, sessions)
        assert result.is_canonizable, f"Errors: {result.errors}"
        assert result.family_spec.family == "balance_de_sesion"  # type: ignore[union-attr]

    def test_valid_propuesta(self, tmp_path):
        sessions = _sessions_dir(tmp_path)
        path = _write_md_json(
            sessions / "05_propuesta_de_sesion" / "m04-s0120-propuesta.md.json",
            title="Propuesta de sesión 0120",
            text="Propuesta.",
        )
        result = check_canonizable(path, sessions)
        assert result.is_canonizable, f"Errors: {result.errors}"
        assert result.family_spec.family == "propuesta_de_sesion"  # type: ignore[union-attr]

    def test_invalid_json(self, tmp_path):
        sessions = _sessions_dir(tmp_path)
        path = sessions / "00_contratos" / "bad.md.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ not valid json }", encoding="utf-8")
        result = check_canonizable(path, sessions)
        assert not result.is_canonizable
        assert any("JSON" in e or "json" in e.lower() for e in result.errors)

    def test_missing_title(self, tmp_path):
        sessions = _sessions_dir(tmp_path)
        path = sessions / "00_contratos" / "notitle.md.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps([{"text": "sin titulo", "type": "text/markdown", "title": ""}]),
            encoding="utf-8",
        )
        result = check_canonizable(path, sessions)
        assert not result.is_canonizable
        assert any("title" in e.lower() for e in result.errors)

    def test_missing_text_field(self, tmp_path):
        sessions = _sessions_dir(tmp_path)
        path = sessions / "00_contratos" / "notext.md.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps([{"title": "Título válido", "type": "text/markdown"}]),
            encoding="utf-8",
        )
        result = check_canonizable(path, sessions)
        assert not result.is_canonizable
        assert any("text" in e.lower() for e in result.errors)

    def test_outside_sessions_dir(self, tmp_path):
        sessions = _sessions_dir(tmp_path)
        outside = tmp_path / "other" / "file.md.json"
        _write_md_json(outside, title="Fuera de sessions")
        result = check_canonizable(outside, sessions)
        assert not result.is_canonizable
        assert any("sessions_dir" in e or "sessions" in e for e in result.errors)

    def test_unknown_family_folder(self, tmp_path):
        sessions = _sessions_dir(tmp_path)
        path = _write_md_json(
            sessions / "07_unknown_family" / "m04-s0121-unknown.md.json",
            title="Unknown family",
        )
        result = check_canonizable(path, sessions)
        assert not result.is_canonizable
        assert any("family" in e.lower() or "unknown" in e.lower() for e in result.errors)

    def test_wrong_extension(self, tmp_path):
        sessions = _sessions_dir(tmp_path)
        path = sessions / "00_contratos" / "file.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"title": "Test", "text": "x"}), encoding="utf-8")
        result = check_canonizable(path, sessions)
        assert not result.is_canonizable
        assert any("extension" in e.lower() or ".md.json" in e for e in result.errors)

    def test_file_does_not_exist(self, tmp_path):
        sessions = _sessions_dir(tmp_path)
        path = sessions / "00_contratos" / "nonexistent.md.json"
        result = check_canonizable(path, sessions)
        assert not result.is_canonizable
        assert any("exist" in e.lower() or "not" in e.lower() for e in result.errors)

    def test_source_path_preserved_in_result(self, tmp_path):
        sessions = _sessions_dir(tmp_path)
        path = _write_md_json(
            sessions / "00_contratos" / "m04-s0121-contrato.md.json",
            title="Contrato",
            text="texto",
        )
        result = check_canonizable(path, sessions)
        assert result.path == path

    def test_session_id_is_filename_minus_extension(self, tmp_path):
        sessions = _sessions_dir(tmp_path)
        path = _write_md_json(
            sessions / "00_contratos" / "m04-s0121-contrato-test.md.json",
            title="Test",
            text="texto",
        )
        result = check_canonizable(path, sessions)
        assert result.session_id == "m04-s0121-contrato-test"


# ── TestIntegrationWithRealSessions ───────────────────────────────────────────

class TestIntegrationWithRealSessions:
    """Spot-check against real session artifacts in the repository."""

    SESSIONS_DIR = REPO_ROOT / "data" / "out" / "local" / "sessions"

    @pytest.mark.skipif(
        not (REPO_ROOT / "data" / "out" / "local" / "sessions" / "06_diagnoses" / "tema").exists(),
        reason="Real sessions/tema folder not found",
    )
    def test_real_thematic_diagnostic_is_canonizable(self):
        tema_dir = self.SESSIONS_DIR / "06_diagnoses" / "tema"
        artifacts = sorted(tema_dir.glob("*.md.json"))
        assert artifacts, "no thematic diagnostic artifacts found in tema/"
        # Check the first one
        result = check_canonizable(artifacts[0], self.SESSIONS_DIR)
        assert result.is_canonizable, (
            f"Real thematic diagnostic failed canonizability:\n"
            f"  path: {artifacts[0]}\n"
            f"  errors: {result.errors}"
        )

    @pytest.mark.skipif(
        not (REPO_ROOT / "data" / "out" / "local" / "sessions" / "06_diagnoses" / "micro-ciclo").exists(),
        reason="Real sessions/micro-ciclo folder not found",
    )
    def test_real_micro_ciclo_diagnostic_is_canonizable(self):
        micro_dir = self.SESSIONS_DIR / "06_diagnoses" / "micro-ciclo"
        artifacts = sorted(micro_dir.glob("*.md.json"))
        assert artifacts, "no micro-ciclo diagnostic artifacts found"
        result = check_canonizable(artifacts[0], self.SESSIONS_DIR)
        assert result.is_canonizable, (
            f"Real micro-ciclo diagnostic failed canonizability:\n"
            f"  path: {artifacts[0]}\n"
            f"  errors: {result.errors}"
        )
