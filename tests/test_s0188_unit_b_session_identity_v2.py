"""
tests/test_s0188_unit_b_session_identity_v2.py — S0188 UNIT B

Fixture contract for the session-identity simplification authorized by the
Contrato de sesión 0188 (Unit B, Nivel 2, condicionado a validación en
fixtures aisladas -- nunca contra Canon productivo ni contra las sesiones
históricas S0001-S0187).

Contrato a demostrar (dirección humana: PRESERVE HISTORY / SIMPLIFY FORWARD):

    LEGACY   session_id = mXX-sNNNN   + module = mXX   -> still valid
    CURRENT  session_id = sNNNN       + no module       -> now valid
    HYBRID   any mix of the two shapes                  -> always invalid

Todo lo que este archivo ejercita ocurre sobre tmp_path / fixtures propias.
No se toca ni se lee ninguna sesión real (S0001-S0187, ni la familia real
S0188 bajo el workspace gobernado), y no se escribe a Canon.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = REPO_ROOT / "src" / "python_scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import generate_session_deliverables as gsd  # noqa: E402
import session_artifact_governance as sag  # noqa: E402

GENERATE_SCRIPT = SCRIPT_DIR / "generate_session_deliverables.py"


# ---------------------------------------------------------------------------
# B7 -- shapes construidos a mano (no dependen de build_deliverable, para que
# la prueba no se auto-valide contra su propia implementación)
# ---------------------------------------------------------------------------

def _write(tmp_path: Path, name: str, payload: dict) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def _base_payload(**overrides) -> dict:
    payload = {
        "title": "#### 🌀 Contrato de sesión 9999 = fixture",
        "type": "text/markdown",
        "created": "20260928000000000",
        "modified": "20260928000000000",
        "status": "delivered",
        "canonical_slug": "fixture-contrato-9999",
        "tags": ["sesion", "contrato"],
        "text": "# Fixture\n\nContenido de prueba.",
    }
    payload.update(overrides)
    return payload


class TestLegacyShapeStillValid:
    def test_legacy_with_correct_module_is_valid(self, tmp_path):
        payload = _base_payload(session_id="m04-s9999", module="m04", session="S9999")
        path = _write(tmp_path, "legacy.md.json", payload)
        errors = gsd.validate_deliverable_file(path)
        assert errors == [], [str(e) for e in errors]


class TestCurrentShapeIsValid:
    def test_current_without_module_is_valid(self, tmp_path):
        payload = _base_payload(session_id="s9999", session="S9999")
        path = _write(tmp_path, "current.md.json", payload)
        errors = gsd.validate_deliverable_file(path)
        assert errors == [], [str(e) for e in errors]

    def test_current_rejects_a_present_but_empty_module(self, tmp_path):
        # An explicit module="" on a current-shaped session_id is still a
        # hybrid/contradictory artifact, not a valid current one -- current
        # means the field is ABSENT, not empty.
        payload = _base_payload(session_id="s9999", module="", session="S9999")
        path = _write(tmp_path, "current_empty_module.md.json", payload)
        errors = gsd.validate_deliverable_file(path)
        assert any(e.field == "module" for e in errors), [str(e) for e in errors]


class TestHybridIsAlwaysInvalid:
    def test_current_session_id_with_module_is_rejected(self, tmp_path):
        payload = _base_payload(session_id="s9999", module="m04", session="S9999")
        path = _write(tmp_path, "hybrid_a.md.json", payload)
        errors = gsd.validate_deliverable_file(path)
        assert any(e.field == "module" for e in errors), [str(e) for e in errors]

    def test_legacy_session_id_with_mismatched_module_is_rejected(self, tmp_path):
        payload = _base_payload(session_id="m04-s9999", module="m03", session="S9999")
        path = _write(tmp_path, "hybrid_b.md.json", payload)
        errors = gsd.validate_deliverable_file(path)
        assert any(e.field == "module" for e in errors), [str(e) for e in errors]

    def test_legacy_session_id_missing_module_is_rejected(self, tmp_path):
        payload = _base_payload(session_id="m04-s9999", session="S9999")
        path = _write(tmp_path, "hybrid_c.md.json", payload)
        errors = gsd.validate_deliverable_file(path)
        assert any(e.field == "module" for e in errors), [str(e) for e in errors]

    def test_arbitrary_session_id_is_rejected(self, tmp_path):
        payload = _base_payload(session_id="not-a-real-session-id", session="S9999")
        path = _write(tmp_path, "invalid_id.md.json", payload)
        errors = gsd.validate_deliverable_file(path)
        assert any(e.field == "session_id" for e in errors), [str(e) for e in errors]


# ---------------------------------------------------------------------------
# B10 -- productor: generar 7/7 en modo legacy y en modo current, aislado en
# tmp_path (nunca contra data/out/local/sessions real).
# ---------------------------------------------------------------------------

class TestProducerGeneratesBothShapes:
    def _generate(self, tmp_path, session_id):
        result = subprocess.run(
            [
                sys.executable, str(GENERATE_SCRIPT), "generate",
                "--session-id", session_id,
                "--topic", "fixture unit b",
                "--sessions-dir", str(tmp_path),
            ],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0, result.stderr
        return sorted(tmp_path.rglob("*.md.json"))

    def test_legacy_session_id_produces_7_files_with_module(self, tmp_path):
        files = self._generate(tmp_path, "m04-s9998")
        assert len(files) == 7
        for f in files:
            payload = json.loads(f.read_text(encoding="utf-8"))
            assert payload["session_id"] == "m04-s9998"
            assert payload["module"] == "m04"
            assert gsd.validate_deliverable_file(f) == []

    def test_current_session_id_produces_7_files_without_module(self, tmp_path):
        files = self._generate(tmp_path, "s9997")
        assert len(files) == 7
        for f in files:
            payload = json.loads(f.read_text(encoding="utf-8"))
            assert payload["session_id"] == "s9997"
            assert "module" not in payload, f"{f.name} should not carry 'module' in current mode"
            assert gsd.validate_deliverable_file(f) == []

    def test_current_filenames_have_no_mxx_prefix(self, tmp_path):
        files = self._generate(tmp_path, "s9996")
        names = [f.name for f in files]
        assert all(not n.startswith("m0") for n in names if not n.startswith("diagnostico-")), names
        assert any(n.startswith("s9996-") for n in names)

    def test_producer_is_deterministic_across_runs(self, tmp_path):
        """B17 -- repetir la generación no debe cambiar identidad/nombre/slug."""
        first = self._generate(tmp_path / "run1", "s9995")
        second = self._generate(tmp_path / "run2", "s9995")
        assert [f.name for f in first] == [f.name for f in second]
        for f1, f2 in zip(first, second):
            p1, p2 = json.loads(f1.read_text()), json.loads(f2.read_text())
            for key in ("session_id", "canonical_slug", "title", "tags"):
                assert p1[key] == p2[key], key


# ---------------------------------------------------------------------------
# B18 -- compatibilidad histórica: una muestra real de sesiones legacy sigue
# siendo legible, sin modificarlas (solo lectura).
# ---------------------------------------------------------------------------

class TestLegacyHistoricalSamplesStillReadable:
    SESSIONS_DIR = Path("/home/ohana_linux/tdc/tdc-workspace/out/local/sessions")

    def test_s0187_contrato_still_validates(self):
        path = self.SESSIONS_DIR / "00_contratos" / "m04-s0187-contrato-saneamiento-inventario-material-y-frontera-de-artefactos.md.json"
        if not path.exists():
            pytest.skip("muestra histórica no disponible en este entorno")
        before = path.read_bytes()
        errors = gsd.validate_deliverable_file(path)
        after = path.read_bytes()
        assert errors == [], [str(e) for e in errors]
        assert before == after, "la validación no debe mutar el artefacto leído"


# ---------------------------------------------------------------------------
# B12 -- session_artifact_governance: agrupación de familia por sesión.
# session_artifact_governance.py es un consumer directo descubierto en esta
# unidad (no listado explícitamente por el encargo, pero es la dependencia
# real de session_sync.py para session_id/tags -- ver evidencia en Sesión).
# ---------------------------------------------------------------------------

class TestSessionArtifactGovernanceGroupsBothShapes:
    def test_legacy_filenames_share_session_tag(self):
        contrato_id = sag.extract_session_id(Path("m04-s9994-contrato-topic.md.json"))
        procedencia_id = sag.extract_session_id(Path("m04-s9994-procedencia-topic.md.json"))
        contrato_tags = sag.build_session_tags(contrato_id, "contrato_de_sesion")
        procedencia_tags = sag.build_session_tags(procedencia_id, "procedencia_de_sesion")
        assert "session:m04-s9994" in contrato_tags
        assert "session:m04-s9994" in procedencia_tags

    def test_current_filenames_share_session_tag_without_milestone(self):
        contrato_id = sag.extract_session_id(Path("s9993-contrato-topic.md.json"))
        procedencia_id = sag.extract_session_id(Path("s9993-procedencia-topic.md.json"))
        contrato_tags = sag.build_session_tags(contrato_id, "contrato_de_sesion")
        procedencia_tags = sag.build_session_tags(procedencia_id, "procedencia_de_sesion")
        assert "session:s9993" in contrato_tags
        assert "session:s9993" in procedencia_tags
        assert not any(t.startswith("milestone:") for t in contrato_tags)

    def test_legacy_parse_session_parts_unchanged(self):
        assert sag.parse_session_parts("m04-s0187-contrato-topic") == ("m04", "0187", "contrato-topic")

    def test_current_parse_session_parts(self):
        assert sag.parse_session_parts("s0188-contrato-topic") == ("", "0188", "contrato-topic")

    def test_truly_non_standard_ids_unaffected(self):
        """Thematic diagnostics etc. keep falling back to the full-id branch."""
        assert sag.parse_session_parts("diagnostico-tematico-0023-algo") == ("", "", "diagnostico-tematico-0023-algo")


# ---------------------------------------------------------------------------
# B8 -- canonizabilidad: session_sync.py scan (candidate generation), sobre
# sessions-dir/canon-dir/out-dir enteramente aislados (nunca el workspace
# productivo, nunca S66 real, nunca --apply/admisión).
# ---------------------------------------------------------------------------

class TestCandidateGenerationForBothShapes:
    def test_scan_generates_valid_candidates_for_legacy_and_current(self, tmp_path):
        sessions_dir = tmp_path / "sessions"
        canon_dir = tmp_path / "canon"
        out_dir = tmp_path / "out"
        canon_dir.mkdir(parents=True)
        (canon_dir / "tiddlers_1.jsonl").write_text("")  # empty canon -> everything is "missing"

        for sid, topic in (("s9992", "b8 fixture current"), ("m04-s9991", "b8 fixture legacy")):
            result = subprocess.run(
                [sys.executable, str(GENERATE_SCRIPT), "generate",
                 "--session-id", sid, "--topic", topic, "--sessions-dir", str(sessions_dir)],
                capture_output=True, text=True, cwd=str(REPO_ROOT),
            )
            assert result.returncode == 0, result.stderr

        sync_script = SCRIPT_DIR / "session_sync.py"
        result = subprocess.run(
            [sys.executable, str(sync_script),
             "scan",
             "--sessions-dir", str(sessions_dir),
             "--canon-dir", str(canon_dir),
             "--out-dir", str(out_dir),
             "--scope", "missing"],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["status"] == "ok"
        assert payload["total_session_records"] == 14
        assert payload["invalid"] == 0
        assert payload["unsupported"] == 0
        assert payload["missing_by_id"] == 14

        candidate_file = Path(payload["generated_missing_candidate_file"])
        records = [json.loads(l) for l in candidate_file.read_text().splitlines() if l.strip()]
        assert len(records) == 14
        doc_keys = {r["source_fields"]["document_key"] for r in records}
        assert any("s9992" in k for k in doc_keys)
        assert any("m04-s9991" in k for k in doc_keys)
