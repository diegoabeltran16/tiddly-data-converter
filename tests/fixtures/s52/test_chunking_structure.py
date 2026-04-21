#!/usr/bin/env python3
"""Focused regression tests for S52 chunking, eligibility and traceability."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import derive_layers  # noqa: E402


class ChunkingStructureTests(unittest.TestCase):
    def test_path_like_python_file_is_code_source(self) -> None:
        rec = {
            "title": "scripts/audit_normative_projection.py",
            "content_type": "text/plain",
            "tags": ["⚙️ Python", "scripts/audit_normative_projection.py", "--- Codigo"],
        }
        self.assertEqual(derive_layers.classify_role(rec), "code_source")

    def test_go_test_file_is_test_fixture(self) -> None:
        rec = {
            "title": "go/canon/semantic_test.go",
            "content_type": "text/plain",
            "tags": ["⚙️ Go", "go/canon/semantic_test.go", "--- Codigo"],
        }
        self.assertEqual(derive_layers.classify_role(rec), "test_fixture")

    def test_archival_only_artifact_is_excluded_from_chunking(self) -> None:
        rec = {
            "title": "out/tiddly-data-converter.reversed.html",
            "content_type": "text/markdown",
            "text": "x" * 12000,
            "tags": [
                "⚙️ HTML",
                "out/tiddly-data-converter.reversed.html",
                "--- Codigo",
                "status:archival-only",
            ],
        }
        payload = derive_layers.classify_payload(rec, "html_artifact", 1800)
        self.assertFalse(payload["is_chunkable_text"])
        self.assertEqual(payload["chunk_exclusion_reason"], "archival_only_skip")
        self.assertEqual(payload["corpus_state"], "archival_only")

    def test_structural_split_respects_target(self) -> None:
        text = (
            "# A\n"
            + ("uno dos tres. " * 800)
            + "\n\n## B\n"
            + ("cuatro cinco seis. " * 700)
            + "\n\n### C\n"
            + ("siete ocho nueve. " * 650)
        )
        chunks = derive_layers.split_structurally(text, "README.md", "readme", 1800, 4000)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(derive_layers.estimate_tokens(chunk) <= 1800 for chunk in chunks))

    def test_chunk_records_include_traceability_aliases(self) -> None:
        rec = {
            "id": "node-1",
            "title": "README.md",
            "text": "# Intro\n" + ("texto de prueba. " * 900),
            "content_type": "text/markdown",
            "document_id": "doc-1",
            "source_position": "html:block0:tiddler1",
            "version_id": "sha256:test",
            "tags": ["⚙️ Markdown", "README.md", "--- Codigo", "state:live-path"],
        }
        payload = derive_layers.classify_payload(rec, "readme", 1800)
        chunks, _, _ = derive_layers.chunk_node(
            rec,
            "node-1",
            "tiddlers_1.jsonl",
            1,
            "readme",
            ["project/docs/readme"],
            ["README.md"],
            ["readme", "repo"],
            payload,
            1800,
            4000,
        )
        self.assertGreater(len(chunks), 0)
        first = chunks[0]
        self.assertEqual(first["source_id"], "node-1")
        self.assertEqual(first["tiddler_id"], "node-1")
        self.assertEqual(first["source_anchor"]["shard_file"], "tiddlers_1.jsonl")
        self.assertEqual(first["section_path"], ["README.md"])
        self.assertEqual(first["taxonomy_path"], ["project/docs/readme"])


if __name__ == "__main__":
    unittest.main()
