#!/usr/bin/env python3
"""Focused regression tests for S54 semantic closure and microchunk densification."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import derive_layers  # noqa: E402


class SemanticMicrochunkTests(unittest.TestCase):
    def test_tools_spec_is_schema(self) -> None:
        rec = {
            "title": "tools/accumulator/spec.md",
            "content_type": "text/markdown",
            "tags": ["⚙️ Markdown", "tools/accumulator/spec.md", "--- Codigo"],
        }
        self.assertEqual(derive_layers.classify_role(rec), "schema")

    def test_inventory_txt_is_manifest(self) -> None:
        rec = {
            "title": "go/go.txt",
            "content_type": "text/plain",
            "tags": ["⚙️ Text", "go/go.txt", "--- Codigo"],
        }
        self.assertEqual(derive_layers.classify_role(rec), "manifest")

    def test_build_artifact_path_is_archival_only_for_chunking(self) -> None:
        rec = {
            "title": "rust/extractor/target/debug/.fingerprint/itoa/lib-itoa.json",
            "content_type": "text/plain",
            "text": "x" * 10000,
            "tags": ["⚙️ JSON", "rust/extractor/target/debug/.fingerprint/itoa/lib-itoa.json", "--- Codigo"],
        }
        payload = derive_layers.classify_payload(rec, "manifest", 1800)
        self.assertFalse(payload["is_chunkable_text"])
        self.assertEqual(payload["corpus_state"], "archival_only")
        self.assertEqual(payload["chunk_exclusion_reason"], "archival_only_skip")

    def test_densify_microchunks_merges_heading_stub_into_context(self) -> None:
        parts = [
            "## CLI",
            "The command accepts --input, --out and --verify while preserving deterministic ordering. "
            * 20,
            "### Exit codes",
            "0 means success, 1 means verification mismatch, and 2 means invalid input. " * 12,
        ]
        dense = derive_layers.densify_microchunks(parts, 1800)
        self.assertEqual(len(dense), 2)
        self.assertIn("## CLI", dense[0])
        self.assertIn("The command accepts --input", dense[0])
        self.assertIn("### Exit codes", dense[1])
        self.assertIn("0 means success", dense[1])
        self.assertTrue(all(derive_layers.estimate_tokens(chunk) <= 1800 for chunk in dense))


if __name__ == "__main__":
    unittest.main()
