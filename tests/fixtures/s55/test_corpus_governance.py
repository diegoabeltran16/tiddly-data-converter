#!/usr/bin/env python3
"""Focused regression tests for S55 machine-readable corpus governance."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import corpus_governance  # noqa: E402
import derive_layers  # noqa: E402


class CorpusGovernanceTests(unittest.TestCase):
    def test_archival_only_tag_has_highest_precedence(self) -> None:
        rec = {
            "title": "README.md",
            "tags": ["state:live-path", "status:archival-only"],
        }
        policy = corpus_governance.resolve_corpus_policy(rec)
        self.assertEqual(policy["corpus_state"], "archival_only")
        self.assertEqual(policy["corpus_state_rule_id"], "archival_only_by_tag")

    def test_superseded_path_resolves_to_historical_snapshot(self) -> None:
        rec = {
            "title": "docs/canon/canon_guarded_session_rules.md",
            "tags": ["superseded-by:esquemas/canon/canon_guarded_session_rules.md"],
        }
        policy = corpus_governance.resolve_corpus_policy(rec)
        self.assertEqual(policy["corpus_state"], "historical_snapshot")
        self.assertEqual(policy["corpus_state_rule_id"], "historical_snapshot_by_superseded_tag")

    def test_layer_registry_keeps_canon_authoritative(self) -> None:
        registry = corpus_governance.load_layer_registry()
        layers = {layer["layer_id"]: layer for layer in registry["layers"]}
        self.assertEqual(layers["canon"]["authority"], "local_source_of_truth")
        self.assertEqual(layers["enriched"]["authority"], "derived_non_authoritative")
        self.assertEqual(layers["ai"]["authority"], "derived_non_authoritative")
        self.assertEqual(layers["reverse_html"]["authority"], "reverse_projection_only")
        self.assertEqual(layers["proposals"]["authority"], "candidate_only")
        self.assertEqual(layers["remote"]["authority"], "remote_exchange_only")

    def test_derive_layers_surfaces_governance_rule_id(self) -> None:
        rec = {
            "id": "node-1",
            "title": "rust/extractor/target/debug/.fingerprint/itoa/lib-itoa.json",
            "content_type": "text/plain",
            "text": "x" * 2000,
            "tags": [],
        }
        payload = derive_layers.classify_payload(rec, "manifest", 1800)
        self.assertEqual(payload["corpus_state"], "archival_only")
        self.assertEqual(payload["corpus_state_rule_id"], "archival_only_build_artifact")

    def test_validate_repository_alignment_passes(self) -> None:
        report = corpus_governance.validate_repository_alignment()
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["ai_alignment"]["mismatched_corpus_state"], 0)
        self.assertEqual(report["ai_alignment"]["mismatched_rule_id"], 0)


if __name__ == "__main__":
    unittest.main()

