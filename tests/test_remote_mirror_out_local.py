#!/usr/bin/env python3
"""Tests for remote_mirror_out_local.py — S100 bilateral sync governance.

Validates:
1. Path encoding: spaces and special chars are properly percent-encoded in Graph URLs.
2. Zone.Identifier exclusion: ADS files with ':' in name are excluded before upload.
3. Prune protection: _remote_outbox/ paths are never deleted by REMOTE_DELETE_EXTRANEOUS.
4. Pull allowlist: remote_pull_sessions only accepts mXX-sNN-*.md.json files.
5. Pull denylist: tiddlers_*.jsonl and .env files are rejected from pull.
6. Retry on 504: upload_with_retry retries on transient errors.
7. Secrets not printed: no token/auth-header leak in error paths.
8. No legacy data/sessions/ creation.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
import urllib.error
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, call, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = REPO_ROOT / "python_scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import remote_mirror_out_local as mirror
import remote_pull_sessions as pull


# ---------------------------------------------------------------------------
# 1. Path encoding
# ---------------------------------------------------------------------------

class TestPathEncoding(unittest.TestCase):

    def test_encode_segment_encodes_spaces(self):
        encoded = mirror.encode_graph_path_segment("m04 diagnostico-global.md.json")
        self.assertNotIn(" ", encoded)
        self.assertIn("%20", encoded)

    def test_encode_segment_encodes_special_chars(self):
        encoded = mirror.encode_graph_path_segment("file (v2).json")
        self.assertNotIn("(", encoded)
        self.assertNotIn(")", encoded)
        self.assertNotIn(" ", encoded)

    def test_encode_rel_path_encodes_each_segment(self):
        rel = "sessions/06_diagnoses/proyecto/m04 diagnostico-global-proyecto-post-s097.md.json"
        encoded = mirror.encode_graph_rel_path(rel)
        self.assertNotIn(" ", encoded)
        self.assertIn("sessions/06_diagnoses/proyecto/", encoded)
        self.assertIn("m04%20diagnostico", encoded)

    def test_encode_rel_path_does_not_encode_separators(self):
        rel = "sessions/sub/file.json"
        encoded = mirror.encode_graph_rel_path(rel)
        self.assertEqual(encoded, "sessions/sub/file.json")

    def test_encode_segment_safe_name(self):
        # A slug-safe name should be unchanged
        encoded = mirror.encode_graph_path_segment("m04-s100-sync-bilateral.md.json")
        self.assertEqual(encoded, "m04-s100-sync-bilateral.md.json")


# ---------------------------------------------------------------------------
# 2. Zone.Identifier / ADS exclusion
# ---------------------------------------------------------------------------

class TestZoneIdentifierExclusion(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _make_file(self, name: str, content: bytes = b"x") -> Path:
        p = self.root / name
        p.write_bytes(content)
        return p

    def test_zone_identifier_excluded(self):
        ads = self._make_file("tiddlers_1.jsonl:Zone.Identifier")
        reason = mirror._exclusion_reason(ads)
        self.assertEqual(reason, "windows_ads_zone_identifier")

    def test_colon_in_name_excluded(self):
        p = self._make_file("some:file.txt")
        reason = mirror._exclusion_reason(p)
        self.assertEqual(reason, "windows_ads_zone_identifier")

    def test_dotenv_excluded(self):
        p = self._make_file(".env")
        reason = mirror._exclusion_reason(p)
        self.assertEqual(reason, "dotenv_credentials")

    def test_dotenv_local_excluded(self):
        p = self._make_file(".env.local")
        reason = mirror._exclusion_reason(p)
        self.assertEqual(reason, "dotenv_credentials")

    def test_ds_store_excluded(self):
        p = self._make_file(".DS_Store")
        reason = mirror._exclusion_reason(p)
        self.assertEqual(reason, "macos_metadata")

    def test_tmp_file_excluded(self):
        p = self._make_file("session.tmp")
        reason = mirror._exclusion_reason(p)
        self.assertEqual(reason, "temporary_file")

    def test_lock_file_excluded(self):
        p = self._make_file("session.lock")
        reason = mirror._exclusion_reason(p)
        self.assertEqual(reason, "temporary_file")

    def test_pycache_excluded(self):
        cache_dir = self.root / "__pycache__"
        cache_dir.mkdir()
        p = cache_dir / "module.cpython-311.pyc"
        p.write_bytes(b"x")
        reason = mirror._exclusion_reason(p)
        self.assertEqual(reason, "cache_or_vcs_directory")

    def test_normal_file_not_excluded(self):
        p = self._make_file("m04-s100-sync-bilateral.md.json")
        reason = mirror._exclusion_reason(p)
        self.assertIsNone(reason)

    def test_iter_syncable_files_excludes_ads(self):
        good = self._make_file("good.md.json", b"good")
        ads = self._make_file("tiddlers_1.jsonl:Zone.Identifier", b"ads")
        stats = mirror.MirrorStats()
        result = mirror.iter_syncable_files(self.root, stats=stats)
        names = [Path(p).name for _, p in result]
        self.assertIn("good.md.json", names)
        self.assertNotIn("tiddlers_1.jsonl:Zone.Identifier", names)
        self.assertEqual(stats.excluded, 1)
        self.assertEqual(stats.excluded_reasons.get("windows_ads_zone_identifier"), 1)

    def test_iter_syncable_files_counts_all_exclusion_types(self):
        self._make_file("good.json", b"good")
        self._make_file("bad:ads.json", b"bad")
        self._make_file(".env", b"secret")
        stats = mirror.MirrorStats()
        result = mirror.iter_syncable_files(self.root, stats=stats)
        self.assertEqual(len(result), 1)
        self.assertEqual(stats.excluded, 2)


# ---------------------------------------------------------------------------
# 3. Prune protection: _remote_outbox/ never deleted
# ---------------------------------------------------------------------------

class TestPruneProtection(unittest.TestCase):

    def test_outbox_root_is_protected(self):
        self.assertTrue(mirror._is_protected_remote_path("_remote_outbox"))

    def test_outbox_sessions_is_protected(self):
        self.assertTrue(mirror._is_protected_remote_path("_remote_outbox/sessions"))

    def test_outbox_file_is_protected(self):
        self.assertTrue(mirror._is_protected_remote_path("_remote_outbox/sessions/m04-s100-test.md.json"))

    def test_non_outbox_is_not_protected(self):
        self.assertFalse(mirror._is_protected_remote_path("sessions/06_diagnoses/test.md.json"))

    def test_outbox_prefix_with_leading_slash(self):
        self.assertTrue(mirror._is_protected_remote_path("/_remote_outbox/sessions/file.md.json"))

    def test_prune_skips_outbox(self):
        """run_live must not delete _remote_outbox/ files even with delete_extraneous=true."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            local_file = root / "local.json"
            local_file.write_bytes(b"local")

            cfg = mirror.MirrorConfig(
                source=root,
                tenant="consumers",
                client_id="fake",
                refresh_token="fake",
                project_root_name="test",
                root_mode="approot",
                create_dirs=True,
                conflict_behavior="replace",
                delete_extraneous=True,
                dry_run=False,
                sync_mode="local_primary",
            )
            stats = mirror.MirrorStats()
            local_files = [("local.json", local_file)]

            # Patch network calls
            with patch.object(mirror, "exchange_refresh_token", return_value="tok"), \
                 patch.object(mirror, "resolve_project_folder", return_value="https://fake/prefix"), \
                 patch.object(mirror, "upload_file", return_value=None), \
                 patch.object(mirror, "list_remote_files", return_value={
                     "local.json",
                     "_remote_outbox/sessions/m04-s100-remote-candidate.md.json",
                 }):
                mirror.run_live(cfg, local_files, stats)

            # _remote_outbox file must NOT be deleted
            self.assertEqual(stats.deleted, 0)
            self.assertEqual(stats.protected, 1)
            self.assertEqual(stats.errors, [])


# ---------------------------------------------------------------------------
# 4 & 5. Pull allowlist / denylist
# ---------------------------------------------------------------------------

class TestPullAllowlist(unittest.TestCase):

    def _check(self, filename: str) -> tuple[bool, str]:
        return pull._is_allowed_outbox_file(filename)

    def test_valid_session_artifact_allowed(self):
        allowed, reason = self._check("m04-s100-sync-bilateral-onedrive.md.json")
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_valid_session_with_letter_suffix_allowed(self):
        allowed, reason = self._check("m04-s100a-addendum.md.json")
        self.assertTrue(allowed)

    def test_canon_shard_denied(self):
        allowed, reason = self._check("tiddlers_1.jsonl")
        self.assertFalse(allowed)
        self.assertEqual(reason, "denylist_canon_shard")

    def test_canon_shard_any_number_denied(self):
        allowed, reason = self._check("tiddlers_99.jsonl")
        self.assertFalse(allowed)
        self.assertEqual(reason, "denylist_canon_shard")

    def test_dotenv_denied(self):
        allowed, reason = self._check(".env")
        self.assertFalse(allowed)
        self.assertEqual(reason, "denylist_credentials")

    def test_ads_zone_identifier_denied(self):
        allowed, reason = self._check("tiddlers_1.jsonl:Zone.Identifier")
        self.assertFalse(allowed)
        self.assertEqual(reason, "denylist_ads_zone_identifier")

    def test_generic_json_file_not_allowed(self):
        allowed, reason = self._check("output.json")
        self.assertFalse(allowed)
        self.assertEqual(reason, "allowlist_not_session_artifact")

    def test_wrong_prefix_not_allowed(self):
        allowed, reason = self._check("session-100-sync.md.json")
        self.assertFalse(allowed)

    def test_pull_live_rejects_canon_shard(self):
        """run_live must not download tiddlers_*.jsonl to local inbox."""
        with tempfile.TemporaryDirectory() as tmp:
            inbox = Path(tmp) / "remote_inbox"
            cfg = pull.PullConfig(
                tenant="consumers",
                client_id="fake",
                refresh_token="fake",
                project_root_name="test",
                root_mode="approot",
                inbox_dir=inbox,
                dry_run=False,
            )
            stats = pull.PullStats()
            items = [{"name": "tiddlers_1.jsonl", "size": 100}]
            pull.run_live(cfg, items, "tok", stats)
            self.assertEqual(stats.pulled, 0)
            self.assertEqual(stats.skipped_denylist, 1)
            self.assertFalse((inbox / "tiddlers_1.jsonl").exists())

    def test_pull_live_accepts_valid_session_artifact(self):
        """run_live must stage mXX-sNN-*.md.json files into inbox."""
        with tempfile.TemporaryDirectory() as tmp:
            inbox = Path(tmp) / "remote_inbox"
            cfg = pull.PullConfig(
                tenant="consumers",
                client_id="fake",
                refresh_token="fake",
                project_root_name="test",
                root_mode="approot",
                inbox_dir=inbox,
                dry_run=False,
            )
            stats = pull.PullStats()
            items = [{
                "name": "m04-s100-sync-bilateral.md.json",
                "size": 50,
                "@microsoft.graph.downloadUrl": "https://fake/download",
            }]
            with patch.object(pull, "_http_get_bytes", return_value=b'{"title": "test"}'):
                pull.run_live(cfg, items, "tok", stats)
            self.assertEqual(stats.pulled, 1)
            self.assertTrue((inbox / "m04-s100-sync-bilateral.md.json").exists())


# ---------------------------------------------------------------------------
# 6. Retry on transient errors (504)
# ---------------------------------------------------------------------------

class TestRetryBackoff(unittest.TestCase):

    def test_upload_succeeds_after_retry(self):
        """_upload_with_retry should retry on 504 and succeed on second attempt."""
        call_count = {"n": 0}

        def _fake_upload(remote_prefix, rel, path, token):
            call_count["n"] += 1
            if call_count["n"] < 2:
                raise urllib.error.HTTPError(
                    url="", code=504, msg="Gateway Timeout",
                    hdrs=MagicMock(get=lambda k, d=None: None),
                    fp=None,
                )

        stats = mirror.MirrorStats()
        with patch.object(mirror, "upload_file", side_effect=_fake_upload), \
             patch("time.sleep"):
            mirror._upload_with_retry("prefix", "rel/file.json", Path("/tmp/x"), "tok", stats)
        self.assertEqual(call_count["n"], 2)
        self.assertEqual(stats.errors, [])

    def test_upload_fails_after_max_retries(self):
        """_upload_with_retry should classify TRANSIENT_GRAPH_ERROR after exhausting retries."""
        def _always_504(*args, **kwargs):
            raise urllib.error.HTTPError(
                url="", code=504, msg="Gateway Timeout",
                hdrs=MagicMock(get=lambda k, d=None: None),
                fp=None,
            )

        stats = mirror.MirrorStats()
        with patch.object(mirror, "upload_file", side_effect=_always_504), \
             patch("time.sleep"):
            with self.assertRaises(urllib.error.HTTPError):
                mirror._upload_with_retry("prefix", "rel/file.json", Path("/tmp/x"), "tok", stats)

    def test_transient_codes_defined(self):
        self.assertIn(504, mirror.TRANSIENT_HTTP_CODES)
        self.assertIn(429, mirror.TRANSIENT_HTTP_CODES)
        self.assertIn(408, mirror.TRANSIENT_HTTP_CODES)
        self.assertIn(503, mirror.TRANSIENT_HTTP_CODES)


# ---------------------------------------------------------------------------
# 7. Secrets not printed or persisted
# ---------------------------------------------------------------------------

class TestSecretsNotLeaked(unittest.TestCase):

    def test_error_message_does_not_contain_token(self):
        """When upload fails, the error message must not contain the token string."""
        stats = mirror.MirrorStats()
        SECRET_TOKEN = "super-secret-refresh-token-12345"

        def _fail(*args, **kwargs):
            raise urllib.error.HTTPError(
                url="", code=401, msg="Unauthorized",
                hdrs=MagicMock(get=lambda k, d=None: None),
                fp=None,
            )

        with patch.object(mirror, "exchange_refresh_token", return_value=SECRET_TOKEN), \
             patch.object(mirror, "resolve_project_folder", return_value="https://fake/prefix"), \
             patch.object(mirror, "_upload_with_retry", side_effect=_fail):
            cfg = mirror.MirrorConfig(
                source=Path("/tmp"),
                tenant="consumers",
                client_id="client-id",
                refresh_token=SECRET_TOKEN,
                project_root_name="test",
                root_mode="approot",
                create_dirs=True,
                conflict_behavior="replace",
                delete_extraneous=False,
                dry_run=False,
                sync_mode="local_primary",
            )
            with tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp) / "file.json"
                p.write_bytes(b"content")
                mirror.run_live(cfg, [("file.json", p)], stats)

        for err in stats.errors:
            self.assertNotIn(SECRET_TOKEN, err, "Refresh token must not appear in error messages")

    def test_no_legacy_data_sessions_path(self):
        """Verify that neither script references data/sessions/ as an output path."""
        mirror_src = (REPO_ROOT / "python_scripts" / "remote_mirror_out_local.py").read_text()
        pull_src = (REPO_ROOT / "python_scripts" / "remote_pull_sessions.py").read_text()
        # The path data/sessions/ must not appear as a write target — only data/out/local/sessions/
        # Allow it in migration_equivalent checks (path_governance references are OK)
        for line in mirror_src.splitlines():
            if "data/sessions/" in line and "migration" not in line.lower() and "#" not in line:
                self.fail(f"remote_mirror_out_local.py references legacy data/sessions/ path: {line!r}")
        for line in pull_src.splitlines():
            if "data/sessions/" in line and "#" not in line:
                self.fail(f"remote_pull_sessions.py references legacy data/sessions/ path: {line!r}")


# ---------------------------------------------------------------------------
# 8. Stats error classification
# ---------------------------------------------------------------------------

class TestStatsErrorClassification(unittest.TestCase):

    def test_add_error_classifies_by_type(self):
        stats = mirror.MirrorStats()
        stats.add_error("AUTH_ERROR", "auth failed")
        stats.add_error("TRANSIENT_GRAPH_ERROR", "504")
        stats.add_error("TRANSIENT_GRAPH_ERROR", "503")
        self.assertEqual(stats.errors_by_type["AUTH_ERROR"], 1)
        self.assertEqual(stats.errors_by_type["TRANSIENT_GRAPH_ERROR"], 2)
        self.assertEqual(len(stats.errors), 3)

    def test_add_excluded_counts_by_reason(self):
        stats = mirror.MirrorStats()
        stats.add_excluded("windows_ads_zone_identifier")
        stats.add_excluded("windows_ads_zone_identifier")
        stats.add_excluded("dotenv_credentials")
        self.assertEqual(stats.excluded, 3)
        self.assertEqual(stats.excluded_reasons["windows_ads_zone_identifier"], 2)
        self.assertEqual(stats.excluded_reasons["dotenv_credentials"], 1)


if __name__ == "__main__":
    unittest.main()
