"""
tests/test_validate_relation_candidates.py — S0125

Pruebas mínimas del contrato DT031 para el validador dry-run de relaciones candidatas.

Cobertura requerida por S0125:
  1. Candidato válido pasa validación.
  2. JSON inválido es rechazado.
  3. Candidato sin campos obligatorios es rechazado.
  4. confidence.score fuera de rango es rechazado.
  5. relation.type no permitido es rechazado.
  6. Target no resuelto es permitido solo si está marcado como 'unresolved'.
  7. El validador en dry-run no escribe en tiddlers_*.jsonl.
  8. El reporte JSON y el reporte humano se generan correctamente.
"""

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# IDs reales del canon para fuente y destino (DT029 y DT031)
REAL_SOURCE_ID = "78c6931c-a450-595f-82db-c426aa4689c5"   # DT031
REAL_TARGET_ID = "ab1b8442-3f91-56dd-b4b0-c8908a2aa09c"   # DT029
CANON_ROOT = Path("data/out/local")

VALID_CANDIDATE: dict = {
    "candidate_id": "rc1_aabbccdd11223344",
    "schema_version": "relations-candidate/v1",
    "status": "candidate",
    "source": {
        "tiddler_id": REAL_SOURCE_ID,
        "title": "DT031 contrato de salida",
        "field_path": "text",
        "chunk_id": None,
    },
    "target": {
        "tiddler_id": REAL_TARGET_ID,
        "title": "DT029 tipología mínima",
        "resolution_status": "resolved",
    },
    "relation": {
        "type": "referencia_a",
        "direction": "source_to_target",
        "label": "test candidate",
    },
    "evidence": {
        "kind": "explicit_reference",
        "excerpt": "Diagnósticos previos consultados: DT029",
        "location": "text/section:test",
        "strength": "E1",
        "secondary": [],
    },
    "confidence": {
        "score": 0.9,
        "method": "rule_based",
        "risk_flags": [],
    },
    "provenance": {
        "generated_by": "test_suite",
        "generated_at": "2026-05-26T10:00:00Z",
        "input_artifacts": ["data/out/local/tiddlers_5.jsonl"],
        "diagnostic_basis": ["DT031"],
        "source_path": "data/out/local/tiddlers_5.jsonl",
    },
    "review": {
        "required": True,
        "review_status": "pending",
        "reviewer": "",
        "reviewed_at": "",
        "notes": "",
    },
    "created_at": "2026-05-26T10:00:00Z",
}

TECHNICAL_CANDIDATE: dict = {
    "candidate_id": "rc1_aaaabbbbccccdddd",
    "candidate_schema_version": "technical-relation-candidates/v1",
    "status": "resolved_for_human_review",
    "relation_type": "references",
    "human_review_decision": "deferred",
    "source": {
        "canonical_id": REAL_SOURCE_ID,
        "canonical_title": "DT031 contrato de salida",
        "repo_path": "src/python_scripts/validate_relation_candidates.py",
        "lifecycle_state": "current_repo_artifact",
    },
    "target": {
        "canonical_id": REAL_TARGET_ID,
        "canonical_title": "DT029 tipología mínima",
        "repo_path": "src/python_scripts/relation_candidate_contract.py",
        "lifecycle_state": "current_repo_artifact",
    },
    "evidence": {
        "evidence_kind": "path_literal",
        "confidence": "high",
        "raw_observation": "technical fixture observation",
    },
    "policy": {
        "human_review_required": True,
        "canonical_admission_allowed": False,
    },
    "session_resolution": {"classification": "resolved_for_human_review"},
}


def _write_jsonl(tmp_dir: Path, candidates: list[dict | str]) -> Path:
    """Escribe una lista de candidatos (dicts o strings) en un JSONL temporal."""
    path = tmp_dir / "input.jsonl"
    lines = []
    for c in candidates:
        lines.append(c if isinstance(c, str) else json.dumps(c, ensure_ascii=False))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _run_validator(
    input_path: Path,
    tmp_dir: Path,
    extra_args: list[str] | None = None,
) -> tuple[int, str, Path, Path]:
    """
    Ejecuta el validador como subproceso.
    Devuelve (returncode, combined_output, report_path, human_review_path).
    """
    report = tmp_dir / "report.json"
    review = tmp_dir / "review.md"
    cmd = [
        sys.executable,
        "src/python_scripts/validate_relation_candidates.py",
        "--input", str(input_path),
        "--canon-root", str(CANON_ROOT),
        "--report", str(report),
        "--human-review", str(review),
        "--dry-run",
    ]
    if extra_args:
        cmd += extra_args
    result = subprocess.run(cmd, capture_output=True, text=True)
    output = result.stdout + result.stderr
    return result.returncode, output, report, review


# ---------------------------------------------------------------------------
# Import directo del módulo para tests de unidad
# ---------------------------------------------------------------------------

sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "python_scripts"))
from validate_relation_candidates import (  # noqa: E402
    ALLOWED_RELATION_TYPES,
    WEAK_EVIDENCE_THRESHOLD,
    load_canon_ids,
    validate_candidate,
    validate_file,
)


# ---------------------------------------------------------------------------
# Test 1 — Candidato válido pasa validación
# ---------------------------------------------------------------------------

class TestValidCandidate:
    def test_valid_candidate_passes(self):
        """Un candidato bien formado con source en canon debe pasar."""
        if not CANON_ROOT.exists():
            pytest.skip("Canon root no disponible en este entorno")
        canon_ids = load_canon_ids(CANON_ROOT)
        seen: dict[str, int] = {}
        raw = json.dumps(VALID_CANDIDATE, ensure_ascii=False)
        result = validate_candidate(raw, 1, canon_ids, seen)
        assert result["ok"] is True, f"Esperado ok=True; errores={result['errors']}"
        assert "valid" in result["categories"]
        assert not result["errors"]

    def test_valid_candidate_no_canon_check_with_empty_canon(self):
        """Sin canon disponible, source.tiddler_id no encontrado → error."""
        raw = json.dumps(VALID_CANDIDATE, ensure_ascii=False)
        result = validate_candidate(raw, 1, set(), {})
        # El ID no está en el conjunto vacío → debe haber error de canon
        assert not result["ok"]
        canon_errors = [e for e in result["errors"] if "no existe en el canon" in e]
        assert canon_errors, f"Esperado error de canon; errores={result['errors']}"


# ---------------------------------------------------------------------------
# Test 2 — JSON inválido es rechazado
# ---------------------------------------------------------------------------

class TestInvalidJson:
    def test_malformed_json_rejected(self):
        """Una línea con JSON roto debe clasificarse como inválida."""
        raw = '{"candidate_id": "rc1_abc123", "status": "candidate"  <- ROTO'
        result = validate_candidate(raw, 1, set(), {})
        assert result["ok"] is False
        assert any("JSON inválido" in e for e in result["errors"])
        assert "invalid" in result["categories"]

    def test_empty_string_rejected(self):
        """String vacío es JSON inválido."""
        result = validate_candidate("", 1, set(), {})
        assert result["ok"] is False

    def test_plain_string_rejected(self):
        """String sin estructura JSON es rechazado."""
        result = validate_candidate("esto no es JSON", 1, set(), {})
        assert result["ok"] is False


# ---------------------------------------------------------------------------
# Test 3 — Candidato sin campos obligatorios es rechazado
# ---------------------------------------------------------------------------

class TestMissingRequiredFields:
    @pytest.mark.parametrize("field_to_remove", [
        "candidate_id",
        "status",
        "source",
        "target",
        "relation",
        "evidence",
        "confidence",
        "provenance",
        "created_at",
    ])
    def test_missing_field_rejected(self, field_to_remove: str):
        """Eliminar cualquier campo obligatorio de primer nivel debe fallar."""
        import copy
        cand = copy.deepcopy(VALID_CANDIDATE)
        del cand[field_to_remove]
        raw = json.dumps(cand, ensure_ascii=False)
        result = validate_candidate(raw, 1, set(), {})
        assert result["ok"] is False, (
            f"Esperado fallo al eliminar {field_to_remove!r}; "
            f"resultado: ok={result['ok']}, errores={result['errors']}"
        )

    def test_empty_source_field_path_rejected(self):
        """source.field_path vacío debe ser rechazado."""
        import copy
        cand = copy.deepcopy(VALID_CANDIDATE)
        cand["source"]["field_path"] = ""
        raw = json.dumps(cand, ensure_ascii=False)
        result = validate_candidate(raw, 1, {REAL_SOURCE_ID}, {})
        assert result["ok"] is False
        assert any("field_path" in e for e in result["errors"])

    def test_empty_evidence_excerpt_rejected(self):
        """evidence.excerpt vacío debe ser rechazado."""
        import copy
        cand = copy.deepcopy(VALID_CANDIDATE)
        cand["evidence"]["excerpt"] = ""
        raw = json.dumps(cand, ensure_ascii=False)
        result = validate_candidate(raw, 1, {REAL_SOURCE_ID}, {})
        assert result["ok"] is False
        assert any("excerpt" in e for e in result["errors"])

    def test_validate_candidate_requires_human_review_decision(self):
        import copy
        cand = copy.deepcopy(TECHNICAL_CANDIDATE)
        del cand["human_review_decision"]
        raw = json.dumps(cand, ensure_ascii=False)
        result = validate_candidate(raw, 1, {REAL_SOURCE_ID, REAL_TARGET_ID}, {})
        assert result["ok"] is False
        assert any("human_review_decision" in e for e in result["errors"])

    def test_technical_candidate_requires_lifecycle_state(self):
        import copy
        cand = copy.deepcopy(TECHNICAL_CANDIDATE)
        cand["target"]["lifecycle_state"] = ""
        raw = json.dumps(cand, ensure_ascii=False)
        result = validate_candidate(raw, 1, {REAL_SOURCE_ID, REAL_TARGET_ID}, {})
        assert result["ok"] is False
        assert any("target.lifecycle_state" in e for e in result["errors"])


# ---------------------------------------------------------------------------
# Test 4 — confidence.score fuera de rango es rechazado
# ---------------------------------------------------------------------------

class TestConfidenceScore:
    @pytest.mark.parametrize("bad_score", [-0.1, 1.01, 2.0, -1])
    def test_score_out_of_range_rejected(self, bad_score: float):
        """Scores fuera de [0.0, 1.0] deben generar error."""
        import copy
        cand = copy.deepcopy(VALID_CANDIDATE)
        cand["confidence"]["score"] = bad_score
        raw = json.dumps(cand, ensure_ascii=False)
        result = validate_candidate(raw, 1, {REAL_SOURCE_ID}, {})
        assert result["ok"] is False
        assert any("score" in e for e in result["errors"])

    @pytest.mark.parametrize("valid_score", [0.0, 0.5, 0.75, 1.0])
    def test_score_in_range_passes(self, valid_score: float):
        """Scores dentro de [0.0, 1.0] con source en canon deben pasar."""
        import copy
        cand = copy.deepcopy(VALID_CANDIDATE)
        cand["confidence"]["score"] = valid_score
        raw = json.dumps(cand, ensure_ascii=False)
        result = validate_candidate(raw, 1, {REAL_SOURCE_ID}, {})
        # Puede haber warnings (weak_evidence) pero no errores de score
        score_errors = [e for e in result["errors"] if "score" in e]
        assert not score_errors, f"No esperado error de score para {valid_score}; errores={result['errors']}"

    def test_score_not_numeric_rejected(self):
        """score como string debe ser rechazado."""
        import copy
        cand = copy.deepcopy(VALID_CANDIDATE)
        cand["confidence"]["score"] = "alto"
        raw = json.dumps(cand, ensure_ascii=False)
        result = validate_candidate(raw, 1, {REAL_SOURCE_ID}, {})
        assert result["ok"] is False

    def test_score_below_threshold_flagged_as_weak(self):
        """Score por debajo del umbral genera categoría weak_evidence."""
        import copy
        cand = copy.deepcopy(VALID_CANDIDATE)
        cand["confidence"]["score"] = WEAK_EVIDENCE_THRESHOLD - 0.01
        raw = json.dumps(cand, ensure_ascii=False)
        result = validate_candidate(raw, 1, {REAL_SOURCE_ID}, {})
        assert "weak_evidence" in result["categories"]


# ---------------------------------------------------------------------------
# Test 5 — relation.type no permitido es rechazado
# ---------------------------------------------------------------------------

class TestRelationType:
    @pytest.mark.parametrize("bad_type", [
        "usa",
        "parte_de",
        "define",
        "unknown_type",
        "",
        "REFERENCES",
        "Referencia_a",
    ])
    def test_invalid_relation_type_rejected(self, bad_type: str):
        """Tipos no presentes en el catálogo deben generar error."""
        import copy
        cand = copy.deepcopy(VALID_CANDIDATE)
        cand["relation"]["type"] = bad_type
        raw = json.dumps(cand, ensure_ascii=False)
        result = validate_candidate(raw, 1, {REAL_SOURCE_ID}, {})
        assert result["ok"] is False
        assert any("relation.type" in e for e in result["errors"])

    @pytest.mark.parametrize("good_type", sorted(ALLOWED_RELATION_TYPES))
    def test_allowed_relation_type_passes(self, good_type: str):
        """Cada tipo del catálogo DT029/DT031 debe ser aceptado."""
        import copy
        cand = copy.deepcopy(VALID_CANDIDATE)
        cand["relation"]["type"] = good_type
        raw = json.dumps(cand, ensure_ascii=False)
        result = validate_candidate(raw, 1, {REAL_SOURCE_ID}, {})
        type_errors = [e for e in result["errors"] if "relation.type" in e]
        assert not type_errors, f"Tipo {good_type!r} rechazado inesperadamente: {type_errors}"


# ---------------------------------------------------------------------------
# Test 6 — Target no resuelto permitido solo si marcado como 'unresolved'
# ---------------------------------------------------------------------------

class TestTargetResolution:
    def test_unresolved_target_marked_is_allowed(self):
        """Target marcado como 'unresolved' sin tiddler_id es permitido."""
        import copy
        cand = copy.deepcopy(VALID_CANDIDATE)
        cand["target"]["resolution_status"] = "unresolved"
        cand["target"]["tiddler_id"] = None
        raw = json.dumps(cand, ensure_ascii=False)
        result = validate_candidate(raw, 1, {REAL_SOURCE_ID}, {})
        # Categoría unresolved_target pero no debería haber error por eso
        assert "unresolved_target" in result["categories"]
        target_errors = [e for e in result["errors"] if "resolution_status" in e or "unresolved" in e.lower()]
        assert not target_errors, f"No esperado error por unresolved marcado: {target_errors}"

    def test_resolved_target_without_id_is_rejected(self):
        """Target marcado como 'resolved' pero sin tiddler_id debe ser rechazado."""
        import copy
        cand = copy.deepcopy(VALID_CANDIDATE)
        cand["target"]["resolution_status"] = "resolved"
        cand["target"]["tiddler_id"] = None
        raw = json.dumps(cand, ensure_ascii=False)
        result = validate_candidate(raw, 1, {REAL_SOURCE_ID}, {})
        assert result["ok"] is False
        assert any("resolution_status" in e or "tiddler_id" in e for e in result["errors"])

    def test_invalid_resolution_status_rejected(self):
        """resolution_status con valor fuera del catálogo debe ser rechazado."""
        import copy
        cand = copy.deepcopy(VALID_CANDIDATE)
        cand["target"]["resolution_status"] = "unknown_status"
        raw = json.dumps(cand, ensure_ascii=False)
        result = validate_candidate(raw, 1, {REAL_SOURCE_ID}, {})
        assert result["ok"] is False
        assert any("resolution_status" in e for e in result["errors"])


# ---------------------------------------------------------------------------
# Test 7 — Dry-run no escribe en tiddlers_*.jsonl
# ---------------------------------------------------------------------------

class TestDryRunIsolation:
    def test_dry_run_does_not_modify_canon(self):
        """El validador en dry-run no debe modificar ningún tiddlers_*.jsonl."""
        if not CANON_ROOT.exists():
            pytest.skip("Canon root no disponible")

        # Capturar MTimes antes
        canon_files = sorted(CANON_ROOT.glob("tiddlers_*.jsonl"))
        if not canon_files:
            pytest.skip("No hay shards del canon")
        mtimes_before = {f: f.stat().st_mtime for f in canon_files}

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_path = _write_jsonl(tmp_path, [VALID_CANDIDATE])
            rc, out, report, review = _run_validator(input_path, tmp_path)

        # Verificar MTimes después
        mtimes_after = {f: f.stat().st_mtime for f in canon_files}
        modified = [str(f) for f in canon_files if mtimes_after[f] != mtimes_before[f]]
        assert not modified, f"tiddlers_*.jsonl fueron modificados en dry-run: {modified}"

    def test_apply_flag_is_blocked(self):
        """--apply debe causar salida con código de error 2."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_path = _write_jsonl(tmp_path, [VALID_CANDIDATE])
            rc, out, report, review = _run_validator(input_path, tmp_path, extra_args=["--apply"])
        assert rc == 2, f"Esperado returncode=2 con --apply; obtenido {rc}"
        assert "--apply" in out or "bloqueada" in out

    def test_missing_dry_run_flag_fails(self):
        """Sin --dry-run el script debe negarse a ejecutar (argparse error)."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_path = _write_jsonl(tmp_path, [VALID_CANDIDATE])
            report = tmp_path / "r.json"
            review = tmp_path / "r.md"
            cmd = [
                sys.executable,
                "src/python_scripts/validate_relation_candidates.py",
                "--input", str(input_path),
                "--canon-root", str(CANON_ROOT),
                "--report", str(report),
                "--human-review", str(review),
                # sin --dry-run
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
        assert result.returncode != 0, "Sin --dry-run debería fallar"


# ---------------------------------------------------------------------------
# Test 8 — Reporte JSON y reporte humano se generan correctamente
# ---------------------------------------------------------------------------

class TestReportGeneration:
    def test_reports_are_generated(self):
        """Con input válido, ambos reportes deben existir."""
        if not CANON_ROOT.exists():
            pytest.skip("Canon root no disponible")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_path = _write_jsonl(tmp_path, [VALID_CANDIDATE])
            rc, out, report, review = _run_validator(input_path, tmp_path)
            assert report.exists(), "Reporte JSON no fue generado"
            assert review.exists(), "Reporte humano (Markdown) no fue generado"

    def test_json_report_structure(self):
        """El reporte JSON debe tener el schema correcto y campos esperados."""
        if not CANON_ROOT.exists():
            pytest.skip("Canon root no disponible")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_path = _write_jsonl(tmp_path, [VALID_CANDIDATE])
            _run_validator(input_path, tmp_path)
            report = tmp_path / "report.json"
            data = json.loads(report.read_text())

        # S0129: schema actualizado a v2; aceptar ambas versiones para compatibilidad
        assert data.get("schema") in {
            "relations-candidate-validation-report/v1",
            "relations-candidate-validation-report/v2",
        }
        assert data.get("dry_run") is True
        assert "summary" in data
        assert "details" in data
        summary = data["summary"]
        assert "total" in summary
        assert "valid" in summary
        assert "invalid" in summary
        assert "unresolved_target" in summary
        assert "weak_evidence" in summary
        assert "duplicate" in summary

    def test_human_review_contains_sections(self):
        """El reporte humano debe contener las secciones principales."""
        if not CANON_ROOT.exists():
            pytest.skip("Canon root no disponible")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_path = _write_jsonl(tmp_path, [VALID_CANDIDATE])
            _run_validator(input_path, tmp_path)
            review = tmp_path / "review.md"
            content = review.read_text()

        assert "## Resumen" in content
        assert "dry-run" in content.lower()
        assert "✅" in content  # candidatos válidos
        assert "❌" in content  # candidatos inválidos

    def test_report_separates_all_categories(self):
        """El reporte JSON debe separar las 5 categorías del contrato."""
        if not CANON_ROOT.exists():
            pytest.skip("Canon root no disponible")
        import copy

        # Crear candidatos de distintas categorías
        valid_cand = copy.deepcopy(VALID_CANDIDATE)
        valid_cand["candidate_id"] = "rc1_" + "a" * 16

        unresolved_cand = copy.deepcopy(VALID_CANDIDATE)
        unresolved_cand["candidate_id"] = "rc1_" + "b" * 16
        unresolved_cand["target"]["resolution_status"] = "unresolved"
        unresolved_cand["target"]["tiddler_id"] = None

        weak_cand = copy.deepcopy(VALID_CANDIDATE)
        weak_cand["candidate_id"] = "rc1_" + "c" * 16
        weak_cand["confidence"]["score"] = 0.2

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_path = _write_jsonl(tmp_path, [valid_cand, unresolved_cand, weak_cand])
            _run_validator(input_path, tmp_path)
            report = tmp_path / "report.json"
            data = json.loads(report.read_text())

        details = data["details"]
        assert len(details["valid"]) >= 1
        assert len(details["unresolved_target"]) >= 1
        assert len(details["weak_evidence"]) >= 1

    def test_duplicate_detection(self):
        """Candidatos con el mismo candidate_id deben detectarse como duplicados."""
        if not CANON_ROOT.exists():
            pytest.skip("Canon root no disponible")
        import copy
        cand1 = copy.deepcopy(VALID_CANDIDATE)
        cand1["candidate_id"] = "rc1_" + "d" * 16
        cand2 = copy.deepcopy(cand1)  # mismo ID → duplicado

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_path = _write_jsonl(tmp_path, [cand1, cand2])
            _run_validator(input_path, tmp_path)
            report = tmp_path / "report.json"
            data = json.loads(report.read_text())

        assert data["summary"]["duplicate"] >= 1


# ---------------------------------------------------------------------------
# Test adicional — validate_file con candidatos mixtos
# ---------------------------------------------------------------------------

class TestValidateFileMixed:
    def test_validate_file_with_sample_jsonl(self):
        """El sample JSONL de S0125 debe evaluarse sin errores del sistema."""
        sample = Path("data/out/local/pipeline/relations_candidates/relations_candidates.sample.jsonl")
        if not sample.exists():
            pytest.skip("Sample JSONL de S0125 no encontrado")
        if not CANON_ROOT.exists():
            pytest.skip("Canon root no disponible")
        canon_ids = load_canon_ids(CANON_ROOT)
        summary = validate_file(sample, canon_ids)
        # El sample tiene candidatos diseñados para cubrir categorías; debe procesarse sin excepción
        assert summary["total"] > 0
        # Al menos uno válido
        assert len(summary["valid"]) >= 1
        # El candidato de target no resuelto debe estar en unresolved_target
        assert len(summary["unresolved_target"]) >= 1
        # El candidato con score bajo debe estar en weak_evidence
        assert len(summary["weak_evidence"]) >= 1
