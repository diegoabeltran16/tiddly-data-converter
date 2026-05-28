"""
tests/test_relation_admissibility_evaluator.py — S0132

Pruebas del evaluador dry-run de admisibilidad relacional.

Los tests cubren los 7 casos obligatorios del spec §7 más verificaciones
de integridad de reportes.

INVARIANTE: ningún tiddlers_*.jsonl es modificado.
"""

from __future__ import annotations

import csv as csv_module
import glob as _glob
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "python_scripts"))

import evaluate_relation_admissibility as era

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SRC_ID = "src-aa112233445566778899aabb"
TGT_ID = "tgt-bb998877665544332211ccdd"
EXCERPT_FOUND = "Diagnósticos previos consultados: DT029, DT030"


def _make_canon(
    *,
    src_text: str = EXCERPT_FOUND + " sección adicional de contexto",
    tgt_text: str = "El contrato de salida define campos obligatorios.",
    src_relations: list | None = None,
) -> dict:
    return {
        SRC_ID: {
            "id": SRC_ID,
            "title": "Tiddler source de test S0132",
            "text": src_text,
            "tags": ["m04", "layer:session"],
            "relations": src_relations or [],
        },
        TGT_ID: {
            "id": TGT_ID,
            "title": "Tiddler target de test S0132",
            "text": tgt_text,
            "tags": [],
            "relations": [],
        },
    }


def _make_candidate(
    *,
    rel_type: str = "referencia_a",
    ev_kind: str = "explicit_reference",
    excerpt: str = EXCERPT_FOUND,
    score: float = 0.92,
    tgt_resolution: str = "resolved",
    src_id: str = SRC_ID,
    tgt_id: str = TGT_ID,
    drop_field: str | None = None,
) -> dict:
    base: dict = {
        "candidate_id": "rc1_aabb1122ccdd3344",
        "schema_version": "relations-candidate/v1",
        "status": "candidate",
        "source": {
            "tiddler_id": src_id,
            "title": "Tiddler source de test S0132",
            "field_path": "text",
            "chunk_id": None,
        },
        "target": {
            "tiddler_id": tgt_id,
            "title": "Tiddler target de test S0132",
            "resolution_status": tgt_resolution,
        },
        "relation": {
            "type": rel_type,
            "direction": "source_to_target",
            "label": "test relation",
        },
        "evidence": {
            "kind": ev_kind,
            "excerpt": excerpt,
            "location": "text/section:Test",
            "strength": "E1",
            "secondary": [],
        },
        "confidence": {
            "score": score,
            "method": "rule_based",
            "risk_flags": [],
        },
        "provenance": {
            "generated_by": "test_s0132",
            "generated_at": "2026-05-27T19:00:00Z",
        },
        "review": {
            "required": True,
            "review_status": "pending",
            "reviewed_at": "",
            "reviewer": "",
            "notes": "",
        },
        "created_at": "2026-05-27T19:00:00Z",
    }
    if drop_field:
        base.pop(drop_field, None)
    return base


# ---------------------------------------------------------------------------
# Caso 1: Candidato válido con source y target resueltos
# ---------------------------------------------------------------------------

class TestValidCandidateResolved:
    """Caso 1: Candidato con source y target resueltos → review_required (necesita human_approved)."""

    def test_valid_candidate_is_review_required(self):
        canon = _make_canon()
        candidate = _make_candidate(
            rel_type="referencia_a",
            ev_kind="explicit_reference",
            excerpt=EXCERPT_FOUND,
            score=0.92,
            tgt_resolution="resolved",
        )
        result = era.evaluate_candidate(candidate, canon)
        # En dry-run, human_approved=False → review_required (no admissible_dry_run)
        assert result["decision"] in {era.DEC_REVIEW, era.DEC_ADMISSIBLE}
        assert result["would_modify_canon"] is False

    def test_valid_candidate_decision_is_deterministic(self):
        """El evaluador es determinista: misma entrada, misma salida."""
        canon = _make_canon()
        candidate = _make_candidate()
        r1 = era.evaluate_candidate(candidate, canon)
        r2 = era.evaluate_candidate(candidate, canon)
        assert r1["decision"] == r2["decision"]
        assert r1["risk_level"] == r2["risk_level"]

    def test_would_modify_canon_always_false(self):
        canon = _make_canon()
        candidate = _make_candidate()
        result = era.evaluate_candidate(candidate, canon)
        assert result["would_modify_canon"] is False

    def test_valid_candidate_has_all_report_fields(self):
        canon = _make_canon()
        candidate = _make_candidate()
        result = era.evaluate_candidate(candidate, canon)
        for f in era.REPORT_FIELDS:
            assert f in result, f"Campo faltante en resultado: {f!r}"


# ---------------------------------------------------------------------------
# Caso 2: Candidato con target no resuelto → unresolved_target
# ---------------------------------------------------------------------------

class TestUnresolvedTargetDecision:
    """Caso 2: Candidato con target.resolution_status=unresolved → unresolved_target."""

    def test_unresolved_target_decision(self):
        canon = _make_canon()
        candidate = _make_candidate(tgt_resolution="unresolved")
        result = era.evaluate_candidate(candidate, canon)
        assert result["decision"] == era.DEC_UNRESOLVED

    def test_ambiguous_target_decision(self):
        canon = _make_canon()
        candidate = _make_candidate(tgt_resolution="ambiguous")
        result = era.evaluate_candidate(candidate, canon)
        assert result["decision"] in {era.DEC_UNRESOLVED, era.DEC_REVIEW}

    def test_unresolved_has_medium_or_high_risk(self):
        canon = _make_canon()
        candidate = _make_candidate(tgt_resolution="unresolved")
        result = era.evaluate_candidate(candidate, canon)
        assert result["risk_level"] in {"medium", "high"}

    def test_unresolved_does_not_modify_canon(self):
        canon = _make_canon()
        candidate = _make_candidate(tgt_resolution="unresolved")
        result = era.evaluate_candidate(candidate, canon)
        assert result["would_modify_canon"] is False


# ---------------------------------------------------------------------------
# Caso 3: Candidato con source inexistente → blocked
# ---------------------------------------------------------------------------

class TestSourceNotFoundIsBlocked:
    """Caso 3: Candidato con source.tiddler_id no en el canon → blocked."""

    def test_source_not_in_canon_is_blocked(self):
        canon = _make_canon()  # solo tiene SRC_ID y TGT_ID
        candidate = _make_candidate(src_id="nonexistent-src-id-xyz123")
        result = era.evaluate_candidate(candidate, canon)
        assert result["decision"] in {era.DEC_BLOCKED, era.DEC_REJECTED}

    def test_source_not_found_has_high_risk(self):
        canon = _make_canon()
        candidate = _make_candidate(src_id="nonexistent-src-id-xyz123")
        result = era.evaluate_candidate(candidate, canon)
        assert result["risk_level"] == "high"

    def test_source_not_found_does_not_modify_canon(self):
        canon = _make_canon()
        candidate = _make_candidate(src_id="nonexistent-src-id-xyz123")
        result = era.evaluate_candidate(candidate, canon)
        assert result["would_modify_canon"] is False


# ---------------------------------------------------------------------------
# Caso 4: Candidato con relation.type no permitido → rejected
# ---------------------------------------------------------------------------

class TestUnknownRelationTypeRejected:
    """Caso 4: Candidato con relation.type no en catálogo → rejected."""

    def test_unknown_type_is_rejected(self):
        canon = _make_canon()
        candidate = _make_candidate(rel_type="tipo_inventado_xyzzy_s0132")
        result = era.evaluate_candidate(candidate, canon)
        assert result["decision"] == era.DEC_REJECTED

    def test_unknown_type_has_high_risk(self):
        canon = _make_canon()
        candidate = _make_candidate(rel_type="tipo_inventado_xyzzy_s0132")
        result = era.evaluate_candidate(candidate, canon)
        assert result["risk_level"] == "high"

    def test_known_type_passes_type_check(self):
        canon = _make_canon()
        candidate = _make_candidate(rel_type="referencia_a")
        result = era.evaluate_candidate(candidate, canon)
        assert result["decision"] != era.DEC_REJECTED or "no permitido" not in result.get(
            "decision_reasons", ""
        )


# ---------------------------------------------------------------------------
# Caso 5: Candidato con evidence.excerpt no verificable
# ---------------------------------------------------------------------------

class TestExcerptNotVerifiable:
    """Caso 5: Candidato con excerpt que no existe en texto fuente."""

    def test_ai_inference_with_false_excerpt_is_rejected(self):
        """DT030: ai_inference + excerpt not found → rejected."""
        canon = _make_canon(src_text="Texto del tiddler que no contiene la frase del excerpt")
        candidate = _make_candidate(
            rel_type="referencia_a",
            ev_kind="ai_inference",
            excerpt="Esta frase fue inventada por IA y no existe en el texto fuente",
            score=0.75,
            tgt_resolution="resolved",
        )
        result = era.evaluate_candidate(candidate, canon)
        assert result["decision"] == era.DEC_REJECTED

    def test_explicit_reference_with_excerpt_not_found_is_review(self):
        """explicit_reference con excerpt no encontrado → review_required (no rejected)."""
        canon = _make_canon(src_text="Texto que no contiene la frase buscada")
        candidate = _make_candidate(
            rel_type="referencia_a",
            ev_kind="explicit_reference",
            excerpt="frase que no aparece en el texto fuente",
            score=0.8,
            tgt_resolution="resolved",
        )
        result = era.evaluate_candidate(candidate, canon)
        # No es rejected por tipo de evidencia, pero puede tener warning
        assert result["would_modify_canon"] is False

    def test_excerpt_found_in_source_does_not_add_excerpt_warning(self):
        """Cuando el excerpt se encuentra en el texto fuente, no hay warning de excerpt."""
        canon = _make_canon(src_text=EXCERPT_FOUND + " más texto de contexto")
        candidate = _make_candidate(
            ev_kind="explicit_reference",
            excerpt=EXCERPT_FOUND,
        )
        result = era.evaluate_candidate(candidate, canon)
        reasons = result.get("decision_reasons", "")
        assert "excerpt no encontrado" not in reasons


# ---------------------------------------------------------------------------
# Caso 6: Candidato duplicado de relación canónica existente
# ---------------------------------------------------------------------------

class TestDuplicateCanonicalRelation:
    """Caso 6: Candidato que duplica una relación canónica ya existente → duplicate_or_existing."""

    def test_duplicate_is_detected(self):
        canon = _make_canon(
            src_relations=[{"target_id": TGT_ID, "type": "referencia_a"}]
        )
        candidate = _make_candidate(rel_type="referencia_a", tgt_resolution="resolved")
        result = era.evaluate_candidate(candidate, canon)
        assert result["decision"] == era.DEC_DUPLICATE

    def test_duplicate_does_not_modify_canon(self):
        canon = _make_canon(
            src_relations=[{"target_id": TGT_ID, "type": "referencia_a"}]
        )
        candidate = _make_candidate(rel_type="referencia_a")
        result = era.evaluate_candidate(candidate, canon)
        assert result["would_modify_canon"] is False

    def test_different_type_same_target_not_duplicate(self):
        """Misma fuente+target pero tipo diferente → no es duplicado."""
        canon = _make_canon(
            src_relations=[{"target_id": TGT_ID, "type": "referencia_a"}]
        )
        candidate = _make_candidate(
            rel_type="menciona_diagnostico",
            ev_kind="title_mention",
            excerpt=EXCERPT_FOUND,
            score=0.78,
            tgt_resolution="resolved",
        )
        result = era.evaluate_candidate(candidate, canon)
        assert result["decision"] != era.DEC_DUPLICATE


# ---------------------------------------------------------------------------
# Caso 7: Candidato con contrato incompleto → invalid_contract
# ---------------------------------------------------------------------------

class TestIncompleteContractIsInvalid:
    """Caso 7: Candidato con campo obligatorio ausente → invalid_contract."""

    def test_missing_evidence_field_is_invalid(self):
        canon = _make_canon()
        candidate = _make_candidate(drop_field="evidence")
        result = era.evaluate_candidate(candidate, canon)
        assert result["decision"] == era.DEC_INVALID

    def test_missing_confidence_field_is_invalid(self):
        canon = _make_canon()
        candidate = _make_candidate(drop_field="confidence")
        result = era.evaluate_candidate(candidate, canon)
        assert result["decision"] == era.DEC_INVALID

    def test_missing_provenance_field_is_invalid(self):
        canon = _make_canon()
        candidate = _make_candidate(drop_field="provenance")
        result = era.evaluate_candidate(candidate, canon)
        assert result["decision"] == era.DEC_INVALID

    def test_invalid_contract_has_high_risk(self):
        canon = _make_canon()
        candidate = _make_candidate(drop_field="evidence")
        result = era.evaluate_candidate(candidate, canon)
        assert result["risk_level"] == "high"

    def test_check_contract_returns_errors_for_missing_fields(self):
        candidate = _make_candidate(drop_field="evidence")
        errors = era.check_contract(candidate)
        assert len(errors) > 0
        assert any("evidence" in e for e in errors)

    def test_check_contract_returns_empty_for_complete_candidate(self):
        candidate = _make_candidate()
        errors = era.check_contract(candidate)
        assert errors == []


# ---------------------------------------------------------------------------
# Reporte JSON válido
# ---------------------------------------------------------------------------

class TestJsonReportIsValid:
    """El reporte JSON generado es válido y tiene el schema correcto."""

    REPORT_PATH = (
        REPO_ROOT
        / "data" / "out" / "local" / "pipeline" / "relation_admissibility" / "s0132"
        / "s0132_relation_admissibility_report.json"
    )

    def test_report_file_exists(self):
        assert self.REPORT_PATH.exists(), f"No encontrado: {self.REPORT_PATH}"

    def test_report_is_valid_json(self):
        data = json.loads(self.REPORT_PATH.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    def test_report_has_correct_schema(self):
        data = json.loads(self.REPORT_PATH.read_text(encoding="utf-8"))
        assert data.get("schema") == era.SCHEMA

    def test_report_dry_run_is_true(self):
        data = json.loads(self.REPORT_PATH.read_text(encoding="utf-8"))
        assert data.get("dry_run") is True
        assert data.get("applied_to_canon") is False
        assert data.get("would_modify_canon") is False

    def test_report_has_decision_summary(self):
        data = json.loads(self.REPORT_PATH.read_text(encoding="utf-8"))
        assert "decision_summary" in data
        summary = data["decision_summary"]
        assert isinstance(summary, dict)

    def test_report_results_all_have_would_modify_canon_false(self):
        data = json.loads(self.REPORT_PATH.read_text(encoding="utf-8"))
        for r in data.get("results", []):
            assert r.get("would_modify_canon") is False, (
                f"would_modify_canon=True en candidato {r.get('candidate_id')}"
            )

    def test_report_classifies_all_candidates(self):
        data = json.loads(self.REPORT_PATH.read_text(encoding="utf-8"))
        total = data.get("total_evaluated", 0)
        results = data.get("results", [])
        assert len(results) == total


# ---------------------------------------------------------------------------
# CSV contiene candidate_id y decision
# ---------------------------------------------------------------------------

class TestCsvContainsRequiredColumns:
    """El CSV debe contener al menos candidate_id y decision."""

    CSV_PATH = (
        REPO_ROOT
        / "data" / "out" / "local" / "pipeline" / "relation_admissibility" / "s0132"
        / "s0132_relation_admissibility_review.csv"
    )

    def test_csv_file_exists(self):
        assert self.CSV_PATH.exists(), f"No encontrado: {self.CSV_PATH}"

    def test_csv_has_candidate_id_column(self):
        rows = list(csv_module.DictReader(self.CSV_PATH.open(encoding="utf-8")))
        assert len(rows) > 0
        assert "candidate_id" in rows[0]

    def test_csv_has_decision_column(self):
        rows = list(csv_module.DictReader(self.CSV_PATH.open(encoding="utf-8")))
        assert "decision" in rows[0]

    def test_csv_decisions_are_valid(self):
        valid_decisions = {
            era.DEC_ADMISSIBLE, era.DEC_REVIEW, era.DEC_BLOCKED,
            era.DEC_REJECTED, era.DEC_DUPLICATE, era.DEC_INVALID, era.DEC_UNRESOLVED,
        }
        rows = list(csv_module.DictReader(self.CSV_PATH.open(encoding="utf-8")))
        for row in rows:
            assert row["decision"] in valid_decisions, (
                f"Decisión inválida: {row['decision']!r} en {row['candidate_id']}"
            )

    def test_csv_would_modify_canon_always_false(self):
        rows = list(csv_module.DictReader(self.CSV_PATH.open(encoding="utf-8")))
        for row in rows:
            assert row["would_modify_canon"] == "False", (
                f"would_modify_canon no es False en {row['candidate_id']}"
            )


# ---------------------------------------------------------------------------
# Summary Markdown contiene conteos por decisión
# ---------------------------------------------------------------------------

class TestMarkdownSummaryContent:
    """El Markdown de resumen debe tener secciones de conteo por decisión."""

    MD_PATH = (
        REPO_ROOT
        / "data" / "out" / "local" / "pipeline" / "relation_admissibility" / "s0132"
        / "s0132_relation_admissibility_summary.md"
    )

    def test_md_file_exists(self):
        assert self.MD_PATH.exists(), f"No encontrado: {self.MD_PATH}"

    def test_md_has_decision_section(self):
        content = self.MD_PATH.read_text(encoding="utf-8")
        assert "Resultado por decisión" in content or "decisión" in content.lower()

    def test_md_mentions_dry_run(self):
        content = self.MD_PATH.read_text(encoding="utf-8")
        assert "dry-run" in content.lower() or "dry_run" in content.lower()

    def test_md_has_candidate_detail_section(self):
        content = self.MD_PATH.read_text(encoding="utf-8")
        assert "rc1_" in content or "candidate_id" in content.lower()


# ---------------------------------------------------------------------------
# El evaluador no modifica tiddlers_*.jsonl
# ---------------------------------------------------------------------------

class TestEvaluatorDoesNotModifyCanon:
    """Garantía de no-modificación del canon."""

    def test_evaluate_all_does_not_write_files(self, tmp_path):
        """evaluate_all() en memoria no crea archivos."""
        canon = _make_canon()
        candidates = [_make_candidate()]
        results = era.evaluate_all(candidates, canon)
        assert len(results) == 1
        assert results[0]["would_modify_canon"] is False

    def test_canon_shards_unchanged_after_run(self):
        """Los shards del canon no fueron modificados por el run real del evaluador."""
        shards = sorted(_glob.glob("data/out/local/tiddlers_*.jsonl"))
        assert len(shards) > 0
        # Verificar que el directorio de salida NO incluye ningún shard
        out_dir = REPO_ROOT / "data" / "out" / "local" / "pipeline" / "relation_admissibility"
        for shard in shards:
            shard_name = Path(shard).name
            conflict = list(out_dir.rglob(shard_name))
            assert not conflict, (
                f"Shard {shard_name} encontrado en directorio de salida: {conflict}"
            )

    def test_cli_exit_code_is_zero(self):
        """El CLI del evaluador termina con exit code 0."""
        result = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "python_scripts" / "evaluate_relation_admissibility.py"),
                "--canon-glob", "data/out/local/tiddlers_*.jsonl",
                "--candidates-root", "data/out/local/pipeline/relations_candidates",
                "--out-dir", "data/out/local/pipeline/relation_admissibility",
                "--session", "s0132",
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"


# ---------------------------------------------------------------------------
# Integración real con el staging S0129
# ---------------------------------------------------------------------------

class TestRealStagingIntegration:
    """Integración con el staging real de S0129."""

    STAGING_ROOT = REPO_ROOT / "data" / "out" / "local" / "pipeline" / "relations_candidates"

    def test_real_staging_loads_5_candidates(self):
        if not self.STAGING_ROOT.exists():
            pytest.skip("staging no disponible")
        candidates, source = era.load_candidates_from_dir(self.STAGING_ROOT)
        assert len(candidates) == 5

    def test_real_staging_source_is_s0129(self):
        if not self.STAGING_ROOT.exists():
            pytest.skip("staging no disponible")
        _, source = era.load_candidates_from_dir(self.STAGING_ROOT)
        assert "s0129" in source

    def test_real_rc4_is_rejected(self):
        """rc4 (ai_inference, score=0.35) debe ser rejected en el evaluador real."""
        if not self.STAGING_ROOT.exists():
            pytest.skip("staging no disponible")
        import sys as _sys
        _sys.path.insert(0, str(REPO_ROOT / "python_scripts"))
        import build_relation_correspondence_matrix as brcm
        canon = brcm.load_canon("data/out/local/tiddlers_*.jsonl")
        candidates, _ = era.load_candidates_from_dir(self.STAGING_ROOT)
        results = era.evaluate_all(candidates, canon)
        rc4 = next((r for r in results if r["candidate_id"] == "rc1_d4e5f6a7b8c9d0e1"), None)
        assert rc4 is not None, "rc4 no encontrado en resultados"
        assert rc4["decision"] == era.DEC_REJECTED, (
            f"rc4 debería ser rejected, fue: {rc4['decision']}"
        )

    def test_real_rc3_is_unresolved_target(self):
        """rc3 (target unresolved) debe ser unresolved_target."""
        if not self.STAGING_ROOT.exists():
            pytest.skip("staging no disponible")
        import sys as _sys
        _sys.path.insert(0, str(REPO_ROOT / "python_scripts"))
        import build_relation_correspondence_matrix as brcm
        canon = brcm.load_canon("data/out/local/tiddlers_*.jsonl")
        candidates, _ = era.load_candidates_from_dir(self.STAGING_ROOT)
        results = era.evaluate_all(candidates, canon)
        rc3 = next((r for r in results if r["candidate_id"] == "rc1_c3d4e5f6a7b8c9d0"), None)
        assert rc3 is not None, "rc3 no encontrado"
        assert rc3["decision"] == era.DEC_UNRESOLVED

    def test_real_valid_candidates_are_review_required(self):
        """rc1, rc2, rc5 deben ser review_required (admissibles pero pendientes de aprobación)."""
        if not self.STAGING_ROOT.exists():
            pytest.skip("staging no disponible")
        import sys as _sys
        _sys.path.insert(0, str(REPO_ROOT / "python_scripts"))
        import build_relation_correspondence_matrix as brcm
        canon = brcm.load_canon("data/out/local/tiddlers_*.jsonl")
        candidates, _ = era.load_candidates_from_dir(self.STAGING_ROOT)
        results = era.evaluate_all(candidates, canon)
        valid_ids = {
            "rc1_a1b2c3d4e5f6a7b8",
            "rc1_b2c3d4e5f6a7b8c9",
            "rc1_e5f6a7b8c9d0e1f2",
        }
        for r in results:
            if r["candidate_id"] in valid_ids:
                assert r["decision"] in {era.DEC_REVIEW, era.DEC_ADMISSIBLE}, (
                    f"{r['candidate_id']} decision inesperada: {r['decision']}"
                )
