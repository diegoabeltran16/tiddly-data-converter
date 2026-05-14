"""
Field equivalence characterization tests for build_enriched_record(),
build_ai_record(), and chunk_node() — S0112.

Freezes structure, types, and stable SHA-256 hashes of sensitive fields
(ai_summary, retrieval_hints, preview_text, semantic_text) so that future
refactors inside Fase D can be detected before they reach production.

Fixtures are fully synthetic — no reads from data/out/local/.
Hashes computed with: SHA-256(json.dumps(v, ensure_ascii=False, sort_keys=True))[:16]

These tests are a precondition for extracting build_enriched_record(),
build_ai_record(), and chunk_node() (Fase D). They must pass before AND
after the extraction with zero behavioral change.
"""
import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python_scripts"))

from derive_layers import (
    build_ai_record,
    build_enriched_record,
    build_relation_resolution_index,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def stable_hash(v) -> str:
    encoded = json.dumps(v, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


# ── Synthetic fixtures ─────────────────────────────────────────────────────────

FIXTURE_GLOSSARY = {
    "id": "aaaaaaaa-bbbb-5ccc-8ddd-eeeeeeeeeeee",
    "title": "Fixture Glossary Term",
    "key": "fixture-glossary-term",
    "canonical_slug": "fixture-glossary-term",
    "role_primary": "glossary",
    "text": "A short glossary entry for testing purposes.",
    "content_type": "text/markdown",
    "relations": [],
    "tags": "[[glossary]]",
    "schema_version": "1.0",
    "created": "20240101000000000",
    "modified": "20240101000000000",
}

FIXTURE_LOG = {
    "id": "bbbbbbbb-cccc-5ddd-8eee-ffffffffffff",
    "title": "Fixture Log Entry",
    "key": "fixture-log-entry",
    "canonical_slug": "fixture-log-entry",
    "role_primary": "log",
    "text": "Session log: fixed steps executed successfully.",
    "content_type": "text/markdown",
    "relations": [],
    "tags": "[[log]]",
    "schema_version": "1.0",
    "created": "20240101000000000",
    "modified": "20240101000000000",
}

# Long enough text (298 tokens) to trigger structured_chunk at target_tokens=100.
_CODE_TEXT = "result = compute_value(x, y)\n" * 50
FIXTURE_CODE = {
    "id": "cccccccc-dddd-5eee-8fff-000000000001",
    "title": "Fixture Code Module",
    "key": "fixture-code-module",
    "canonical_slug": "fixture-code-module",
    "role_primary": "code",
    "text": _CODE_TEXT,
    "content_type": "text/plain",
    "relations": [],
    "tags": "[[code]]",
    "schema_version": "1.0",
    "created": "20240101000000000",
    "modified": "20240101000000000",
}


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _build_enriched(rec=None, *, role="glossary", taxonomy=None, section=None):
    rec = rec or FIXTURE_GLOSSARY
    return build_enriched_record(
        rec,
        "tiddlers_1.jsonl",
        1,
        role,
        taxonomy or [role],
        section or [rec["title"]],
    )


def _build_ai(rec, *, role, target_tokens=500, max_tokens=1000):
    canon = [(rec, "tiddlers_1.jsonl", 1)]
    relation_index = build_relation_resolution_index(canon)
    ai_rec, chunks, invalid_rels, payload_info, relation_event = build_ai_record(
        rec,
        "tiddlers_1.jsonl",
        1,
        role,
        [role],
        [rec["title"]],
        relation_index["ids"],
        relation_index,
        target_tokens,
        max_tokens,
        None,
    )
    return ai_rec, chunks, invalid_rels, payload_info, relation_event


# ── Enriched record equivalence ────────────────────────────────────────────────

class TestEnrichedRecordEquivalence:
    """Freezes field values for build_enriched_record() on FIXTURE_GLOSSARY."""

    def test_id_preserved(self):
        enriched = _build_enriched()
        assert enriched["id"] == "aaaaaaaa-bbbb-5ccc-8ddd-eeeeeeeeeeee"

    def test_role_primary_passed_through(self):
        enriched = _build_enriched()
        assert enriched["role_primary"] == "glossary"

    def test_role_primary_contract_verdict_ok(self):
        enriched = _build_enriched()
        assert enriched["role_primary_contract_verdict"] == "role_ok"

    def test_corpus_state_live_path(self):
        enriched = _build_enriched()
        assert enriched["corpus_state"] == "live_path"

    def test_chunk_eligibility_eligible(self):
        enriched = _build_enriched()
        assert enriched["chunk_eligibility"] == "eligible"

    def test_readability_prose_for_markdown(self):
        enriched = _build_enriched()
        assert enriched["readability"] == "prose"

    def test_preview_text_hash_frozen(self):
        enriched = _build_enriched()
        assert stable_hash(enriched["preview_text"]) == "fb67b6d5f8a761e1"

    def test_semantic_text_hash_frozen(self):
        enriched = _build_enriched()
        assert stable_hash(enriched["semantic_text"]) == "fb67b6d5f8a761e1"

    def test_token_estimate_frozen(self):
        enriched = _build_enriched()
        assert enriched["size_metrics"]["token_estimate"] == 10

    def test_required_fields_present(self):
        enriched = _build_enriched()
        required = {
            "id", "title", "role_primary", "corpus_state", "chunk_eligibility",
            "readability", "preview_text", "semantic_text", "content",
            "size_metrics", "derivation", "quality_flags",
        }
        assert required <= set(enriched.keys())

    def test_content_has_markdown_key(self):
        enriched = _build_enriched()
        assert "markdown" in enriched["content"]
        assert "plain" in enriched["content"]

    def test_derivation_has_session_key(self):
        enriched = _build_enriched()
        assert "session" in enriched["derivation"]
        assert enriched["derivation"]["source_shard"] == "tiddlers_1.jsonl"

    def test_idempotent_for_same_input(self):
        e1 = _build_enriched()
        e2 = _build_enriched()
        assert stable_hash(e1["preview_text"]) == stable_hash(e2["preview_text"])
        assert stable_hash(e1["semantic_text"]) == stable_hash(e2["semantic_text"])


# ── AI record equivalence (no chunks) ─────────────────────────────────────────

class TestAiRecordEquivalence:
    """Freezes field values for build_ai_record() on FIXTURE_LOG (small, no chunks)."""

    def test_returns_5_tuple(self):
        result = _build_ai(FIXTURE_LOG, role="log")
        assert len(result) == 5

    def test_chunk_strategy_no_chunk_small(self):
        ai_rec, *_ = _build_ai(FIXTURE_LOG, role="log")
        assert ai_rec["chunk_strategy"] == "no_chunk_small"

    def test_is_chunkable_text_true(self):
        ai_rec, *_ = _build_ai(FIXTURE_LOG, role="log")
        assert ai_rec["is_chunkable_text"] is True

    def test_token_estimate_frozen(self):
        ai_rec, *_ = _build_ai(FIXTURE_LOG, role="log")
        assert ai_rec["token_estimate"] == 10

    def test_chunk_eligibility_eligible(self):
        ai_rec, *_ = _build_ai(FIXTURE_LOG, role="log")
        assert ai_rec["chunk_eligibility"] == "eligible"

    def test_no_chunks_produced(self):
        ai_rec, chunks, *_ = _build_ai(FIXTURE_LOG, role="log")
        assert chunks == []

    def test_no_invalid_rels(self):
        ai_rec, chunks, invalid_rels, *_ = _build_ai(FIXTURE_LOG, role="log")
        assert invalid_rels == []

    def test_relation_targets_empty(self):
        ai_rec, *_ = _build_ai(FIXTURE_LOG, role="log")
        assert ai_rec["relation_targets"] == []

    def test_ai_summary_hash_frozen(self):
        ai_rec, *_ = _build_ai(FIXTURE_LOG, role="log")
        assert stable_hash(ai_rec["ai_summary"]) == "220a0ae8adab871e"

    def test_semantic_text_hash_frozen(self):
        ai_rec, *_ = _build_ai(FIXTURE_LOG, role="log")
        assert stable_hash(ai_rec["semantic_text"]) == "220a0ae8adab871e"

    def test_preview_text_hash_frozen(self):
        ai_rec, *_ = _build_ai(FIXTURE_LOG, role="log")
        assert stable_hash(ai_rec["preview_text"]) == "220a0ae8adab871e"

    def test_retrieval_hints_hash_frozen(self):
        ai_rec, *_ = _build_ai(FIXTURE_LOG, role="log")
        assert stable_hash(ai_rec["retrieval_hints"]) == "4367f53966ade3fa"

    def test_retrieval_hints_count_frozen(self):
        ai_rec, *_ = _build_ai(FIXTURE_LOG, role="log")
        assert len(ai_rec["retrieval_hints"]) == 3

    def test_required_ai_fields_present(self):
        ai_rec, *_ = _build_ai(FIXTURE_LOG, role="log")
        required = {
            "id", "title", "role_primary", "ai_summary", "preview_text",
            "semantic_text", "retrieval_hints", "relation_targets",
            "chunk_strategy", "chunk_eligibility", "is_chunkable_text",
            "token_estimate", "corpus_state", "derivation",
        }
        assert required <= set(ai_rec.keys())

    def test_idempotent_for_same_input(self):
        ai1, *_ = _build_ai(FIXTURE_LOG, role="log")
        ai2, *_ = _build_ai(FIXTURE_LOG, role="log")
        assert stable_hash(ai1["ai_summary"]) == stable_hash(ai2["ai_summary"])
        assert stable_hash(ai1["retrieval_hints"]) == stable_hash(ai2["retrieval_hints"])


# ── Chunk equivalence (structured_chunk path) ──────────────────────────────────

class TestChunkEquivalence:
    """Freezes chunk output for build_ai_record() on FIXTURE_CODE (structured_chunk, 4 chunks)."""

    def test_chunk_strategy_structured_chunk(self):
        ai_rec, *_ = _build_ai(FIXTURE_CODE, role="code", target_tokens=100, max_tokens=500)
        assert ai_rec["chunk_strategy"] == "structured_chunk"

    def test_is_chunkable_text_true(self):
        ai_rec, *_ = _build_ai(FIXTURE_CODE, role="code", target_tokens=100, max_tokens=500)
        assert ai_rec["is_chunkable_text"] is True

    def test_token_estimate_frozen(self):
        ai_rec, *_ = _build_ai(FIXTURE_CODE, role="code", target_tokens=100, max_tokens=500)
        assert ai_rec["token_estimate"] == 298

    def test_chunk_count_frozen(self):
        _, chunks, *_ = _build_ai(FIXTURE_CODE, role="code", target_tokens=100, max_tokens=500)
        assert len(chunks) == 4

    def test_chunk_total_frozen(self):
        _, chunks, *_ = _build_ai(FIXTURE_CODE, role="code", target_tokens=100, max_tokens=500)
        for chunk in chunks:
            assert chunk["chunk_total"] == 4

    def test_chunk_source_id_matches_fixture(self):
        _, chunks, *_ = _build_ai(FIXTURE_CODE, role="code", target_tokens=100, max_tokens=500)
        for chunk in chunks:
            assert chunk["source_id"] == "cccccccc-dddd-5eee-8fff-000000000001"

    def test_chunk_ids_have_expected_format(self):
        _, chunks, *_ = _build_ai(FIXTURE_CODE, role="code", target_tokens=100, max_tokens=500)
        for i, chunk in enumerate(chunks):
            assert chunk["chunk_id"] == f"cccccccc-dddd-5eee-8fff-000000000001::chunk:{i}"

    def test_chunk_indices_sequential(self):
        _, chunks, *_ = _build_ai(FIXTURE_CODE, role="code", target_tokens=100, max_tokens=500)
        assert [c["chunk_index"] for c in chunks] == list(range(4))

    def test_chunk0_role_primary(self):
        _, chunks, *_ = _build_ai(FIXTURE_CODE, role="code", target_tokens=100, max_tokens=500)
        assert chunks[0]["role_primary"] == "code"

    def test_chunk0_within_target(self):
        _, chunks, *_ = _build_ai(FIXTURE_CODE, role="code", target_tokens=100, max_tokens=500)
        assert chunks[0]["within_target"] is True

    def test_chunk0_within_hard_max(self):
        _, chunks, *_ = _build_ai(FIXTURE_CODE, role="code", target_tokens=100, max_tokens=500)
        assert chunks[0]["within_hard_max"] is True

    def test_chunk0_text_hash_frozen(self):
        _, chunks, *_ = _build_ai(FIXTURE_CODE, role="code", target_tokens=100, max_tokens=500)
        assert stable_hash(chunks[0]["text"]) == "b71c14f6bf64b1db"

    def test_chunk0_retrieval_hints_frozen(self):
        _, chunks, *_ = _build_ai(FIXTURE_CODE, role="code", target_tokens=100, max_tokens=500)
        assert chunks[0]["retrieval_hints"] == ["fixture", "code", "module"]

    def test_chunks_required_fields_present(self):
        _, chunks, *_ = _build_ai(FIXTURE_CODE, role="code", target_tokens=100, max_tokens=500)
        required = {
            "chunk_id", "source_id", "chunk_index", "chunk_total",
            "role_primary", "text", "token_estimate", "within_target",
            "within_hard_max", "retrieval_hints", "relation_targets",
            "corpus_state", "chunk_eligibility",
        }
        for chunk in chunks:
            assert required <= set(chunk.keys())

    def test_idempotent_chunk0_text(self):
        _, chunks1, *_ = _build_ai(FIXTURE_CODE, role="code", target_tokens=100, max_tokens=500)
        _, chunks2, *_ = _build_ai(FIXTURE_CODE, role="code", target_tokens=100, max_tokens=500)
        assert stable_hash(chunks1[0]["text"]) == stable_hash(chunks2[0]["text"])
