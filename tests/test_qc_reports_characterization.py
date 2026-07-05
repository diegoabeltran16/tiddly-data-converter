"""
Characterization tests for QC Reports functions — S0119.

Freezes the observable output structure of the 5 write_* QC report functions
before and after the move from derive_layers.py to qc_reports.py.

These tests do NOT run the full pipeline. They call the individual report
functions directly with minimal synthetic inputs and verify field-level
equivalence using non-volatile keys.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "src" / "python_scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from derive_layers import (  # noqa: E402
    write_classification_report,
    write_chunk_qc_report,
    write_retrieval_qc_report,
    write_relations_qc_report,
    write_derivation_report,
)

VOLATILE_KEYS = {"generated_at", "timestamp", "created", "modified", "elapsed", "duration"}


def _load_report(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ── write_classification_report ───────────────────────────────────────────────

class TestWriteClassificationReport:
    def test_file_created(self, tmp_path):
        ai = [{"role_primary": "concept", "title": "T1"},
              {"role_primary": "session", "title": "T2"}]
        enriched = [{"taxonomy_path": "A/B", "section_path": "S1"},
                    {"taxonomy_path": None, "section_path": None}]
        p = write_classification_report(tmp_path, ai, enriched)
        assert p.name == "classification_report.json"
        assert p.exists()

    def test_total_nodes(self, tmp_path):
        ai = [{"role_primary": "concept", "title": f"T{i}"} for i in range(5)]
        enriched = [{"taxonomy_path": None, "section_path": None}] * 5
        p = write_classification_report(tmp_path, ai, enriched)
        assert _load_report(p)["total_nodes"] == 5

    def test_role_distribution(self, tmp_path):
        ai = [{"role_primary": "concept", "title": "T1"},
              {"role_primary": "concept", "title": "T2"},
              {"role_primary": "session", "title": "T3"}]
        enriched = [{"taxonomy_path": None, "section_path": None}] * 3
        report = _load_report(write_classification_report(tmp_path, ai, enriched))
        assert report["role_primary_distribution"]["concept"] == 2
        assert report["role_primary_distribution"]["session"] == 1

    def test_unclassified_count(self, tmp_path):
        ai = [{"role_primary": "unclassified", "title": "U1"},
              {"role_primary": "concept", "title": "C1"}]
        enriched = [{"taxonomy_path": None, "section_path": None}] * 2
        report = _load_report(write_classification_report(tmp_path, ai, enriched))
        assert report["unclassified_count"] == 1

    def test_taxonomy_coverage(self, tmp_path):
        ai = [{"role_primary": "concept", "title": f"T{i}"} for i in range(4)]
        enriched = [{"taxonomy_path": "A/B", "section_path": None},
                    {"taxonomy_path": "C/D", "section_path": None},
                    {"taxonomy_path": None, "section_path": None},
                    {"taxonomy_path": None, "section_path": None}]
        report = _load_report(write_classification_report(tmp_path, ai, enriched))
        assert report["taxonomy_path_coverage"]["nodes_with_taxonomy"] == 2
        assert report["taxonomy_path_coverage"]["total"] == 4

    def test_required_keys(self, tmp_path):
        ai = [{"role_primary": "concept", "title": "T1"}]
        enriched = [{"taxonomy_path": None, "section_path": None}]
        report = _load_report(write_classification_report(tmp_path, ai, enriched))
        for key in ("session", "total_nodes", "role_primary_distribution",
                    "unclassified_count", "unclassified_fraction",
                    "taxonomy_path_coverage", "section_path_coverage", "role_samples"):
            assert key in report, f"Missing key: {key}"


# ── write_chunk_qc_report ─────────────────────────────────────────────────────

def _chunk(node_id="n1", tokens=100, within_target=True, within_hard_max=True):
    return {
        "node_id": node_id,
        "chunk_id": f"chunk-{node_id}",
        "token_estimate": tokens,
        "within_target": within_target,
        "within_hard_max": within_hard_max,
        "fallback": False,
        "source_anchor": "sa",
        "source_id": "si",
        "source_title": "st",
        "source_canonical_slug": "scs",
        "title": "Title",
        "text": "Some text here.",
    }


class TestWriteChunkQcReport:
    def test_file_created(self, tmp_path):
        ai = [{"is_textual_payload": True, "is_chunkable_text": True, "chunk_eligibility": "eligible"}]
        p = write_chunk_qc_report(tmp_path, ai, [_chunk()], [], 1800, 4000)
        assert p.name == "chunk_qc_report.json"
        assert p.exists()

    def test_total_nodes(self, tmp_path):
        ai = [{"is_textual_payload": True, "is_chunkable_text": True, "chunk_eligibility": "eligible"},
              {"is_textual_payload": False, "is_chunkable_text": False, "chunk_eligibility": "excluded"}]
        report = _load_report(write_chunk_qc_report(tmp_path, ai, [], [], 1800, 4000))
        assert report["total_nodes"] == 2

    def test_chunks_above_target(self, tmp_path):
        ai = [{"is_textual_payload": True, "is_chunkable_text": True, "chunk_eligibility": "eligible"}]
        chunks = [_chunk("n1", 2000, within_target=False, within_hard_max=True),
                  _chunk("n2", 100, within_target=True, within_hard_max=True)]
        report = _load_report(write_chunk_qc_report(tmp_path, ai, chunks, [], 1800, 4000))
        assert report["chunks_above_target"] == 1
        assert report["chunks_above_hard_max"] == 0

    def test_hard_max_violated_flag(self, tmp_path):
        ai = [{"is_textual_payload": True, "is_chunkable_text": True, "chunk_eligibility": "eligible"}]
        chunks = [_chunk("n1", 5000, within_target=False, within_hard_max=False)]
        report = _load_report(write_chunk_qc_report(tmp_path, ai, chunks, [], 1800, 4000))
        assert report["hard_max_violated"] is True
        assert report["chunks_above_hard_max"] == 1

    def test_no_violation_when_clean(self, tmp_path):
        ai = [{"is_textual_payload": True, "is_chunkable_text": True, "chunk_eligibility": "eligible"}]
        chunks = [_chunk("n1", 500, within_target=True, within_hard_max=True)]
        report = _load_report(write_chunk_qc_report(tmp_path, ai, chunks, [], 1800, 4000))
        assert report["hard_max_violated"] is False

    def test_required_keys(self, tmp_path):
        ai = [{"is_textual_payload": True, "is_chunkable_text": True, "chunk_eligibility": "eligible"}]
        report = _load_report(write_chunk_qc_report(tmp_path, ai, [], [], 1800, 4000))
        for key in ("session", "total_nodes", "total_chunks_generated", "chunks_above_target",
                    "chunks_above_hard_max", "hard_max_violated", "config", "traceability_summary",
                    "chunk_eligibility_distribution"):
            assert key in report, f"Missing key: {key}"


# ── write_retrieval_qc_report ─────────────────────────────────────────────────

class TestWriteRetrievalQcReport:
    def test_file_created(self, tmp_path):
        ai = [{"retrieval_terms": ["foo"], "retrieval_aliases": [], "retrieval_hints": ["foo"]}]
        p = write_retrieval_qc_report(tmp_path, ai)
        assert p.name == "retrieval_qc_report.json"
        assert p.exists()

    def test_total_nodes(self, tmp_path):
        ai = [{"retrieval_terms": ["a"], "retrieval_aliases": [], "retrieval_hints": ["a"]},
              {"retrieval_terms": [], "retrieval_aliases": [], "retrieval_hints": []}]
        report = _load_report(write_retrieval_qc_report(tmp_path, ai))
        assert report["total_nodes"] == 2

    def test_hint_totals(self, tmp_path):
        ai = [{"retrieval_terms": ["a", "b"], "retrieval_aliases": ["c"], "retrieval_hints": ["a", "b", "c"]},
              {"retrieval_terms": ["d"], "retrieval_aliases": [], "retrieval_hints": ["d"]}]
        report = _load_report(write_retrieval_qc_report(tmp_path, ai))
        assert report["total_retrieval_terms"] == 3
        assert report["total_retrieval_aliases"] == 1
        assert report["total_retrieval_hints"] == 4

    def test_nodes_with_empty_hints(self, tmp_path):
        ai = [{"retrieval_terms": ["a"], "retrieval_aliases": [], "retrieval_hints": ["a"]},
              {"retrieval_terms": [], "retrieval_aliases": [], "retrieval_hints": []}]
        report = _load_report(write_retrieval_qc_report(tmp_path, ai))
        assert report["nodes_with_empty_hints"] == 1

    def test_nodes_with_aliases(self, tmp_path):
        ai = [{"retrieval_terms": ["a"], "retrieval_aliases": ["b"], "retrieval_hints": ["a", "b"]},
              {"retrieval_terms": ["c"], "retrieval_aliases": [], "retrieval_hints": ["c"]}]
        report = _load_report(write_retrieval_qc_report(tmp_path, ai))
        assert report["nodes_with_aliases"] == 1

    def test_required_keys(self, tmp_path):
        ai = [{"retrieval_terms": [], "retrieval_aliases": [], "retrieval_hints": []}]
        report = _load_report(write_retrieval_qc_report(tmp_path, ai))
        for key in ("session", "total_nodes", "total_retrieval_hints", "total_retrieval_terms",
                    "total_retrieval_aliases", "nodes_with_aliases", "nodes_with_empty_hints",
                    "avg_hints_per_node", "dedup_resolved_count"):
            assert key in report, f"Missing key: {key}"


# ── write_relations_qc_report ─────────────────────────────────────────────────

class TestWriteRelationsQcReport:
    def test_file_created(self, tmp_path):
        ai = [{"relation_targets": [{"type": "parent"}]}]
        p = write_relations_qc_report(tmp_path, ai, [])
        assert p.name == "relations_qc_report.json"
        assert p.exists()

    def test_total_valid_relations(self, tmp_path):
        ai = [{"relation_targets": [{"type": "parent"}, {"type": "child"}]},
              {"relation_targets": [{"type": "sibling"}]}]
        report = _load_report(write_relations_qc_report(tmp_path, ai, []))
        assert report["total_valid_relations"] == 3

    def test_invalid_relations_count(self, tmp_path):
        ai = [{"relation_targets": []}]
        invalid = [{"type": "parent", "reason": "unknown_id", "relation_source": "manual"},
                   {"type": "child", "reason": "unknown_id", "relation_source": "manual"}]
        report = _load_report(write_relations_qc_report(tmp_path, ai, invalid))
        assert report["total_invalid_relations_discarded"] == 2
        assert report["invalid_relation_reason_distribution"]["unknown_id"] == 2

    def test_relation_type_distribution(self, tmp_path):
        ai = [{"relation_targets": [{"type": "parent"}, {"type": "parent"}, {"type": "child"}]}]
        report = _load_report(write_relations_qc_report(tmp_path, ai, []))
        assert report["relation_type_distribution"]["parent"] == 2
        assert report["relation_type_distribution"]["child"] == 1

    def test_required_keys(self, tmp_path):
        ai = [{"relation_targets": []}]
        report = _load_report(write_relations_qc_report(tmp_path, ai, []))
        for key in ("session", "total_nodes", "total_valid_relations",
                    "total_invalid_relations_discarded", "relation_type_distribution",
                    "invalid_relation_reason_distribution", "invalid_relation_source_distribution",
                    "invalid_relation_samples", "chunk_relation_type_distribution"):
            assert key in report, f"Missing key: {key}"


# ── write_derivation_report ───────────────────────────────────────────────────

class TestWriteDerivationReport:
    def _args(self):
        canon = [({"content_type": "note"}, None, None),
                 ({"content_type": "session"}, None, None)]
        enriched = [{"field": "x"}, {"field": "y"}]
        ai = [{"role_primary": "concept", "corpus_state": "active", "corpus_state_rule_id": "r1"},
              {"role_primary": "session", "corpus_state": "active", "corpus_state_rule_id": "r1"}]
        chunks = []
        shard_paths = [Path("tiddlers_1.jsonl")]
        return canon, enriched, ai, chunks, shard_paths

    def test_file_created(self, tmp_path):
        p = write_derivation_report(tmp_path, *self._args(), 1800, 4000)
        assert p.name == "derivation_report.json"
        assert p.exists()

    def test_input_counts(self, tmp_path):
        report = _load_report(write_derivation_report(tmp_path, *self._args(), 1800, 4000))
        assert report["input"]["total_records"] == 2
        assert report["input"]["canon_shard_count"] == 1

    def test_output_counts(self, tmp_path):
        report = _load_report(write_derivation_report(tmp_path, *self._args(), 1800, 4000))
        assert report["output"]["enriched_records"] == 2
        assert report["output"]["ai_records"] == 2
        assert report["output"]["total_chunks"] == 0

    def test_identity_check_matching(self, tmp_path):
        report = _load_report(write_derivation_report(tmp_path, *self._args(), 1800, 4000))
        assert report["identity_check"]["ids_match"] is True

    def test_identity_check_mismatch(self, tmp_path):
        canon = [({"content_type": "note"}, None, None),
                 ({"content_type": "session"}, None, None),
                 ({"content_type": "contract"}, None, None)]
        enriched = [{"x": 1}, {"x": 2}]
        ai = [{"role_primary": "concept", "corpus_state": "active", "corpus_state_rule_id": "r1"},
              {"role_primary": "concept", "corpus_state": "active", "corpus_state_rule_id": "r1"}]
        report = _load_report(
            write_derivation_report(tmp_path, canon, enriched, ai, [], [Path("t1.jsonl")], 1800, 4000)
        )
        assert report["identity_check"]["ids_match"] is False

    def test_content_type_distribution(self, tmp_path):
        report = _load_report(write_derivation_report(tmp_path, *self._args(), 1800, 4000))
        assert report["content_type_distribution"]["note"] == 1
        assert report["content_type_distribution"]["session"] == 1

    def test_required_keys(self, tmp_path):
        report = _load_report(write_derivation_report(tmp_path, *self._args(), 1800, 4000))
        for key in ("session", "schema_version", "input", "output", "identity_check",
                    "classification_summary", "governance", "content_type_distribution",
                    "chunking_summary", "hardening_notes"):
            assert key in report, f"Missing key: {key}"
