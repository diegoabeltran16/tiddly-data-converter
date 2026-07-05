"""tests/test_source_fields_contract.py — S0133

Tests del contrato operativo de source_fields por artifact_family (DT035 v1).

Cubre los 12 casos mínimos obligatorios definidos en S0133 §11.

Ejecutar:
    python3 -m pytest tests/test_source_fields_contract.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

from source_fields_contract import (
    ERROR,
    WARNING,
    CODE_MISSING_SOURCE_FIELDS,
    CODE_SOURCE_FIELDS_NOT_DICT,
    CODE_MISSING_BASELINE_FIELD,
    CODE_MISSING_DT035_FIELD,
    CODE_MISSING_FAMILY_DECLARED_FIELD,
    CODE_FORBIDDEN_FIELD,
    CODE_LEGACY_FIELD,
    CODE_INVALID_CANONICAL_STATUS,
    CODE_UNSAFE_SOURCE_PATH,
    CODE_FAMILY_MISMATCH,
    CODE_UNKNOWN_ARTIFACT_FAMILY,
    CODE_ARBITRARY_EXTENSION_FIELD,
    CODE_SOURCE_FIELDS_NOT_FLAT,
    validate_source_fields,
    BASELINE_REQUIRED_FIELDS,
    DT035_MINIMUM_COMMON_FIELDS,
    FORBIDDEN_FIELDS,
    LEGACY_FIELDS,
    FAMILY_DECLARED_FIELDS,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _minimal_source_fields() -> dict:
    """source_fields mínimo válido (baseline)."""
    return {
        "artifact_family": "balance_de_sesion",
        "canonical_status": "candidate_not_admitted",
        "session_origin": "m04-s0133-source-fields-operativo",
        "source_path": "data/out/local/sessions/04_balance_de_sesion/m04-s0133-balance.md.json",
        "provenance_ref": "data/out/local/sessions/04_balance_de_sesion/m04-s0133-balance.md.json",
    }


def _record_with_sf(sf: dict) -> dict:
    return {
        "title": "Test record",
        "artifact_family": sf.get("artifact_family", ""),
        "source_fields": sf,
    }


# ── Caso 1: Acepta source_fields mínimo válido ────────────────────────────────

class TestCase01_AcceptsMinimalValid:
    def test_baseline_valid_no_issues(self):
        sf = _minimal_source_fields()
        record = _record_with_sf(sf)
        issues = validate_source_fields(record, level="baseline")
        errors = [i for i in issues if i.severity == ERROR]
        assert errors == [], f"Errores inesperados: {errors}"

    def test_baseline_valid_allows_warnings(self):
        """No se exigen cero warnings, solo cero errores."""
        sf = _minimal_source_fields()
        record = _record_with_sf(sf)
        issues = validate_source_fields(record, level="baseline")
        # Puede haber warnings (campo arbitrario, etc.) pero no errores
        errors = [i for i in issues if i.severity == ERROR]
        assert errors == []

    def test_admitted_status_is_valid(self):
        sf = _minimal_source_fields()
        sf["canonical_status"] = "local_admitted"
        record = _record_with_sf(sf)
        issues = validate_source_fields(record)
        cs_errors = [i for i in issues if i.code == CODE_INVALID_CANONICAL_STATUS and i.severity == ERROR]
        assert cs_errors == []


# ── Caso 2: Rechaza source_fields ausente cuando artifact_family lo requiere ──

class TestCase02_RejectsMissingSourceFields:
    def test_known_family_without_sf_emits_warning(self):
        record = {
            "title": "Test",
            "artifact_family": "balance_de_sesion",
        }
        issues = validate_source_fields(record)
        codes = [i.code for i in issues]
        assert CODE_MISSING_SOURCE_FIELDS in codes

    def test_unknown_family_without_sf_no_sf001(self):
        """Si no hay artifact_family conocida, no se exige source_fields."""
        record = {
            "title": "Test",
            "source_fields": None,
        }
        issues = validate_source_fields(record)
        codes = [i.code for i in issues]
        assert CODE_MISSING_SOURCE_FIELDS not in codes

    def test_relation_candidate_without_sf_emits_warning(self):
        record = {
            "title": "RC test",
            "artifact_family": "relation_candidate",
        }
        issues = validate_source_fields(record)
        codes = [i.code for i in issues]
        assert CODE_MISSING_SOURCE_FIELDS in codes


# ── Caso 3: Rechaza source_fields que no sea objeto ──────────────────────────

class TestCase03_RejectsNonDictSourceFields:
    @pytest.mark.parametrize("bad_value", [
        "string_value",
        42,
        3.14,
        None,
        ["list", "item"],
        True,
    ])
    def test_non_dict_source_fields_emits_error(self, bad_value):
        record = {
            "title": "Test",
            "artifact_family": "contrato_de_sesion",
            "source_fields": bad_value,
        }
        if bad_value is None:
            # None es "ausente" → SF001 warning, no SF002
            issues = validate_source_fields(record)
            codes = [i.code for i in issues]
            assert CODE_SOURCE_FIELDS_NOT_DICT not in codes
        else:
            issues = validate_source_fields(record)
            errors = [i for i in issues if i.severity == ERROR]
            codes = [i.code for i in errors]
            assert CODE_SOURCE_FIELDS_NOT_DICT in codes


# ── Caso 4: Rechaza campos reservados dentro de source_fields ─────────────────

class TestCase04_RejectsForbiddenFields:
    @pytest.mark.parametrize("forbidden_field,value", [
        ("schema_version", "v0"),
        ("id", "some-uuid"),
        ("key", "some-key"),
        ("title", "some title"),
        ("text", "some text"),
        ("relations", "[]"),
        ("content", "content value"),
        ("canonical_slug", "some-slug"),
        ("version_id", "sha256:abc"),
        ("source_fields", "{}"),
        ("document_id", "doc-123"),
    ])
    def test_forbidden_field_emits_error(self, forbidden_field, value):
        sf = _minimal_source_fields()
        sf[forbidden_field] = value
        record = _record_with_sf(sf)
        issues = validate_source_fields(record, strict_forbidden=True)
        codes = [i.code for i in issues if i.severity == ERROR]
        assert CODE_FORBIDDEN_FIELD in codes, (
            f"Campo prohibido '{forbidden_field}' no fue detectado. "
            f"Issues: {[i.code for i in issues]}"
        )

    def test_source_tags_forbidden(self):
        sf = _minimal_source_fields()
        sf["source_tags"] = "tag1 tag2"
        record = _record_with_sf(sf)
        issues = validate_source_fields(record, strict_forbidden=True)
        codes = [i.code for i in issues if i.severity == ERROR]
        assert CODE_FORBIDDEN_FIELD in codes

    def test_normalized_tags_forbidden(self):
        sf = _minimal_source_fields()
        sf["normalized_tags"] = "tag1 tag2"
        record = _record_with_sf(sf)
        issues = validate_source_fields(record, strict_forbidden=True)
        codes = [i.code for i in issues if i.severity == ERROR]
        assert CODE_FORBIDDEN_FIELD in codes


# ── Caso 5: Rechaza campos derivados dentro de source_fields ──────────────────

class TestCase05_RejectsDerivedFields:
    """Los campos derivados ya están cubiertos por FORBIDDEN_FIELDS en el contrato."""

    def test_role_primary_forbidden(self):
        sf = _minimal_source_fields()
        sf["role_primary"] = "policy"
        record = _record_with_sf(sf)
        issues = validate_source_fields(record, strict_forbidden=True)
        codes = [i.code for i in issues if i.severity == ERROR]
        assert CODE_FORBIDDEN_FIELD in codes

    def test_taxonomy_path_forbidden(self):
        sf = _minimal_source_fields()
        sf["taxonomy_path"] = "canon/sesion"
        record = _record_with_sf(sf)
        issues = validate_source_fields(record, strict_forbidden=True)
        codes = [i.code for i in issues if i.severity == ERROR]
        assert CODE_FORBIDDEN_FIELD in codes

    def test_semantic_text_forbidden(self):
        sf = _minimal_source_fields()
        sf["semantic_text"] = "some semantic text"
        record = _record_with_sf(sf)
        issues = validate_source_fields(record, strict_forbidden=True)
        codes = [i.code for i in issues if i.severity == ERROR]
        assert CODE_FORBIDDEN_FIELD in codes


# ── Caso 6: Acepta campos extendidos con prefijo x_ ──────────────────────────

class TestCase06_AcceptsXPrefixFields:
    def test_x_prefix_field_no_error(self):
        sf = _minimal_source_fields()
        sf["x_review_note"] = "Revisado manualmente"
        sf["x_validation_context"] = "S0133"
        sf["x_source_family_detail"] = "balance intermedio"
        record = _record_with_sf(sf)
        issues = validate_source_fields(record, level="baseline")
        arb_errors = [
            i for i in issues
            if i.code == CODE_ARBITRARY_EXTENSION_FIELD and i.severity == ERROR
        ]
        assert arb_errors == []

    def test_x_underscore_prefix_accepted(self):
        sf = _minimal_source_fields()
        sf["x_custom_field_123"] = "valor"
        record = _record_with_sf(sf)
        issues = validate_source_fields(record)
        arb_errs = [i for i in issues if i.code == CODE_ARBITRARY_EXTENSION_FIELD]
        assert arb_errs == []


# ── Caso 7: Rechaza campos arbitrarios sin prefijo x_ ────────────────────────

class TestCase07_RejectsArbitraryUnprefixedFields:
    def test_arbitrary_field_without_x_prefix_emits_warning(self):
        sf = _minimal_source_fields()
        sf["mi_campo_raro"] = "valor"
        record = _record_with_sf(sf)
        issues = validate_source_fields(record)
        codes = [i.code for i in issues]
        assert CODE_ARBITRARY_EXTENSION_FIELD in codes

    def test_arbitrary_field_not_an_error_by_default(self):
        """Por defecto es WARNING, no ERROR."""
        sf = _minimal_source_fields()
        sf["campo_sin_prefijo"] = "valor"
        record = _record_with_sf(sf)
        issues = validate_source_fields(record)
        arb_errs = [i for i in issues if i.code == CODE_ARBITRARY_EXTENSION_FIELD and i.severity == ERROR]
        assert arb_errs == []


# ── Caso 8: Rechaza source_path absoluto ─────────────────────────────────────

class TestCase08_RejectsAbsoluteSourcePath:
    def test_absolute_path_emits_error(self):
        sf = _minimal_source_fields()
        sf["source_path"] = "/home/user/data/sessions/file.json"
        record = _record_with_sf(sf)
        issues = validate_source_fields(record)
        errors = [i for i in issues if i.code == CODE_UNSAFE_SOURCE_PATH and i.severity == ERROR]
        assert errors, "Se esperaba error SF009 por ruta absoluta"

    def test_windows_absolute_path_emits_error(self):
        sf = _minimal_source_fields()
        sf["source_path"] = "/repositorios/tiddly/data/sessions/file.json"
        record = _record_with_sf(sf)
        issues = validate_source_fields(record)
        errors = [i for i in issues if i.code == CODE_UNSAFE_SOURCE_PATH and i.severity == ERROR]
        assert errors


# ── Caso 9: Rechaza source_path con .. ───────────────────────────────────────

class TestCase09_RejectsPathTraversal:
    def test_dotdot_in_path_emits_error(self):
        sf = _minimal_source_fields()
        sf["source_path"] = "data/out/local/sessions/../../../etc/passwd"
        record = _record_with_sf(sf)
        issues = validate_source_fields(record)
        errors = [i for i in issues if i.code == CODE_UNSAFE_SOURCE_PATH and i.severity == ERROR]
        assert errors, "Se esperaba error SF009 por path traversal con .."

    def test_single_dotdot_emits_error(self):
        sf = _minimal_source_fields()
        sf["source_path"] = "data/out/../local/sessions/file.json"
        record = _record_with_sf(sf)
        issues = validate_source_fields(record)
        errors = [i for i in issues if i.code == CODE_UNSAFE_SOURCE_PATH and i.severity == ERROR]
        assert errors


# ── Caso 10: Rechaza mismatch entre artifact_family superior y source_fields ──

class TestCase10_RejectsFamilyMismatch:
    def test_family_mismatch_emits_error(self):
        sf = _minimal_source_fields()
        sf["artifact_family"] = "contrato_de_sesion"
        record = {
            "title": "Test",
            "artifact_family": "balance_de_sesion",  # diferente del source_fields
            "source_fields": sf,
        }
        issues = validate_source_fields(record)
        errors = [i for i in issues if i.code == CODE_FAMILY_MISMATCH]
        assert errors, "Se esperaba error SF010 por discrepancia de artifact_family"

    def test_family_match_no_sf010(self):
        sf = _minimal_source_fields()
        sf["artifact_family"] = "balance_de_sesion"
        record = {
            "title": "Test",
            "artifact_family": "balance_de_sesion",
            "source_fields": sf,
        }
        issues = validate_source_fields(record)
        errors = [i for i in issues if i.code == CODE_FAMILY_MISMATCH]
        assert errors == []

    def test_alias_match_no_sf010(self):
        """Alias como 'balance' debe coincidir con 'balance_de_sesion'."""
        sf = _minimal_source_fields()
        sf["artifact_family"] = "balance"
        record = {
            "title": "Test",
            "artifact_family": "balance_de_sesion",
            "source_fields": sf,
        }
        issues = validate_source_fields(record)
        errors = [i for i in issues if i.code == CODE_FAMILY_MISMATCH]
        assert errors == []


# ── Caso 11: Valida correctamente familias diagnósticas ──────────────────────

class TestCase11_DiagnosticFamiliesValidated:
    @pytest.mark.parametrize("family", [
        "diagnostico_tematico",
        "diagnostico_de_sesion",
        "diagnostico_de_micro_ciclo",
        "diagnostico_de_meso_ciclo",
        "diagnostico_de_proyecto",
    ])
    def test_diagnostic_family_known(self, family):
        sf = _minimal_source_fields()
        sf["artifact_family"] = family
        record = {
            "title": "Test diagnostic",
            "artifact_family": family,
            "source_fields": sf,
        }
        issues = validate_source_fields(record, level="baseline")
        unknown = [i for i in issues if i.code == CODE_UNKNOWN_ARTIFACT_FAMILY]
        assert unknown == [], f"Familia '{family}' no debería ser desconocida"

    def test_diagnostico_tematico_declared_fields_at_family_level(self):
        sf = _minimal_source_fields()
        sf["artifact_family"] = "diagnostico_tematico"
        sf["declared_central_question"] = "¿Cómo se valida source_fields?"
        sf["declared_analyzed_families_json"] = '["balance_de_sesion", "contrato_de_sesion"]'
        sf["declared_recommendations_json"] = '["Adoptar DT035 v1"]'
        record = {
            "title": "DT035 test",
            "artifact_family": "diagnostico_tematico",
            "source_fields": sf,
        }
        issues = validate_source_fields(record, level="family")
        family_errors = [
            i for i in issues if i.code == CODE_MISSING_FAMILY_DECLARED_FIELD
        ]
        assert family_errors == [], f"Errores inesperados en family: {family_errors}"

    def test_diagnostico_tematico_missing_declared_emits_warning(self):
        sf = _minimal_source_fields()
        sf["artifact_family"] = "diagnostico_tematico"
        # No incluye declared_central_question ni otros
        record = {
            "title": "DT sin declarados",
            "artifact_family": "diagnostico_tematico",
            "source_fields": sf,
        }
        issues = validate_source_fields(record, level="family")
        family_warnings = [
            i for i in issues if i.code == CODE_MISSING_FAMILY_DECLARED_FIELD
        ]
        assert len(family_warnings) >= 3, (
            f"Se esperaban al menos 3 warnings por campos declared_ faltantes; "
            f"se obtuvieron: {[(i.code, i.field) for i in family_warnings]}"
        )


# ── Caso 12: Valida correctamente relation_candidate sin admitirlo al canon ───

class TestCase12_RelationCandidateNotAdmitted:
    def test_relation_candidate_valid_not_admitted_status(self):
        sf = {
            "artifact_family": "relation_candidate",
            "canonical_status": "candidate_not_admitted",
            "session_origin": "m04-s0133",
            "source_path": "data/out/local/pipeline/relations_candidates/rc.jsonl",
            "provenance_ref": "data/out/local/pipeline/relations_candidates/rc.jsonl",
            "declared_source_tiddler_id": "uuid-source-123",
            "declared_target_tiddler_id": "uuid-target-456",
            "declared_relation_type": "referencias_a",
        }
        record = {
            "title": "RC test",
            "artifact_family": "relation_candidate",
            "source_fields": sf,
        }
        issues = validate_source_fields(record, level="family")
        errors = [i for i in issues if i.severity == ERROR]
        assert errors == [], f"Errores inesperados en relation_candidate: {errors}"

    def test_relation_candidate_rejected_status_invalid(self):
        """'local_admitted' es estado válido, pero 'invented' no lo es."""
        sf = _minimal_source_fields()
        sf["artifact_family"] = "relation_candidate"
        sf["canonical_status"] = "invented_status_xyz"
        record = {
            "title": "RC test invalid status",
            "artifact_family": "relation_candidate",
            "source_fields": sf,
        }
        issues = validate_source_fields(record)
        cs_issues = [i for i in issues if i.code == CODE_INVALID_CANONICAL_STATUS]
        assert cs_issues, "Se esperaba SF008 por estado inventado"

    def test_relation_candidate_no_canon_modification(self):
        """validate_source_fields no modifica el record (non-destructive)."""
        sf = _minimal_source_fields()
        sf["artifact_family"] = "relation_candidate"
        record = {
            "title": "RC test",
            "artifact_family": "relation_candidate",
            "source_fields": dict(sf),
        }
        original_sf = dict(sf)
        original_record_keys = set(record.keys())

        validate_source_fields(record, level="family")

        # Verificar no modificación
        assert set(record.keys()) == original_record_keys
        assert record["source_fields"] == original_sf, "validate_source_fields NO debe modificar el record"


# ── Tests adicionales de robustez ─────────────────────────────────────────────

class TestAdditional:
    def test_source_fields_with_nested_dict_emits_sf013(self):
        record = {
            "title": "Test",
            "artifact_family": "contrato_de_sesion",
            "source_fields": {
                "artifact_family": "contrato_de_sesion",
                "canonical_status": "candidate_not_admitted",
                "session_origin": "m04-s0133",
                "source_path": "data/out/local/sessions/00_contratos/test.json",
                "provenance_ref": "data/out/local/sessions/00_contratos/test.json",
                "nested_object": {"key": "value"},  # violación map[string]string
            },
        }
        issues = validate_source_fields(record)
        codes = [i.code for i in issues if i.severity == ERROR]
        assert CODE_SOURCE_FIELDS_NOT_FLAT in codes

    def test_legacy_fields_emit_warning_not_error_by_default(self):
        sf = _minimal_source_fields()
        for legacy_field in ("type", "tags", "created", "modified"):
            sf[legacy_field] = "valor_legado"
        record = _record_with_sf(sf)
        issues = validate_source_fields(record, legacy_as_error=False)
        legacy_errors = [i for i in issues if i.code == CODE_LEGACY_FIELD and i.severity == ERROR]
        assert legacy_errors == [], "Los campos legados deben ser WARNING, no ERROR por defecto"

    def test_legacy_fields_emit_error_with_legacy_as_error(self):
        sf = _minimal_source_fields()
        sf["type"] = "text/markdown"
        record = _record_with_sf(sf)
        issues = validate_source_fields(record, legacy_as_error=True)
        legacy_errors = [i for i in issues if i.code == CODE_LEGACY_FIELD and i.severity == ERROR]
        assert legacy_errors, "Con legacy_as_error=True, 'type' debe emitir ERROR"

    def test_dt035_level_warns_missing_extended_fields(self):
        sf = _minimal_source_fields()  # solo tiene los 5 baseline
        record = _record_with_sf(sf)
        issues = validate_source_fields(record, level="dt035")
        dt035_warnings = [i for i in issues if i.code == CODE_MISSING_DT035_FIELD]
        # Esperamos warnings por los campos DT035 extendidos ausentes
        assert len(dt035_warnings) >= 1, (
            "Nivel dt035 debe emitir al menos 1 warning por campos extendidos ausentes"
        )

    def test_valid_dt035_complete_record_no_errors(self):
        """Registro completo DT035 v1 sin errores."""
        sf = {
            "artifact_family": "contrato_de_sesion",
            "canonical_status": "candidate_not_admitted",
            "session_origin": "m04-s0133",
            "source_path": "data/out/local/sessions/00_contratos/m04-s0133-contrato.md.json",
            "provenance_ref": "data/out/local/sessions/00_contratos/m04-s0133-contrato.md.json",
            "document_key": "data/out/local/sessions/m04-s0133-source-fields",
            "source_title": "Contrato S0133 — source_fields operativo",
            "source_type": "text/markdown",
            "source_created": "20260601000000000",
            "source_modified": "20260601000000000",
            "source_tags_json": '["sesion", "contrato_de_sesion", "m04", "s0133"]',
        }
        record = {
            "title": "Test contrato completo",
            "artifact_family": "contrato_de_sesion",
            "source_fields": sf,
        }
        issues = validate_source_fields(record, level="dt035")
        errors = [i for i in issues if i.severity == ERROR]
        assert errors == [], f"Registro DT035 completo no debe tener errores: {errors}"

    def test_record_without_source_fields_and_no_known_family(self):
        """Un registro sin artifact_family conocida no requiere source_fields."""
        record = {"title": "Regular tiddler without family"}
        issues = validate_source_fields(record)
        assert issues == []

    def test_empty_source_fields_dict_emits_baseline_errors(self):
        """source_fields vacío debe reportar todos los campos baseline faltantes."""
        record = {
            "title": "Empty SF",
            "artifact_family": "balance_de_sesion",
            "source_fields": {},
        }
        issues = validate_source_fields(record)
        baseline_errors = [i for i in issues if i.code == CODE_MISSING_BASELINE_FIELD]
        assert len(baseline_errors) == len(BASELINE_REQUIRED_FIELDS), (
            f"Se esperaban {len(BASELINE_REQUIRED_FIELDS)} errores baseline, "
            f"se obtuvieron {len(baseline_errors)}"
        )

    @pytest.mark.parametrize("family,required_fields", [
        ("contrato_de_sesion", {"declared_objective", "declared_inputs_json",
                                "declared_outputs_json", "declared_constraints_json"}),
        ("propuesta_de_sesion", {"declared_next_step", "declared_options_json",
                                 "declared_blockers_json"}),
        ("hipotesis_de_sesion", {"declared_hypotheses_json", "declared_verdicts_json"}),
    ])
    def test_family_declared_fields_coverage(self, family, required_fields):
        """Cada familia tiene sus campos declared_ definidos en el contrato."""
        contract_fields = FAMILY_DECLARED_FIELDS.get(family, frozenset())
        for req in required_fields:
            assert req in contract_fields, (
                f"Campo '{req}' no está en FAMILY_DECLARED_FIELDS['{family}']"
            )

    def test_all_known_session_families_have_declared_fields(self):
        """Todas las familias de sesión estándar tienen al menos un declared_ field."""
        session_families = [
            "contrato_de_sesion",
            "procedencia_de_sesion",
            "detalles_de_sesion",
            "hipotesis_de_sesion",
            "balance_de_sesion",
            "propuesta_de_sesion",
            "diagnostico_de_sesion",
        ]
        for fam in session_families:
            assert fam in FAMILY_DECLARED_FIELDS, f"Familia '{fam}' no tiene FAMILY_DECLARED_FIELDS"
            assert len(FAMILY_DECLARED_FIELDS[fam]) > 0, (
                f"FAMILY_DECLARED_FIELDS['{fam}'] está vacío"
            )

    def test_source_path_pointing_to_canon_shard_rejected(self):
        sf = _minimal_source_fields()
        sf["source_path"] = "data/out/local/tiddlers_3.jsonl"
        record = _record_with_sf(sf)
        issues = validate_source_fields(record)
        canon_errors = [i for i in issues if i.code == CODE_UNSAFE_SOURCE_PATH and i.severity == ERROR]
        assert canon_errors, "source_path apuntando a tiddlers_*.jsonl debe emitir SF009 error"
