"""
Characterization tests for classify_role() and derive_taxonomy_and_section() — S0110, updated S0116.

Freezes:
  - The role_primary distribution across 1090 AI records (read-only).
  - The fast-path behavior for each role present in the distribution.
  - Representative heuristic paths triggered by title patterns.
  - Edge-case behavior (empty title, None fields, minimal records).

These tests are a precondition for extracting classification.py (Fase C).
They must pass before AND after the extraction with zero behavioral change.

Distribution updated from S0110 baseline (1014 records, 7 roles) to
post-S0115 state (1090 records, 5 roles active in AI layer).
"""
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python_scripts"))

from derive_layers import classify_role, derive_taxonomy_and_section, VALID_ROLES

AI_DIR = REPO_ROOT / "data" / "out" / "local" / "ai"

# ── Distribution constants ─────────────────────────────────────────────────────

# Distribution frozen at post-S0115 state. Update when AI layer is regenerated.
EXPECTED_ROLE_DISTRIBUTION = {
    "code": 392,
    "log": 453,
    "config": 168,
    "glossary": 61,
    "evidence": 16,
}
EXPECTED_TOTAL = 1090


# ── Helpers ────────────────────────────────────────────────────────────────────

def _load_ai_records() -> list:
    records = []
    for path in sorted(AI_DIR.glob("tiddlers_ai_*.jsonl")):
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
    return records


# ── Distribution freeze ────────────────────────────────────────────────────────

class TestRoleDistributionFreeze:
    """Freezes the role_primary distribution across all 1014 AI records."""

    def test_total_ai_record_count(self):
        records = _load_ai_records()
        assert len(records) == EXPECTED_TOTAL

    def test_role_distribution_frozen(self):
        records = _load_ai_records()
        dist = dict(Counter(r.get("role_primary") for r in records))
        assert dist == EXPECTED_ROLE_DISTRIBUTION, (
            f"Role distribution changed.\nGot:      {dist}\nExpected: {EXPECTED_ROLE_DISTRIBUTION}"
        )

    def test_no_unclassified_roles_in_ai_records(self):
        records = _load_ai_records()
        unclassified = [r for r in records if r.get("role_primary") == "unclassified"]
        assert len(unclassified) == 0, f"Found {len(unclassified)} unclassified records"

    def test_all_ai_roles_are_valid(self):
        records = _load_ai_records()
        invalid = [
            r.get("title", "")[:60]
            for r in records
            if r.get("role_primary") not in VALID_ROLES
        ]
        assert len(invalid) == 0, f"Found records with invalid roles: {invalid[:5]}"

    def test_distribution_roles_are_subset_of_valid_roles(self):
        for role in EXPECTED_ROLE_DISTRIBUTION:
            assert role in VALID_ROLES, f"Role {role!r} in distribution is not in VALID_ROLES"


# ── Fast path ─────────────────────────────────────────────────────────────────

class TestClassifyRoleFastPath:
    """
    The fast path returns the existing role_primary when it is already valid.
    All 1014 tiddlers in the AI layer use this path exclusively.
    """

    @pytest.mark.parametrize("role", list(EXPECTED_ROLE_DISTRIBUTION))
    def test_fast_path_returns_existing_role(self, role):
        rec = {"title": "irrelevant-title", "role_primary": role}
        assert classify_role(rec) == role

    def test_fast_path_does_not_mutate_record(self):
        rec = {"title": "irrelevant-title", "role_primary": "code"}
        original = dict(rec)
        classify_role(rec)
        assert rec == original

    def test_fast_path_overrides_heuristics(self):
        # Even a title that would trigger "glossary" heuristic is overridden
        # by a valid pre-set role_primary
        rec = {"title": "Glosario de términos", "role_primary": "code"}
        assert classify_role(rec) == "code"


# ── Heuristic paths ────────────────────────────────────────────────────────────

class TestClassifyRoleHeuristicPaths:
    """
    Characterizes heuristic code paths triggered when role_primary is absent
    or invalid. These paths are exercised by the tests but not by actual
    AI records (all of which use the fast path).
    """

    # Session-type tiddlers
    def test_session_title_pattern(self):
        rec = {"title": "#### 🌀 Sesión 0099 = alguna sesión de trabajo"}
        assert classify_role(rec) == "session"

    def test_hypothesis_title_hipotesis_de_sesion(self):
        rec = {"title": "#### 🌀🧪 Hipótesis de sesión 0099 = algo"}
        assert classify_role(rec) == "hypothesis"

    def test_provenance_title_procedencia_de_sesion(self):
        rec = {"title": "#### 🌀🧾 Procedencia de sesión 0099 = algo"}
        assert classify_role(rec) == "provenance"

    # Glossary / dictionary
    def test_glossary_keyword_in_title(self):
        rec = {"title": "Glosario de términos del proyecto"}
        assert classify_role(rec) == "glossary"

    def test_dictionary_keyword_in_title(self):
        rec = {"title": "Diccionario de conceptos"}
        assert classify_role(rec) == "dictionary"

    # Repository path artifacts
    def test_python_source_file(self):
        rec = {"title": "python_scripts/derive_layers.py"}
        assert classify_role(rec) == "code_source"

    def test_github_workflow_yaml(self):
        rec = {"title": ".github/workflows/ci.yml"}
        assert classify_role(rec) == "config"

    def test_gitignore_file(self):
        rec = {"title": ".gitignore"}
        assert classify_role(rec) == "config"

    def test_markdown_readme(self):
        rec = {"title": "README.md"}
        assert classify_role(rec) == "readme"

    # Report / audit
    def test_report_keyword_in_title(self):
        rec = {"title": "Report de auditoría 2025"}
        assert classify_role(rec) == "report"

    def test_audit_keyword_not_session(self):
        rec = {"title": "audit-summary"}
        assert classify_role(rec) == "report"

    # Algorithm
    def test_algoritmos_in_title(self):
        rec = {"title": "Algoritmos de optimización"}
        assert classify_role(rec) == "algorithm"

    # Policy (structural title patterns)
    def test_policy_principios_de_gestion(self):
        rec = {"title": "Principios de gestión del conocimiento"}
        assert classify_role(rec) == "policy"

    # Draft tiddlers
    def test_draft_of_session(self):
        rec = {"title": "Draft of '#### 🌀 Sesión 0099 = algo'"}
        assert classify_role(rec) == "session"


# ── Edge cases ────────────────────────────────────────────────────────────────

class TestClassifyRoleEdgeCases:
    """Characterizes behavior at the boundaries: empty/None fields."""

    def test_empty_title_returns_unclassified(self):
        rec = {"title": ""}
        assert classify_role(rec) == "unclassified"

    def test_missing_title_key_returns_unclassified(self):
        rec = {}
        assert classify_role(rec) == "unclassified"

    def test_none_title_returns_unclassified(self):
        rec = {"title": None}
        assert classify_role(rec) == "unclassified"

    def test_none_role_primary_falls_through_to_heuristics(self):
        rec = {"title": "Glosario de términos", "role_primary": None}
        assert classify_role(rec) == "glossary"

    def test_invalid_role_primary_falls_through_to_heuristics(self):
        rec = {"title": "Glosario de términos", "role_primary": "invalid_role_xyz"}
        assert classify_role(rec) == "glossary"

    def test_minimal_record_no_crash(self):
        # No fields at all — must not raise
        classify_role({})

    def test_binary_record_returns_asset(self):
        rec = {"title": "image.png", "is_binary": True}
        assert classify_role(rec) == "asset"

    def test_image_content_type_returns_asset(self):
        rec = {"title": "photo.jpg", "content_type": "image/jpeg"}
        assert classify_role(rec) == "asset"


# ── derive_taxonomy_and_section characterization ──────────────────────────────

class TestDeriveTaxonomyAndSection:
    """
    Characterizes derive_taxonomy_and_section() for the roles present
    in the distribution. No canon modification; read-only behavior.
    """

    @pytest.mark.parametrize("role,expected_taxonomy", [
        ("code", None),         # "code" not in role_to_taxonomy (only "code_source" is) — returns []
        ("log", None),          # "log" not in role_to_taxonomy — returns []
        ("config", ["project/config"]),
        ("glossary", ["project/docs/glossary"]),
        ("evidence", None),     # "evidence" not in role_to_taxonomy — returns []
        ("procedure", None),    # "procedure" not in role_to_taxonomy — returns []
        ("policy", ["project/governance/policy"]),
    ])
    def test_taxonomy_derived_from_role_when_missing(self, role, expected_taxonomy):
        rec = {"title": "some-title", "role_primary": role, "_derived_role": role}
        taxonomy, _ = derive_taxonomy_and_section(rec)
        if expected_taxonomy is None:
            assert taxonomy == [], f"Expected empty taxonomy for role {role!r}, got {taxonomy}"
        else:
            assert taxonomy == expected_taxonomy, (
                f"Taxonomy mismatch for role {role!r}: got {taxonomy}, expected {expected_taxonomy}"
            )

    def test_existing_taxonomy_is_preserved(self):
        rec = {
            "title": "some-title",
            "role_primary": "code",
            "_derived_role": "code",
            "taxonomy_path": ["custom/taxonomy"],
        }
        taxonomy, _ = derive_taxonomy_and_section(rec)
        assert taxonomy == ["custom/taxonomy"]

    def test_existing_section_is_preserved(self):
        rec = {
            "title": "some-title",
            "role_primary": "code",
            "_derived_role": "code",
            "section_path": ["Existing Section"],
        }
        _, section = derive_taxonomy_and_section(rec)
        assert section == ["Existing Section"]

    def test_markdown_heading_title_derives_section(self):
        rec = {
            "title": "## My Section",
            "role_primary": "code",
            "_derived_role": "code",
        }
        _, section = derive_taxonomy_and_section(rec)
        assert section == ["## My Section"]

    def test_session_title_derives_section(self):
        rec = {
            "title": "#### 🌀 Sesión 0099 = algo",
            "role_primary": "log",
            "_derived_role": "log",
        }
        _, section = derive_taxonomy_and_section(rec)
        assert section == ["#### 🌀 Sesión 0099 = algo"]

    def test_empty_title_no_crash(self):
        rec = {"title": "", "role_primary": "code", "_derived_role": "code"}
        taxonomy, section = derive_taxonomy_and_section(rec)
        assert isinstance(taxonomy, list)
        assert isinstance(section, list)

    def test_returns_tuple_of_two_lists(self):
        rec = {"title": "some-title", "role_primary": "config", "_derived_role": "config"}
        result = derive_taxonomy_and_section(rec)
        assert isinstance(result, tuple) and len(result) == 2
        taxonomy, section = result
        assert isinstance(taxonomy, list)
        assert isinstance(section, list)
