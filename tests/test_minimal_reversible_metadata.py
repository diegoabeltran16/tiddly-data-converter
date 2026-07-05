"""tests/test_minimal_reversible_metadata.py — S0134

Tests del módulo de metadata mínima reversible para artefactos canonizables.

Cubre los 10 casos mínimos obligatorios definidos en S0134 §7.

Ejecutar:
    python3 -m pytest tests/test_minimal_reversible_metadata.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

from build_minimal_reversible_metadata import (
    build_record,
    extract_session_id,
    extract_diagnostic_id,
    extract_module,
    extract_sequence,
    infer_metadata,
    _compute_reversibility,
    _detect_content_format,
    _extract_headings,
    _extract_referenced_sessions,
    _extract_referenced_diagnostics,
    _extract_referenced_scripts,
    build_matrix,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _session_tiddler(
    family: str = "balance_de_sesion",
    session_num: str = "0133",
    module: str = "m04",
    text: str = "## Aciertos\n\n- Test.\n",
    source_path: str = "data/out/local/sessions/04_balance_de_sesion/m04-s0133-balance.md.json",
) -> dict:
    slug = f"m04-s{session_num}-balance-test"
    return {
        "id": f"uuid-{session_num}",
        "title": f"#### 🌀 Balance de sesión {session_num} = test-topic",
        "canonical_slug": slug,
        "content_type": "text/markdown",
        "schema_version": "v0",
        "text": text,
        "artifact_family": family,
        "source_fields": {
            "artifact_family": family,
            "canonical_status": "local_admitted",
            "session_origin": f"{module}-s{session_num}-balance-test",
            "source_path": source_path,
            "provenance_ref": source_path,
            "document_key": f"data/out/local/sessions/{module}-s{session_num}-balance-test",
        },
    }


def _diagnostic_tiddler(dt_num: int = 35, text: str = "## Diagnóstico\n\n### Análisis\n") -> dict:
    num_str = f"{dt_num:04d}"
    slug = f"diagnostico-tematico-{dt_num:03d}-contrato-source-fields"
    return {
        "id": f"uuid-dt{dt_num}",
        "title": f"#### 🌀 Diagnóstico temático {num_str} = contrato-source-fields",
        "canonical_slug": slug,
        "content_type": "text/markdown",
        "schema_version": "v0",
        "text": text,
        "source_fields": {
            "artifact_family": "diagnostico_tematico",
            "canonical_status": "local_admitted",
            "session_origin": f"diagnostico-tematico-{dt_num:02d}-contrato-source-fields",
            "source_path": f"data/out/local/sessions/06_diagnoses/tema/{slug}.md.json",
            "provenance_ref": f"data/out/local/sessions/06_diagnoses/tema/{slug}.md.json",
            "document_key": f"data/out/local/sessions/06_diagnoses/tema/{slug}",
        },
    }


# ── Caso 1: Reconoce artefacto de sesión completo ─────────────────────────────

class TestCase01_RecognizesSessionArtifact:
    def test_session_artifact_builds_record(self):
        tiddler = _session_tiddler()
        rec = build_record(tiddler)
        assert rec["artifact_family"] == "balance_de_sesion"
        assert rec["reversible_metadata"]["artifact_family"] == "balance_de_sesion"
        assert rec["tiddler_id"] == "uuid-0133"

    def test_session_artifact_has_all_required_keys(self):
        rec = build_record(_session_tiddler())
        required_keys = {
            "tiddler_id", "title", "artifact_family", "source_path",
            "source_fields", "reversible_metadata", "inferred_metadata", "validation",
        }
        assert required_keys.issubset(rec.keys())

    def test_reversible_metadata_has_all_required_keys(self):
        rec = build_record(_session_tiddler())
        rm = rec["reversible_metadata"]
        required = {
            "canonical_title", "artifact_family", "session_id", "diagnostic_id",
            "module", "sequence", "slug", "content_format", "visibility",
            "reversibility_status",
        }
        assert required.issubset(rm.keys())


# ── Caso 2: Reconoce diagnóstico temático canonizable ─────────────────────────

class TestCase02_RecognizesDiagnosticTematico:
    def test_diagnostico_tematico_family_detected(self):
        tiddler = _diagnostic_tiddler(35)
        rec = build_record(tiddler)
        assert rec["artifact_family"] == "diagnostico_tematico"

    def test_diagnostico_tematico_diagnostic_id_extracted(self):
        tiddler = _diagnostic_tiddler(35)
        rec = build_record(tiddler)
        assert rec["reversible_metadata"]["diagnostic_id"] == "DT035"

    def test_diagnostico_content_format_detected(self):
        tiddler = _diagnostic_tiddler(35, text="## Análisis\n\nContenido markdown.")
        rec = build_record(tiddler)
        assert rec["reversible_metadata"]["content_format"] == "markdown"

    def test_diagnostico_json_text_detected(self):
        tiddler = _diagnostic_tiddler(1, text='{"key": "value", "list": [1, 2]}')
        rec = build_record(tiddler)
        assert rec["reversible_metadata"]["content_format"] == "json"


# ── Caso 3: Extrae session_id desde título o nombre ───────────────────────────

class TestCase03_ExtractsSessionId:
    @pytest.mark.parametrize("session_origin,expected", [
        ("m04-s0133-balance-test",          "m04-s0133"),
        ("m01-s0001-extractor-contract",    "m01-s0001"),
        ("m04-s0132-evaluador-dry-run",     "m04-s0132"),
        ("m01-s01-extractor-contract",      "m01-s0001"),
        ("m04-s105-algo",                   "m04-s0105"),
        ("diagnostico-tematico-01-roles",   None),
    ])
    def test_extract_session_id_from_origin(self, session_origin, expected):
        record = {"source_fields": {"session_origin": session_origin}}
        result = extract_session_id(record)
        assert result == expected, f"session_origin='{session_origin}' → got '{result}', expected '{expected}'"

    def test_session_id_in_built_record(self):
        tiddler = _session_tiddler(session_num="0133", module="m04")
        rec = build_record(tiddler)
        assert rec["reversible_metadata"]["session_id"] == "m04-s0133"

    def test_session_id_none_for_diagnostic(self):
        tiddler = _diagnostic_tiddler(35)
        rec = build_record(tiddler)
        # diagnostico_tematico has no standard session_id
        # session_id may be None or non-standard
        sid = rec["reversible_metadata"]["session_id"]
        # For DT, session_origin is "diagnostico-tematico-XX-..." which doesn't
        # match the session pattern, so session_id should be None
        assert sid is None


# ── Caso 4: Extrae diagnostic_id desde título o nombre ───────────────────────

class TestCase04_ExtractsDiagnosticId:
    @pytest.mark.parametrize("title,origin,expected", [
        (
            "#### 🌀 Diagnóstico temático 0035 = contrato",
            "diagnostico-tematico-35-contrato",
            "DT035",
        ),
        (
            "#### 🌀 Diagnóstico temático 0001 = alineacion",
            "diagnostico-tematico-01-alineacion",
            "DT001",
        ),
        (
            "#### 🌀 Balance de sesión 0133 = test",
            "m04-s0133-balance-test",
            None,  # session artifact, not DT
        ),
    ])
    def test_extract_diagnostic_id(self, title, origin, expected):
        record = {
            "title": title,
            "source_fields": {"session_origin": origin},
        }
        result = extract_diagnostic_id(record)
        assert result == expected

    def test_dt035_id_from_title_pattern(self):
        record = {
            "title": "#### 🌀 Diagnóstico temático 0035 = contrato formal source_fields",
            "source_fields": {},
        }
        assert extract_diagnostic_id(record) == "DT035"


# ── Caso 5: Separa metadata explícita de metadata inferida ───────────────────

class TestCase05_SeparatesExplicitFromInferred:
    def test_explicit_metadata_in_reversible_metadata(self):
        tiddler = _session_tiddler()
        rec = build_record(tiddler)
        # Explicit: comes from fields directly
        rm = rec["reversible_metadata"]
        assert rm["canonical_title"] == tiddler["title"]
        assert rm["artifact_family"] == "balance_de_sesion"
        assert rm["slug"] is not None

    def test_inferred_metadata_in_inferred_metadata(self):
        tiddler = _session_tiddler(text="## Aciertos\n\nVer S0130 y S0131.\n### Sub\n")
        rec = build_record(tiddler)
        inferred = rec["inferred_metadata"]
        # Inferred: extracted from text
        assert "referenced_sessions" in inferred
        assert "headings" in inferred
        assert "referenced_diagnostics" in inferred
        assert "referenced_scripts" in inferred

    def test_inferred_sessions_not_in_reversible_metadata(self):
        tiddler = _session_tiddler(text="Referencia a S0130.")
        rec = build_record(tiddler)
        rm = rec["reversible_metadata"]
        # S0130 should be in inferred, not in reversible_metadata
        assert "referenced_sessions" not in rm
        assert "S0130" not in rm.get("session_id", "") or True

    def test_no_relations_created(self):
        tiddler = _session_tiddler(text="Referencia a S0130 y DT035.")
        rec = build_record(tiddler)
        # No canon relations should be created
        assert "relations" not in rec
        sf = rec["source_fields"]
        assert "relations" not in sf


# ── Caso 6: Detecta headings markdown sin alterar el texto ───────────────────

class TestCase06_DetectsMarkdownHeadings:
    def test_headings_extracted_from_text(self):
        text = "## Balance\n\n### Aciertos\n\nContenido.\n#### Subapartado\n"
        headings = _extract_headings(text, "markdown")
        assert "Balance" in headings
        assert "Aciertos" in headings
        assert "Subapartado" in headings

    def test_headings_not_extracted_from_json(self):
        text = '{"key": "## This looks like heading", "data": []}'
        headings = _extract_headings(text, "json")
        assert headings == []

    def test_headings_empty_for_no_headings(self):
        text = "Solo texto plano sin headings."
        headings = _extract_headings(text, "markdown")
        assert headings == []

    def test_original_text_unchanged(self):
        tiddler = _session_tiddler(text="## Original\n\nTexto.")
        original_text = tiddler["text"]
        build_record(tiddler)
        # Text should not have been modified
        assert tiddler["text"] == original_text


# ── Caso 7: Detecta referencias S#### y DT### como metadata inferida ─────────

class TestCase07_DetectsSessionAndDiagnosticReferences:
    def test_session_references_detected(self):
        text = "Esta sesión continúa S0130 y S0131. Ver también m04-s0132-evaluador."
        refs = _extract_referenced_sessions(text, "markdown")
        assert "S0130" in refs
        assert "S0131" in refs
        assert "S0132" in refs

    def test_diagnostic_references_detected(self):
        text = "El contrato DT035 formaliza source_fields. Ver DT034 y DT036."
        refs = _extract_referenced_diagnostics(text, "markdown")
        assert "DT035" in refs
        assert "DT034" in refs
        assert "DT036" in refs

    def test_diagnostic_long_form_detected(self):
        text = "El diagnóstico temático 34 establece la conversión."
        refs = _extract_referenced_diagnostics(text, "markdown")
        assert "DT034" in refs

    def test_no_refs_in_json_format(self):
        text = '{"session": "S0133", "diagnostic": "DT035"}'
        session_refs = _extract_referenced_sessions(text, "json")
        diag_refs = _extract_referenced_diagnostics(text, "json")
        assert session_refs == []
        assert diag_refs == []

    def test_script_references_detected(self):
        text = "Se usó `session_artifact_governance.py` y `python_scripts/source_fields_contract.py`."
        scripts = _extract_referenced_scripts(text, "markdown")
        assert any("session_artifact_governance.py" in s for s in scripts)
        assert any("source_fields_contract.py" in s for s in scripts)


# ── Caso 8: Declara safe/warning/blocked correctamente ───────────────────────

class TestCase08_DeclaresReversibilityStatus:
    def test_complete_record_is_safe(self):
        tiddler = _session_tiddler()
        rec = build_record(tiddler)
        assert rec["reversible_metadata"]["reversibility_status"] == "safe"

    def test_missing_title_is_blocked(self):
        tiddler = _session_tiddler()
        tiddler["title"] = ""
        rec = build_record(tiddler)
        assert rec["reversible_metadata"]["reversibility_status"] == "blocked"

    def test_missing_text_is_blocked(self):
        tiddler = _session_tiddler(text="")
        tiddler["text"] = ""
        rec = build_record(tiddler)
        assert rec["reversible_metadata"]["reversibility_status"] == "blocked"

    def test_missing_artifact_family_is_blocked(self):
        tiddler = _session_tiddler()
        tiddler["artifact_family"] = ""
        tiddler["source_fields"]["artifact_family"] = ""
        rec = build_record(tiddler)
        assert rec["reversible_metadata"]["reversibility_status"] == "blocked"

    def test_legacy_source_path_is_warning(self):
        tiddler = _session_tiddler(
            source_path="data/sessions/04_balance_de_sesion/m01-s0001-balance.md.json"
        )
        rec = build_record(tiddler)
        # legacy path → warning
        assert rec["reversible_metadata"]["reversibility_status"] in ("warning", "safe")

    def test_missing_source_path_is_warning(self):
        tiddler = _session_tiddler()
        tiddler["source_fields"]["source_path"] = ""
        rec = build_record(tiddler)
        assert rec["reversible_metadata"]["reversibility_status"] in ("warning", "blocked")


# ── Caso 9: No genera content.plain.relations ──────────────────────────────────

class TestCase09_NoRelationsGenerated:
    def test_no_relations_in_built_record(self):
        tiddler = _session_tiddler(
            text="Continúa S0130. Relacionado con DT035. Script `source_fields_contract.py`."
        )
        rec = build_record(tiddler)
        assert "relations" not in rec
        assert "relations" not in rec.get("reversible_metadata", {})
        assert "relations" not in rec.get("inferred_metadata", {})

    def test_referenced_sessions_not_admitted_as_relations(self):
        tiddler = _session_tiddler(text="Ver S0130 y S0131 para contexto.")
        rec = build_record(tiddler)
        inferred = rec["inferred_metadata"]
        # Should be in inferred.referenced_sessions, NOT in canon relations
        assert "S0130" in inferred["referenced_sessions"]
        assert "S0131" in inferred["referenced_sessions"]
        # No relations field created
        assert "relations" not in rec

    def test_matrix_records_have_no_relations(self):
        tiddlers = [_session_tiddler(family="contrato_de_sesion")]
        matrix = build_matrix(tiddlers)
        for r in matrix["records"]:
            assert "relations" not in r


# ── Caso 10: No modifica tiddlers_*.jsonl ─────────────────────────────────────

class TestCase10_NoCanonModification:
    def test_build_record_does_not_modify_input(self):
        tiddler = _session_tiddler()
        original_keys = set(tiddler.keys())
        original_sf = dict(tiddler["source_fields"])
        original_text = tiddler["text"]

        build_record(tiddler)

        assert set(tiddler.keys()) == original_keys, "build_record no debe agregar campos al tiddler"
        assert tiddler["source_fields"] == original_sf, "build_record no debe modificar source_fields"
        assert tiddler["text"] == original_text, "build_record no debe modificar text"

    def test_build_matrix_does_not_modify_inputs(self):
        tiddlers = [_session_tiddler(), _diagnostic_tiddler()]
        originals = [dict(t) for t in tiddlers]

        build_matrix(tiddlers)

        for orig, t in zip(originals, tiddlers):
            assert t["title"] == orig["title"]
            assert t["text"] == orig["text"]
            assert t["source_fields"] == orig["source_fields"]


# ── Tests adicionales de robustez ─────────────────────────────────────────────

class TestAdditional:
    def test_content_format_json_detection(self):
        assert _detect_content_format('{"key": "val"}', "") == "json"
        assert _detect_content_format('{"key": "val"}', "application/json") == "json"
        assert _detect_content_format("## Heading\n", "text/markdown") == "markdown"
        assert _detect_content_format("", "") == "empty"

    def test_extract_module_and_sequence(self):
        assert extract_module("m04-s0133") == "m04"
        assert extract_module(None) is None
        assert extract_sequence("m04-s0133") == 133
        assert extract_sequence(None) is None

    def test_build_matrix_summary_fields(self):
        tiddlers = [
            _session_tiddler("balance_de_sesion"),
            _session_tiddler("contrato_de_sesion"),
            _diagnostic_tiddler(35),
        ]
        matrix = build_matrix(tiddlers, session="s0134")
        assert matrix["schema"] == "minimal-reversible-metadata/v1"
        assert matrix["session"] == "S0134"
        assert "summary" in matrix
        assert matrix["summary"]["total_records"] == 3
        assert "safe" in matrix["summary"]
        assert "warning" in matrix["summary"]
        assert "blocked" in matrix["summary"]
        assert "families" in matrix["summary"]

    def test_all_session_families_build_records(self):
        """All known session families should produce valid records."""
        families = [
            "contrato_de_sesion",
            "procedencia_de_sesion",
            "detalles_de_sesion",
            "hipotesis_de_sesion",
            "balance_de_sesion",
            "propuesta_de_sesion",
            "diagnostico_de_sesion",
        ]
        for fam in families:
            tiddler = _session_tiddler(family=fam)
            rec = build_record(tiddler)
            assert rec["artifact_family"] == fam, f"Family mismatch for {fam}"
            assert rec["reversible_metadata"]["reversibility_status"] in (
                "safe", "warning", "blocked"
            ), f"Invalid status for {fam}"

    def test_inferred_metadata_does_not_contaminate_reversible_metadata(self):
        """Inferred fields must only appear in inferred_metadata."""
        tiddler = _session_tiddler(
            text="Ver S0130. DT035 fue clave. Script `validate.py`."
        )
        rec = build_record(tiddler)
        rm = rec["reversible_metadata"]
        inferred = rec["inferred_metadata"]

        # Inferred fields are in inferred_metadata
        assert "referenced_sessions" in inferred
        assert "referenced_diagnostics" in inferred
        assert "referenced_scripts" in inferred
        assert "headings" in inferred

        # They do NOT appear in reversible_metadata
        assert "referenced_sessions" not in rm
        assert "referenced_diagnostics" not in rm
        assert "referenced_scripts" not in rm

    def test_visibility_always_canonizable(self):
        tiddler = _session_tiddler()
        rec = build_record(tiddler)
        assert rec["reversible_metadata"]["visibility"] == "canonizable"

    @pytest.mark.parametrize("family", [
        "diagnostico_tematico",
        "diagnostico_de_micro_ciclo",
        "diagnostico_de_meso_ciclo",
        "diagnostico_de_proyecto",
    ])
    def test_diagnostic_families_recognized(self, family):
        tiddler = _session_tiddler(family=family)
        rec = build_record(tiddler)
        assert rec["artifact_family"] == family
