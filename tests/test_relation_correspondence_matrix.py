"""
tests/test_relation_correspondence_matrix.py — S0130

Pruebas mínimas para build_relation_correspondence_matrix.py.

Cobertura obligatoria (10 casos):
  1.  Tiddler con tag nativo pero sin metadata relacional.
  2.  Tiddler con metadata rica pero sin candidato relacional.
  3.  Candidato con source y target válidos → candidate_only.
  4.  Candidato con target unresolved.
  5.  Candidato sin evidence excerpt.
  6.  Candidato duplicado (staging_category=duplicate).
  7.  Caso alineado: candidato válido + relación canónica existente → metadata_candidate_aligned.
  8.  Caso conflictivo: candidato inválido → conflict.
  9.  Ejecución CLI con directorio de candidatos inexistente → matriz vacía sin error.
  10. Garantía dry-run: el script no modifica tiddlers_*.jsonl.
"""

import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "python_scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import build_relation_correspondence_matrix as brcm

# ---------------------------------------------------------------------------
# Fixtures de mini-canon controlado
# ---------------------------------------------------------------------------

SRC_ID = "src-0000aaaa1111bbbb"
TGT_ID = "tgt-cccc2222dddd3333"
OTHER_ID = "other-eeee4444ffff5555"


def _make_tiddler(tid: str, title: str = "Test Tiddler", **overrides: Any) -> dict:
    base = {
        "id": tid,
        "title": title,
        "canonical_slug": title.lower().replace(" ", "-"),
        "tags": ["layer:session", "milestone:m04"],
        "text": "Texto de ejemplo para el tiddler de prueba.",
        "semantic_text": "Texto semántico de ejemplo.",
        "role_primary": "log",
        "source_fields": {"field_a": "val_a", "field_b": "val_b", "field_c": "val_c", "field_d": "val_d"},
        "relations": [],
    }
    base.update(overrides)
    return base


def _make_candidate(
    cid: str = "rc1_aabb1122334455667788",
    src_id: str = SRC_ID,
    tgt_id: str = TGT_ID,
    staging_cat: str = "valid",
    score: float = 0.85,
    excerpt: str = "texto de evidencia",
    ev_kind: str = "explicit_reference",
    resolution: str = "resolved",
    **overrides: Any,
) -> dict:
    base: dict = {
        "candidate_id": cid,
        "status": "candidate",
        "_staging_category": staging_cat,
        "source": {
            "tiddler_id": src_id,
            "title": "Source title",
            "field_path": "text",
        },
        "target": {
            "tiddler_id": tgt_id if resolution != "unresolved" else None,
            "title": "Target title",
            "resolution_status": resolution,
        },
        "relation": {"type": "referencia_a", "direction": "source_to_target"},
        "evidence": {"kind": ev_kind, "excerpt": excerpt, "location": "text/test"},
        "confidence": {"score": score, "method": "rule_based"},
        "provenance": {"generated_by": "test", "generated_at": "2026-05-27T00:00:00Z"},
        "created_at": "2026-05-27T00:00:00Z",
    }
    base.update(overrides)
    return base


def _mini_canon(*records: dict) -> dict[str, dict]:
    return {r["id"]: r for r in records}


# ===========================================================================
# Test 1 — Tiddler con tag nativo pero sin metadata relacional
# ===========================================================================
class TestTagOnlyTiddler:
    def test_tag_only_tiddler_classified_correctly(self):
        """Tiddler con tags y texto pero sin relaciones → metadata_partial."""
        r = _make_tiddler(SRC_ID, relations=[])
        density = brcm.classify_metadata_density(r)
        assert density in (brcm.DENSITY_PARTIAL, brcm.DENSITY_CONDENSED)

    def test_tag_only_normalized(self):
        r = _make_tiddler(SRC_ID, tags=["layer:session", "Milestone:M04", "  artifact:balance  "])
        norm = brcm.normalize_tags(r["tags"])
        assert "layer:session" in norm
        assert "milestone:m04" in norm
        assert "artifact:balance" in norm

    def test_tiddler_without_relations_has_zero_canonical_targets(self):
        r = _make_tiddler(SRC_ID, relations=[])
        ids = brcm.extract_canonical_relation_target_ids(r)
        assert ids == set()


# ===========================================================================
# Test 2 — Tiddler con metadata rica pero sin candidato
# ===========================================================================
class TestMetadataRichNoCandidates:
    def test_rich_tiddler_classified_as_rich(self):
        """Tiddler con source_fields + relaciones → metadata_rich."""
        r = _make_tiddler(
            SRC_ID,
            relations=[{"type": "references", "target_id": TGT_ID, "evidence": "wikilink"}],
            source_fields={"a": 1, "b": 2, "c": 3, "d": 4},
        )
        density = brcm.classify_metadata_density(r)
        assert density == brcm.DENSITY_RICH

    def test_matrix_with_no_candidates_is_empty(self):
        canon = _mini_canon(_make_tiddler(SRC_ID))
        matrix = brcm.build_matrix(canon, candidates=[])
        assert matrix == []

    def test_canonical_relation_target_ids_extracted(self):
        r = _make_tiddler(
            SRC_ID,
            relations=[
                {"type": "references", "target_id": TGT_ID, "evidence": "wikilink"},
                {"type": "references", "target_id": OTHER_ID, "evidence": "structural_tag"},
            ],
        )
        ids = brcm.extract_canonical_relation_target_ids(r)
        assert ids == {TGT_ID, OTHER_ID}


# ===========================================================================
# Test 3 — Candidato con source y target válidos → candidate_only
# ===========================================================================
class TestValidCandidateOnly:
    def test_valid_candidate_no_canon_relation_is_candidate_only(self):
        """Candidato válido cuyo source no tiene relación canónica → candidate_only."""
        canon = _mini_canon(
            _make_tiddler(SRC_ID, relations=[]),  # sin relaciones canónicas
            _make_tiddler(TGT_ID, title="Target"),
        )
        cand = _make_candidate()
        matrix = brcm.build_matrix(canon, [cand])
        assert len(matrix) == 1
        assert matrix[0]["correspondence_status"] == brcm.CORR_CANDIDATE_ONLY
        assert matrix[0]["risk_level"] == brcm.RISK_MEDIUM
        assert matrix[0]["recommended_action"] == "human_review_before_admission"

    def test_valid_candidate_preserves_candidate_id(self):
        canon = _mini_canon(_make_tiddler(SRC_ID), _make_tiddler(TGT_ID))
        cand = _make_candidate(cid="rc1_xxyyzz1122334455")
        matrix = brcm.build_matrix(canon, [cand])
        assert matrix[0]["candidate_id"] == "rc1_xxyyzz1122334455"


# ===========================================================================
# Test 4 — Candidato con target unresolved
# ===========================================================================
class TestUnresolvedTarget:
    def test_unresolved_candidate_is_classified_correctly(self):
        canon = _mini_canon(_make_tiddler(SRC_ID))
        cand = _make_candidate(
            tgt_id="",
            resolution="unresolved",
            staging_cat="unresolved_target",
        )
        matrix = brcm.build_matrix(canon, [cand])
        assert matrix[0]["correspondence_status"] == brcm.CORR_UNRESOLVED
        assert matrix[0]["risk_level"] == brcm.RISK_MEDIUM
        assert matrix[0]["recommended_action"] == "resolve_target_id_before_admission"

    def test_unresolved_details_show_target_not_in_canon(self):
        canon = _mini_canon(_make_tiddler(SRC_ID))
        cand = _make_candidate(
            tgt_id="",
            resolution="unresolved",
            staging_cat="unresolved_target",
        )
        matrix = brcm.build_matrix(canon, [cand])
        assert matrix[0]["correspondence_details"]["target_in_canon"] is False


# ===========================================================================
# Test 5 — Candidato sin evidence excerpt → missing_evidence
# ===========================================================================
class TestMissingEvidence:
    def test_empty_excerpt_is_missing_evidence(self):
        canon = _mini_canon(_make_tiddler(SRC_ID), _make_tiddler(TGT_ID))
        cand = _make_candidate(excerpt="", staging_cat="valid")
        matrix = brcm.build_matrix(canon, [cand])
        assert matrix[0]["correspondence_status"] == brcm.CORR_MISSING_EVIDENCE
        assert matrix[0]["risk_level"] == brcm.RISK_HIGH

    def test_whitespace_only_excerpt_is_missing_evidence(self):
        canon = _mini_canon(_make_tiddler(SRC_ID), _make_tiddler(TGT_ID))
        cand = _make_candidate(excerpt="   ", staging_cat="valid")
        matrix = brcm.build_matrix(canon, [cand])
        assert matrix[0]["correspondence_status"] == brcm.CORR_MISSING_EVIDENCE


# ===========================================================================
# Test 6 — Candidato duplicado → duplicate_candidate
# ===========================================================================
class TestDuplicateCandidate:
    def test_duplicate_staging_category_classified_correctly(self):
        canon = _mini_canon(_make_tiddler(SRC_ID), _make_tiddler(TGT_ID))
        cand = _make_candidate(staging_cat="duplicate")
        matrix = brcm.build_matrix(canon, [cand])
        assert matrix[0]["correspondence_status"] == brcm.CORR_DUPLICATE
        assert matrix[0]["risk_level"] == brcm.RISK_MEDIUM
        assert "deduplicate" in matrix[0]["recommended_action"]


# ===========================================================================
# Test 7 — Caso alineado: candidato + relación canónica existente
# ===========================================================================
class TestAlignedCandidate:
    def test_candidate_with_existing_canonical_relation_is_meta_cand_aligned(self):
        """Candidato cuyo source ya tiene relación canónica al mismo target → metadata_candidate_aligned."""
        canon = _mini_canon(
            _make_tiddler(
                SRC_ID,
                relations=[{"type": "references", "target_id": TGT_ID, "evidence": "wikilink"}],
            ),
            _make_tiddler(TGT_ID),
        )
        cand = _make_candidate()
        matrix = brcm.build_matrix(canon, [cand])
        assert matrix[0]["correspondence_status"] == brcm.CORR_META_CAND_ALIGNED
        assert matrix[0]["risk_level"] == brcm.RISK_LOW
        assert matrix[0]["correspondence_details"]["target_already_in_canonical_relations"] is True

    def test_aligned_candidate_has_low_risk(self):
        canon = _mini_canon(
            _make_tiddler(
                SRC_ID,
                relations=[{"type": "references", "target_id": TGT_ID, "evidence": "wikilink"}],
            ),
            _make_tiddler(TGT_ID),
        )
        cand = _make_candidate()
        matrix = brcm.build_matrix(canon, [cand])
        assert matrix[0]["risk_level"] == brcm.RISK_LOW
        assert matrix[0]["recommended_action"] == "admit_when_governed_circuit_ready"


# ===========================================================================
# Test 8 — Caso conflictivo: candidato inválido
# ===========================================================================
class TestConflictCandidate:
    def test_invalid_staging_category_is_conflict(self):
        canon = _mini_canon(_make_tiddler(SRC_ID), _make_tiddler(TGT_ID))
        cand = _make_candidate(staging_cat="invalid", score=0.35, ev_kind="ai_inference")
        matrix = brcm.build_matrix(canon, [cand])
        assert matrix[0]["correspondence_status"] == brcm.CORR_CONFLICT
        assert matrix[0]["risk_level"] == brcm.RISK_HIGH
        assert "discard" in matrix[0]["recommended_action"]

    def test_conflict_details_contain_reason(self):
        canon = _mini_canon(_make_tiddler(SRC_ID), _make_tiddler(TGT_ID))
        cand = _make_candidate(staging_cat="invalid")
        matrix = brcm.build_matrix(canon, [cand])
        assert matrix[0]["correspondence_details"].get("reason") == "invalid_by_validator"


# ===========================================================================
# Test 9 — CLI con directorio de candidatos inexistente → matriz vacía
# ===========================================================================
class TestMissingCandidatesDir:
    def test_missing_dir_produces_empty_candidates(self):
        """Directorio de candidatos ausente → candidates=[] sin crash."""
        with tempfile.TemporaryDirectory() as tmp:
            nonexistent = Path(tmp) / "does_not_exist"
            candidates = brcm.load_candidates_from_dir(nonexistent)
            assert candidates == []

    def test_cli_with_missing_candidates_dir_exits_ok(self):
        """El CLI completa normalmente aunque no haya candidatos."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_p = Path(tmp)
            # Crear un mini-shard
            shard = tmp_p / "tiddlers_1.jsonl"
            shard.write_text(
                json.dumps(_make_tiddler(SRC_ID)) + "\n", encoding="utf-8"
            )
            out_dir = tmp_p / "output"
            result = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "python_scripts" / "build_relation_correspondence_matrix.py"),
                    "--canon-glob", str(tmp_p / "tiddlers_*.jsonl"),
                    "--candidates-root", str(tmp_p / "nonexistent"),
                    "--out-dir", str(out_dir),
                    "--session", "test",
                    "--dry-run",
                ],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
            )
            assert result.returncode == 0, f"stderr: {result.stderr}"
            # Debe generar los 3 archivos
            assert (out_dir / "test" / "test_relation_correspondence_matrix.json").exists()
            assert (out_dir / "test" / "test_relation_correspondence_summary.md").exists()
            assert (out_dir / "test" / "test_relation_correspondence_review.csv").exists()

    def test_cli_with_missing_candidates_dir_produces_empty_matrix(self):
        """Con sin candidatos, la matriz JSON tiene 0 entradas."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_p = Path(tmp)
            shard = tmp_p / "tiddlers_1.jsonl"
            shard.write_text(
                json.dumps(_make_tiddler(SRC_ID)) + "\n", encoding="utf-8"
            )
            out_dir = tmp_p / "output"
            subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "python_scripts" / "build_relation_correspondence_matrix.py"),
                    "--canon-glob", str(tmp_p / "tiddlers_*.jsonl"),
                    "--candidates-root", str(tmp_p / "nonexistent"),
                    "--out-dir", str(out_dir),
                    "--session", "test",
                    "--dry-run",
                ],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
            )
            report = json.loads(
                (out_dir / "test" / "test_relation_correspondence_matrix.json").read_text()
            )
            assert report["matrix"] == []
            assert report["matrix_summary"]["total_candidates_analyzed"] == 0


# ===========================================================================
# Test 10 — Garantía dry-run: el script no modifica tiddlers_*.jsonl
# ===========================================================================
class TestDryRunGuarantee:
    def test_script_does_not_modify_canon(self):
        """Ejecutar el script real no debe cambiar ningún shard del canon."""
        canon_root = REPO_ROOT / "data" / "out" / "local"
        shards = sorted(canon_root.glob("tiddlers_*.jsonl"))
        if not shards:
            pytest.skip("canon no disponible")

        # Capturar hashes antes
        before = {p.name: p.read_bytes() for p in shards}

        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "python_scripts" / "build_relation_correspondence_matrix.py"),
                    "--canon-glob", "data/out/local/tiddlers_*.jsonl",
                    "--candidates-root", "data/out/local/pipeline/relations_candidates",
                    "--out-dir", str(Path(tmp) / "out"),
                    "--session", "dryruntest",
                    "--dry-run",
                ],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
            )

        after = {p.name: p.read_bytes() for p in shards}
        assert before == after, "El script modificó archivos del canon — error grave"

    def test_apply_flag_is_blocked(self):
        """El flag --apply debe ser bloqueado y retornar código 2."""
        result = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "python_scripts" / "build_relation_correspondence_matrix.py"),
                "--canon-glob", "data/out/local/tiddlers_*.jsonl",
                "--candidates-root", "data/out/local/pipeline/relations_candidates",
                "--out-dir", "/tmp/test_out",
                "--session", "test",
                "--dry-run",
                "--apply",
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 2
        assert "bloqueado" in result.stderr.lower() or "apply" in result.stderr.lower()


# ===========================================================================
# Casos adicionales — build_json_report y build_csv
# ===========================================================================
class TestReportGeneration:
    def _minimal_matrix_entry(self) -> dict:
        cand = _make_candidate()
        canon = _mini_canon(_make_tiddler(SRC_ID), _make_tiddler(TGT_ID))
        matrix = brcm.build_matrix(canon, [cand])
        return matrix[0]

    def test_json_report_has_correct_schema(self):
        entry = self._minimal_matrix_entry()
        canon_summary = brcm.build_canon_metadata_summary(
            _mini_canon(_make_tiddler(SRC_ID))
        )
        report = brcm.build_json_report([entry], canon_summary, "test", "/tmp/cands")
        assert report["schema"] == "relation-correspondence-matrix/v1"
        assert report["dry_run"] is True
        assert "matrix" in report
        assert "matrix_summary" in report
        assert "canon_summary" in report

    def test_json_report_summary_counts_correctly(self):
        canon = _mini_canon(_make_tiddler(SRC_ID), _make_tiddler(TGT_ID))
        c1 = _make_candidate(cid="rc1_aabb1122334455667788", staging_cat="valid")
        c2 = _make_candidate(cid="rc1_bbcc2233445566778899", staging_cat="invalid")
        matrix = brcm.build_matrix(canon, [c1, c2])
        canon_summary = brcm.build_canon_metadata_summary(
            _mini_canon(_make_tiddler(SRC_ID))
        )
        report = brcm.build_json_report(matrix, canon_summary, "test", "/tmp")
        assert report["matrix_summary"]["total_candidates_analyzed"] == 2

    def test_csv_has_all_required_columns(self):
        entry = self._minimal_matrix_entry()
        csv_content = brcm.build_csv([entry])
        reader = csv.DictReader(csv_content.splitlines())
        required = {
            "candidate_id", "source_title", "candidate_target_title",
            "candidate_relation_type", "candidate_confidence_score",
            "correspondence_status", "risk_level", "recommended_action",
        }
        assert required.issubset(set(reader.fieldnames or []))

    def test_markdown_summary_contains_expected_sections(self):
        canon = _mini_canon(_make_tiddler(SRC_ID), _make_tiddler(TGT_ID))
        cand = _make_candidate()
        matrix = brcm.build_matrix(canon, [cand])
        canon_summary = brcm.build_canon_metadata_summary(
            _mini_canon(_make_tiddler(SRC_ID))
        )
        md = brcm.build_markdown_summary(matrix, canon_summary, "s0130")
        assert "## 1. Resumen del canon" in md
        assert "## 2. Análisis de candidatos" in md
        assert "## 3. Detalle por candidato" in md
        assert "## 4. Recomendación para S0131" in md

    def test_csv_is_parseable(self):
        canon = _mini_canon(_make_tiddler(SRC_ID), _make_tiddler(TGT_ID))
        cands = [
            _make_candidate(cid="rc1_aabb1122334455667788"),
            _make_candidate(cid="rc1_bbcc2233445566778899", staging_cat="invalid"),
        ]
        matrix = brcm.build_matrix(canon, cands)
        csv_content = brcm.build_csv(matrix)
        rows = list(csv.DictReader(csv_content.splitlines()))
        assert len(rows) == 2
        for row in rows:
            assert row["candidate_id"].startswith("rc1_")


# ===========================================================================
# Integración con el sample real de S0129
# ===========================================================================
class TestRealStagingIntegration:
    def test_real_sample_produces_5_entries(self):
        """El validador real produce una matriz con 5 entradas (todos los candidatos de S0125)."""
        candidates_root = REPO_ROOT / "data" / "out" / "local" / "pipeline" / "relations_candidates"
        if not candidates_root.exists():
            pytest.skip("staging no disponible")
        candidates = brcm.load_candidates_from_dir(candidates_root)
        assert len(candidates) == 5

    def test_real_matrix_has_no_aligned_entries(self):
        """Los candidatos del staging actual no tienen relaciones canónicas previas → no aligned."""
        candidates_root = REPO_ROOT / "data" / "out" / "local" / "pipeline" / "relations_candidates"
        if not candidates_root.exists():
            pytest.skip("staging no disponible")
        canon = brcm.load_canon("data/out/local/tiddlers_*.jsonl")
        candidates = brcm.load_candidates_from_dir(candidates_root)
        matrix = brcm.build_matrix(canon, candidates)
        aligned = [e for e in matrix if e["correspondence_status"] == brcm.CORR_ALIGNED]
        assert aligned == [], f"Se esperaba 0 aligned, encontrado: {len(aligned)}"

    def test_real_matrix_has_conflict_for_rc4(self):
        """rc4 debe aparecer como conflict (invalid por validator)."""
        candidates_root = REPO_ROOT / "data" / "out" / "local" / "pipeline" / "relations_candidates"
        if not candidates_root.exists():
            pytest.skip("staging no disponible")
        canon = brcm.load_canon("data/out/local/tiddlers_*.jsonl")
        candidates = brcm.load_candidates_from_dir(candidates_root)
        matrix = brcm.build_matrix(canon, candidates)
        # rc4 en staging tiene candidate_id "rc1_d4e5f6a7b8c9d0e1" (invalid_candidates.jsonl)
        rc4 = next((e for e in matrix if e["candidate_id"] == "rc1_d4e5f6a7b8c9d0e1"), None)
        assert rc4 is not None, "rc4 (rc1_d4e5f6a7b8c9d0e1) not found in matrix"
        assert rc4["correspondence_status"] == brcm.CORR_CONFLICT
