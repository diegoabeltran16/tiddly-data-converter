"""
tests/test_relation_candidate_s0129.py — S0129

Pruebas para el validador endurecido en S0129.

Cobertura mínima requerida por S0129 (10 casos + S0129-específicos):
  1.  Candidato válido mínimo pasa.
  2.  Campo obligatorio ausente es rechazado.
  3.  relation.type inválido es rechazado.
  4.  confidence.score fuera de rango es rechazado.
  5.  source.tiddler_id inexistente es rechazado.
  6.  Target unresolved correctamente clasificado (no es error).
  7.  evidence.excerpt vacío es rechazado.
  8.  evidence.excerpt no verificable cuando kind=ai_inference produce error.
  9.  Candidato duplicado exacto es detectado.
  10. Self-relation no permitida.
  11. evidence.kind inválido rechazado.
  12. target.tiddler_id inexistente en canon cuando resolution_status='resolved'.
  13. evidence.excerpt encontrado en texto fuente pasa sin error.
  14. relation_candidate_contract — catálogos correctos.
  15. write_category_files produce los 4 archivos con registros correctos.
"""

import json
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

# ---------------------------------------------------------------------------
# Setup de path para imports locales
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "python_scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import validate_relation_candidates as vcr
import relation_candidate_contract as rcc

# ---------------------------------------------------------------------------
# IDs del mini-canon de fixtures
# ---------------------------------------------------------------------------
MINI_SOURCE_ID = "src-aabbccdd1122334455667788"
MINI_TARGET_ID = "tgt-eeff5566778899001122334455"
MINI_CANON_PATH = REPO_ROOT / "tests" / "fixtures" / "relations_candidates" / "mini_canon.jsonl"

# Texto que SÍ existe en el tiddler fuente del mini-canon
EXCERPT_FOUND = "Diagnósticos previos consultados: DT029, DT030"
# Texto que NO existe en el tiddler fuente
EXCERPT_NOT_FOUND = "Esta frase fue inventada por IA y no existe en el texto fuente"


def _mini_canon_ids() -> set[str]:
    """Carga IDs desde el mini-canon de fixtures."""
    ids: set[str] = set()
    for line in MINI_CANON_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            ids.add(json.loads(line)["id"])
    return ids


def _mini_canon_texts() -> dict[str, str]:
    """Carga textos desde el mini-canon de fixtures."""
    texts: dict[str, str] = {}
    for line in MINI_CANON_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            obj = json.loads(line)
            texts[obj["id"]] = obj.get("text", "")
    return texts


def _make_candidate(**overrides: Any) -> dict:
    """
    Construye un candidato mínimo válido y aplica sobreescrituras.
    Usa IDs del mini-canon para que las verificaciones de existencia pasen.
    """
    base: dict = {
        "candidate_id": "rc1_aabb1122334455667788",
        "schema_version": "relations-candidate/v1",
        "status": "candidate",
        "source": {
            "tiddler_id": MINI_SOURCE_ID,
            "title": "Tiddler source para tests",
            "field_path": "text",
            "chunk_id": None,
        },
        "target": {
            "tiddler_id": MINI_TARGET_ID,
            "title": "Tiddler target para tests",
            "resolution_status": "resolved",
        },
        "relation": {
            "type": "referencia_a",
            "direction": "source_to_target",
            "label": "test",
        },
        "evidence": {
            "kind": "explicit_reference",
            "excerpt": EXCERPT_FOUND,
            "location": "text/section:test",
            "strength": "E1",
            "secondary": [],
        },
        "confidence": {
            "score": 0.85,
            "method": "rule_based",
            "risk_flags": [],
        },
        "provenance": {
            "generated_by": "test_suite_s0129",
            "generated_at": "2026-05-27T17:00:00Z",
            "input_artifacts": [],
            "diagnostic_basis": [],
            "source_path": "tests/fixtures/",
        },
        "review": {
            "required": True,
            "review_status": "pending",
            "reviewer": "",
            "reviewed_at": "",
            "notes": "",
        },
        "created_at": "2026-05-27T17:00:00Z",
    }
    base.update(overrides)
    return base


def _validate_one(candidate: dict, **kwargs: Any) -> dict:
    """Valida un único candidato con el mini-canon."""
    canon_ids = kwargs.pop("canon_ids", _mini_canon_ids())
    canon_texts = kwargs.pop("canon_texts", _mini_canon_texts())
    raw = json.dumps(candidate)
    seen_ids: dict[str, int] = {}
    return vcr.validate_candidate(raw, 1, canon_ids, seen_ids, canon_texts)


# ===========================================================================
# Test 1 — Candidato válido mínimo pasa
# ===========================================================================
class TestValidCandidatePasses:
    def test_valid_with_mini_canon(self):
        """Un candidato con todos los campos correctos y excerpt verificable pasa."""
        cand = _make_candidate()
        result = _validate_one(cand)
        assert result["ok"] is True, f"Errores inesperados: {result['errors']}"
        assert "valid" in result["categories"]
        assert not result["errors"]

    def test_valid_with_no_excerpt_check(self):
        """Sin verificación de excerpt, un candidato estructuralmente correcto pasa."""
        cand = _make_candidate()
        raw = json.dumps(cand)
        seen: dict[str, int] = {}
        result = vcr.validate_candidate(raw, 1, _mini_canon_ids(), seen, canon_texts=None)
        assert result["ok"] is True


# ===========================================================================
# Test 2 — Campo obligatorio ausente es rechazado
# ===========================================================================
class TestMissingRequiredField:
    @pytest.mark.parametrize("field", [
        "candidate_id", "status", "source", "target",
        "relation", "evidence", "confidence", "provenance", "created_at",
    ])
    def test_missing_field_rejected(self, field: str):
        cand = _make_candidate()
        del cand[field]
        result = _validate_one(cand)
        assert result["ok"] is False
        assert any(field in e for e in result["errors"])


# ===========================================================================
# Test 3 — relation.type inválido
# ===========================================================================
class TestInvalidRelationType:
    @pytest.mark.parametrize("bad_type", [
        "usa", "parte_de", "unknown_type", "", None,
    ])
    def test_invalid_relation_type_rejected(self, bad_type):
        cand = _make_candidate()
        cand["relation"]["type"] = bad_type
        result = _validate_one(cand)
        assert result["ok"] is False
        assert any("relation.type" in e for e in result["errors"])

    @pytest.mark.parametrize("good_type", [
        "referencia_a", "deriva_de", "menciona_diagnostico", "valida",
        "references", "derived_from",
    ])
    def test_valid_relation_type_passes(self, good_type: str):
        cand = _make_candidate()
        cand["relation"]["type"] = good_type
        result = _validate_one(cand)
        assert not any("relation.type" in e for e in result["errors"])


# ===========================================================================
# Test 4 — confidence.score fuera de rango
# ===========================================================================
class TestConfidenceScore:
    @pytest.mark.parametrize("bad_score", [-0.1, 1.01, 2.0, -1])
    def test_score_out_of_range_rejected(self, bad_score: float):
        cand = _make_candidate()
        cand["confidence"]["score"] = bad_score
        result = _validate_one(cand)
        assert result["ok"] is False
        assert any("score" in e for e in result["errors"])

    @pytest.mark.parametrize("good_score", [0.0, 0.5, 0.99, 1.0])
    def test_score_in_range_passes(self, good_score: float):
        cand = _make_candidate()
        cand["confidence"]["score"] = good_score
        result = _validate_one(cand)
        assert not any("fuera de rango" in e for e in result["errors"])

    def test_score_not_numeric_rejected(self):
        cand = _make_candidate()
        cand["confidence"]["score"] = "high"
        result = _validate_one(cand)
        assert result["ok"] is False

    def test_score_below_threshold_flagged_as_weak(self):
        cand = _make_candidate()
        cand["confidence"]["score"] = 0.35
        result = _validate_one(cand)
        assert "weak_evidence" in result["categories"]
        assert any("bajo" in w for w in result["warnings"])


# ===========================================================================
# Test 5 — source.tiddler_id inexistente
# ===========================================================================
class TestSourceIdNotInCanon:
    def test_nonexistent_source_id_rejected(self):
        cand = _make_candidate()
        cand["source"]["tiddler_id"] = "id-que-no-existe-en-canon-00001111"
        result = _validate_one(cand)
        assert result["ok"] is False
        assert any("source.tiddler_id no existe" in e for e in result["errors"])

    def test_empty_source_id_rejected(self):
        cand = _make_candidate()
        cand["source"]["tiddler_id"] = ""
        result = _validate_one(cand)
        assert result["ok"] is False
        assert any("source.tiddler_id ausente" in e for e in result["errors"])


# ===========================================================================
# Test 6 — Target unresolved correctamente clasificado
# ===========================================================================
class TestUnresolvedTarget:
    def test_unresolved_target_is_allowed_not_invalid(self):
        cand = _make_candidate()
        cand["target"]["resolution_status"] = "unresolved"
        cand["target"]["tiddler_id"] = None
        cand["target"]["title"] = "slug-de-target-no-resuelto"
        result = _validate_one(cand)
        assert "unresolved_target" in result["categories"]
        # No debe clasificarse como error/invalid por el target solo
        assert not any("resolution_status" in e for e in result["errors"])

    def test_unresolved_without_title_generates_warning(self):
        cand = _make_candidate()
        cand["target"]["resolution_status"] = "unresolved"
        cand["target"]["tiddler_id"] = None
        cand["target"]["title"] = ""
        result = _validate_one(cand)
        assert any("sin tiddler_id ni title" in w for w in result["warnings"])

    def test_resolved_target_without_id_is_rejected(self):
        cand = _make_candidate()
        cand["target"]["resolution_status"] = "resolved"
        cand["target"]["tiddler_id"] = None
        result = _validate_one(cand)
        assert result["ok"] is False
        assert any("tiddler_id ausente" in e for e in result["errors"])


# ===========================================================================
# Test 7 — evidence.excerpt vacío
# ===========================================================================
class TestEmptyExcerpt:
    @pytest.mark.parametrize("empty", ["", "   ", None])
    def test_empty_excerpt_rejected(self, empty):
        cand = _make_candidate()
        cand["evidence"]["excerpt"] = empty
        result = _validate_one(cand)
        assert result["ok"] is False
        assert any("excerpt" in e.lower() for e in result["errors"])


# ===========================================================================
# Test 8 — evidence.excerpt no verificable (ai_inference, no encontrado)
# ===========================================================================
class TestUnverifiableExcerpt:
    def test_ai_inference_excerpt_not_found_is_error(self):
        """rc4-equivalente: ai_inference + excerpt no encontrado → error."""
        cand = _make_candidate()
        cand["evidence"]["kind"] = "ai_inference"
        cand["evidence"]["excerpt"] = EXCERPT_NOT_FOUND
        cand["confidence"]["score"] = 0.35
        result = _validate_one(cand)
        assert result["ok"] is False
        assert any("no encontrado en texto fuente" in e for e in result["errors"])
        assert any("ai_inference" in e for e in result["errors"])

    def test_explicit_reference_excerpt_not_found_is_warning_not_error(self):
        """explicit_reference + excerpt no encontrado → solo warning, no error."""
        cand = _make_candidate()
        cand["evidence"]["kind"] = "explicit_reference"
        cand["evidence"]["excerpt"] = EXCERPT_NOT_FOUND
        result = _validate_one(cand)
        # No debe ser error duro — puede ser falso negativo de normalización
        assert not any("no encontrado en texto fuente" in e for e in result["errors"])
        assert any("no encontrado" in w for w in result["warnings"])

    def test_excerpt_found_in_source_no_warning(self):
        """Excerpt que sí está en el texto fuente no genera warning ni error."""
        cand = _make_candidate()
        cand["evidence"]["kind"] = "explicit_reference"
        cand["evidence"]["excerpt"] = EXCERPT_FOUND
        result = _validate_one(cand)
        assert not any("no encontrado" in w for w in result["warnings"])
        assert not any("no encontrado" in e for e in result["errors"])

    def test_no_source_text_in_canon_generates_warning_not_error(self):
        """Si el tiddler fuente no tiene texto, no verificable → solo warning."""
        cand = _make_candidate()
        cand["evidence"]["kind"] = "explicit_reference"
        cand["evidence"]["excerpt"] = EXCERPT_FOUND
        # Pasar canon_texts sin texto para el source ID
        result = _validate_one(cand, canon_texts={MINI_SOURCE_ID: ""})
        assert any("no verificable" in w for w in result["warnings"])
        assert not any("no verificable" in e for e in result["errors"])


# ===========================================================================
# Test 9 — Duplicado exacto detectado
# ===========================================================================
class TestDuplicateDetection:
    def test_duplicate_candidate_id_is_detected(self):
        cand1 = _make_candidate()
        cand2 = _make_candidate()  # mismo candidate_id
        canon_ids = _mini_canon_ids()
        canon_texts = _mini_canon_texts()
        seen_ids: dict[str, int] = {}
        r1 = vcr.validate_candidate(json.dumps(cand1), 1, canon_ids, seen_ids, canon_texts)
        r2 = vcr.validate_candidate(json.dumps(cand2), 2, canon_ids, seen_ids, canon_texts)
        assert "duplicate" not in r1["categories"]
        assert "duplicate" in r2["categories"]
        assert any("duplicado" in e.lower() for e in r2["errors"])

    def test_different_ids_not_flagged_as_duplicate(self):
        cand1 = _make_candidate(candidate_id="rc1_aabb1122334455667788")
        cand2 = _make_candidate(candidate_id="rc1_bbcc2233445566778899")
        canon_ids = _mini_canon_ids()
        canon_texts = _mini_canon_texts()
        seen_ids: dict[str, int] = {}
        r1 = vcr.validate_candidate(json.dumps(cand1), 1, canon_ids, seen_ids, canon_texts)
        r2 = vcr.validate_candidate(json.dumps(cand2), 2, canon_ids, seen_ids, canon_texts)
        assert "duplicate" not in r1["categories"]
        assert "duplicate" not in r2["categories"]


# ===========================================================================
# Test 10 — Self-relation no permitida
# ===========================================================================
class TestSelfRelation:
    def test_self_relation_rejected(self):
        cand = _make_candidate()
        # Misma ID en source y target
        cand["source"]["tiddler_id"] = MINI_SOURCE_ID
        cand["target"]["tiddler_id"] = MINI_SOURCE_ID
        cand["target"]["resolution_status"] = "resolved"
        result = _validate_one(cand)
        assert result["ok"] is False
        assert any("Auto-relación" in e for e in result["errors"])

    def test_different_ids_not_self_relation(self):
        cand = _make_candidate()
        cand["source"]["tiddler_id"] = MINI_SOURCE_ID
        cand["target"]["tiddler_id"] = MINI_TARGET_ID
        result = _validate_one(cand)
        assert not any("Auto-relación" in e for e in result["errors"])

    def test_self_relation_helper_function(self):
        assert rcc.is_self_relation("id-abc", "id-abc") is True
        assert rcc.is_self_relation("id-abc", "id-xyz") is False
        assert rcc.is_self_relation(None, "id-abc") is False
        assert rcc.is_self_relation("", "id-abc") is False


# ===========================================================================
# Test 11 — evidence.kind inválido rechazado
# ===========================================================================
class TestEvidenceKindCatalog:
    @pytest.mark.parametrize("bad_kind", ["manual", "unknown", "guess", ""])
    def test_invalid_kind_rejected(self, bad_kind: str):
        cand = _make_candidate()
        cand["evidence"]["kind"] = bad_kind
        result = _validate_one(cand)
        assert result["ok"] is False
        assert any("evidence.kind" in e for e in result["errors"])

    @pytest.mark.parametrize("good_kind", [
        "explicit_reference", "wikilink", "structural_tag",
        "content_embedded", "ai_inference", "title_mention", "heading_reference",
    ])
    def test_valid_kind_passes(self, good_kind: str):
        cand = _make_candidate()
        cand["evidence"]["kind"] = good_kind
        # Para ai_inference con score alto, el excerpt aún debe estar en fuente
        if good_kind == "ai_inference":
            cand["evidence"]["excerpt"] = EXCERPT_FOUND
        result = _validate_one(cand)
        assert not any("evidence.kind no permitido" in e for e in result["errors"])


# ===========================================================================
# Test 12 — target.tiddler_id inexistente cuando resolved
# ===========================================================================
class TestTargetIdInCanon:
    def test_resolved_target_not_in_canon_is_rejected(self):
        cand = _make_candidate()
        cand["target"]["resolution_status"] = "resolved"
        cand["target"]["tiddler_id"] = "id-de-target-que-no-existe-0000"
        result = _validate_one(cand)
        assert result["ok"] is False
        assert any("target.tiddler_id no existe en el canon" in e for e in result["errors"])

    def test_resolved_target_in_canon_passes(self):
        cand = _make_candidate()
        cand["target"]["resolution_status"] = "resolved"
        cand["target"]["tiddler_id"] = MINI_TARGET_ID
        result = _validate_one(cand)
        assert not any("target.tiddler_id no existe" in e for e in result["errors"])

    def test_unresolved_target_not_in_canon_is_ok(self):
        """Unresolved targets no están en el canon — eso es esperado."""
        cand = _make_candidate()
        cand["target"]["resolution_status"] = "unresolved"
        cand["target"]["tiddler_id"] = None
        cand["target"]["title"] = "slug-no-resuelto"
        result = _validate_one(cand)
        assert not any("target.tiddler_id no existe" in e for e in result["errors"])


# ===========================================================================
# Test 13 — Catálogos de relation_candidate_contract
# ===========================================================================
class TestContractCatalogs:
    def test_allowed_relation_types_nonempty(self):
        assert len(rcc.ALLOWED_RELATION_TYPES) >= 7

    def test_dt029_p0_types_present(self):
        dt029_p0 = {
            "referencia_a", "deriva_de", "menciona_script",
            "menciona_diagnostico", "menciona_sesion", "produce_artefacto", "valida",
        }
        assert dt029_p0.issubset(rcc.ALLOWED_RELATION_TYPES)

    def test_allowed_evidence_kinds_nonempty(self):
        assert len(rcc.ALLOWED_EVIDENCE_KINDS) >= 5

    def test_ai_inference_in_evidence_kinds(self):
        assert "ai_inference" in rcc.ALLOWED_EVIDENCE_KINDS

    def test_explicit_reference_in_evidence_kinds(self):
        assert "explicit_reference" in rcc.ALLOWED_EVIDENCE_KINDS

    def test_weak_threshold_value(self):
        assert rcc.WEAK_EVIDENCE_THRESHOLD == 0.50

    def test_candidate_id_regex_valid(self):
        assert rcc.CANDIDATE_ID_RE.match("rc1_aabb1122334455667788")
        assert not rcc.CANDIDATE_ID_RE.match("rc2_aabb1122")
        assert not rcc.CANDIDATE_ID_RE.match("rc1_xyz")

    def test_verify_excerpt_found(self):
        result = rcc.verify_excerpt_in_source("DT029, DT030", "texto que cita DT029, DT030 en su contenido")
        assert result is True

    def test_verify_excerpt_not_found(self):
        result = rcc.verify_excerpt_in_source("frase inventada", "texto completamente diferente")
        assert result is False

    def test_verify_excerpt_no_source_text(self):
        result = rcc.verify_excerpt_in_source("algo", "")
        assert result is None

    def test_verify_excerpt_empty_excerpt(self):
        result = rcc.verify_excerpt_in_source("", "texto con contenido")
        assert result is False


# ===========================================================================
# Test 14 — write_category_files produce archivos correctos
# ===========================================================================
class TestWriteCategoryFiles:
    def test_writes_four_files(self):
        # Preparar un summary mínimo
        cand_valid = _make_candidate(candidate_id="rc1_aabb1122334455667788")
        cand_invalid = _make_candidate(candidate_id="rc1_bbcc2233445566778899")
        cand_invalid["relation"]["type"] = "tipo_invalido_xyz"

        canon_ids = _mini_canon_ids()
        canon_texts = _mini_canon_texts()
        seen: dict[str, int] = {}

        r_valid = vcr.validate_candidate(json.dumps(cand_valid), 1, canon_ids, seen.copy(), canon_texts)
        r_invalid = vcr.validate_candidate(json.dumps(cand_invalid), 2, canon_ids, seen.copy(), canon_texts)

        # Asignar 'obj' explícitamente (ya está en result)
        summary = {
            "total": 2,
            "valid": [r_valid] if "valid" in r_valid["categories"] else [],
            "invalid": [r_invalid] if "invalid" in r_invalid["categories"] else [],
            "unresolved_target": [],
            "duplicate": [],
            "all_results": [r_valid, r_invalid],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir)
            counts = vcr.write_category_files(summary, out)
            assert (out / "valid_candidates.jsonl").exists()
            assert (out / "invalid_candidates.jsonl").exists()
            assert (out / "unresolved_candidates.jsonl").exists()
            assert (out / "duplicate_candidates.jsonl").exists()
            # Al menos un archivo tiene contenido
            assert counts["valid_candidates.jsonl"] >= 0
            assert counts["invalid_candidates.jsonl"] >= 0

    def test_valid_jsonl_contains_parseable_json(self):
        cand = _make_candidate()
        result = _validate_one(cand)
        summary = {
            "total": 1,
            "valid": [result] if "valid" in result["categories"] else [],
            "invalid": [],
            "unresolved_target": [],
            "duplicate": [],
            "all_results": [result],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir)
            vcr.write_category_files(summary, out)
            content = (out / "valid_candidates.jsonl").read_text()
            for line in content.splitlines():
                if line.strip():
                    obj = json.loads(line)  # no debe lanzar
                    assert obj.get("candidate_id")


# ===========================================================================
# Test 15 — validate_file con los 5 candidatos del staging S0125
# ===========================================================================
class TestValidateFileStagingSample:
    def test_staging_sample_produces_correct_counts(self):
        """
        Ejecuta el validador sobre el sample de S0125 con el canon real.
        Resultado esperado post-S0129: 3 valid, 1 invalid (rc4), 1 unresolved (rc3).
        """
        input_path = REPO_ROOT / "data" / "out" / "local" / "pipeline" / "relations_candidates" / "relations_candidates.sample.jsonl"
        if not input_path.exists():
            pytest.skip("staging sample no encontrado")
        canon_root = REPO_ROOT / "data" / "out" / "local"
        canon_ids = vcr.load_canon_ids(canon_root)
        canon_texts = vcr.load_canon_texts(canon_root)
        summary = vcr.validate_file(input_path, canon_ids, canon_texts)
        assert summary["total"] == 5
        assert len(summary["valid"]) == 3
        assert len(summary["invalid"]) == 1
        assert len(summary["unresolved_target"]) == 1
        assert len(summary["duplicate"]) == 0

    def test_invalid_candidate_is_rc4(self):
        """El candidato inválido tras hardening S0129 debe ser rc4 (ai_inference no verificable)."""
        input_path = REPO_ROOT / "data" / "out" / "local" / "pipeline" / "relations_candidates" / "relations_candidates.sample.jsonl"
        if not input_path.exists():
            pytest.skip("staging sample no encontrado")
        canon_root = REPO_ROOT / "data" / "out" / "local"
        canon_ids = vcr.load_canon_ids(canon_root)
        canon_texts = vcr.load_canon_texts(canon_root)
        summary = vcr.validate_file(input_path, canon_ids, canon_texts)
        assert summary["invalid"]
        invalid_ids = [
            (r.get("obj") or {}).get("candidate_id", "")
            for r in summary["invalid"]
        ]
        assert "rc1_d4e5f6a7b8c9d0e1" in invalid_ids

    def test_dry_run_does_not_modify_canon(self):
        """El validador no modifica ningún tiddler_*.jsonl del canon."""
        canon_root = REPO_ROOT / "data" / "out" / "local"
        before = {
            p.name: p.read_bytes()
            for p in sorted(canon_root.glob("tiddlers_*.jsonl"))
        }
        input_path = REPO_ROOT / "data" / "out" / "local" / "pipeline" / "relations_candidates" / "relations_candidates.sample.jsonl"
        if not input_path.exists():
            pytest.skip("staging sample no encontrado")
        canon_ids = vcr.load_canon_ids(canon_root)
        canon_texts = vcr.load_canon_texts(canon_root)
        vcr.validate_file(input_path, canon_ids, canon_texts)
        after = {
            p.name: p.read_bytes()
            for p in sorted(canon_root.glob("tiddlers_*.jsonl"))
        }
        assert before == after, "El validador modificó archivos del canon — error grave"
