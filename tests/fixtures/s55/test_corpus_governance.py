#!/usr/bin/env python3
"""Focused regression tests for S55 machine-readable corpus governance."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

import corpus_governance  # noqa: E402
import derive_layers  # noqa: E402
import path_governance as pg  # noqa: E402


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
        self.assertEqual(
            layers["microsoft_copilot"]["authority"],
            "derived_non_authoritative_agent_projection",
        )
        self.assertEqual(layers["microsoft_copilot"]["presence"], "required")
        copilot_patterns = set(layers["microsoft_copilot"]["path_patterns"])
        self.assertIn("entities.json", copilot_patterns)
        self.assertIn("nodes.csv", copilot_patterns)
        self.assertIn("overview.txt", copilot_patterns)
        self.assertNotIn("tiddlers_microsoft_copilot_*.jsonl", copilot_patterns)
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

    def test_locator_and_layer_path_alignment_pass(self) -> None:
        """S0187 D23-A locator contract, isolated from content freshness.

        GLOBAL_STATUS_TEST != LOCATOR_CONTRACT_TEST: report["status"] mixes
        locator alignment with derived-layer content freshness (AI/enriched
        record counts), which can legitimately go stale independent of
        whether paths are correctly governed. This test proves only the
        locator contract -- declared bundle/registry locators match the
        governed WORKSPACE_ROOT-relative shape, and required layers resolve
        to real, existing governed paths -- and must stay green regardless
        of AI/enriched content drift.
        """
        report = corpus_governance.validate_repository_alignment()

        for field, info in report["bundle_alignment"].items():
            self.assertTrue(info["aligned"], f"bundle field {field} not aligned: {info}")

        for layer_id, info in report["layer_path_alignment"].items():
            self.assertTrue(info["aligned"], f"layer {layer_id} path not aligned: {info}")

        # Independent proof, not a re-check of corpus_governance's own math:
        # the declared locators must match as_workspace_locator() computed
        # directly from path_governance's governed DEFAULT_* Path objects.
        expected_bundle_locators = {
            "local_output_root": pg.as_workspace_locator(pg.DEFAULT_LOCAL_OUT_DIR),
            "remote_output_root": pg.as_workspace_locator(pg.DEFAULT_REMOTE_OUT_DIR),
            "session_proposal_artifact_pattern": pg.as_workspace_locator(pg.DEFAULT_PROPOSALS_FILE),
            "reverse_html_root": pg.as_workspace_locator(pg.DEFAULT_REVERSE_HTML_DIR),
        }
        for field, expected in expected_bundle_locators.items():
            self.assertEqual(report["bundle_alignment"][field]["actual"], expected)

        governed_layer_paths = {
            "canon": pg.DEFAULT_CANON_DIR,
            "proposals": pg.DEFAULT_PROPOSALS_FILE,
            "enriched": pg.DEFAULT_ENRICHED_DIR,
            "ai": pg.DEFAULT_AI_DIR,
            "audit": pg.DEFAULT_AUDIT_DIR,
            "reverse_html": pg.DEFAULT_REVERSE_HTML_DIR,
            "export": pg.DEFAULT_EXPORT_DIR,
            "microsoft_copilot": pg.DEFAULT_MICROSOFT_COPILOT_DIR,
            "remote": pg.DEFAULT_REMOTE_OUT_DIR,
        }
        for layer in report["layer_presence"]:
            governed_path = governed_layer_paths[layer["layer_id"]]
            self.assertEqual(layer["exists"], governed_path.exists())
            if layer["presence"] == "required":
                self.assertTrue(
                    governed_path.exists(),
                    f"required governed layer path does not exist: {governed_path}",
                )


if __name__ == "__main__":
    unittest.main()
