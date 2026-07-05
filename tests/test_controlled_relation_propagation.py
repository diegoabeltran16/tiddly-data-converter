#!/usr/bin/env python3
"""Regression tests for controlled_v1 chunk relation propagation."""

from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

import derive_layers  # noqa: E402


def _target(idx: int, title: str | None = None) -> dict:
    title = title or f"Target {idx}"
    return {
        "id": f"target-{idx}",
        "title": title,
        "key": title,
        "canonical_slug": title.lower().replace(" ", "-"),
        "role_primary": "glossary",
        "text": title,
        "content_type": "text/markdown",
        "relations": [],
    }


def _source(
    *,
    relations: list[dict] | None = None,
    embedded_relations: list[dict] | None = None,
    idx: int = 1,
) -> dict:
    return {
        "id": f"source-{idx}",
        "title": f"Source {idx}",
        "key": f"Source {idx}",
        "canonical_slug": f"source-{idx}",
        "role_primary": "readme",
        "text": "# Intro\n\n" + ("alpha beta gamma delta. " * 120),
        "content_type": "text/markdown",
        "content": {
            "plain": json.dumps({"relations": embedded_relations or []}),
        },
        "relations": relations or [],
    }


def _context(records: list[dict]) -> tuple[dict, dict]:
    canon = [(rec, "tiddlers_1.jsonl", idx) for idx, rec in enumerate(records, 1)]
    relation_index = derive_layers.build_relation_resolution_index(canon)
    classified = [
        (
            rec,
            "tiddlers_1.jsonl",
            idx,
            rec.get("role_primary") or "readme",
            ["tests"],
            [rec.get("title")],
        )
        for idx, rec in enumerate(records, 1)
    ]
    propagation_context = derive_layers.build_relation_propagation_context(
        classified,
        relation_index,
    )
    return relation_index, propagation_context


def _build_chunks(source: dict, records: list[dict]) -> tuple[list[dict], list[dict], dict]:
    relation_index, propagation_context = _context(records)
    ai_rec, chunks, invalid_rels, _payload, event = derive_layers.build_ai_record(
        source,
        "tiddlers_1.jsonl",
        1,
        "readme",
        ["tests"],
        [source["title"]],
        relation_index["ids"],
        relation_index,
        80,
        200,
        propagation_context,
    )
    assert ai_rec["id"] == source["id"]
    assert chunks
    return chunks, invalid_rels, event


def test_chunk_inherits_valid_relations_from_source_tiddler() -> None:
    target = _target(1, "Useful Target")
    source = _source(relations=[{"type": "define", "target": "Useful Target"}])

    chunks, invalid_rels, event = _build_chunks(source, [source, target])

    assert invalid_rels == []
    assert chunks[0]["relation_targets"] == [
        {"target_id": "target-1", "type": "define", "evidence": "canonical_relation"}
    ]
    assert chunks[0]["relation_count"] == 1
    assert chunks[0]["relation_target_count"] == 1
    assert chunks[0]["relation_propagation_policy"] == "controlled_v1"
    assert event["relation_targets_after"] == 1


def test_stale_embedded_target_is_blocked_from_chunk_propagation() -> None:
    source = _source(
        embedded_relations=[{"type": "define", "target": "Missing Target"}],
    )

    chunks, invalid_rels, event = _build_chunks(source, [source])

    assert chunks[0]["relation_targets"] == []
    assert event["stale_relation_targets_blocked"] == 1
    assert "stale_target_blocked" in event["relation_quality_flags"]
    assert invalid_rels[0]["target_ref"] == "Missing Target"


def test_duplicate_target_is_collapsed_across_canonical_and_embedded_sources() -> None:
    target = _target(1, "Shared Target")
    source = _source(
        relations=[{"type": "usa", "target_id": "target-1"}],
        embedded_relations=[{"type": "define", "target": "Shared Target"}],
    )

    chunks, _invalid_rels, event = _build_chunks(source, [source, target])

    target_ids = [rel["target_id"] for rel in chunks[0]["relation_targets"]]
    assert target_ids == ["target-1"]
    assert chunks[0]["relation_targets"][0]["type"] == "define"
    assert event["duplicate_relation_targets_collapsed"] == 1


def test_generic_hub_target_is_detected_and_filtered() -> None:
    hub = _target(99, "Generic Hub")
    sources = [
        _source(relations=[{"type": "usa", "target": "Generic Hub"}], idx=idx)
        for idx in range(1, 22)
    ]

    chunks, _invalid_rels, event = _build_chunks(sources[0], [*sources, hub])

    assert chunks[0]["relation_targets"] == []
    assert event["hub_targets_filtered"] == 1
    assert "hub_target_filtered" in event["relation_quality_flags"]


def test_relation_target_limit_per_chunk_is_respected() -> None:
    targets = [_target(idx) for idx in range(1, 11)]
    source = _source(
        relations=[
            {"type": "define", "target_id": target["id"]}
            for target in targets
        ],
    )

    chunks, _invalid_rels, event = _build_chunks(source, [source, *targets])

    assert len(chunks[0]["relation_targets"]) == derive_layers.MAX_RELATION_TARGETS_PER_CHUNK
    assert event["relation_targets_capped"] == 2


def test_controlled_chunks_remain_jsonl_serializable_and_schema_compatible() -> None:
    target = _target(1)
    source = _source(relations=[{"type": "define", "target_id": "target-1"}])

    chunks, _invalid_rels, _event = _build_chunks(source, [source, target])
    encoded = json.dumps(chunks[0], ensure_ascii=False)
    decoded = json.loads(encoded)

    assert isinstance(decoded["relation_targets"], list)
    assert decoded["relation_count"] == len(decoded["relation_targets"])
    assert decoded["relation_target_count"] == len(decoded["relation_targets"])
    assert decoded["source_id"] == "source-1"
    assert decoded["source_title"] == "Source 1"
    assert decoded["source_canonical_slug"] == "source-1"
