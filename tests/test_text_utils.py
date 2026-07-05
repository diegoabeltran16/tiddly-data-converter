"""
Characterization tests for text_utils.py — S0108.

These tests freeze observable behavior of the 7 pure-text functions
extracted from derive_layers.py. They must pass identically before and
after the extraction, serving as the equivalence guard.
"""
import sys
import os

# Allow importing from src/python_scripts/ without installing the package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "python_scripts"))

import pytest
from text_utils import (
    estimate_tokens,
    looks_like_build_artifact_path,
    looks_like_inventory_manifest,
    looks_like_repo_path,
    normalize_for_dedup,
    safe_str,
    strip_emoji,
)


# ── safe_str ──────────────────────────────────────────────────────────────────

class TestSafeStr:
    def test_none_returns_empty(self):
        assert safe_str(None) == ""

    def test_string_passthrough(self):
        assert safe_str("hello") == "hello"

    def test_int_converted(self):
        assert safe_str(42) == "42"

    def test_empty_string(self):
        assert safe_str("") == ""

    def test_zero_converted(self):
        assert safe_str(0) == "0"

    def test_false_converted(self):
        assert safe_str(False) == "False"


# ── normalize_for_dedup ───────────────────────────────────────────────────────

class TestNormalizeForDedup:
    def test_lowercase(self):
        assert normalize_for_dedup("HELLO") == "hello"

    def test_strips_whitespace(self):
        assert normalize_for_dedup("  hello  ") == "hello"

    def test_removes_accents(self):
        assert normalize_for_dedup("café") == "cafe"
        assert normalize_for_dedup("résumé") == "resume"
        assert normalize_for_dedup("niño") == "nino"

    def test_empty_string(self):
        assert normalize_for_dedup("") == ""

    def test_already_normalized(self):
        assert normalize_for_dedup("hello world") == "hello world"


# ── strip_emoji ───────────────────────────────────────────────────────────────

class TestStripEmoji:
    def test_removes_emoji(self):
        assert strip_emoji("hello 🌀 world") == "hello  world"

    def test_no_emoji_unchanged(self):
        assert strip_emoji("hello world") == "hello world"

    def test_only_emoji_becomes_empty(self):
        assert strip_emoji("🌀🧠") == ""

    def test_strips_trailing_space(self):
        result = strip_emoji("test 🎯")
        assert not result.endswith(" ")


# ── estimate_tokens ───────────────────────────────────────────────────────────

class TestEstimateTokens:
    def test_empty_string_returns_zero(self):
        assert estimate_tokens("") == 0

    def test_whitespace_only_returns_zero(self):
        assert estimate_tokens("   ") == 0

    def test_single_word_returns_at_least_one(self):
        assert estimate_tokens("hello") >= 1

    def test_longer_text_more_tokens(self):
        short = estimate_tokens("hello")
        long_ = estimate_tokens("hello world this is a longer sentence with many words")
        assert long_ > short

    def test_none_like_empty(self):
        assert estimate_tokens("") == 0

    def test_prose_estimate_reasonable(self):
        text = "The quick brown fox jumps over the lazy dog."
        tokens = estimate_tokens(text)
        assert 8 <= tokens <= 20

    def test_code_estimate_positive(self):
        code = "def compute_quality_flags(rec: dict) -> dict:\n    return {}\n"
        assert estimate_tokens(code) >= 5


# ── looks_like_repo_path ──────────────────────────────────────────────────────

class TestLooksLikeRepoPath:
    def test_path_with_slash(self):
        assert looks_like_repo_path("src/main.py") is True

    def test_gitignore(self):
        assert looks_like_repo_path(".gitignore") is True

    def test_readme(self):
        assert looks_like_repo_path("README.md") is True

    def test_plain_title(self):
        assert looks_like_repo_path("Mi hipótesis sobre X") is False

    def test_none_is_false(self):
        assert looks_like_repo_path(None) is False

    def test_empty_is_false(self):
        assert looks_like_repo_path("") is False

    def test_file_with_extension(self):
        assert looks_like_repo_path("config.yaml") is True

    def test_word_without_extension(self):
        assert looks_like_repo_path("sesion") is False

    def test_estructura_txt(self):
        assert looks_like_repo_path("estructura.txt") is True


# ── looks_like_build_artifact_path ───────────────────────────────────────────

class TestLooksLikeBuildArtifactPath:
    def test_target_path(self):
        assert looks_like_build_artifact_path("rust/target/release/foo") is True

    def test_fingerprint_path(self):
        assert looks_like_build_artifact_path("build/.fingerprint/bar") is True

    def test_debug_build(self):
        assert looks_like_build_artifact_path("out/debug/build/lib") is True

    def test_regular_path(self):
        assert looks_like_build_artifact_path("src/main.rs") is False

    def test_none_is_false(self):
        assert looks_like_build_artifact_path(None) is False

    def test_case_insensitive(self):
        assert looks_like_build_artifact_path("RUST/TARGET/release") is True


# ── looks_like_inventory_manifest ─────────────────────────────────────────────

class TestLooksLikeInventoryManifest:
    def test_contratos_txt(self):
        assert looks_like_inventory_manifest("contratos.txt") is True

    def test_estructura_txt(self):
        assert looks_like_inventory_manifest("estructura.txt") is True

    def test_scripts_txt(self):
        assert looks_like_inventory_manifest("scripts.txt") is True

    def test_subpath_go_txt(self):
        assert looks_like_inventory_manifest("some/path/go.txt") is True

    def test_subpath_python_txt(self):
        assert looks_like_inventory_manifest("src/python.txt") is True

    def test_random_txt(self):
        assert looks_like_inventory_manifest("notes.txt") is False

    def test_none_is_false(self):
        assert looks_like_inventory_manifest(None) is False

    def test_empty_is_false(self):
        assert looks_like_inventory_manifest("") is False
