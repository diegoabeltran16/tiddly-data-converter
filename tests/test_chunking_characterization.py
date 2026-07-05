"""
Characterization tests for chunking.py — S0109.

These tests freeze the observable behavior of the 13 chunking functions
extracted from derive_layers.py. They serve as the equivalence guard:
behavior must be identical before and after the extraction.

Tests follow the same patterns as tests/fixtures/s52/test_chunking_structure.py
but target the new isolated chunking module.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "python_scripts"))

import pytest
from chunking import (
    DEFAULT_MICROCHUNK_MIN_TOKENS,
    chunk_by_code_boundaries,
    chunk_by_headers,
    chunk_by_paragraphs,
    chunk_by_sentences,
    densify_microchunks,
    extract_chunk_heading,
    hard_split,
    is_code_like_payload,
    is_microchunk,
    is_separator_only_chunk,
    join_chunk_text,
    merge_segments,
    split_structurally,
)
from text_utils import estimate_tokens


# ── chunk_by_headers ──────────────────────────────────────────────────────────

class TestChunkByHeaders:
    def test_single_section_returns_one_chunk(self):
        text = "# Title\nsome content"
        result = chunk_by_headers(text)
        assert len(result) == 1
        assert "Title" in result[0]

    def test_two_headers_split_into_two(self):
        text = "# A\ncontent A\n## B\ncontent B"
        result = chunk_by_headers(text)
        assert len(result) == 2

    def test_no_headers_returns_original(self):
        text = "plain text without headers"
        result = chunk_by_headers(text)
        assert len(result) == 1
        assert result[0].strip() == text.strip()

    def test_empty_sections_filtered(self):
        text = "# A\n# B\ncontent"
        result = chunk_by_headers(text)
        assert all(s.strip() for s in result)

    def test_three_sections(self):
        text = "# H1\ntext1\n## H2\ntext2\n### H3\ntext3"
        result = chunk_by_headers(text)
        assert len(result) == 3


# ── chunk_by_paragraphs ───────────────────────────────────────────────────────

class TestChunkByParagraphs:
    def test_double_newline_splits(self):
        text = "para one\n\npara two"
        result = chunk_by_paragraphs(text)
        assert len(result) == 2

    def test_single_paragraph(self):
        text = "just one paragraph"
        result = chunk_by_paragraphs(text)
        assert len(result) == 1

    def test_empty_paragraphs_filtered(self):
        text = "para1\n\n\n\npara2"
        result = chunk_by_paragraphs(text)
        assert len(result) == 2
        assert all(p.strip() for p in result)


# ── chunk_by_sentences ────────────────────────────────────────────────────────

class TestChunkBySentences:
    def test_splits_on_period(self):
        text = "First sentence. Second sentence. Third."
        result = chunk_by_sentences(text)
        assert len(result) >= 2

    def test_single_sentence_not_split(self):
        text = "Only one sentence here"
        result = chunk_by_sentences(text)
        assert len(result) == 1


# ── chunk_by_code_boundaries ──────────────────────────────────────────────────

class TestChunkByCodeBoundaries:
    def test_splits_on_def(self):
        text = "def foo():\n    return 1\ndef bar():\n    return 2"
        result = chunk_by_code_boundaries(text)
        assert len(result) == 2

    def test_splits_on_class(self):
        text = "class A:\n    pass\nclass B:\n    pass"
        result = chunk_by_code_boundaries(text)
        assert len(result) == 2

    def test_no_boundaries_returns_one(self):
        text = "x = 1\ny = 2\nz = 3"
        result = chunk_by_code_boundaries(text)
        assert len(result) == 1


# ── hard_split ────────────────────────────────────────────────────────────────

class TestHardSplit:
    def test_short_text_not_split(self):
        text = "short text"
        result = hard_split(text, 1000)
        assert len(result) == 1

    def test_long_text_is_split(self):
        text = "word " * 2000
        result = hard_split(text, 100)
        assert len(result) > 1

    def test_all_parts_nonempty(self):
        text = "word " * 500
        result = hard_split(text, 50)
        assert all(r.strip() for r in result)

    def test_no_content_lost(self):
        text = "abc def ghi jkl mno pqr stu vwx yz. " * 200
        result = hard_split(text, 40)
        combined = " ".join(result)
        for word in ["abc", "def", "yz."]:
            assert word in combined


# ── merge_segments ────────────────────────────────────────────────────────────

class TestMergeSegments:
    def test_small_segments_merged(self):
        segments = ["a", "b", "c"]
        result = merge_segments(segments, 500, 1000)
        assert len(result) == 1

    def test_large_segment_hard_split(self):
        big = "word " * 2000
        result = merge_segments([big], 100, 200)
        assert len(result) > 1

    def test_result_nonempty(self):
        segments = ["hello", "world"]
        result = merge_segments(segments, 1000, 2000)
        assert all(r.strip() for r in result)


# ── is_code_like_payload ──────────────────────────────────────────────────────

class TestIsCodeLikePayload:
    def test_code_source_role(self):
        assert is_code_like_payload("anything", "code_source") is True

    def test_test_fixture_role(self):
        assert is_code_like_payload("anything", "test_fixture") is True

    def test_py_extension(self):
        assert is_code_like_payload("script.py", "session") is True

    def test_go_extension(self):
        assert is_code_like_payload("main.go", "session") is True

    def test_prose_title(self):
        assert is_code_like_payload("My hypothesis", "hypothesis") is False

    def test_rs_extension(self):
        assert is_code_like_payload("lib.rs", "session") is True


# ── split_structurally ────────────────────────────────────────────────────────

class TestSplitStructurally:
    def test_short_text_not_split(self):
        text = "Hello world"
        result = split_structurally(text, "test.md", "session", 1800, 4000)
        assert result == [text]

    def test_empty_text_returns_empty(self):
        result = split_structurally("", "test.md", "session", 1800, 4000)
        assert result == []

    def test_long_prose_splits(self):
        text = ("The quick brown fox. " * 800) + "\n\n" + ("Another paragraph. " * 800)
        result = split_structurally(text, "doc.md", "session", 1800, 4000)
        assert len(result) > 1

    def test_long_text_with_headers_splits(self):
        text = (
            "# Section A\n" + ("content A " * 800) +
            "\n\n## Section B\n" + ("content B " * 700)
        )
        result = split_structurally(text, "doc.md", "session", 1800, 4000)
        assert len(result) > 1

    def test_respects_target_tokens(self):
        text = (
            "# A\n" + ("uno dos tres. " * 800) +
            "\n\n## B\n" + ("cuatro cinco seis. " * 700) +
            "\n\n### C\n" + ("siete ocho nueve. " * 650)
        )
        result = split_structurally(text, "README.md", "readme", 1800, 4000)
        for chunk in result:
            tok = estimate_tokens(chunk)
            assert tok <= 4000, f"Chunk exceeds hard max: {tok} tokens"


# ── join_chunk_text ───────────────────────────────────────────────────────────

class TestJoinChunkText:
    def test_joins_with_double_newline(self):
        result = join_chunk_text("left", "right")
        assert result == "left\n\nright"

    def test_empty_left_returns_right(self):
        result = join_chunk_text("", "right")
        assert result == "right"

    def test_empty_right_returns_left(self):
        result = join_chunk_text("left", "")
        assert result == "left"

    def test_strips_trailing_from_left(self):
        result = join_chunk_text("left   ", "right")
        assert result == "left\n\nright"


# ── is_separator_only_chunk ───────────────────────────────────────────────────

class TestIsSeparatorOnlyChunk:
    def test_heading_only_is_separator(self):
        assert is_separator_only_chunk("# Title") is True

    def test_content_is_not_separator(self):
        assert is_separator_only_chunk("# Title\nsome content") is False

    def test_empty_is_separator(self):
        assert is_separator_only_chunk("") is True

    def test_horizontal_rule_is_separator(self):
        assert is_separator_only_chunk("---") is True

    def test_code_fence_is_separator(self):
        assert is_separator_only_chunk("```") is True


# ── is_microchunk ─────────────────────────────────────────────────────────────

class TestIsMicrochunk:
    def test_low_token_count_is_micro(self):
        assert is_microchunk("tiny", 10) is True

    def test_high_token_count_is_not_micro(self):
        text = "word " * 200
        tok = estimate_tokens(text)
        assert is_microchunk(text, tok) is False

    def test_separator_only_is_micro_regardless_of_tokens(self):
        assert is_microchunk("# Title", 100) is True

    def test_constant_value_is_80(self):
        assert DEFAULT_MICROCHUNK_MIN_TOKENS == 80


# ── densify_microchunks ───────────────────────────────────────────────────────

class TestDensifyMicrochunks:
    def test_single_chunk_unchanged(self):
        chunks = ["hello world"]
        result = densify_microchunks(chunks, 1800)
        assert len(result) == 1

    def test_heading_only_merged_into_next(self):
        chunks = ["# Heading", "actual content here that has real body text"]
        result = densify_microchunks(chunks, 1800)
        assert len(result) == 1
        assert "Heading" in result[0]
        assert "actual content" in result[0]

    def test_empty_chunks_filtered(self):
        chunks = ["", "  ", "real content"]
        result = densify_microchunks(chunks, 1800)
        assert all(c.strip() for c in result)

    def test_large_chunks_not_merged(self):
        big = "word " * 1000
        chunks = [big, big]
        result = densify_microchunks(chunks, 1800)
        assert len(result) == 2


# ── extract_chunk_heading ─────────────────────────────────────────────────────

class TestExtractChunkHeading:
    def test_uses_first_heading(self):
        text = "# My Heading\nsome content"
        result = extract_chunk_heading(text, [], "fallback")
        assert result == "# My Heading"

    def test_falls_back_to_section_path(self):
        text = "no heading here just text"
        result = extract_chunk_heading(text, ["section > subsection"], "fallback")
        assert "section" in result

    def test_falls_back_to_title(self):
        text = "no heading here just text"
        result = extract_chunk_heading(text, [], "my title")
        assert result == "my title"

    def test_skips_tiddlywiki_meta_headings(self):
        text = "# [[Tags]]\n# Real Heading\ncontent"
        result = extract_chunk_heading(text, [], "fallback")
        assert "Real Heading" in result or result == "fallback"

    def test_truncates_at_160_chars(self):
        long_heading = "# " + "x" * 200
        result = extract_chunk_heading(long_heading, [], "fallback")
        assert len(result) <= 160
