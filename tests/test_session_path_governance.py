#!/usr/bin/env python3
"""Session path governance tests — S94.

Validates that:
1. DEFAULT_SESSIONS_DIR points to data/out/local/sessions (not data/sessions).
2. AGENT_SESSION_ROOT default in mcp_env_manager description is data/out/local/sessions.
3. data/sessions/ is classified as a prohibited path in migration tables.
4. No new session artifacts are generated under data/sessions/.
5. The mirror source (LOCAL_SYNC_SOURCE) defaults to data/out/local/.
6. The canon policy bundle fixture is tracked and non-empty.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = REPO_ROOT / "python_scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import admit_session_candidates as asc
import mcp_env_manager as mgr


# ---------------------------------------------------------------------------
# 1. DEFAULT_SESSIONS_DIR must point to data/out/local/sessions
# ---------------------------------------------------------------------------

class TestDefaultSessionsDir:

    def test_default_sessions_dir_is_data_out_local_sessions(self):
        expected = REPO_ROOT / "data" / "out" / "local" / "sessions"
        assert asc.DEFAULT_SESSIONS_DIR == expected, (
            f"DEFAULT_SESSIONS_DIR={asc.DEFAULT_SESSIONS_DIR!r} "
            f"expected {expected!r}"
        )

    def test_default_sessions_dir_does_not_use_data_sessions(self):
        path_str = str(asc.DEFAULT_SESSIONS_DIR).replace("\\", "/")
        assert "/data/sessions" not in path_str or "/data/out/local/sessions" in path_str, (
            "DEFAULT_SESSIONS_DIR must not resolve to data/sessions without data/out/local"
        )

    def test_default_sessions_dir_string_representation(self):
        """as_display_path(DEFAULT_SESSIONS_DIR) must contain data/out/local/sessions."""
        display = asc.as_display_path(asc.DEFAULT_SESSIONS_DIR)
        assert "data/out/local/sessions" in display.replace("\\", "/"), (
            f"Display path {display!r} must contain data/out/local/sessions"
        )


# ---------------------------------------------------------------------------
# 2. AGENT_SESSION_ROOT description in mcp_env_manager must reference correct path
# ---------------------------------------------------------------------------

class TestAgentSessionRootDescription:

    def test_agent_session_root_description_mentions_data_out_local_sessions(self):
        desc = mgr.VARIABLE_DESCRIPTIONS.get("AGENT_SESSION_ROOT", "")
        assert "data/out/local/sessions" in desc, (
            f"AGENT_SESSION_ROOT description {desc!r} must mention data/out/local/sessions"
        )

    def test_agent_session_root_is_in_variables_not_secrets(self):
        assert "AGENT_SESSION_ROOT" in mgr.VARIABLES, (
            "AGENT_SESSION_ROOT must be in VARIABLES (non-sensitive)"
        )
        assert "AGENT_SESSION_ROOT" not in mgr.SECRETS, (
            "AGENT_SESSION_ROOT must not be in SECRETS"
        )


# ---------------------------------------------------------------------------
# 3. data/sessions is classified as prohibited/legacy in migration tables
# ---------------------------------------------------------------------------

class TestMigrationPathTables:

    def test_admit_session_candidates_maps_data_sessions_to_data_out_local_sessions(self):
        """admit_session_candidates.py must have data/sessions/ → data/out/local/sessions/ migration."""
        prefixes = dict(asc._MIGRATION_PATH_PREFIXES)
        assert "data/sessions/" in prefixes, (
            "admit_session_candidates._MIGRATION_PATH_PREFIXES must map data/sessions/"
        )
        assert prefixes["data/sessions/"] == "data/out/local/sessions/", (
            f"data/sessions/ maps to {prefixes['data/sessions/']!r}, expected data/out/local/sessions/"
        )

    def test_session_sync_maps_data_sessions_to_data_out_local_sessions(self):
        """session_sync.py must have the same migration mapping."""
        import session_sync as ss
        prefixes = dict(ss._MIGRATION_PATH_PREFIXES)
        assert "data/sessions/" in prefixes, (
            "session_sync._MIGRATION_PATH_PREFIXES must map data/sessions/"
        )
        assert prefixes["data/sessions/"] == "data/out/local/sessions/", (
            f"session_sync: data/sessions/ maps to {prefixes['data/sessions/']!r}"
        )

    def test_is_migration_equivalent_path_detects_data_sessions_as_old(self):
        """_is_migration_equivalent_path must recognize data/sessions/ paths as old."""
        old = "data/sessions/00_contratos/m04-s94-test.md.json"
        new = "data/out/local/sessions/00_contratos/m04-s94-test.md.json"
        assert asc._is_migration_equivalent_path(old, new), (
            "data/sessions/ path should be recognized as equivalent (migration) to data/out/local/sessions/"
        )


# ---------------------------------------------------------------------------
# 4. No current session artifacts exist under data/sessions/
# ---------------------------------------------------------------------------

class TestNoArtifactsUnderDataSessions:

    def test_data_sessions_directory_does_not_exist_or_is_empty(self):
        """data/sessions/ should not exist or be empty (it's gitignored and prohibited)."""
        bad_dir = REPO_ROOT / "data" / "sessions"
        if bad_dir.exists():
            # If it exists, it must contain no session deliverable files
            json_files = list(bad_dir.rglob("*.md.json"))
            assert json_files == [], (
                f"data/sessions/ contains session deliverable files that should be in "
                f"data/out/local/sessions/: {[str(f) for f in json_files]}"
            )

    def test_data_sessions_is_in_gitignore(self):
        """data/sessions must be listed in .gitignore."""
        gitignore = REPO_ROOT / ".gitignore"
        if not gitignore.is_file():
            pytest.skip(".gitignore not found")
        content = gitignore.read_text(encoding="utf-8")
        assert "data/sessions" in content, (
            ".gitignore must contain 'data/sessions' to prevent accidental tracking"
        )


# ---------------------------------------------------------------------------
# 5. LOCAL_SYNC_SOURCE default must reference data/out/local/
# ---------------------------------------------------------------------------

class TestLocalSyncSource:

    def test_local_sync_source_description_mentions_data_out_local(self):
        desc = mgr.VARIABLE_DESCRIPTIONS.get("LOCAL_SYNC_SOURCE", "")
        assert "data/out/local" in desc, (
            f"LOCAL_SYNC_SOURCE description {desc!r} must mention data/out/local"
        )

    def test_local_sync_source_is_in_variables_not_secrets(self):
        assert "LOCAL_SYNC_SOURCE" in mgr.VARIABLES
        assert "LOCAL_SYNC_SOURCE" not in mgr.SECRETS


# ---------------------------------------------------------------------------
# 6. Canon policy bundle fixture is tracked and non-empty
# ---------------------------------------------------------------------------

class TestCanonPolicyBundleFixture:

    FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "canon_policy_bundle.json"

    def test_fixture_exists(self):
        assert self.FIXTURE_PATH.is_file(), (
            f"tests/fixtures/canon_policy_bundle.json must exist for CI walk-up fallback"
        )

    def test_fixture_is_non_empty(self):
        assert self.FIXTURE_PATH.stat().st_size > 0, (
            "tests/fixtures/canon_policy_bundle.json must not be empty"
        )

    def test_fixture_contains_role_primary_contract(self):
        import json
        data = json.loads(self.FIXTURE_PATH.read_text(encoding="utf-8"))
        assert "role_primary_contract" in data, (
            "canon_policy_bundle.json must have role_primary_contract key"
        )
        assert data["role_primary_contract"].get("field") == "role_primary", (
            "role_primary_contract.field must equal 'role_primary'"
        )

    def test_data_out_sessions_policy_bundle_matches_fixture_if_present(self):
        """If the canonical bundle exists locally, it must match the fixture."""
        import json
        canonical = REPO_ROOT / "data" / "out" / "local" / "sessions" / "00_contratos" / "policy" / "canon_policy_bundle.json"
        if not canonical.is_file():
            pytest.skip("Canonical bundle not present (expected in CI — data/out gitignored)")
        fixture_data = json.loads(self.FIXTURE_PATH.read_text(encoding="utf-8"))
        canonical_data = json.loads(canonical.read_text(encoding="utf-8"))
        assert fixture_data == canonical_data, (
            "tests/fixtures/canon_policy_bundle.json must match "
            "data/out/local/sessions/00_contratos/policy/canon_policy_bundle.json. "
            "Run: cp data/out/local/sessions/00_contratos/policy/canon_policy_bundle.json "
            "tests/fixtures/canon_policy_bundle.json"
        )


if __name__ == "__main__":
    import unittest
    unittest.main()
