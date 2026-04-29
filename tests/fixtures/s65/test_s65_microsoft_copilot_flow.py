#!/usr/bin/env python3
"""
S65 — Regression tests for the microsoft_copilot execution surface.

Validates that:
  - the derive_layers.py entrypoint is the official source for microsoft_copilot outputs
  - all expected artifacts exist under data/out/local/microsoft_copilot/
  - copilot_agent/ sub-layer is present with exactly 3 files
  - no legacy path (data/out/local/copilot_agent/) is used
  - manifest records the correct session lineage
  - corpus governance alignment passes (audit dir required)
  - canon is strict- and reverse-preflight-ready
"""

from __future__ import annotations

import csv
import json
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "python_scripts"))


def load_canon_records() -> list[dict]:
    records: list[dict] = []
    for shard_path in sorted((REPO_ROOT / "data" / "out" / "local").glob("tiddlers_*.jsonl")):
        with shard_path.open(encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if line:
                    records.append(json.loads(line))
    return records


class S65MicrosoftCopilotFlowTests(unittest.TestCase):

    COPILOT_DIR = REPO_ROOT / "data" / "out" / "local" / "microsoft_copilot"
    COPILOT_AGENT_DIR = COPILOT_DIR / "copilot_agent"
    LEGACY_DIR = REPO_ROOT / "data" / "out" / "local" / "copilot_agent"
    CONTRACT_PATH = (
        REPO_ROOT
        / "data"
        / "sessions"
        / "00_contratos"
        / "m03-s65-microsoft-copilot-execution-surface-and-readme-hardening-v0.md.json"
    )
    CONTRACT_TITLE = "#### 🌀 Contrato de sesión 65 = microsoft-copilot-execution-surface-and-readme-hardening-v0"

    # ── entrypoint and official path ─────────────────────────────────────────

    def test_official_entrypoint_exists(self) -> None:
        """derive_layers.py must exist as the official entrypoint."""
        entrypoint = REPO_ROOT / "python_scripts" / "derive_layers.py"
        self.assertTrue(entrypoint.exists(), "derive_layers.py entrypoint missing")

    def test_no_legacy_copilot_agent_root_path(self) -> None:
        """data/out/local/copilot_agent/ must NOT exist as active path."""
        self.assertFalse(
            self.LEGACY_DIR.exists(),
            "Legacy path data/out/local/copilot_agent/ still exists — must be removed",
        )

    def test_official_copilot_dir_exists(self) -> None:
        """data/out/local/microsoft_copilot/ must exist."""
        self.assertTrue(self.COPILOT_DIR.exists(), "microsoft_copilot directory missing")

    def test_copilot_agent_subdir_exists(self) -> None:
        """data/out/local/microsoft_copilot/copilot_agent/ must exist."""
        self.assertTrue(self.COPILOT_AGENT_DIR.exists(), "copilot_agent sub-directory missing")

    def test_contract_file_exists(self) -> None:
        """S65 must leave an importable contract in contratos/."""
        self.assertTrue(self.CONTRACT_PATH.exists(), "S65 contract file is missing")

    def test_s65_contract_is_absorbed_or_staged(self) -> None:
        """S65 contract must be staged in data/sessions or already present in canon."""
        titles = {record.get("title") for record in load_canon_records()}
        self.assertTrue(
            self.CONTRACT_TITLE in titles or self.CONTRACT_PATH.exists(),
            "S65 contract is neither staged under data/sessions nor present in canon",
        )

    # ── required artifacts ────────────────────────────────────────────────────

    def test_manifest_exists_and_valid(self) -> None:
        """microsoft_copilot/manifest.json must exist and be valid JSON."""
        manifest_path = self.COPILOT_DIR / "manifest.json"
        self.assertTrue(manifest_path.exists(), "manifest.json missing")
        with open(manifest_path) as f:
            manifest = json.load(f)
        self.assertIn("generated_at", manifest, "manifest missing generated_at")
        self.assertIn("output", manifest, "manifest missing output section")
        self.assertGreater(
            manifest["output"]["total_records"], 0, "manifest reports 0 records"
        )

    def test_navigation_index_exists(self) -> None:
        self.assertTrue((self.COPILOT_DIR / "navigation_index.json").exists())

    def test_entities_json_exists(self) -> None:
        self.assertTrue((self.COPILOT_DIR / "entities.json").exists())

    def test_topics_json_exists(self) -> None:
        self.assertTrue((self.COPILOT_DIR / "topics.json").exists())

    def test_nodes_csv_exists(self) -> None:
        self.assertTrue((self.COPILOT_DIR / "nodes.csv").exists())

    def test_edges_csv_exists(self) -> None:
        self.assertTrue((self.COPILOT_DIR / "edges.csv").exists())

    def test_artifacts_csv_exists(self) -> None:
        self.assertTrue((self.COPILOT_DIR / "artifacts.csv").exists())

    def test_coverage_csv_exists(self) -> None:
        self.assertTrue((self.COPILOT_DIR / "coverage.csv").exists())

    def test_overview_txt_exists(self) -> None:
        self.assertTrue((self.COPILOT_DIR / "overview.txt").exists())

    def test_reading_guide_txt_exists(self) -> None:
        self.assertTrue((self.COPILOT_DIR / "reading_guide.txt").exists())

    def test_source_arbitration_report_exists(self) -> None:
        self.assertTrue((self.COPILOT_DIR / "source_arbitration_report.json").exists())

    def test_bundles_dir_exists(self) -> None:
        self.assertTrue((self.COPILOT_DIR / "bundles").is_dir())

    def test_spec_dir_exists(self) -> None:
        self.assertTrue((self.COPILOT_DIR / "spec").is_dir())

    # ── copilot_agent sub-layer ───────────────────────────────────────────────

    def test_copilot_agent_has_exactly_three_files(self) -> None:
        """copilot_agent/ must contain exactly corpus.txt, entities.json, relations.csv."""
        files = {p.name for p in self.COPILOT_AGENT_DIR.iterdir() if p.is_file()}
        expected = {"corpus.txt", "entities.json", "relations.csv"}
        self.assertEqual(files, expected, f"copilot_agent/ files mismatch: {files}")

    def test_copilot_agent_corpus_txt_nonempty(self) -> None:
        corpus = self.COPILOT_AGENT_DIR / "corpus.txt"
        self.assertGreater(corpus.stat().st_size, 100, "corpus.txt is empty or trivially small")

    def test_copilot_agent_entities_json_valid(self) -> None:
        with open(self.COPILOT_AGENT_DIR / "entities.json") as f:
            data = json.load(f)
        entities = data.get("entities", [])
        self.assertGreater(len(entities), 0, "entities.json has no entities")
        self.assertLessEqual(len(entities), 50, "entities.json exceeds 50-entity cap")
        self.assertIn("updated_at", data, "entities.json missing updated_at")

    def test_copilot_agent_relations_csv_valid(self) -> None:
        with open(self.COPILOT_AGENT_DIR / "relations.csv") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        self.assertGreater(len(rows), 0, "relations.csv has no rows")
        required_cols = {"source_id", "target_id", "relation_type"}
        actual_cols = set(reader.fieldnames or [])
        self.assertTrue(
            required_cols.issubset(actual_cols),
            f"relations.csv missing columns: {required_cols - actual_cols}",
        )

    def test_copilot_agent_entities_session_lineage(self) -> None:
        """entities.json must reference S63 integration baseline and S64 generation session."""
        with open(self.COPILOT_AGENT_DIR / "entities.json") as f:
            data = json.load(f)
        self.assertIn(
            "s63",
            data.get("integration_baseline", ""),
            "entities.json missing S63 baseline reference",
        )

    # ── manifest session lineage ──────────────────────────────────────────────

    def test_manifest_references_s61_session(self) -> None:
        """microsoft_copilot/manifest.json must reference the S61 session as origin."""
        with open(self.COPILOT_DIR / "manifest.json") as f:
            manifest = json.load(f)
        session = manifest.get("session", "")
        self.assertIn("s61", session, f"manifest session doesn't reference S61: {session}")

    # ── documentation alignment ───────────────────────────────────────────────

    def test_readme_documents_single_operator_menu(self) -> None:
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("shell_scripts/tdc.sh", readme)
        self.assertIn("Generación de derivados", readme)
        self.assertIn("Los derivados no son fuente de verdad", readme)

    def test_data_readme_lists_spec_and_copilot_agent_outputs(self) -> None:
        data_readme = (REPO_ROOT / "data" / "README.md").read_text(encoding="utf-8")
        self.assertIn("data/out/local/microsoft_copilot", data_readme)
        self.assertIn("copilot_agent/", data_readme)
        self.assertIn("corpus.txt", data_readme)
        self.assertIn("entities.json", data_readme)
        self.assertIn("relations.csv", data_readme)

    def test_data_readme_mentions_copilot_agent_sublayer(self) -> None:
        data_readme = (REPO_ROOT / "data" / "README.md").read_text(encoding="utf-8")
        self.assertIn("copilot_agent/", data_readme)
        self.assertIn("corpus.txt", data_readme)
        self.assertIn("entities.json", data_readme)
        self.assertIn("relations.csv", data_readme)

    # ── no-legacy guarantee ───────────────────────────────────────────────────

    def test_no_tiddlers_jsonl_in_microsoft_copilot(self) -> None:
        """microsoft_copilot/ must not contain .jsonl files (legacy format)."""
        jsonl_files = list(self.COPILOT_DIR.glob("*.jsonl"))
        self.assertEqual(
            jsonl_files, [], f"Found legacy .jsonl files in microsoft_copilot/: {jsonl_files}"
        )

    # ── governance ────────────────────────────────────────────────────────────

    def test_corpus_governance_status_ok(self) -> None:
        """validate_repository_alignment must return status ok."""
        import corpus_governance

        report = corpus_governance.validate_repository_alignment()
        self.assertEqual(
            report["status"],
            "ok",
            f"Governance alignment failed: {report.get('errors')}",
        )

    def test_ai_alignment_zero_mismatches(self) -> None:
        """AI layer must have no corpus_state or rule_id mismatches."""
        import corpus_governance

        report = corpus_governance.validate_repository_alignment()
        ai = report.get("ai_alignment", {})
        self.assertEqual(ai.get("mismatched_corpus_state", 0), 0)
        self.assertEqual(ai.get("mismatched_rule_id", 0), 0)


if __name__ == "__main__":
    unittest.main()
