"""Regression coverage for productive equivalence contract v2.

The filename is kept for the historical test location.  The assertions are
contractual rather than tied to S0173 counts, paths, or identifiers.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

from rag_derivative_writers import ProductiveWriteBlocked  # noqa: E402
from validate_productive_equivalence import (  # noqa: E402
    build_equivalence_report,
    _non_versioned_canon_projection_evolution,
    _semantic_projection_policy_evolution,
    _tolerable_lane_b_lifecycle_transition,
    _tolerable_template_prune,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def _canon_record(record_id: str, version_id: str) -> dict:
    return {
        "id": record_id,
        "version_id": version_id,
        "title": f"Title {record_id}",
        "canonical_slug": record_id,
        "schema_version": "v0",
    }


def _write_canon(root: Path, records: list[dict]) -> None:
    _write_jsonl(root / "tiddlers_1.jsonl", records)


def _record(record_id: str, version_id: str, *, semantic: str = "same", schema: str = "surface/v1", artifact_family: str | None = None) -> dict:
    record = {
        "id": record_id,
        "version_id": version_id,
        "schema_version": schema,
        "semantic_text": semantic,
        "retrieval_hints": ["rag"],
        "embedding_metadata": {"promoted_metadata": {"topics": ["rag"]}},
        "rag_allowed_tags": ["rag"],
    }
    if artifact_family:
        record["artifact_family"] = artifact_family
    return record


def _write_enriched(root: Path, rows: list[dict]) -> None:
    _write_jsonl(root / "enriched" / "tiddlers_enriched_1.jsonl", rows)


def _report(tmp_path: Path, baseline_rows: list[dict], staging_rows: list[dict], canon_rows: list[dict]) -> dict:
    baseline = tmp_path / "baseline"
    staging = tmp_path / "staging"
    canon = tmp_path / "canon"
    _write_enriched(baseline, baseline_rows)
    _write_enriched(staging, staging_rows)
    _write_canon(canon, canon_rows)
    return build_equivalence_report(baseline, staging, canon_dir=canon, families=["enriched"])


def _write_chunks(root: Path, rows: list[dict]) -> None:
    _write_jsonl(root / "ai" / "chunks_ai_1.jsonl", rows)


def _chunk(chunk_id: str, source_id: str, version_id: str, *, text: str = "chunk text") -> dict:
    return {
        "chunk_id": chunk_id,
        "source_id": source_id,
        "source_version_id": version_id,
        "text": text,
        "chunk_index": 0,
        "chunk_total": 1,
        "within_hard_max": True,
        "source_anchor": {"canon_id": source_id, "shard_file": "shard.jsonl", "shard_line": 1},
    }


def _report_with_chunks(
    tmp_path: Path,
    enriched_baseline: list[dict],
    enriched_staging: list[dict],
    chunk_baseline: list[dict],
    chunk_staging: list[dict],
    canon_rows: list[dict],
) -> dict:
    baseline = tmp_path / "baseline"
    staging = tmp_path / "staging"
    canon = tmp_path / "canon"
    _write_enriched(baseline, enriched_baseline)
    _write_enriched(staging, enriched_staging)
    _write_chunks(baseline, chunk_baseline)
    _write_chunks(staging, chunk_staging)
    _write_canon(canon, canon_rows)
    return build_equivalence_report(baseline, staging, canon_dir=canon, families=["enriched", "chunks_ai"])


def test_unchanged_record_is_equivalent(tmp_path: Path) -> None:
    report = _report(tmp_path, [_record("same", "v1")], [_record("same", "v1")], [_canon_record("same", "v1")])
    assert report["equivalence_status"] == "equivalent"
    assert report["blocking"] is False
    assert report["families"]["enriched"]["unchanged_shared_records"] == 1


def test_same_version_semantic_change_is_blocking_regression(tmp_path: Path) -> None:
    report = _report(tmp_path, [_record("same", "v1")], [_record("same", "v1", semantic="changed")], [_canon_record("same", "v1")])
    family = report["families"]["enriched"]
    assert report["equivalence_status"] == "not_equivalent"
    assert family["unexpected_semantic_regressions"] == 1
    assert family["blocking"] is True


def test_redaction_vocabulary_growth_is_non_blocking_evolution(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        [_record("same", "v1", semantic="algo canon real")],
        [_record("same", "v1", semantic="algo [RAG_TAG_BLOCKED] real")],
        [_canon_record("same", "v1")],
    )
    family = report["families"]["enriched"]
    assert report["equivalence_status"] == "equivalent_with_expected_canonical_evolution"
    assert report["blocking"] is False
    assert family["blocking"] is False
    assert family["unexpected_semantic_regressions"] == 0
    assert family["redaction_vocabulary_evolution"] == 1
    assert report["evolution"]["redaction_vocabulary_evolution"] == 1


def test_two_adjacent_redacted_terms_with_connector_word_are_non_blocking(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        [_record("same", "v1", semantic="algo, estado de canon, final")],
        [_record("same", "v1", semantic="algo, [RAG_TAG_BLOCKED] de [RAG_TAG_BLOCKED], final")],
        [_canon_record("same", "v1")],
    )
    family = report["families"]["enriched"]
    assert report["blocking"] is False
    assert family["redaction_vocabulary_evolution"] == 1
    assert family["unexpected_semantic_regressions"] == 0


def test_two_adjacent_occurrences_of_the_same_redacted_term_are_non_blocking(tmp_path: Path) -> None:
    # The marker's own literal text can coincidentally self-overlap when the
    # same redacted term appears twice close together (".../canon-x/canon-x"
    # -> ".../[RAG_TAG_BLOCKED]-x/[RAG_TAG_BLOCKED]-x"), which can fool the
    # differ into treating a fragment of the marker as a genuine equal
    # anchor between the two occurrences.
    report = _report(
        tmp_path,
        [_record("same", "v1", semantic="Titulo: canon-gate-docs\nKey: canon-gate-docs")],
        [_record("same", "v1", semantic="Titulo: [RAG_TAG_BLOCKED]-gate-docs\nKey: [RAG_TAG_BLOCKED]-gate-docs")],
        [_canon_record("same", "v1")],
    )
    family = report["families"]["enriched"]
    assert report["blocking"] is False
    assert family["redaction_vocabulary_evolution"] == 1
    assert family["unexpected_semantic_regressions"] == 0


def test_three_redacted_terms_in_a_tag_list_are_non_blocking(tmp_path: Path) -> None:
    # Three distinct redacted terms close together in a comma-separated list
    # can make the token differ align text across the wrong occurrences,
    # producing a hunk difflib itself cannot cleanly attribute to any single
    # substitution; the whole-text wildcard fallback resolves it directly.
    tags_list = '"tags":["topic:canon","topic:schema-v0","topic:canon-jsonl","topic:validation"]'
    redacted_list = (
        '"tags":["topic:[RAG_TAG_BLOCKED]","topic:[RAG_TAG_BLOCKED]-v0",'
        '"topic:[RAG_TAG_BLOCKED]-jsonl","topic:validation"]'
    )
    report = _report(
        tmp_path,
        [_record("same", "v1", semantic=tags_list)],
        [_record("same", "v1", semantic=redacted_list)],
        [_canon_record("same", "v1")],
    )
    family = report["families"]["enriched"]
    assert report["blocking"] is False
    assert family["redaction_vocabulary_evolution"] == 1
    assert family["unexpected_semantic_regressions"] == 0


def test_redaction_marker_next_to_unrelated_change_still_blocks(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        [_record("same", "v1", semantic="algo canon real")],
        [_record("same", "v1", semantic="algo [RAG_TAG_BLOCKED] FAKE")],
        [_canon_record("same", "v1")],
    )
    family = report["families"]["enriched"]
    assert report["blocking"] is True
    assert family["unexpected_semantic_regressions"] == 1
    assert family["redaction_vocabulary_evolution"] == 0


def test_redaction_marker_with_metadata_change_still_blocks(tmp_path: Path) -> None:
    baseline = [_record("same", "v1", semantic="algo canon real")]
    staged = _record("same", "v1", semantic="algo [RAG_TAG_BLOCKED] real")
    staged["embedding_metadata"] = {"promoted_metadata": {"topics": ["different"]}}
    report = _report(tmp_path, baseline, [staged], [_canon_record("same", "v1")])
    family = report["families"]["enriched"]
    assert report["blocking"] is True
    assert family["unexpected_semantic_regressions"] == 1
    assert family["redaction_vocabulary_evolution"] == 0


def test_placeholder_resolved_in_retrieval_hints_alone_is_non_blocking(tmp_path: Path) -> None:
    baseline = _record("same", "v1", semantic="algo real")
    baseline["retrieval_hints"] = ["code", "unknown"]
    staged = _record("same", "v1", semantic="algo real")
    staged["retrieval_hints"] = ["code", "artefacto_repositorio"]
    report = _report(tmp_path, [baseline], [staged], [_canon_record("same", "v1")])
    family = report["families"]["enriched"]
    assert report["blocking"] is False
    assert family["unexpected_semantic_regressions"] == 0
    assert family["placeholder_resolved"] == 1
    assert report["evolution"]["placeholder_resolved"] == 1


def test_placeholder_resolved_in_metadata_and_retrieval_hints_together(tmp_path: Path) -> None:
    baseline = _record("same", "v1", semantic="algo real")
    baseline["retrieval_hints"] = ["code", "unknown"]
    baseline["embedding_metadata"] = {"artifact_family": "unknown", "semantic_family": "unknown"}
    staged = _record("same", "v1", semantic="algo real")
    staged["retrieval_hints"] = ["code", "artefacto_repositorio"]
    staged["embedding_metadata"] = {"artifact_family": "artefacto_repositorio", "semantic_family": "artefacto_repositorio"}
    report = _report(tmp_path, [baseline], [staged], [_canon_record("same", "v1")])
    family = report["families"]["enriched"]
    assert report["blocking"] is False
    assert family["placeholder_resolved"] == 1


def test_placeholder_reverse_transition_still_blocks(tmp_path: Path) -> None:
    baseline = _record("same", "v1", semantic="algo real")
    baseline["retrieval_hints"] = ["code", "artefacto_repositorio"]
    staged = _record("same", "v1", semantic="algo real")
    staged["retrieval_hints"] = ["code", "unknown"]
    report = _report(tmp_path, [baseline], [staged], [_canon_record("same", "v1")])
    family = report["families"]["enriched"]
    assert report["blocking"] is True
    assert family["placeholder_resolved"] == 0
    assert family["unexpected_semantic_regressions"] == 1


def test_concrete_to_concrete_retrieval_hint_change_still_blocks(tmp_path: Path) -> None:
    baseline = _record("same", "v1", semantic="algo real")
    baseline["retrieval_hints"] = ["code", "artefacto_repositorio"]
    staged = _record("same", "v1", semantic="algo real")
    staged["retrieval_hints"] = ["code", "documento_referencia"]
    report = _report(tmp_path, [baseline], [staged], [_canon_record("same", "v1")])
    family = report["families"]["enriched"]
    assert report["blocking"] is True
    assert family["placeholder_resolved"] == 0
    assert family["unexpected_semantic_regressions"] == 1


def test_inconsistent_placeholder_pairs_between_metadata_and_retrieval_still_blocks(tmp_path: Path) -> None:
    baseline = _record("same", "v1", semantic="algo real")
    baseline["retrieval_hints"] = ["code", "unknown"]
    baseline["embedding_metadata"] = {"artifact_family": "unknown"}
    staged = _record("same", "v1", semantic="algo real")
    staged["retrieval_hints"] = ["code", "artefacto_repositorio"]
    staged["embedding_metadata"] = {"artifact_family": "documento_referencia"}
    report = _report(tmp_path, [baseline], [staged], [_canon_record("same", "v1")])
    family = report["families"]["enriched"]
    assert report["blocking"] is True
    assert family["placeholder_resolved"] == 0
    assert family["unexpected_semantic_regressions"] == 1


def test_two_different_placeholder_pairs_within_metadata_still_blocks(tmp_path: Path) -> None:
    baseline = _record("same", "v1", semantic="algo real")
    baseline["embedding_metadata"] = {"artifact_family": "unknown", "language_family": "unknown"}
    staged = _record("same", "v1", semantic="algo real")
    staged["embedding_metadata"] = {"artifact_family": "artefacto_repositorio", "language_family": "documento_referencia"}
    report = _report(tmp_path, [baseline], [staged], [_canon_record("same", "v1")])
    family = report["families"]["enriched"]
    assert report["blocking"] is True
    assert family["placeholder_resolved"] == 0
    assert family["unexpected_semantic_regressions"] == 1


def test_placeholder_resolution_with_rag_filter_change_still_blocks(tmp_path: Path) -> None:
    baseline = _record("same", "v1", semantic="algo real")
    baseline["retrieval_hints"] = ["code", "unknown"]
    baseline["rag_allowed_tags"] = ["rag"]
    staged = _record("same", "v1", semantic="algo real")
    staged["retrieval_hints"] = ["code", "artefacto_repositorio"]
    staged["rag_allowed_tags"] = ["rag", "extra"]
    report = _report(tmp_path, [baseline], [staged], [_canon_record("same", "v1")])
    family = report["families"]["enriched"]
    assert report["blocking"] is True
    assert family["placeholder_resolved"] == 0
    assert family["unexpected_semantic_regressions"] == 1


def test_placeholder_resolution_with_unrelated_semantic_text_change_still_blocks(tmp_path: Path) -> None:
    baseline = _record("same", "v1", semantic="algo real")
    baseline["retrieval_hints"] = ["code", "unknown"]
    staged = _record("same", "v1", semantic="algo FALSIFICADO")
    staged["retrieval_hints"] = ["code", "artefacto_repositorio"]
    report = _report(tmp_path, [baseline], [staged], [_canon_record("same", "v1")])
    family = report["families"]["enriched"]
    assert report["blocking"] is True
    assert family["placeholder_resolved"] == 0
    assert family["unexpected_semantic_regressions"] == 1


def test_retrieval_hints_growth_alone_is_non_blocking_evolution(tmp_path: Path) -> None:
    baseline = [_record("same", "v1", semantic="algo real")]
    staged = _record("same", "v1", semantic="algo real")
    staged["retrieval_hints"] = ["rag", "application/json"]
    report = _report(tmp_path, baseline, [staged], [_canon_record("same", "v1")])
    family = report["families"]["enriched"]
    assert report["blocking"] is False
    assert family["unexpected_semantic_regressions"] == 0
    assert family["additive_derivative_evolution"] == 1
    assert report["evolution"]["additive_derivative_evolution"] == 1


def test_new_relations_section_pure_insertion_is_non_blocking_evolution(tmp_path: Path) -> None:
    baseline = [_record("same", "v1", semantic="algo real")]
    staged = _record("same", "v1", semantic="algo real\n\n# Relaciones canonicas\n- usa -> otro-id")
    report = _report(tmp_path, baseline, [staged], [_canon_record("same", "v1")])
    family = report["families"]["enriched"]
    assert report["blocking"] is False
    assert family["unexpected_semantic_regressions"] == 0
    assert family["additive_derivative_evolution"] == 1


def test_combined_retrieval_growth_and_relation_insertion_is_non_blocking(tmp_path: Path) -> None:
    baseline = [_record("same", "v1", semantic="algo real")]
    staged = _record("same", "v1", semantic="algo real\n\n# Relaciones canonicas\n- usa -> otro-id")
    staged["retrieval_hints"] = ["rag", "application/json"]
    report = _report(tmp_path, baseline, [staged], [_canon_record("same", "v1")])
    family = report["families"]["enriched"]
    assert report["blocking"] is False
    assert family["additive_derivative_evolution"] == 1


def test_retrieval_hints_losing_an_entry_still_blocks(tmp_path: Path) -> None:
    baseline = [_record("same", "v1", semantic="algo real")]
    staged = _record("same", "v1", semantic="algo real")
    staged["retrieval_hints"] = []
    report = _report(tmp_path, baseline, [staged], [_canon_record("same", "v1")])
    family = report["families"]["enriched"]
    assert report["blocking"] is True
    assert family["unexpected_semantic_regressions"] == 1
    assert family["additive_derivative_evolution"] == 0


def test_removed_content_alongside_retrieval_growth_still_blocks(tmp_path: Path) -> None:
    baseline = [_record("same", "v1", semantic="algo real informacion importante")]
    staged = _record("same", "v1", semantic="algo real")
    staged["retrieval_hints"] = ["rag", "application/json"]
    report = _report(tmp_path, baseline, [staged], [_canon_record("same", "v1")])
    family = report["families"]["enriched"]
    assert report["blocking"] is True
    assert family["unexpected_semantic_regressions"] == 1
    assert family["additive_derivative_evolution"] == 0


def test_altered_existing_content_alongside_retrieval_growth_still_blocks(tmp_path: Path) -> None:
    baseline = [_record("same", "v1", semantic="algo real informacion")]
    staged = _record("same", "v1", semantic="algo real FALSIFICADA")
    staged["retrieval_hints"] = ["rag", "application/json"]
    report = _report(tmp_path, baseline, [staged], [_canon_record("same", "v1")])
    family = report["families"]["enriched"]
    assert report["blocking"] is True
    assert family["unexpected_semantic_regressions"] == 1
    assert family["additive_derivative_evolution"] == 0


def test_metadata_change_alongside_retrieval_growth_still_blocks(tmp_path: Path) -> None:
    baseline = [_record("same", "v1", semantic="algo real")]
    staged = _record("same", "v1", semantic="algo real")
    staged["retrieval_hints"] = ["rag", "application/json"]
    staged["embedding_metadata"] = {"promoted_metadata": {"topics": ["different"]}}
    report = _report(tmp_path, baseline, [staged], [_canon_record("same", "v1")])
    family = report["families"]["enriched"]
    assert report["blocking"] is True
    assert family["unexpected_semantic_regressions"] == 1
    assert family["additive_derivative_evolution"] == 0


def test_current_canonical_update_is_non_blocking(tmp_path: Path) -> None:
    report = _report(tmp_path, [_record("same", "v1")], [_record("same", "v2", semantic="changed")], [_canon_record("same", "v2")])
    assert report["equivalence_status"] == "equivalent_with_expected_canonical_evolution"
    assert report["evolution"] == {"additions": 0, "updates": 1, "removals": 0, "regressions": 0, "redaction_vocabulary_evolution": 0, "additive_derivative_evolution": 0, "placeholder_resolved": 0, "semantic_projection_policy_evolution": 0, "non_versioned_canon_projection_evolution": 0, "identity_migrated": 0}
    assert report["families"]["enriched"]["canonical_updates"] == 1


def test_invalid_version_transition_blocks_even_when_content_changed(tmp_path: Path) -> None:
    report = _report(tmp_path, [_record("same", "v1")], [_record("same", "v3", semantic="changed")], [_canon_record("same", "v2")])
    assert report["families"]["enriched"]["invalid_version_transitions"] == 1
    assert report["blocking"] is True


def test_new_record_requires_current_canonical_membership_and_version(tmp_path: Path) -> None:
    report = _report(tmp_path, [], [_record("new", "v1")], [_canon_record("new", "v1")])
    assert report["equivalence_status"] == "equivalent_with_expected_canonical_evolution"
    assert report["families"]["enriched"]["added_from_current_canon"] == 1


def test_orphaned_derived_record_is_blocking(tmp_path: Path) -> None:
    report = _report(tmp_path, [], [_record("orphan", "v1")], [])
    assert report["families"]["enriched"]["invalid_canonical_membership"] == 1
    assert report["blocking"] is True


def test_historical_removal_remains_blocking(tmp_path: Path) -> None:
    report = _report(tmp_path, [_record("lost", "v1")], [], [_canon_record("lost", "v1")])
    assert report["families"]["enriched"]["removed_historical_records"] == 1
    assert report["blocking"] is True


_MIGRATION_BODY = (
    "# Contenido principal\nDiagnostico tematico sobre gobernanza relacional "
    "candidatas admitidas revision humana pendiente arquitectura evidencia "
    "canonica proyecto tiddler workspace generado sesion analisis."
)
_UNRELATED_BODY = (
    "# Contenido principal\nInforme distinto sobre logistica externa "
    "proveedores contratos financieros calendario reuniones presupuesto "
    "anual departamento recursos humanos oficina central."
)


# --- cross-family removal aggregation -------------------------------------
#
# The top-level `evolution["removals"]` is a union of removal *evidence*
# (canon/source ids) across every compared family, not a per-family sum.
# chunks_ai's own removal evidence already resolves to the *source* canon
# id (not the raw chunk id), so the same real removal or the same governed
# migration, observed from multiple families, must collapse to one unique
# entry in that union -- never inflate it, and never silently merge two
# genuinely different identities either.


def test_same_real_removal_across_two_families_is_counted_once(tmp_path: Path) -> None:
    report = _report_with_chunks(
        tmp_path,
        [_record("lost", "v1")],
        [],
        [_chunk("lost::chunk:0", "lost", "v1")],
        [],
        [],
    )
    assert report["families"]["enriched"]["removed_historical_records"] == 1
    assert report["families"]["chunks_ai"]["removed_historical_records"] == 1
    assert report["evolution"]["removals"] == 1
    assert report["blocking"] is True


def test_two_distinct_real_removals_count_as_two(tmp_path: Path) -> None:
    report = _report_with_chunks(
        tmp_path,
        [_record("lost-a", "v1"), _record("lost-b", "v1")],
        [],
        [],
        [],
        [],
    )
    assert report["evolution"]["removals"] == 2
    assert report["blocking"] is True


def test_migrated_source_with_many_removed_chunks_does_not_inflate_unique_removals(tmp_path: Path) -> None:
    report = _report_with_chunks(
        tmp_path,
        [_record("old-034", "v1", semantic=_MIGRATION_BODY)],
        [_record("new-0034", "v2", semantic=_MIGRATION_BODY.replace("canonica", "[RAG_TAG_BLOCKED]"))],
        [
            _chunk("old-034::chunk:0", "old-034", "v1", text="chunk zero"),
            _chunk("old-034::chunk:1", "old-034", "v1", text="chunk one"),
            _chunk("old-034::chunk:2", "old-034", "v1", text="chunk two"),
        ],
        [],
        [_canon_record("new-0034", "v2")],
    )
    assert report["families"]["chunks_ai"]["removed_historical_records"] == 0
    assert report["families"]["chunks_ai"]["identity_migrated_records"] == 3
    assert report["evolution"]["removals"] == 0
    assert report["evolution"]["identity_migrated"] == 1
    assert report["blocking"] is False


def test_distinct_removed_ids_with_similar_content_are_not_deduplicated(tmp_path: Path) -> None:
    report = _report_with_chunks(
        tmp_path,
        [_record("similar-a", "v1", semantic=_MIGRATION_BODY), _record("similar-b", "v1", semantic=_MIGRATION_BODY)],
        [],
        [],
        [],
        [],
    )
    assert report["evolution"]["removals"] == 2
    assert report["evolution"]["identity_migrated"] == 0
    assert report["blocking"] is True


def test_zero_removals_reports_zero_unique(tmp_path: Path) -> None:
    report = _report_with_chunks(
        tmp_path,
        [_record("same", "v1")],
        [_record("same", "v1")],
        [],
        [],
        [_canon_record("same", "v1")],
    )
    assert report["evolution"]["removals"] == 0
    assert report["blocking"] is False


def test_real_removal_alongside_a_migration_still_blocks(tmp_path: Path) -> None:
    # The migration reclassification must not become a blanket pass: a
    # genuinely unmatched removal sitting next to a legitimate migration
    # still blocks.
    report = _report_with_chunks(
        tmp_path,
        [_record("old-034", "v1", semantic=_MIGRATION_BODY), _record("really-lost", "v1")],
        [_record("new-0034", "v2", semantic=_MIGRATION_BODY.replace("canonica", "[RAG_TAG_BLOCKED]"))],
        [],
        [],
        [_canon_record("new-0034", "v2")],
    )
    assert report["evolution"]["identity_migrated"] == 1
    assert report["evolution"]["removals"] == 1
    assert report["blocking"] is True


def test_identity_migration_reclassifies_governed_rename_as_non_blocking(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        [_record("old-034", "v1", semantic=_MIGRATION_BODY)],
        [_record("new-0034", "v2", semantic=_MIGRATION_BODY.replace("canonica", "[RAG_TAG_BLOCKED]"))],
        [_canon_record("new-0034", "v2")],
    )
    family = report["families"]["enriched"]
    assert family["removed_historical_records"] == 0
    assert family["identity_migrated_records"] == 1
    assert report["evolution"]["identity_migrated"] == 1
    assert report["blocking"] is False
    assert report["equivalence_status"] == "equivalent_with_expected_canonical_evolution"


def test_identity_migration_ambiguous_candidates_stay_blocking(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        [_record("old-034", "v1", semantic=_MIGRATION_BODY)],
        [
            _record("candidate-a", "v2", semantic=_MIGRATION_BODY),
            _record("candidate-b", "v3", semantic=_MIGRATION_BODY),
        ],
        [_canon_record("candidate-a", "v2"), _canon_record("candidate-b", "v3")],
    )
    family = report["families"]["enriched"]
    assert family["identity_migrated_records"] == 0
    assert family["removed_historical_records"] == 1
    assert report["blocking"] is True


def test_identity_migration_no_similar_candidate_stays_blocking(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        [_record("old-034", "v1", semantic=_MIGRATION_BODY)],
        [_record("unrelated-new", "v2", semantic=_UNRELATED_BODY)],
        [_canon_record("unrelated-new", "v2")],
    )
    family = report["families"]["enriched"]
    assert family["identity_migrated_records"] == 0
    assert family["removed_historical_records"] == 1
    assert report["blocking"] is True


def test_identity_migration_residual_semantic_difference_stays_blocking(tmp_path: Path) -> None:
    altered = _MIGRATION_BODY + " Nueva conclusion agregada que cambia el sentido del diagnostico."
    report = _report(
        tmp_path,
        [_record("old-034", "v1", semantic=_MIGRATION_BODY)],
        [_record("new-0034", "v2", semantic=altered)],
        [_canon_record("new-0034", "v2")],
    )
    family = report["families"]["enriched"]
    assert family["identity_migrated_records"] == 0
    assert family["removed_historical_records"] == 1
    assert report["blocking"] is True


def test_mixed_growth_and_updates_are_counted_without_hardcoded_incident_values(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        [_record("unchanged", "v1"), _record("updated", "v1")],
        [_record("unchanged", "v1"), _record("updated", "v2", semantic="new"), _record("added", "v1")],
        [_canon_record("unchanged", "v1"), _canon_record("updated", "v2"), _canon_record("added", "v1")],
    )
    assert report["equivalence_status"] == "equivalent_with_expected_canonical_evolution"
    assert report["evolution"] == {"additions": 1, "updates": 1, "removals": 0, "regressions": 0, "redaction_vocabulary_evolution": 0, "additive_derivative_evolution": 0, "placeholder_resolved": 0, "semantic_projection_policy_evolution": 0, "non_versioned_canon_projection_evolution": 0, "identity_migrated": 0}


def test_schema_and_explicit_family_mismatches_block_a_version_update(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        [_record("same", "v1")],
        [_record("same", "v2", schema="surface/v2", artifact_family="ai")],
        [_canon_record("same", "v2")],
    )
    family = report["families"]["enriched"]
    assert family["schema_mismatches"] == 1
    assert family["family_mismatches"] == 1
    assert report["blocking"] is True


def test_duplicate_staging_identity_blocks(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        [],
        [_record("duplicate", "v1"), _record("duplicate", "v1")],
        [_canon_record("duplicate", "v1")],
    )
    assert report["families"]["enriched"]["duplicate_records"] == 1
    assert report["blocking"] is True


def test_unchanged_chunks_need_not_grow_for_new_non_chunkable_canon_record(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    staging = tmp_path / "staging"
    canon = tmp_path / "canon"
    chunk = {
        "chunk_id": "existing::chunk:0",
        "source_id": "existing",
        "source_version_id": "v1",
        "text": "stable chunk",
        "chunk_index": 0,
        "chunk_total": 1,
        "within_hard_max": True,
        "source_anchor": {"canon_id": "existing", "shard_file": "old.jsonl", "shard_line": 1},
    }
    changed_location = chunk | {"source_anchor": {"canon_id": "existing", "shard_file": "new.jsonl", "shard_line": 99}}
    _write_jsonl(baseline / "ai" / "chunks_ai_1.jsonl", [chunk])
    _write_jsonl(staging / "ai" / "chunks_ai_1.jsonl", [changed_location])
    _write_canon(canon, [_canon_record("existing", "v1"), _canon_record("non-chunkable", "v1")])
    report = build_equivalence_report(baseline, staging, canon_dir=canon, families=["chunks_ai"])
    assert report["equivalence_status"] == "equivalent"
    assert report["families"]["chunks_ai"]["chunk_mismatches"] == 0


def test_productive_write_boundary_rejects_missing_exact_authorization() -> None:
    with pytest.raises(ProductiveWriteBlocked, match="exact S0173 authorization phrase"):
        from rag_derivative_writers import promote_staging_transaction

        promote_staging_transaction(
            staging_root=REPO_ROOT / "data" / "out" / "local" / "pipeline" / "rag_derivation" / "s0173" / "staging",
            rollback_root=REPO_ROOT / "data" / "out" / "local" / "pipeline" / "rag_derivation" / "s0173" / "rollback_snapshot",
            authorization={},
            planned_families=["enriched"],
            transaction_journal=REPO_ROOT / "data" / "out" / "local" / "pipeline" / "rag_derivation" / "s0173" / "test-journal.jsonl",
            receipt_path=REPO_ROOT / "data" / "out" / "local" / "pipeline" / "rag_derivation" / "s0173" / "test-receipt.json",
        )


# ---------------------------------------------------------------------------
# RAG_TYPED_EQUIVALENCE_EVOLUTION_FIX: SEMANTIC_PROJECTION_POLICY_EVOLUTION and
# NON_VERSIONED_CANON_PROJECTION_EVOLUTION -- typed, narrow, non-id-specific
# recognition of two governed same-version_id derivative deltas that the four
# pre-existing categories did not cover: (a) a source_fields template prune a
# governed re-admission legitimately produces, optionally combined with
# ordinary redaction growth, and (b) a Lane B historical-review lifecycle
# reclassification surfacing in the rendered source_fields section.
# ---------------------------------------------------------------------------


def _source_fields_semantic_text(source_fields_lines: list[str], content: str = "algo real") -> str:
    return "\n".join(
        [
            "# Procedencia / source_fields",
            *source_fields_lines,
            "",
            "# Contenido principal",
            content,
        ]
    )


class TestTolerableTemplatePrune:
    def test_exact_prune_of_allowed_keys_is_recognized(self) -> None:
        previous = "\n".join(
            [
                "canonical_status: local_admitted",
                "created: 20260101000000000",
                "modified: 20260101000000000",
                "session_origin: s1",
                "tags: excluded_from_semantic_text_by_tag_sanitation_policy",
                "tmap.id: abc-123",
                "type: text/markdown",
            ]
        )
        current = "\n".join(["canonical_status: local_admitted", "session_origin: s1"])
        assert _tolerable_template_prune(previous, current) is True

    def test_removal_outside_allowed_key_set_is_rejected(self) -> None:
        previous = "\n".join(["canonical_status: local_admitted", "created: 20260101000000000", "session_origin: s1"])
        current = "canonical_status: local_admitted"
        assert _tolerable_template_prune(previous, current) is False

    def test_prune_combined_with_marker_substitution_on_surviving_key_is_recognized(self) -> None:
        previous = "\n".join(["created: 20260101000000000", "provenance_ref: data/canon [RAG_TAG_BLOCKED_NEVER]memoria"])
        # marker substitution on the surviving key: the redacted marker covers
        # more vocabulary than before, nothing else changes.
        previous = "\n".join(["created: 20260101000000000", "provenance_ref: sessions/06_diagnoses/memoria/x.json"])
        current = "\n".join(["provenance_ref: sessions/06_diagnoses/[RAG_TAG_BLOCKED]/x.json"])
        assert _tolerable_template_prune(previous, current) is True

    def test_non_marker_value_change_on_surviving_key_is_rejected(self) -> None:
        previous = "\n".join(["created: 20260101000000000", "session_origin: s1"])
        current = "session_origin: s2"
        assert _tolerable_template_prune(previous, current) is False

    def test_added_key_is_rejected(self) -> None:
        previous = "created: 20260101000000000"
        current = "\n".join(["created: 20260101000000000", "extra_new_field: value"])
        assert _tolerable_template_prune(previous, current) is False


class TestSemanticProjectionPolicyEvolution:
    def test_template_pruning_exact_is_recognized(self) -> None:
        previous = _source_fields_semantic_text(
            ["canonical_status: local_admitted", "created: 20260101000000000", "modified: 20260101000000000", "tags: excluded_from_semantic_text_by_tag_sanitation_policy", "tmap.id: abc", "type: text/markdown"]
        )
        current = _source_fields_semantic_text(["canonical_status: local_admitted"])
        assert _semantic_projection_policy_evolution(previous, current) is True

    def test_redaction_growth_alone_outside_source_fields_is_recognized(self) -> None:
        previous = "# Contenido principal\nalgo real memoria"
        current = "# Contenido principal\nalgo real [RAG_TAG_BLOCKED]"
        assert _semantic_projection_policy_evolution(previous, current) is True

    def test_pruning_combined_with_redaction_growth_is_recognized(self) -> None:
        previous = _source_fields_semantic_text(
            ["created: 20260101000000000", "modified: 20260101000000000"], content="algo real memoria"
        )
        current = _source_fields_semantic_text([], content="algo real [RAG_TAG_BLOCKED]")
        assert _semantic_projection_policy_evolution(previous, current) is True

    def test_removal_of_unauthorized_content_is_rejected(self) -> None:
        previous = _source_fields_semantic_text(["created: 20260101000000000", "session_origin: s1"])
        current = _source_fields_semantic_text([])
        assert _semantic_projection_policy_evolution(previous, current) is False

    def test_marker_substitution_alongside_unrelated_rewrite_is_rejected(self) -> None:
        # The marker/real-content swap alone is tolerable (either direction --
        # see _hunk_is_marker_substitution), but a second, unrelated word
        # changing in the same section is not, and must still fail closed.
        previous = "# Contenido principal\nalgo [RAG_TAG_BLOCKED] real y datos"
        current = "# Contenido principal\nalgo memoria real y estructuras"
        assert _semantic_projection_policy_evolution(previous, current) is False

    def test_unrelated_semantic_rewrite_is_rejected(self) -> None:
        previous = "# Contenido principal\nalgo real"
        current = "# Contenido principal\nalgo completamente distinto"
        assert _semantic_projection_policy_evolution(previous, current) is False

    def test_section_added_wholesale_is_rejected(self) -> None:
        previous = "# Contenido principal\nalgo real"
        current = "# Contenido principal\nalgo real\n\n# Relaciones canonicas\n- references -> other"
        assert _semantic_projection_policy_evolution(previous, current) is False


class TestTolerableLaneBLifecycleTransition:
    def _previous(self) -> str:
        return "\n".join(
            [
                "artifact_family: artefacto_repositorio",
                "authority_level: current_verified",
                "is_current_repo_artifact: true",
                "repo_lifecycle_state: current_repo_artifact",
                "repo_path: docs/example.md",
            ]
        )

    def test_lifecycle_projection_exact_is_recognized(self) -> None:
        current = "\n".join(
            [
                "artifact_family: artefacto_repositorio",
                "authority_level: historical_snapshot",
                "is_current_repo_artifact: false",
                "moved_to_candidate: 5add2c83-a347-5d6e-95cf-32c4a9e3bac8",
                "repo_lifecycle_state: historical_snapshot",
                "repo_path: docs/example.md",
            ]
        )
        assert _tolerable_lane_b_lifecycle_transition(self._previous(), current) is True

    def test_lifecycle_without_moved_to_candidate_is_recognized(self) -> None:
        current = "\n".join(
            [
                "artifact_family: artefacto_repositorio",
                "authority_level: historical_snapshot",
                "is_current_repo_artifact: false",
                "repo_lifecycle_state: historical_snapshot",
                "repo_path: docs/example.md",
            ]
        )
        assert _tolerable_lane_b_lifecycle_transition(self._previous(), current) is True

    def test_partial_lifecycle_transition_is_rejected(self) -> None:
        current = "\n".join(
            [
                "artifact_family: artefacto_repositorio",
                "authority_level: historical_snapshot",
                "is_current_repo_artifact: true",
                "repo_lifecycle_state: current_repo_artifact",
                "repo_path: docs/example.md",
            ]
        )
        assert _tolerable_lane_b_lifecycle_transition(self._previous(), current) is False

    def test_unrelated_key_change_alongside_lifecycle_is_rejected(self) -> None:
        current = "\n".join(
            [
                "artifact_family: artefacto_repositorio",
                "authority_level: historical_snapshot",
                "is_current_repo_artifact: false",
                "repo_lifecycle_state: historical_snapshot",
                "repo_path: docs/renamed.md",
            ]
        )
        assert _tolerable_lane_b_lifecycle_transition(self._previous(), current) is False

    def test_malformed_moved_to_candidate_is_rejected(self) -> None:
        current = "\n".join(
            [
                "artifact_family: artefacto_repositorio",
                "authority_level: historical_snapshot",
                "is_current_repo_artifact: false",
                "moved_to_candidate: not-a-uuid",
                "repo_lifecycle_state: historical_snapshot",
                "repo_path: docs/example.md",
            ]
        )
        assert _tolerable_lane_b_lifecycle_transition(self._previous(), current) is False

    def test_removed_key_is_rejected(self) -> None:
        current = "\n".join(
            [
                "authority_level: historical_snapshot",
                "is_current_repo_artifact: false",
                "repo_lifecycle_state: historical_snapshot",
            ]
        )
        assert _tolerable_lane_b_lifecycle_transition(self._previous(), current) is False


class TestNonVersionedCanonProjectionEvolution:
    def test_lifecycle_projection_exact_is_recognized(self) -> None:
        previous = _source_fields_semantic_text(
            [
                "authority_level: current_verified",
                "is_current_repo_artifact: true",
                "repo_lifecycle_state: current_repo_artifact",
            ]
        )
        current = _source_fields_semantic_text(
            [
                "authority_level: historical_snapshot",
                "is_current_repo_artifact: false",
                "moved_to_candidate: 5add2c83-a347-5d6e-95cf-32c4a9e3bac8",
                "repo_lifecycle_state: historical_snapshot",
            ]
        )
        assert _non_versioned_canon_projection_evolution(previous, current) is True

    def test_lifecycle_with_unrelated_content_rewrite_is_rejected(self) -> None:
        previous = _source_fields_semantic_text(
            ["authority_level: current_verified", "is_current_repo_artifact: true", "repo_lifecycle_state: current_repo_artifact"],
            content="algo real",
        )
        current = _source_fields_semantic_text(
            ["authority_level: historical_snapshot", "is_current_repo_artifact: false", "repo_lifecycle_state: historical_snapshot"],
            content="algo completamente distinto",
        )
        assert _non_versioned_canon_projection_evolution(previous, current) is False


class TestSemanticProjectionPolicyEvolutionEndToEnd:
    def test_template_prune_with_role_primary_placeholder_swap_is_non_blocking(self, tmp_path: Path) -> None:
        baseline = _record(
            "same",
            "v1",
            semantic=_source_fields_semantic_text(
                ["canonical_status: local_admitted", "created: 20260101000000000", "modified: 20260101000000000", "tags: excluded_from_semantic_text_by_tag_sanitation_policy", "tmap.id: abc", "type: text/markdown"]
            ),
        )
        baseline["retrieval_hints"] = ["thematic_diagnostic", "unclassified"]
        baseline["embedding_metadata"] = {"role_primary": "unclassified", "semantic_family": "thematic_diagnostic"}
        staged = _record(
            "same",
            "v1",
            semantic=_source_fields_semantic_text(["canonical_status: local_admitted"]),
        )
        staged["retrieval_hints"] = ["diagnostico", "thematic_diagnostic"]
        staged["embedding_metadata"] = {"role_primary": "diagnostico", "semantic_family": "thematic_diagnostic"}
        report = _report(tmp_path, [baseline], [staged], [_canon_record("same", "v1")])
        family = report["families"]["enriched"]
        assert report["blocking"] is False
        assert family["unexpected_semantic_regressions"] == 0
        assert family["semantic_projection_policy_evolution"] == 1
        assert report["evolution"]["semantic_projection_policy_evolution"] == 1
        assert report["equivalence_status"] == "equivalent_with_expected_canonical_evolution"

    def test_template_prune_with_two_different_metadata_pairs_still_blocks(self, tmp_path: Path) -> None:
        # A single, unambiguous placeholder pair is tolerated (see the
        # success case above); two keys resolving to two *different* pairs
        # is ambiguous and must still fail closed, exactly like the
        # pre-existing placeholder_resolved category's own contract.
        baseline = _record(
            "same",
            "v1",
            semantic=_source_fields_semantic_text(["created: 20260101000000000"]),
        )
        baseline["embedding_metadata"] = {"role_primary": "unclassified", "secondary_role": "unclassified"}
        staged = _record("same", "v1", semantic=_source_fields_semantic_text([]))
        staged["embedding_metadata"] = {"role_primary": "diagnostico", "secondary_role": "artefacto"}
        report = _report(tmp_path, [baseline], [staged], [_canon_record("same", "v1")])
        family = report["families"]["enriched"]
        assert report["blocking"] is True
        assert family["semantic_projection_policy_evolution"] == 0
        assert family["unexpected_semantic_regressions"] == 1


class TestNonVersionedCanonProjectionEvolutionEndToEnd:
    def test_lane_b_lifecycle_transition_is_non_blocking(self, tmp_path: Path) -> None:
        baseline = _record(
            "same",
            "v1",
            semantic=_source_fields_semantic_text(
                [
                    "artifact_family: artefacto_repositorio",
                    "authority_level: current_verified",
                    "is_current_repo_artifact: true",
                    "repo_lifecycle_state: current_repo_artifact",
                ]
            ),
        )
        staged = _record(
            "same",
            "v1",
            semantic=_source_fields_semantic_text(
                [
                    "artifact_family: artefacto_repositorio",
                    "authority_level: historical_snapshot",
                    "is_current_repo_artifact: false",
                    "moved_to_candidate: 5add2c83-a347-5d6e-95cf-32c4a9e3bac8",
                    "repo_lifecycle_state: historical_snapshot",
                ]
            ),
        )
        report = _report(tmp_path, [baseline], [staged], [_canon_record("same", "v1")])
        family = report["families"]["enriched"]
        assert report["blocking"] is False
        assert family["unexpected_semantic_regressions"] == 0
        assert family["non_versioned_canon_projection_evolution"] == 1
        assert report["evolution"]["non_versioned_canon_projection_evolution"] == 1
        assert report["equivalence_status"] == "equivalent_with_expected_canonical_evolution"

    def test_lane_b_lifecycle_transition_with_unrelated_content_rewrite_still_blocks(self, tmp_path: Path) -> None:
        baseline = _record(
            "same",
            "v1",
            semantic=_source_fields_semantic_text(
                ["authority_level: current_verified", "is_current_repo_artifact: true", "repo_lifecycle_state: current_repo_artifact"],
                content="algo real",
            ),
        )
        staged = _record(
            "same",
            "v1",
            semantic=_source_fields_semantic_text(
                ["authority_level: historical_snapshot", "is_current_repo_artifact: false", "repo_lifecycle_state: historical_snapshot"],
                content="algo completamente distinto",
            ),
        )
        report = _report(tmp_path, [baseline], [staged], [_canon_record("same", "v1")])
        family = report["families"]["enriched"]
        assert report["blocking"] is True
        assert family["non_versioned_canon_projection_evolution"] == 0
        assert family["unexpected_semantic_regressions"] == 1

    def test_unknown_same_version_metadata_only_difference_still_blocks(self, tmp_path: Path) -> None:
        baseline = _record("same", "v1", semantic="algo real")
        baseline["embedding_metadata"] = {"promoted_metadata": {"topics": ["rag"]}}
        staged = _record("same", "v1", semantic="algo real")
        staged["embedding_metadata"] = {"promoted_metadata": {"topics": ["completely_different"]}}
        report = _report(tmp_path, [baseline], [staged], [_canon_record("same", "v1")])
        family = report["families"]["enriched"]
        assert report["blocking"] is True
        assert family["semantic_projection_policy_evolution"] == 0
        assert family["non_versioned_canon_projection_evolution"] == 0
        assert family["unexpected_semantic_regressions"] == 1
