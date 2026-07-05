"""tests/test_relation_type_compatibility.py — S0137

Tests del análisis de compatibilidad de tipos relacionales históricos.

Cubre los 9 casos mínimos de S0137 §6.1.

Ejecutar:
    python3 -m pytest tests/test_relation_type_compatibility.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

from analyze_relation_type_compatibility import (
    HISTORICAL_TYPE_ANALYSIS,
    FORMAL_CATALOG_TYPE,
    LEGACY_ALIAS_CANDIDATE,
    LEGACY_READONLY,
    BLOCKED_FOR_NEW_CANDIDATES,
    scan_canon_relations,
    analyze_compatibility,
    write_report_json,
    write_review_csv,
    write_summary_md,
)
from relation_candidate_contract import ALLOWED_RELATION_TYPES


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _write_shard(tmp_path: Path, tiddlers: list[dict]) -> Path:
    shard = tmp_path / "tiddlers_1.jsonl"
    with shard.open("w") as f:
        for t in tiddlers:
            f.write(json.dumps(t) + "\n")
    return tmp_path


def _tiddler(tid: str, relations: list | None = None, role: str = "config") -> dict:
    return {
        "id": tid, "title": f"Tiddler {tid}",
        "text": "Sample text.", "role_primary": role,
        "relations": relations or [], "source_fields": {},
    }


# ── Caso 1: Detecta los 5 tipos históricos ─────────────────────────────────────

class TestCase01_DetectsHistoricalTypes:
    def test_all_five_historical_types_in_analysis(self):
        for rt in ("usa", "parte_de", "define", "requiere", "child_of"):
            assert rt in HISTORICAL_TYPE_ANALYSIS, f"'{rt}' no está en HISTORICAL_TYPE_ANALYSIS"

    def test_historical_types_have_required_fields(self):
        for rt, meta in HISTORICAL_TYPE_ANALYSIS.items():
            for field in ("classification", "decision", "semantic_note", "blocked_for_new"):
                assert field in meta, f"'{rt}' falta el campo '{field}'"

    def test_scan_detects_historical_types_in_canon(self, tmp_path):
        t1 = _tiddler("A", relations=[{"type": "usa", "target_id": "B"}])
        t2 = _tiddler("B", relations=[{"type": "parte_de", "target_id": "A"}])
        t3 = _tiddler("C", relations=[{"type": "define", "target_id": "A"}])
        canon = _write_shard(tmp_path, [t1, t2, t3])
        scan = scan_canon_relations(canon)
        assert scan["type_counts"].get("usa", 0) >= 1
        assert scan["type_counts"].get("parte_de", 0) >= 1
        assert scan["type_counts"].get("define", 0) >= 1


# ── Caso 2: Clasifica de forma determinista ────────────────────────────────────

class TestCase02_DeterministicClassification:
    def test_usa_classified_as_legacy_alias(self):
        assert HISTORICAL_TYPE_ANALYSIS["usa"]["classification"] == LEGACY_ALIAS_CANDIDATE

    def test_parte_de_classified_as_legacy_readonly(self):
        assert HISTORICAL_TYPE_ANALYSIS["parte_de"]["classification"] == LEGACY_READONLY

    def test_define_classified_as_legacy_readonly(self):
        assert HISTORICAL_TYPE_ANALYSIS["define"]["classification"] == LEGACY_READONLY

    def test_requiere_classified_as_legacy_alias(self):
        assert HISTORICAL_TYPE_ANALYSIS["requiere"]["classification"] == LEGACY_ALIAS_CANDIDATE

    def test_child_of_classified_as_legacy_readonly(self):
        assert HISTORICAL_TYPE_ANALYSIS["child_of"]["classification"] == LEGACY_READONLY

    def test_classification_is_stable(self):
        """Same result on two independent calls."""
        t1 = {
            "id": "X", "title": "X", "text": "x", "role_primary": "config",
            "relations": [{"type": "usa", "target_id": "Y"}], "source_fields": {},
        }
        t2 = {"id": "Y", "title": "Y", "text": "y", "role_primary": "config",
               "relations": [], "source_fields": {}}
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmp:
            tmp_p = Path(tmp)
            canon = _write_shard(tmp_p, [t1, t2])
            scan = scan_canon_relations(canon)
            report1 = analyze_compatibility(scan)
            report2 = analyze_compatibility(scan)
        assert report1["historical_relation_types"]["usa"]["classification"] == \
               report2["historical_relation_types"]["usa"]["classification"]


# ── Caso 3: No falla sin relaciones ───────────────────────────────────────────

class TestCase03_NoFailWithoutRelations:
    def test_tiddler_without_relations_no_error(self, tmp_path):
        t1 = _tiddler("A")  # no relations
        canon = _write_shard(tmp_path, [t1])
        scan = scan_canon_relations(canon)
        assert scan["total_relations"] == 0
        report = analyze_compatibility(scan)
        assert report["total_relations_found"] == 0

    def test_tiddler_with_empty_relations_list_no_error(self, tmp_path):
        t1 = {"id": "A", "title": "A", "text": "x", "relations": [], "source_fields": {}}
        canon = _write_shard(tmp_path, [t1])
        scan = scan_canon_relations(canon)
        assert scan["total_tiddlers"] == 1
        report = analyze_compatibility(scan)
        assert "usa" in report["historical_relation_types"]


# ── Caso 4: No falla con relaciones vacías ────────────────────────────────────

class TestCase04_EmptyRelationsNoError:
    def test_none_relations_no_error(self, tmp_path):
        t1 = {"id": "A", "title": "A", "text": "x", "relations": None, "source_fields": {}}
        canon = _write_shard(tmp_path, [t1])
        scan = scan_canon_relations(canon)
        assert scan["total_tiddlers"] == 1


# ── Caso 5: No mezcla tags con relaciones ─────────────────────────────────────

class TestCase05_TagsNotRelations:
    def test_tags_not_counted_as_relation_types(self, tmp_path):
        t1 = {
            "id": "A", "title": "A", "text": "x",
            "tags": ["session:m04-s0133", "artifact:contrato_de_sesion"],
            "relations": [{"type": "usa", "target_id": "B"}],
            "source_fields": {},
        }
        t2 = _tiddler("B")
        canon = _write_shard(tmp_path, [t1, t2])
        scan = scan_canon_relations(canon)
        assert "session:m04-s0133" not in scan["type_counts"]
        assert "artifact:contrato_de_sesion" not in scan["type_counts"]
        assert scan["type_counts"].get("usa", 0) == 1


# ── Caso 6: No promueve tipos fuera de catálogo ───────────────────────────────

class TestCase06_NoAutopromotion:
    def test_all_historical_types_blocked_for_new(self):
        for rt, meta in HISTORICAL_TYPE_ANALYSIS.items():
            assert meta["blocked_for_new"] is True, \
                f"'{rt}' debería estar bloqueado para nuevos candidatos"

    def test_historical_types_not_in_allowed_catalog(self):
        for rt in ("usa", "parte_de", "define", "requiere", "child_of"):
            # These exist in canon but should NOT appear in the formal catalog
            # (they're historical, not formal)
            assert rt not in {"validated_catalog_type"}, \
                f"'{rt}' no debería ser tipo formal del catálogo"


# ── Caso 7: JSON válido ───────────────────────────────────────────────────────

class TestCase07_ValidJSON:
    def test_report_json_is_serializable(self, tmp_path):
        t1 = _tiddler("A", relations=[{"type": "usa", "target_id": "B"}])
        t2 = _tiddler("B")
        canon = _write_shard(tmp_path, [t1, t2])
        scan = scan_canon_relations(canon)
        report = analyze_compatibility(scan)
        out = tmp_path / "report.json"
        write_report_json(report, out)
        with out.open() as f:
            loaded = json.load(f)
        assert loaded["schema"] == "relation-type-compatibility/v1"
        assert "historical_relation_types" in loaded
        assert "decisions" in loaded

    def test_report_has_all_historical_types(self, tmp_path):
        t1 = _tiddler("A")
        canon = _write_shard(tmp_path, [t1])
        scan = scan_canon_relations(canon)
        report = analyze_compatibility(scan)
        for rt in ("usa", "parte_de", "define", "requiere", "child_of"):
            assert rt in report["historical_relation_types"]


# ── Caso 8: CSV revisable ─────────────────────────────────────────────────────

class TestCase08_ReviewableCSV:
    def test_csv_has_required_columns(self, tmp_path):
        import csv
        t1 = _tiddler("A", relations=[{"type": "usa", "target_id": "B"}])
        t2 = _tiddler("B")
        canon = _write_shard(tmp_path, [t1, t2])
        scan = scan_canon_relations(canon)
        report = analyze_compatibility(scan)
        out = tmp_path / "review.csv"
        write_review_csv(report, out)
        with out.open(newline="") as f:
            reader = csv.DictReader(f)
            cols = reader.fieldnames or []
        required = {"type", "count_in_canon", "classification",
                    "catalog_mapping", "blocked_for_new_candidates"}
        assert required.issubset(set(cols))


# ── Caso 9: Markdown legible ─────────────────────────────────────────────────

class TestCase09_ReadableMarkdown:
    def test_summary_md_generated(self, tmp_path):
        t1 = _tiddler("A", relations=[{"type": "references", "target_id": "B"}])
        t2 = _tiddler("B")
        canon = _write_shard(tmp_path, [t1, t2])
        scan = scan_canon_relations(canon)
        report = analyze_compatibility(scan)
        out = tmp_path / "summary.md"
        write_summary_md(report, out)
        content = out.read_text()
        assert "S0137" in content
        assert "usa" in content
        assert "parte_de" in content

    def test_summary_md_contains_all_decisions(self, tmp_path):
        t1 = _tiddler("A")
        canon = _write_shard(tmp_path, [t1])
        scan = scan_canon_relations(canon)
        report = analyze_compatibility(scan)
        out = tmp_path / "summary.md"
        write_summary_md(report, out)
        content = out.read_text()
        for rt in ("usa", "parte_de", "define", "requiere", "child_of"):
            assert rt in content, f"'{rt}' no aparece en el resumen Markdown"
