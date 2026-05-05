#!/usr/bin/env python3
"""Security tests for mcp_env_manager — S92 secretless .env policy.

Validates that:
1. Initialising .env does NOT write any SECRET_KEYS.
2. write_env_key() raises ValueError for any secret key.
3. show_status output contains no secret values and no derivated secret counts.
4. _build_mirror_env() does NOT extract secrets from .env; takes them from os.environ.
5. Preview forces SYNC_DRY_RUN=true.
6. Sync real passes SYNC_DRY_RUN=false only after confirmation.
7. No test fixture contains real tokens.
"""

from __future__ import annotations

import importlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Import the module under test
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = REPO_ROOT / "python_scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import mcp_env_manager as mgr


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_env_path(tmp_dir: str) -> Path:
    return Path(tmp_dir) / ".env"


# ---------------------------------------------------------------------------
# 1. Initialising .env does NOT include any secret key
# ---------------------------------------------------------------------------

class TestInitEnvNoSecrets(unittest.TestCase):

    def test_env_template_has_no_secret_keys(self):
        """ENV_TEMPLATE must not contain any key from SECRETS."""
        for key in mgr.SECRETS:
            self.assertNotIn(
                f"{key}=",
                mgr.ENV_TEMPLATE,
                msg=f"ENV_TEMPLATE must not contain secret key '{key}'",
            )

    def test_init_env_creates_file_without_secrets(self):
        """action_init_env() must not write secret keys to the new .env file."""
        with tempfile.TemporaryDirectory() as tmp:
            env_path = _fresh_env_path(tmp)
            with patch.object(mgr, "ENV_PATH", env_path), \
                 patch.object(mgr, "REPO_ROOT", Path(tmp)), \
                 patch("builtins.print"):
                mgr.action_init_env()

            content = env_path.read_text(encoding="utf-8")
            for key in mgr.SECRETS:
                self.assertNotIn(
                    f"{key}=",
                    content,
                    msg=f"action_init_env() must not write secret key '{key}=' to .env",
                )

    def test_init_env_contains_all_variables(self):
        """action_init_env() must write all VARIABLES to the new .env file."""
        with tempfile.TemporaryDirectory() as tmp:
            env_path = _fresh_env_path(tmp)
            with patch.object(mgr, "ENV_PATH", env_path), \
                 patch.object(mgr, "REPO_ROOT", Path(tmp)), \
                 patch("builtins.print"):
                mgr.action_init_env()

            content = env_path.read_text(encoding="utf-8")
            for key in mgr.VARIABLES:
                self.assertIn(
                    key,
                    content,
                    msg=f"action_init_env() must write variable '{key}' to .env",
                )


# ---------------------------------------------------------------------------
# 2. write_env_key() raises ValueError for secret keys
# ---------------------------------------------------------------------------

class TestWriteEnvKeyGuard(unittest.TestCase):

    def test_write_env_key_rejects_msa_refresh_token(self):
        """write_env_key('MSA_REFRESH_TOKEN', ...) must raise ValueError."""
        with tempfile.TemporaryDirectory() as tmp:
            env_path = _fresh_env_path(tmp)
            with self.assertRaises(ValueError):
                mgr.write_env_key("MSA_REFRESH_TOKEN", "fake-token", path=env_path)

    def test_write_env_key_rejects_azure_client_id(self):
        """write_env_key('AZURE_CLIENT_ID', ...) must raise ValueError."""
        with tempfile.TemporaryDirectory() as tmp:
            env_path = _fresh_env_path(tmp)
            with self.assertRaises(ValueError):
                mgr.write_env_key("AZURE_CLIENT_ID", "fake-id", path=env_path)

    def test_write_env_key_rejects_azure_tenant_id(self):
        """write_env_key('AZURE_TENANT_ID', ...) must raise ValueError."""
        with tempfile.TemporaryDirectory() as tmp:
            env_path = _fresh_env_path(tmp)
            with self.assertRaises(ValueError):
                mgr.write_env_key("AZURE_TENANT_ID", "fake-tenant", path=env_path)

    def test_write_env_key_rejects_any_token_key(self):
        """write_env_key() must reject any key containing 'TOKEN'."""
        with tempfile.TemporaryDirectory() as tmp:
            env_path = _fresh_env_path(tmp)
            with self.assertRaises(ValueError):
                mgr.write_env_key("MY_API_TOKEN", "fake", path=env_path)

    def test_write_env_key_rejects_any_secret_key(self):
        """write_env_key() must reject any key containing 'SECRET'."""
        with tempfile.TemporaryDirectory() as tmp:
            env_path = _fresh_env_path(tmp)
            with self.assertRaises(ValueError):
                mgr.write_env_key("CLIENT_SECRET", "fake", path=env_path)

    def test_write_env_key_rejects_password_key(self):
        """write_env_key() must reject any key containing 'PASSWORD'."""
        with tempfile.TemporaryDirectory() as tmp:
            env_path = _fresh_env_path(tmp)
            with self.assertRaises(ValueError):
                mgr.write_env_key("DB_PASSWORD", "fake", path=env_path)

    def test_write_env_key_accepts_safe_variable(self):
        """write_env_key() must accept non-sensitive variables."""
        with tempfile.TemporaryDirectory() as tmp:
            env_path = _fresh_env_path(tmp)
            # Should not raise
            mgr.write_env_key("SYNC_DRY_RUN", "true", path=env_path)
            content = env_path.read_text(encoding="utf-8")
            self.assertIn("SYNC_DRY_RUN=true", content)

    def test_write_env_key_does_not_write_secret_to_disk(self):
        """Attempting to write a secret must not create any file content."""
        with tempfile.TemporaryDirectory() as tmp:
            env_path = _fresh_env_path(tmp)
            try:
                mgr.write_env_key("MSA_REFRESH_TOKEN", "supersecret", path=env_path)
            except ValueError:
                pass
            # The file must not exist or must not contain the secret value
            if env_path.is_file():
                content = env_path.read_text(encoding="utf-8")
                self.assertNotIn("supersecret", content)


# ---------------------------------------------------------------------------
# 3. action_show_status() does not print secret values or derived counts
# ---------------------------------------------------------------------------

class TestShowStatusSafety(unittest.TestCase):

    def _run_show_status_with_populated_env(self, tmp: str) -> str:
        """Return captured stdout of action_show_status() with a .env that has all VARIABLES set."""
        env_path = _fresh_env_path(tmp)
        # Write all VARIABLES with dummy values; no secrets
        lines = "\n".join(f"{k}=dummy_value" for k in mgr.VARIABLES) + "\n"
        env_path.write_text(lines, encoding="utf-8")

        buf = io.StringIO()
        with patch.object(mgr, "ENV_PATH", env_path), \
             patch.object(mgr, "REPO_ROOT", Path(tmp)), \
             patch("mcp_env_manager._is_gitignored", return_value=True), \
             patch("sys.stdout", buf):
            mgr.action_show_status()
        return buf.getvalue()

    def test_show_status_does_not_print_secret_values(self):
        """action_show_status() must not print any mock secret value."""
        with tempfile.TemporaryDirectory() as tmp:
            output = self._run_show_status_with_populated_env(tmp)
            # No token/secret values should appear
            self.assertNotIn("dummy_secret", output)
            self.assertNotIn("fake_token", output)

    def test_show_status_does_not_print_secret_counts_from_env(self):
        """action_show_status() must not compute or display a count from .env secrets."""
        with tempfile.TemporaryDirectory() as tmp:
            output = self._run_show_status_with_populated_env(tmp)
            # The old pattern "N/3 secrets configurados" must not appear
            import re
            self.assertIsNone(
                re.search(r"\d+/3 secrets configurados", output),
                msg="Output must not contain derived secret count",
            )

    def test_show_status_prints_runtime_only_policy(self):
        """action_show_status() must state the secrets runtime policy."""
        with tempfile.TemporaryDirectory() as tmp:
            output = self._run_show_status_with_populated_env(tmp)
            self.assertIn("runtime only", output.lower())


# ---------------------------------------------------------------------------
# 4. _build_mirror_env() sources secrets from os.environ, not .env
# ---------------------------------------------------------------------------

class TestBuildMirrorEnv(unittest.TestCase):

    def test_build_mirror_env_does_not_extract_secrets_from_env_file(self):
        """_build_mirror_env() must not include secrets read from .env file."""
        with tempfile.TemporaryDirectory() as tmp:
            env_path = _fresh_env_path(tmp)
            # Write secrets into the .env file (simulates old behavior)
            env_path.write_text(
                "SYNC_DRY_RUN=true\nMSA_REFRESH_TOKEN=should-not-appear\nAZURE_CLIENT_ID=also-not\n",
                encoding="utf-8",
            )
            clean_env = {k: v for k, v in os.environ.items()
                         if k not in mgr.SECRETS}
            with patch.object(mgr, "ENV_PATH", env_path), \
                 patch.dict(os.environ, clean_env, clear=True):
                result = mgr._build_mirror_env("true")

            self.assertNotIn("should-not-appear", result.values())
            self.assertNotIn("also-not", result.values())
            # Secrets should be absent (not leaked from .env)
            self.assertEqual(result.get("MSA_REFRESH_TOKEN", ""), "")
            self.assertEqual(result.get("AZURE_CLIENT_ID", ""), "")

    def test_build_mirror_env_passes_through_runtime_secrets(self):
        """_build_mirror_env() must preserve secrets already in os.environ."""
        with tempfile.TemporaryDirectory() as tmp:
            env_path = _fresh_env_path(tmp)
            env_path.write_text("SYNC_DRY_RUN=false\n", encoding="utf-8")
            with patch.object(mgr, "ENV_PATH", env_path), \
                 patch.dict(os.environ, {"MSA_REFRESH_TOKEN": "runtime-token"}, clear=False):
                result = mgr._build_mirror_env("false")

            self.assertEqual(result.get("MSA_REFRESH_TOKEN"), "runtime-token")

    def test_build_mirror_env_loads_variables_from_env_file(self):
        """_build_mirror_env() must load non-sensitive variables from .env."""
        with tempfile.TemporaryDirectory() as tmp:
            env_path = _fresh_env_path(tmp)
            env_path.write_text("SYNC_DRY_RUN=false\nONEDRIVE_ROOT_MODE=approot\n", encoding="utf-8")
            clean_env = {k: v for k, v in os.environ.items()
                         if k not in ("SYNC_DRY_RUN", "ONEDRIVE_ROOT_MODE")}
            with patch.object(mgr, "ENV_PATH", env_path), \
                 patch.dict(os.environ, clean_env, clear=True):
                result = mgr._build_mirror_env("true")

            # SYNC_DRY_RUN is forced by the argument, not .env
            self.assertEqual(result["SYNC_DRY_RUN"], "true")
            # ONEDRIVE_ROOT_MODE comes from .env
            self.assertEqual(result.get("ONEDRIVE_ROOT_MODE"), "approot")


# ---------------------------------------------------------------------------
# 5. Preview mode forces SYNC_DRY_RUN=true
# ---------------------------------------------------------------------------

class TestPreviewForcessDryRun(unittest.TestCase):

    def test_preview_passes_sync_dry_run_true(self):
        """action_preview() must set SYNC_DRY_RUN=true in the subprocess env."""
        captured_env = {}

        def fake_run(args, cwd, env):
            captured_env.update(env)

        with tempfile.TemporaryDirectory() as tmp:
            env_path = _fresh_env_path(tmp)
            env_path.write_text("SYNC_DRY_RUN=false\n", encoding="utf-8")
            with patch.object(mgr, "ENV_PATH", env_path), \
                 patch.object(mgr, "REPO_ROOT", Path(tmp)), \
                 patch("subprocess.run", side_effect=fake_run), \
                 patch("builtins.print"):
                mgr.action_preview()

        self.assertEqual(captured_env.get("SYNC_DRY_RUN"), "true")


# ---------------------------------------------------------------------------
# 6. Sync manual sets SYNC_DRY_RUN=false after confirmation
# ---------------------------------------------------------------------------

class TestSyncManualDryRunFalse(unittest.TestCase):

    def test_sync_manual_passes_dry_run_false_after_confirmation(self):
        """action_sync_manual() must pass SYNC_DRY_RUN=false to subprocess after confirm."""
        captured_env = {}

        def fake_run(args, cwd, env):
            captured_env.update(env)

        with tempfile.TemporaryDirectory() as tmp:
            env_path = _fresh_env_path(tmp)
            env_path.write_text("SYNC_DRY_RUN=true\n", encoding="utf-8")
            with patch.object(mgr, "ENV_PATH", env_path), \
                 patch.object(mgr, "REPO_ROOT", Path(tmp)), \
                 patch("subprocess.run", side_effect=fake_run), \
                 patch("builtins.print"), \
                 patch.dict(os.environ, {
                     "AZURE_CLIENT_ID": "fake-client-id",
                     "MSA_REFRESH_TOKEN": "fake-token",
                 }), \
                 patch("mcp_env_manager._prompt", return_value="s"):
                mgr.action_sync_manual()

        self.assertEqual(captured_env.get("SYNC_DRY_RUN"), "false")

    def test_sync_manual_cancelled_does_not_call_subprocess(self):
        """action_sync_manual() must not run subprocess if user cancels."""
        subprocess_called = []

        def fake_run(args, cwd, env):
            subprocess_called.append(True)

        with tempfile.TemporaryDirectory() as tmp:
            env_path = _fresh_env_path(tmp)
            with patch.object(mgr, "ENV_PATH", env_path), \
                 patch("subprocess.run", side_effect=fake_run), \
                 patch("builtins.print"), \
                 patch.dict(os.environ, {
                     "AZURE_CLIENT_ID": "fake-client-id",
                     "MSA_REFRESH_TOKEN": "fake-token",
                 }), \
                 patch("mcp_env_manager._prompt", return_value="N"):
                mgr.action_sync_manual()

        self.assertEqual(subprocess_called, [])

    def test_sync_manual_without_secrets_does_not_call_subprocess(self):
        """action_sync_manual() must not run subprocess if secrets are unavailable."""
        subprocess_called = []

        def fake_run(args, cwd, env):
            subprocess_called.append(True)

        clean_env = {k: v for k, v in os.environ.items()
                     if k not in ("AZURE_CLIENT_ID", "MSA_REFRESH_TOKEN")}
        with tempfile.TemporaryDirectory() as tmp:
            env_path = _fresh_env_path(tmp)
            with patch.object(mgr, "ENV_PATH", env_path), \
                 patch("subprocess.run", side_effect=fake_run), \
                 patch("builtins.print"), \
                 patch.dict(os.environ, clean_env, clear=True), \
                 patch("getpass.getpass", return_value=""):
                mgr.action_sync_manual()

        self.assertEqual(subprocess_called, [])


# ---------------------------------------------------------------------------
# 7. No fixture file contains token-like values
# ---------------------------------------------------------------------------

class TestNoRealTokensInFixtures(unittest.TestCase):

    FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures"
    # Patterns that would indicate real credentials
    SUSPICIOUS_PATTERNS = [
        "MSA_REFRESH_TOKEN=",
        "AZURE_CLIENT_ID=",
        "refresh_token",
        "access_token",
        "client_secret",
    ]

    def test_no_credentials_in_fixture_files(self):
        """No test fixture file should contain credential key=value patterns."""
        if not self.FIXTURE_DIR.is_dir():
            self.skipTest("Fixture directory not found")

        for fixture_file in self.FIXTURE_DIR.rglob("*"):
            if not fixture_file.is_file():
                continue
            try:
                content = fixture_file.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for pattern in self.SUSPICIOUS_PATTERNS:
                # Allow key names without assigned values (e.g. in env templates)
                # Only flag if there's an actual non-empty value
                import re
                if re.search(rf"{re.escape(pattern)}\s*=\s*\S+", content):
                    self.fail(
                        f"Fixture '{fixture_file.name}' contains potential credential: '{pattern}=...'"
                    )


# ---------------------------------------------------------------------------
# 8. looks_sensitive / assert_not_secret_key unit tests
# ---------------------------------------------------------------------------

class TestSensitivityGuard(unittest.TestCase):

    def test_looks_sensitive_detects_token(self):
        self.assertTrue(mgr.looks_sensitive("MSA_REFRESH_TOKEN"))

    def test_looks_sensitive_detects_secret(self):
        self.assertTrue(mgr.looks_sensitive("CLIENT_SECRET"))

    def test_looks_sensitive_detects_password(self):
        self.assertTrue(mgr.looks_sensitive("DB_PASSWORD"))

    def test_looks_sensitive_detects_private(self):
        self.assertTrue(mgr.looks_sensitive("PRIVATE_KEY"))

    def test_looks_sensitive_false_for_safe_vars(self):
        for key in mgr.VARIABLES:
            self.assertFalse(
                mgr.looks_sensitive(key),
                msg=f"VARIABLES member '{key}' should not be flagged as sensitive",
            )

    def test_assert_not_secret_key_raises_for_secrets(self):
        for key in mgr.SECRETS:
            with self.assertRaises(ValueError, msg=f"assert_not_secret_key should raise for '{key}'"):
                mgr.assert_not_secret_key(key)

    def test_assert_not_secret_key_passes_for_variables(self):
        for key in mgr.VARIABLES:
            try:
                mgr.assert_not_secret_key(key)
            except ValueError:
                self.fail(f"assert_not_secret_key raised unexpectedly for variable '{key}'")


if __name__ == "__main__":
    unittest.main()
