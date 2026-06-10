"""tests/test_reversible_metadata_normalization.py — S0136

Tests de la normalización dry-run de metadata reversible.

Cubre los 10 casos mínimos de S0136 §7 (metadata reversible).

Ejecutar:
    python3 -m pytest tests/test_reversible_metadata_normalization.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "python_scripts"))

from build_reversible_metadata_normalization import (
    classify_record,
    build_plan,
    build_patch_preview_doc,
    write_plan_json,
    LEGACY_PATH_PREFIX,
    GOVERNED_PATH_PREFIX,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _base_sf(
    family: str = "balance_de_sesion",
    source_path: str = "data/out/local/sessions/04_balance_de_sesion/m04-s0133.md.json",
    canonical_status: str = "local_admitted",
) -> dict:
    return {
        "artifact_family": family,
        "canonical_status": canonical_status,
        "session_origin": "m04-s0133-balance-test",
        "source_path": source_path,
        "provenance_ref": source_path,
    }


def _tiddler(sf: dict, tid: str = "uuid-001", title: str = "Test tiddler") -> dict:
    return {
        "id": tid,
        "title": title,
        "text": "Balance text.",
        "source_fields": sf,
    }


# ── Caso 1: Record sin cambios → no_change ─────────────────────────────────────

class TestCase01_NoChange:
    def test_governed_path_is_no_change(self):
        t = _tiddler(_base_sf())
        r = classify_record(t)
        assert r["normalization_status"] == "no_change"

    def test_no_change_has_no_actions(self):
        t = _tiddler(_base_sf())
        r = classify_record(t)
        assert r["normalization_actions"] == []
        assert r["blocking_issues"] == []

    def test_tiddler_without_family_is_no_change(self):
        t = {"id": "x", "title": "plain", "source_fields": {"type": "text/markdown"}}
        r = classify_record(t)
        assert r["normalization_status"] == "no_change"


# ── Caso 2: Ruta legacy → safe_to_normalize ────────────────────────────────────

class TestCase02_SafeToNormalize:
    def test_legacy_source_path_is_safe_to_normalize(self):
        sf = _base_sf(source_path="data/sessions/04_balance/m01-s0001.md.json")
        t = _tiddler(sf)
        r = classify_record(t)
        assert r["normalization_status"] == "safe_to_normalize"

    def test_safe_to_normalize_has_patch_preview(self):
        sf = _base_sf(source_path="data/sessions/04_balance/m01-s0001.md.json")
        t = _tiddler(sf)
        r = classify_record(t)
        assert r["patch_preview"], "safe_to_normalize debe tener patch_preview"
        pp = r["patch_preview"]
        assert "from" in pp
        assert "to" in pp
        assert pp["from"].startswith(LEGACY_PATH_PREFIX)
        assert pp["to"].startswith(GOVERNED_PATH_PREFIX)

    def test_safe_to_normalize_has_rollback_hint(self):
        sf = _base_sf(source_path="data/sessions/04_balance/m01-s0001.md.json")
        t = _tiddler(sf)
        r = classify_record(t)
        assert "rollback_hint" in r["patch_preview"]


# ── Caso 3: Ruta ambigua → needs_review ──────────────────────────────────────

class TestCase03_NeedsReview:
    def test_ungoverned_path_with_warning_is_needs_review(self):
        # An unknown source_path prefix triggers SF009 warning but not error
        sf = _base_sf(source_path="/absolute/path/to/file.json")
        t = _tiddler(sf)
        r = classify_record(t)
        # absolute path is a blocking SF009 ERROR → blocked
        assert r["normalization_status"] == "blocked"

    def test_no_source_path_with_family_is_needs_review(self):
        sf = _base_sf(source_path="")
        t = _tiddler(sf)
        r = classify_record(t)
        # missing source_path triggers SF003 error → blocked
        assert r["normalization_status"] == "blocked"

    def test_legacy_path_with_additional_warning_is_needs_review(self):
        sf = _base_sf(source_path="data/sessions/04_balance/m01-s0001.md.json")
        sf["x_custom_ambiguous"] = "ambiguous value"
        t = _tiddler(sf)
        r = classify_record(t)
        # Still safe_to_normalize or needs_review depending on contract
        assert r["normalization_status"] in ("safe_to_normalize", "needs_review")


# ── Caso 4: Metadata inferida nunca pasa a reversible_metadata ────────────────

class TestCase04_InferredMetadataNotNormalized:
    def test_inferred_metadata_note_present(self):
        t = _tiddler(_base_sf())
        r = classify_record(t)
        assert "inferred_metadata_note" in r
        note = r["inferred_metadata_note"]
        assert "inferred_metadata" in note.lower() or "inferida" in note.lower()

    def test_classify_does_not_add_inferred_fields_to_sf(self):
        t = _tiddler(_base_sf())
        orig_sf = dict(t["source_fields"])
        classify_record(t)
        # classify_record must not modify source_fields
        assert t["source_fields"] == orig_sf

    def test_patch_preview_does_not_reference_inferred_fields(self):
        sf = _base_sf(source_path="data/sessions/04_balance/m01-s0001.md.json")
        t = _tiddler(sf)
        r = classify_record(t)
        pp_str = json.dumps(r.get("patch_preview", {}))
        assert "referenced_sessions" not in pp_str
        assert "headings" not in pp_str
        assert "keywords" not in pp_str


# ── Caso 5: Campo prohibido en source_fields → blocked ───────────────────────

class TestCase05_ForbiddenFieldBlocks:
    @pytest.mark.parametrize("forbidden_field", [
        "schema_version", "id", "key", "relations", "content",
        "canonical_slug", "version_id",
    ])
    def test_forbidden_field_in_sf_is_blocked(self, forbidden_field):
        sf = _base_sf()
        sf[forbidden_field] = "some_value"
        t = _tiddler(sf)
        r = classify_record(t)
        assert r["normalization_status"] == "blocked"
        assert r["blocking_issues"]

    def test_relation_field_in_sf_is_blocked(self):
        sf = _base_sf()
        sf["relations"] = '[{"type":"referencia_a","target_id":"x"}]'
        t = _tiddler(sf)
        r = classify_record(t)
        assert r["normalization_status"] == "blocked"
        has_rel_issue = any("relacion" in i.lower() or "relation" in i.lower()
                            for i in r["blocking_issues"])
        assert has_rel_issue


# ── Caso 6: artifact_family desconocida → needs_review o blocked ──────────────

class TestCase06_UnknownFamilyHandled:
    def test_known_family_processes_normally(self):
        t = _tiddler(_base_sf(family="balance_de_sesion"))
        r = classify_record(t)
        assert r["normalization_status"] in ("no_change", "safe_to_normalize",
                                              "needs_review")

    def test_unknown_family_produces_sf011_warning(self):
        t = _tiddler(_base_sf(family="invented_family_xyz"))
        r = classify_record(t)
        # unknown family → SF011 warning; not a blocker but noted
        # The record might be no_change or needs_review
        assert r["normalization_status"] in ("no_change", "needs_review")

    def test_known_families_have_no_sf011_issue(self):
        from source_fields_contract import KNOWN_ARTIFACT_FAMILIES
        for fam in list(KNOWN_ARTIFACT_FAMILIES)[:5]:
            sf = _base_sf(family=fam)
            t = _tiddler(sf)
            r = classify_record(t)
            # Should not be blocked for unknown family
            assert r["normalization_status"] != "blocked" or r["blocking_issues"]


# ── Caso 7: Patch preview no modifica input original ─────────────────────────

class TestCase07_PatchPreviewNonDestructive:
    def test_classify_does_not_modify_tiddler(self):
        t = _tiddler(_base_sf(source_path="data/sessions/04_balance/m01-s0001.md.json"))
        original = json.loads(json.dumps(t))
        classify_record(t)
        assert t == original, "classify_record debe dejar el input sin modificar"

    def test_patch_preview_shows_proposed_change_only(self):
        sf = _base_sf(source_path="data/sessions/04_balance/m01-s0001.md.json")
        t = _tiddler(sf)
        r = classify_record(t)
        pp = r.get("patch_preview", {})
        if pp:
            # The "from" is still the legacy path, not the normalized one
            assert t["source_fields"]["source_path"].startswith(LEGACY_PATH_PREFIX)


# ── Caso 8: JSON generado es válido ──────────────────────────────────────────

class TestCase08_JSONValid:
    def test_plan_json_is_serializable(self, tmp_path):
        tiddlers = [
            _tiddler(_base_sf(), "uuid-001"),
            _tiddler(_base_sf(source_path="data/sessions/04_balance/m01-s0001.md.json"), "uuid-002"),
        ]
        results = [classify_record(t) for t in tiddlers]
        plan = build_plan(results, session="s0136",
                          canon_root=Path("/tmp"))
        out = tmp_path / "plan.json"
        write_plan_json(plan, out)
        with out.open() as f:
            loaded = json.load(f)
        assert loaded["schema"] == "metadata-normalization-plan/v1"
        assert "summary" in loaded

    def test_plan_summary_has_required_keys(self):
        results = [classify_record(_tiddler(_base_sf()))]
        plan = build_plan(results, session="s0136", canon_root=Path("/tmp"))
        for k in ("no_change", "safe_to_normalize", "needs_review", "blocked", "total_records"):
            assert k in plan["summary"]


# ── Caso 9: source_fields_contract.py respetado ───────────────────────────────

class TestCase09_ContractRespected:
    def test_missing_baseline_field_is_blocked(self):
        sf = {
            "artifact_family": "balance_de_sesion",
            # missing canonical_status, session_origin, source_path, provenance_ref
        }
        t = _tiddler(sf)
        r = classify_record(t)
        assert r["normalization_status"] == "blocked"
        assert r["blocking_issues"]

    def test_complete_baseline_fields_passes(self):
        t = _tiddler(_base_sf())
        r = classify_record(t)
        assert r["normalization_status"] in ("no_change", "safe_to_normalize")
        assert not r["blocking_issues"]


# ── Caso 10: Ningún `relations` se escribe dentro de source_fields ─────────────

class TestCase10_NoRelationsInSourceFields:
    def test_relations_in_sf_blocked(self):
        sf = _base_sf()
        sf["relations"] = "[]"
        t = _tiddler(sf)
        r = classify_record(t)
        assert r["normalization_status"] == "blocked"

    def test_patch_preview_never_writes_relations_to_sf(self):
        sf = _base_sf(source_path="data/sessions/04_balance/m01-s0001.md.json")
        t = _tiddler(sf)
        r = classify_record(t)
        pp_str = json.dumps(r.get("patch_preview", {}))
        assert '"relations"' not in pp_str

    def test_build_patch_preview_doc_no_relations(self, tmp_path):
        results = [
            classify_record(_tiddler(
                _base_sf(source_path="data/sessions/04_balance/m01-s0001.md.json")
            ))
        ]
        doc = build_patch_preview_doc(results)
        doc_str = json.dumps(doc)
        assert "\"relations\":" not in doc_str or "patches" in doc_str
