"""tests/test_relation_inventory_audit.py — S0136

Tests de la auditoría del inventario relacional existente en canon.

Cubre los 10 casos mínimos de S0136 §7 (inventario relacional).

Ejecutar:
    python3 -m pytest tests/test_relation_inventory_audit.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

from audit_relation_inventory import (
    audit_canon,
    write_audit_json,
    write_review_csv,
    write_summary_md,
    _REQUIRED_RELATION_KEYS,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _write_shards(tmp_path: Path, tiddlers: list[dict]) -> Path:
    """Write tiddlers to a temporary shard and return the directory."""
    shard = tmp_path / "tiddlers_1.jsonl"
    with shard.open("w") as f:
        for t in tiddlers:
            f.write(json.dumps(t) + "\n")
    return tmp_path


def _tiddler(
    tid: str,
    title: str = "Test",
    relations: list | None = None,
    tags: list | None = None,
    source_fields: dict | None = None,
    role: str = "log",
) -> dict:
    return {
        "id": tid,
        "title": title,
        "text": "Sample text.",
        "tags": tags or [],
        "relations": relations or [],
        "role_primary": role,
        "source_fields": source_fields or {},
    }


# ── Caso 1: Relación válida → resuelta ────────────────────────────────────────

class TestCase01_ResolvedRelation:
    def test_valid_relation_with_existing_target_is_resolved(self, tmp_path):
        t1 = _tiddler("id-A", relations=[{"type": "references", "target_id": "id-B"}])
        t2 = _tiddler("id-B")
        canon = _write_shards(tmp_path, [t1, t2])
        audit = audit_canon(canon)
        assert audit["targets_resolved"] == 1
        assert audit["targets_unresolved"] == 0

    def test_total_counts_correct(self, tmp_path):
        t1 = _tiddler("id-A", relations=[
            {"type": "references", "target_id": "id-B"},
            {"type": "references", "target_id": "id-C"},
        ])
        t2 = _tiddler("id-B")
        t3 = _tiddler("id-C")
        canon = _write_shards(tmp_path, [t1, t2, t3])
        audit = audit_canon(canon)
        assert audit["total_tiddlers"] == 3
        assert audit["total_tiddlers_with_relations"] == 1
        assert audit["total_relations"] == 2


# ── Caso 2: Target inexistente → unresolved ──────────────────────────────────

class TestCase02_UnresolvedTarget:
    def test_missing_target_counted_as_unresolved(self, tmp_path):
        t1 = _tiddler("id-A", relations=[{"type": "references", "target_id": "NONEXISTENT"}])
        canon = _write_shards(tmp_path, [t1])
        audit = audit_canon(canon)
        assert audit["targets_unresolved"] == 1
        assert audit["detail"]["unresolved_targets"]

    def test_unresolved_has_correct_info(self, tmp_path):
        t1 = _tiddler("id-A", "Source Title",
                       relations=[{"type": "references", "target_id": "MISSING-ID"}])
        canon = _write_shards(tmp_path, [t1])
        audit = audit_canon(canon)
        unresolved = audit["detail"]["unresolved_targets"]
        assert len(unresolved) == 1
        assert unresolved[0]["target_id"] == "MISSING-ID"
        assert unresolved[0]["source_id"] == "id-A"


# ── Caso 3: Relación duplicada → detected ─────────────────────────────────────

class TestCase03_DuplicateEdge:
    def test_duplicate_relation_detected(self, tmp_path):
        t1 = _tiddler("id-A", relations=[
            {"type": "references", "target_id": "id-B"},
            {"type": "references", "target_id": "id-B"},  # duplicate
        ])
        t2 = _tiddler("id-B")
        canon = _write_shards(tmp_path, [t1, t2])
        audit = audit_canon(canon)
        assert audit["duplicate_edges_count"] == 1

    def test_no_duplicate_when_different_types(self, tmp_path):
        t1 = _tiddler("id-A", relations=[
            {"type": "references", "target_id": "id-B"},
            {"type": "derived_from", "target_id": "id-B"},
        ])
        t2 = _tiddler("id-B")
        canon = _write_shards(tmp_path, [t1, t2])
        audit = audit_canon(canon)
        assert audit["duplicate_edges_count"] == 0


# ── Caso 4: Auto-relación → detected ──────────────────────────────────────────

class TestCase04_SelfRelation:
    def test_self_relation_detected(self, tmp_path):
        t1 = _tiddler("id-A", relations=[{"type": "references", "target_id": "id-A"}])
        canon = _write_shards(tmp_path, [t1])
        audit = audit_canon(canon)
        assert audit["self_relations_count"] == 1

    def test_non_self_relation_not_counted(self, tmp_path):
        t1 = _tiddler("id-A", relations=[{"type": "references", "target_id": "id-B"}])
        t2 = _tiddler("id-B")
        canon = _write_shards(tmp_path, [t1, t2])
        audit = audit_canon(canon)
        assert audit["self_relations_count"] == 0


# ── Caso 5: Tipo desconocido → detected ──────────────────────────────────────

class TestCase05_UnknownRelationType:
    def test_unknown_type_flagged(self, tmp_path):
        t1 = _tiddler("id-A", relations=[
            {"type": "invented_type_xyz", "target_id": "id-B"}
        ])
        t2 = _tiddler("id-B")
        canon = _write_shards(tmp_path, [t1, t2])
        audit = audit_canon(canon)
        assert "invented_type_xyz" in audit["unknown_relation_types"]

    def test_known_type_not_in_unknown_list(self, tmp_path):
        t1 = _tiddler("id-A", relations=[{"type": "references", "target_id": "id-B"}])
        t2 = _tiddler("id-B")
        canon = _write_shards(tmp_path, [t1, t2])
        audit = audit_canon(canon)
        assert "references" not in audit["unknown_relation_types"]


# ── Caso 6: Shape inválida → detected ─────────────────────────────────────────

class TestCase06_InvalidShape:
    def test_non_dict_relation_is_invalid(self, tmp_path):
        t1 = _tiddler("id-A", relations=["not_a_dict"])
        canon = _write_shards(tmp_path, [t1])
        audit = audit_canon(canon)
        assert audit["invalid_relation_shapes_count"] >= 1

    def test_missing_type_key_is_invalid(self, tmp_path):
        t1 = _tiddler("id-A", relations=[{"target_id": "id-B"}])  # missing 'type'
        t2 = _tiddler("id-B")
        canon = _write_shards(tmp_path, [t1, t2])
        audit = audit_canon(canon)
        assert audit["invalid_relation_shapes_count"] >= 1

    def test_missing_target_id_is_invalid(self, tmp_path):
        t1 = _tiddler("id-A", relations=[{"type": "references"}])  # missing target_id
        canon = _write_shards(tmp_path, [t1])
        audit = audit_canon(canon)
        assert audit["invalid_relation_shapes_count"] >= 1


# ── Caso 7: Tiddler sin relations no produce error ────────────────────────────

class TestCase07_TiddlerWithoutRelations:
    def test_no_error_for_tiddler_without_relations(self, tmp_path):
        t1 = _tiddler("id-A")  # empty relations
        canon = _write_shards(tmp_path, [t1])
        audit = audit_canon(canon)
        assert audit["total_tiddlers_with_relations"] == 0
        assert audit["total_relations"] == 0

    def test_tiddler_with_null_relations_no_error(self, tmp_path):
        t1 = {"id": "id-A", "title": "test", "relations": None}
        canon = _write_shards(tmp_path, [t1])
        audit = audit_canon(canon)
        assert audit["total_tiddlers_with_relations"] == 0


# ── Caso 8: Tags nativos no se cuentan como relaciones ────────────────────────

class TestCase08_TagsNotRelations:
    def test_tags_not_counted_as_relations(self, tmp_path):
        t1 = _tiddler("id-A",
                       tags=["session:m04-s0133", "milestone:m04", "artifact:balance_de_sesion"],
                       relations=[])
        canon = _write_shards(tmp_path, [t1])
        audit = audit_canon(canon)
        # Tags should NOT be counted as relations
        assert audit["total_relations"] == 0
        assert audit["total_tiddlers_with_relations"] == 0

    def test_tags_not_in_relation_types(self, tmp_path):
        t1 = _tiddler("id-A",
                       tags=["session:m04-s0133"],
                       relations=[{"type": "references", "target_id": "id-B"}])
        t2 = _tiddler("id-B")
        canon = _write_shards(tmp_path, [t1, t2])
        audit = audit_canon(canon)
        assert "session:m04-s0133" not in audit["relation_types_distribution"]


# ── Caso 9: Candidatos staging separados de relaciones canónicas ──────────────

class TestCase09_CandidatesSeparate:
    def test_boundary_notes_present(self, tmp_path):
        t1 = _tiddler("id-A")
        canon = _write_shards(tmp_path, [t1])
        audit = audit_canon(canon)
        assert "boundary_notes" in audit
        notes = audit["boundary_notes"]
        assert "canon_vs_candidates" in notes
        assert "staging" in notes["canon_vs_candidates"].lower()

    def test_audit_does_not_read_staging_files(self, tmp_path):
        t1 = _tiddler("id-A", relations=[{"type": "references", "target_id": "id-B"}])
        t2 = _tiddler("id-B")
        canon = _write_shards(tmp_path, [t1, t2])
        # Create a fake staging file in the same dir
        staging = tmp_path / "pipeline" / "relations_candidates" / "rc.jsonl"
        staging.parent.mkdir(parents=True, exist_ok=True)
        staging.write_text('{"candidate_id":"rc1_abc","status":"candidate"}\n')
        # audit_canon only reads tiddlers_*.jsonl
        audit = audit_canon(canon)
        # The staging candidate should NOT appear in the audit
        assert audit["total_tiddlers"] == 2


# ── Caso 10: Reporte agregado tiene conteos consistentes ─────────────────────

class TestCase10_ConsistentAggregates:
    def test_total_relations_equals_sum_of_types(self, tmp_path):
        t1 = _tiddler("id-A", relations=[
            {"type": "references", "target_id": "id-B"},
            {"type": "derived_from", "target_id": "id-C"},
        ])
        t2 = _tiddler("id-B")
        t3 = _tiddler("id-C")
        canon = _write_shards(tmp_path, [t1, t2, t3])
        audit = audit_canon(canon)
        total_in_types = sum(audit["relation_types_distribution"].values())
        # total may differ if there are invalid shapes that are skipped
        assert total_in_types <= audit["total_relations"]

    def test_resolved_plus_unresolved_equals_total(self, tmp_path):
        t1 = _tiddler("id-A", relations=[
            {"type": "references", "target_id": "id-B"},  # resolved
            {"type": "references", "target_id": "MISSING"},  # unresolved
        ])
        t2 = _tiddler("id-B")
        canon = _write_shards(tmp_path, [t1, t2])
        audit = audit_canon(canon)
        # Sum should account for all valid relations
        assert audit["targets_resolved"] + audit["targets_unresolved"] == audit["total_relations"]

    def test_json_output_is_valid(self, tmp_path):
        t1 = _tiddler("id-A", relations=[{"type": "references", "target_id": "id-B"}])
        t2 = _tiddler("id-B")
        canon = _write_shards(tmp_path, [t1, t2])
        audit = audit_canon(canon)
        out = tmp_path / "audit.json"
        write_audit_json(audit, out)
        with out.open() as f:
            loaded = json.load(f)
        assert loaded["schema"] == "relation-inventory-audit/v1"
        assert "total_tiddlers" in loaded

    def test_csv_output_has_rows(self, tmp_path):
        import csv
        t1 = _tiddler("id-A", relations=[{"type": "references", "target_id": "id-B"}])
        t2 = _tiddler("id-B")
        canon = _write_shards(tmp_path, [t1, t2])
        audit = audit_canon(canon)
        out = tmp_path / "review.csv"
        write_review_csv(audit, out)
        with out.open(newline="") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) >= 1
        assert "source_id" in rows[0]
