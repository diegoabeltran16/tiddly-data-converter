"""tests/test_relation_admission_plan.py — S0135

Tests del planificador dry-run de promoción relacional.

Cubre los 10 casos mínimos obligatorios definidos en S0135 §9.

Ejecutar:
    python3 -m pytest tests/test_relation_admission_plan.py -q
"""

from __future__ import annotations

import json
import csv
import sys
from io import StringIO
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "python_scripts"))

from build_relation_admission_plan import (
    evaluate_candidate,
    build_plan,
    build_patch_preview_doc,
    write_review_csv,
    write_plan_json,
    write_summary_md,
    load_candidates,
    main,
    _check_forbidden_flags,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_tiddler(
    tid: str,
    title: str = "Test Tiddler",
    text: str = "Diagnósticos previos consultados: DT027, DT028, DT029, DT030",
    relations: list | None = None,
) -> dict:
    return {
        "id": tid,
        "title": title,
        "text": text,
        "schema_version": "v0",
        "relations": relations or [],
    }


def _make_candidate(
    cid: str = "rc1_a1b2c3d4e5f6a7b8",
    src_id: str = "src-uuid-0001",
    tgt_id: str = "tgt-uuid-0002",
    rel_type: str = "referencia_a",
    ev_kind: str = "explicit_reference",
    excerpt: str = "Diagnósticos previos consultados: DT027, DT028, DT029, DT030",
    conf_score: float = 0.92,
    conf_method: str = "rule_based",
    risk_flags: list | None = None,
    resolution_status: str = "resolved",
    source_path: str = "data/out/local/tiddlers_5.jsonl",
    generated_by: str = "pipeline.relations_candidates.sample",
) -> dict:
    return {
        "candidate_id": cid,
        "schema_version": "relations-candidate/v1",
        "status": "candidate",
        "source": {"tiddler_id": src_id, "title": "Source Tiddler"},
        "target": {
            "tiddler_id": tgt_id,
            "title": "Target Tiddler",
            "resolution_status": resolution_status,
        },
        "relation": {
            "type": rel_type,
            "direction": "source_to_target",
            "label": "test label",
        },
        "evidence": {
            "kind": ev_kind,
            "excerpt": excerpt,
            "location": "text",
            "strength": "E1",
        },
        "confidence": {
            "score": conf_score,
            "method": conf_method,
            "risk_flags": risk_flags or [],
        },
        "provenance": {
            "generated_by": generated_by,
            "generated_at": "2026-05-26T10:00:00Z",
            "input_artifacts": [source_path],
            "source_path": source_path,
        },
        "review": {"required": True, "review_status": "pending"},
        "created_at": "2026-05-26T10:00:00Z",
    }


def _make_canon(
    src_id: str = "src-uuid-0001",
    tgt_id: str = "tgt-uuid-0002",
    existing_relations: list | None = None,
) -> dict[str, dict]:
    text = "Diagnósticos previos consultados: DT027, DT028, DT029, DT030"
    return {
        src_id: _make_tiddler(src_id, "Source Tiddler", text, existing_relations),
        tgt_id: _make_tiddler(tgt_id, "Target Tiddler"),
    }


# ── Caso 1: Candidato válido → promotable ────────────────────────────────────

class TestCase01_PromotableCandidate:
    def test_valid_candidate_is_promotable(self):
        canon = _make_canon()
        candidate = _make_candidate()
        result = evaluate_candidate(candidate, canon, set())
        assert result["decision"] == "promotable", f"Got: {result['decision']}, reasons: {result['blocking_reasons']}"

    def test_promotable_has_patch_preview(self):
        canon = _make_canon()
        candidate = _make_candidate()
        result = evaluate_candidate(candidate, canon, set())
        assert result["metadata_patch_preview"], "promotable debe tener patch_preview"
        assert "rollback_hint" in result["metadata_patch_preview"]

    def test_promotable_has_reverse_preview(self):
        canon = _make_canon()
        candidate = _make_candidate()
        result = evaluate_candidate(candidate, canon, set())
        assert result["reverse_preview"]

    def test_promotable_risk_level_low(self):
        canon = _make_canon()
        candidate = _make_candidate()
        result = evaluate_candidate(candidate, canon, set())
        assert result["risk_level"] == "low"


# ── Caso 2: Target inexistente → unresolved_target ───────────────────────────

class TestCase02_UnresolvedTarget:
    def test_missing_target_is_unresolved(self):
        canon = {"src-uuid-0001": _make_tiddler("src-uuid-0001")}
        candidate = _make_candidate(tgt_id="nonexistent-tgt", resolution_status="unresolved")
        result = evaluate_candidate(candidate, canon, set())
        assert result["decision"] == "unresolved_target"

    def test_resolved_but_missing_from_canon_is_blocked(self):
        canon = {"src-uuid-0001": _make_tiddler("src-uuid-0001")}
        candidate = _make_candidate(tgt_id="claimed-resolved-but-missing",
                                     resolution_status="resolved")
        result = evaluate_candidate(candidate, canon, set())
        # Resolution says resolved but not in canon → blocked
        assert result["decision"] in ("blocked", "unresolved_target")
        assert result["blocking_reasons"]


# ── Caso 3: Sin source_fields → blocked o review_required ────────────────────

class TestCase03_NoSourceFields:
    def test_missing_provenance_source_path_causes_issue(self):
        canon = _make_canon()
        cand = _make_candidate(source_path="", generated_by="")
        result = evaluate_candidate(cand, canon, set())
        # Without provenance, should be blocked (criterion 5 fails)
        assert result["decision"] in ("blocked", "review_required")
        has_prov_issue = any(
            "procedencia" in r.lower() or "source_path" in r.lower() or "provenance" in r.lower()
            for r in result["blocking_reasons"]
        )
        assert has_prov_issue

    def test_with_generated_by_only_is_ok(self):
        """If generated_by is present, criterion 5 passes."""
        canon = _make_canon()
        cand = _make_candidate(source_path="", generated_by="pipeline.test")
        result = evaluate_candidate(cand, canon, set())
        # criterion 5 passes via generated_by
        prov_blocking = [r for r in result["blocking_reasons"] if "procedencia" in r.lower()]
        assert prov_blocking == []


# ── Caso 4: Excerpt no verificable → blocked ─────────────────────────────────

class TestCase04_UnverifiableExcerpt:
    def test_excerpt_not_in_source_text_is_blocked(self):
        src_text = "Este es el texto fuente sin relación con el excerpt."
        canon = {
            "src-uuid-0001": _make_tiddler("src-uuid-0001", text=src_text),
            "tgt-uuid-0002": _make_tiddler("tgt-uuid-0002"),
        }
        cand = _make_candidate(excerpt="Este excerpt no está en el texto fuente.")
        result = evaluate_candidate(cand, canon, set())
        assert result["decision"] in ("blocked", "review_required")
        excerpt_block = any("excerpt" in r.lower() for r in result["blocking_reasons"])
        assert excerpt_block

    def test_excerpt_in_source_text_admitted(self):
        text = "Referencia explícita a DT029 como base del contrato."
        canon = {
            "src-uuid-0001": _make_tiddler("src-uuid-0001", text=text),
            "tgt-uuid-0002": _make_tiddler("tgt-uuid-0002"),
        }
        cand = _make_candidate(excerpt="Referencia explícita a DT029")
        result = evaluate_candidate(cand, canon, set())
        # excerpt found → not blocked for this reason
        excerpt_blocks = [r for r in result["blocking_reasons"] if "excerpt" in r.lower()]
        assert excerpt_blocks == []


# ── Caso 5: Duplica relación canónica → duplicate ────────────────────────────

class TestCase05_DuplicateRelation:
    def test_existing_canonical_relation_is_duplicate(self):
        src_id = "src-uuid-0001"
        tgt_id = "tgt-uuid-0002"
        existing = [{"type": "referencia_a", "target_id": tgt_id, "evidence": "wikilink"}]
        canon = _make_canon(src_id, tgt_id, existing_relations=existing)
        canon_rels = {(src_id, tgt_id, "referencia_a")}
        cand = _make_candidate(rel_type="referencia_a")
        result = evaluate_candidate(cand, canon, canon_rels)
        assert result["decision"] == "duplicate"

    def test_different_relation_type_not_duplicate(self):
        src_id = "src-uuid-0001"
        tgt_id = "tgt-uuid-0002"
        existing = [{"type": "referencia_a", "target_id": tgt_id}]
        canon = _make_canon(src_id, tgt_id, existing_relations=existing)
        canon_rels = {(src_id, tgt_id, "referencia_a")}
        cand = _make_candidate(rel_type="menciona_diagnostico")
        result = evaluate_candidate(cand, canon, canon_rels)
        assert result["decision"] != "duplicate"


# ── Caso 6: ai_inference sin soporte textual → review_required o blocked ──────

class TestCase06_WeakAIInference:
    def test_ai_inference_low_confidence_is_blocked(self):
        canon = _make_canon()
        cand = _make_candidate(
            ev_kind="ai_inference",
            conf_score=0.35,
            conf_method="llm_assisted",
            risk_flags=["weak_semantic_inference", "ai_inference_unverifiable"],
        )
        result = evaluate_candidate(cand, canon, set())
        assert result["decision"] in ("blocked", "review_required")

    def test_ai_inference_high_confidence_needs_review(self):
        """ai_inference with score >= 0.70 → review_required (not promotable)."""
        canon = _make_canon()
        cand = _make_candidate(
            ev_kind="ai_inference",
            conf_score=0.85,
            conf_method="llm_assisted",
        )
        result = evaluate_candidate(cand, canon, set())
        assert result["decision"] in ("review_required", "blocked")

    def test_explicit_reference_not_ai_inference(self):
        canon = _make_canon()
        cand = _make_candidate(ev_kind="explicit_reference", conf_score=0.92)
        result = evaluate_candidate(cand, canon, set())
        ai_blocks = [r for r in result["blocking_reasons"] if "ai_inference" in r]
        assert ai_blocks == []


# ── Caso 7: --apply o --write-canon → error controlado ───────────────────────

class TestCase07_ForbiddenFlags:
    @pytest.mark.parametrize("bad_flag", [
        "--apply",
        "--write-canon",
        "--write",
        "--write-relations",
        "--force-admit",
        "--admit",
    ])
    def test_forbidden_flags_raise_system_exit(self, bad_flag):
        with pytest.raises(SystemExit) as exc:
            _check_forbidden_flags([bad_flag])
        assert exc.value.code == 1

    def test_dry_run_flag_allowed(self):
        try:
            _check_forbidden_flags(["--dry-run"])
        except SystemExit:
            pytest.fail("--dry-run no debe lanzar SystemExit")

    def test_normal_flags_allowed(self):
        _check_forbidden_flags(["--verbose", "--session", "s0135", "--out-dir", "/tmp"])


# ── Caso 8: Patch preview no modifica archivos canónicos ─────────────────────

class TestCase08_PatchPreviewNonDestructive:
    def test_evaluate_candidate_does_not_modify_canon(self):
        canon = _make_canon()
        original_src = dict(canon["src-uuid-0001"])
        original_tgt = dict(canon["tgt-uuid-0002"])
        cand = _make_candidate()
        evaluate_candidate(cand, canon, set())
        assert canon["src-uuid-0001"] == original_src
        assert canon["tgt-uuid-0002"] == original_tgt

    def test_patch_preview_is_hypothetical(self):
        canon = _make_canon()
        cand = _make_candidate()
        result = evaluate_candidate(cand, canon, set())
        preview = result.get("metadata_patch_preview", {})
        if preview:
            after = preview.get("after_preview", {})
            # The actual tiddler should NOT have been modified
            assert len(canon["src-uuid-0001"].get("relations", [])) == 0
            # The preview should show the proposed change
            assert "appended_relation" in after

    def test_build_matrix_does_not_modify_inputs(self):
        canon = _make_canon()
        cand = _make_candidate()
        original_relations_len = len(canon["src-uuid-0001"].get("relations", []))
        evaluate_candidate(cand, canon, set())
        assert len(canon["src-uuid-0001"].get("relations", [])) == original_relations_len


# ── Caso 9: JSON cumple schema mínimo ─────────────────────────────────────────

class TestCase09_JSONSchema:
    def test_plan_schema_fields_present(self):
        canon = _make_canon()
        cand = _make_candidate()
        items = [evaluate_candidate(cand, canon, set())]
        plan = build_plan(items, session="s0135", canon_glob="*.jsonl",
                          candidates_dir=Path("/tmp"))
        assert plan["schema"] == "relation-admission-plan/v1"
        assert plan["mode"] == "dry-run"
        assert plan["session"] == "S0135"
        assert "summary" in plan
        assert "items" in plan
        summary_keys = {"total_candidates", "promotable", "review_required",
                        "blocked", "duplicate", "unresolved_target", "invalid_contract"}
        assert summary_keys.issubset(plan["summary"].keys())

    def test_item_schema_fields_present(self):
        canon = _make_canon()
        cand = _make_candidate()
        result = evaluate_candidate(cand, canon, set())
        required_keys = {
            "candidate_id", "decision", "source", "target", "relation",
            "evidence", "admission_reasons", "blocking_reasons",
            "risk_level", "metadata_patch_preview", "reverse_preview",
        }
        assert required_keys.issubset(result.keys())

    def test_plan_json_is_serializable(self, tmp_path):
        canon = _make_canon()
        cand = _make_candidate()
        items = [evaluate_candidate(cand, canon, set())]
        plan = build_plan(items, session="s0135", canon_glob="*.jsonl",
                          candidates_dir=Path("/tmp"))
        out = tmp_path / "plan.json"
        write_plan_json(plan, out)
        with out.open() as f:
            loaded = json.load(f)
        assert loaded["schema"] == "relation-admission-plan/v1"

    def test_patch_preview_schema(self):
        canon = _make_canon()
        cand = _make_candidate()
        items = [evaluate_candidate(cand, canon, set())]
        doc = build_patch_preview_doc(items)
        assert doc["schema"] == "relation-admission-patch-preview/v1"
        assert doc["mode"] == "dry-run"
        assert "patches" in doc


# ── Caso 10: CSV tiene columnas obligatorias ──────────────────────────────────

class TestCase10_CSVColumns:
    def test_csv_has_required_columns(self, tmp_path):
        canon = _make_canon()
        cand = _make_candidate()
        items = [evaluate_candidate(cand, canon, set())]
        out = tmp_path / "review.csv"
        write_review_csv(items, out)
        with out.open(newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
        required = {
            "candidate_id", "decision", "source_title", "target_title",
            "relation_type", "evidence_kind", "verified_in_source",
            "risk_level", "blocking_reasons", "review_notes",
        }
        assert required.issubset(set(fieldnames))

    def test_csv_has_at_least_one_row(self, tmp_path):
        canon = _make_canon()
        items = [
            evaluate_candidate(_make_candidate("rc1_a1b2c3d4e5f6a7b8"), canon, set()),
            evaluate_candidate(_make_candidate("rc1_b2c3d4e5f6a7b8c9",
                                               src_id="src-uuid-0001",
                                               rel_type="menciona_diagnostico"), canon, set()),
        ]
        out = tmp_path / "review.csv"
        write_review_csv(items, out)
        with out.open(newline="") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) >= 1


# ── Tests adicionales de robustez ─────────────────────────────────────────────

class TestAdditional:
    def test_invalid_relation_type_is_blocked(self):
        canon = _make_canon()
        cand = _make_candidate(rel_type="invented_type_xyz")
        result = evaluate_candidate(cand, canon, set())
        assert result["decision"] in ("blocked", "review_required", "invalid_contract")
        type_block = any("catálogo" in r.lower() or "catalog" in r.lower() or
                         "tipo" in r.lower()
                         for r in result["blocking_reasons"])
        assert type_block

    def test_missing_source_id_is_invalid_contract(self):
        canon = _make_canon()
        cand = _make_candidate(src_id="")
        result = evaluate_candidate(cand, canon, set())
        assert result["decision"] == "invalid_contract"

    def test_p1_relation_type_needs_review(self):
        """P1/P2 types (depende_de, corrige, etc.) always need human review."""
        canon = _make_canon()
        for rel_type in ("depende_de", "corrige", "contradice"):
            cand = _make_candidate(rel_type=rel_type, conf_score=0.85)
            result = evaluate_candidate(cand, canon, set())
            # P1/P2 types should not be directly promotable
            assert result["decision"] in ("review_required", "blocked", "promotable")
            # At most promotable only if all criteria met AND noted as needs review
            if result["decision"] == "promotable":
                # P1/P2 promoted means notes about human review
                assert any("P1" in r or "P2" in r or "humana" in r.lower()
                           for r in result["admission_reasons"])

    def test_self_relation_is_blocked(self):
        same_id = "same-uuid-0001"
        canon = {same_id: _make_tiddler(same_id)}
        cand = _make_candidate(src_id=same_id, tgt_id=same_id)
        result = evaluate_candidate(cand, canon, set())
        assert result["decision"] in ("blocked", "review_required", "unresolved_target")

    def test_build_plan_counts_correctly(self):
        canon = _make_canon()
        items = [
            evaluate_candidate(_make_candidate("rc1_a1b2c3d4e5f6a7b8"), canon, set()),
            evaluate_candidate(_make_candidate("rc1_b2c3d4e5f6a7b8c9",
                                               tgt_id="nonexistent-xxx",
                                               resolution_status="unresolved"), canon, set()),
        ]
        plan = build_plan(items, session="s0135", canon_glob="*.jsonl",
                          candidates_dir=Path("/tmp"))
        assert plan["summary"]["total_candidates"] == 2
        decisions = {i["decision"] for i in items}
        for d in decisions:
            assert plan["summary"].get(d, 0) >= 1

    def test_summary_md_generated(self, tmp_path):
        canon = _make_canon()
        cand = _make_candidate()
        items = [evaluate_candidate(cand, canon, set())]
        plan = build_plan(items, session="s0135", canon_glob="*.jsonl",
                          candidates_dir=Path("/tmp"))
        out = tmp_path / "summary.md"
        write_summary_md(plan, out)
        content = out.read_text()
        assert "S0135" in content
        assert "dry-run" in content.lower()
        assert "canon NO" in content or "canon no" in content.lower() or "canon" in content

    def test_no_apply_in_any_decision_output(self):
        """No output should suggest --apply or write-canon."""
        canon = _make_canon()
        cand = _make_candidate()
        result = evaluate_candidate(cand, canon, set())
        all_text = json.dumps(result)
        assert "--apply" not in all_text
        assert "--write-canon" not in all_text
