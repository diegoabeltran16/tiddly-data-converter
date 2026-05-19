"""P0 contract tests for remote_pull_canon.py — S0117.

Verifies authentication errors, download errors, dry_run governance, target path
governance, and secret non-disclosure. All HTTP calls are mocked — no real network
access, no OneDrive, no Microsoft endpoints.

Para ejecutar en aislamiento:
    pytest tests/test_remote_pull_canon_p0.py -v
"""

from __future__ import annotations

import io
import json
import os
import sys
import urllib.error
import urllib.request
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "python_scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import remote_pull_canon as rpc  # noqa: E402


# ── Helpers ───────────────────────────────────────────────────────────────────

def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://login.microsoftonline.com/consumers/oauth2/v2.0/token",
        code=code,
        msg=f"HTTP {code}",
        hdrs={},
        fp=None,
    )


def _run_main(env: dict[str, str]) -> tuple[int, str, str]:
    """Call rpc.main() with patched env vars, return (rc, stdout, stderr)."""
    out = io.StringIO()
    err = io.StringIO()
    with patch.dict(os.environ, env):
        with redirect_stdout(out), redirect_stderr(err):
            rc = rpc.main()
    return rc, out.getvalue(), err.getvalue()


def _extract_summary(stdout: str) -> dict:
    # The JSON summary block always starts at a '{' that begins a new line.
    idx = stdout.find("\n{")
    start = idx + 1 if idx != -1 else stdout.index("{")
    return json.loads(stdout[start:])


# ── A5: dry_run mode ──────────────────────────────────────────────────────────

class TestA5DryRunMode:
    """dry_run=true (env PULL_DRY_RUN=true) skips auth and returns exit 0."""

    def test_exits_zero(self):
        rc, _, _ = _run_main({"PULL_DRY_RUN": "true"})
        assert rc == 0

    def test_prints_dry_run_marker(self):
        _, stdout, _ = _run_main({"PULL_DRY_RUN": "true"})
        assert "dry" in stdout.lower()

    def test_summary_json_is_valid(self):
        _, stdout, _ = _run_main({"PULL_DRY_RUN": "true"})
        summary = _extract_summary(stdout)
        assert summary["dry_run"] is True
        assert summary["downloaded"] == 0
        assert summary["errors"] == []

    def test_no_http_calls_in_dry_run(self):
        with patch("urllib.request.urlopen") as mock_open:
            rc, _, _ = _run_main({"PULL_DRY_RUN": "true"})
        mock_open.assert_not_called()
        assert rc == 0

    def test_dry_run_default_when_env_unset(self):
        # PULL_DRY_RUN not in env → defaults to True
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PULL_DRY_RUN", None)
            with patch("urllib.request.urlopen") as mock_open:
                out = io.StringIO()
                err = io.StringIO()
                with redirect_stdout(out), redirect_stderr(err):
                    rc = rpc.main()
        mock_open.assert_not_called()
        assert rc == 0


# ── A6 / A7: target governance ────────────────────────────────────────────────

class TestA6A7TargetGovernance:
    """LOCAL_SYNC_TARGET is respected; dry_run with empty target exits cleanly."""

    def test_dry_run_summary_contains_correct_target(self, tmp_path):
        _, stdout, _ = _run_main({
            "PULL_DRY_RUN": "true",
            "LOCAL_SYNC_TARGET": str(tmp_path),
        })
        summary = _extract_summary(stdout)
        assert str(tmp_path) in summary["target"] or tmp_path.name in summary["target"]

    def test_live_download_writes_to_local_sync_target(self, tmp_path):
        fake_rel = "subdir/data.jsonl"
        fake_content = b'{"id":"test"}\n'
        out = io.StringIO()
        err = io.StringIO()
        with (
            patch.dict(os.environ, {
                "PULL_DRY_RUN": "false",
                "AZURE_CLIENT_ID": "fake-client",
                "MSA_REFRESH_TOKEN": "fake-refresh",
                "LOCAL_SYNC_TARGET": str(tmp_path),
            }),
            patch.object(rpc, "exchange_refresh_token", return_value="fake-token"),
            patch.object(rpc, "list_remote_files", return_value=[fake_rel]),
            patch.object(rpc, "_http_get_bytes", return_value=fake_content),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            rc = rpc.main()

        assert rc == 0
        downloaded = tmp_path / fake_rel
        assert downloaded.exists(), f"Expected downloaded file at {downloaded}"
        assert downloaded.read_bytes() == fake_content

    def test_empty_tmp_target_exits_cleanly_in_dry_run(self, tmp_path):
        rc, _, _ = _run_main({
            "PULL_DRY_RUN": "true",
            "LOCAL_SYNC_TARGET": str(tmp_path),
        })
        assert rc == 0


# ── A1 / A2: authentication errors ───────────────────────────────────────────

class TestA1A2AuthErrors:
    """HTTP 401 and 403 from token exchange are classified as AUTH_ERROR."""

    def test_http_401_returns_exit_one(self):
        out = io.StringIO()
        err = io.StringIO()
        with (
            patch.dict(os.environ, {
                "PULL_DRY_RUN": "false",
                "AZURE_CLIENT_ID": "fake-client",
                "MSA_REFRESH_TOKEN": "fake-token",
            }),
            patch("urllib.request.urlopen", side_effect=_http_error(401)),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            rc = rpc.main()
        assert rc == 1

    def test_http_401_reports_auth_error(self):
        out = io.StringIO()
        err = io.StringIO()
        with (
            patch.dict(os.environ, {
                "PULL_DRY_RUN": "false",
                "AZURE_CLIENT_ID": "fake-client",
                "MSA_REFRESH_TOKEN": "fake-token",
            }),
            patch("urllib.request.urlopen", side_effect=_http_error(401)),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            rpc.main()
        assert "AUTH_ERROR" in err.getvalue()

    def test_http_403_returns_exit_one(self):
        out = io.StringIO()
        err = io.StringIO()
        with (
            patch.dict(os.environ, {
                "PULL_DRY_RUN": "false",
                "AZURE_CLIENT_ID": "fake-client",
                "MSA_REFRESH_TOKEN": "fake-token",
            }),
            patch("urllib.request.urlopen", side_effect=_http_error(403)),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            rc = rpc.main()
        assert rc == 1

    def test_http_403_reports_auth_error(self):
        out = io.StringIO()
        err = io.StringIO()
        with (
            patch.dict(os.environ, {
                "PULL_DRY_RUN": "false",
                "AZURE_CLIENT_ID": "fake-client",
                "MSA_REFRESH_TOKEN": "fake-token",
            }),
            patch("urllib.request.urlopen", side_effect=_http_error(403)),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            rpc.main()
        assert "AUTH_ERROR" in err.getvalue()

    def test_missing_client_id_blocks_live_mode(self):
        out = io.StringIO()
        err = io.StringIO()
        with (
            patch.dict(os.environ, {
                "PULL_DRY_RUN": "false",
                "AZURE_CLIENT_ID": "",
                "MSA_REFRESH_TOKEN": "fake-token",
            }),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            rc = rpc.main()
        assert rc == 1
        assert "AZURE_CLIENT_ID" in err.getvalue()

    def test_missing_refresh_token_blocks_live_mode(self):
        out = io.StringIO()
        err = io.StringIO()
        with (
            patch.dict(os.environ, {
                "PULL_DRY_RUN": "false",
                "AZURE_CLIENT_ID": "fake-client",
                "MSA_REFRESH_TOKEN": "",
            }),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            rc = rpc.main()
        assert rc == 1
        assert "MSA_REFRESH_TOKEN" in err.getvalue()


# ── A3: download errors ───────────────────────────────────────────────────────

class TestA3DownloadErrors:
    """HTTP 404 during file download is classified as DOWNLOAD_ERROR."""

    def test_http_404_classified_as_download_error(self, tmp_path):
        out = io.StringIO()
        err = io.StringIO()
        with (
            patch.dict(os.environ, {
                "PULL_DRY_RUN": "false",
                "AZURE_CLIENT_ID": "fake-client",
                "MSA_REFRESH_TOKEN": "fake-refresh",
                "LOCAL_SYNC_TARGET": str(tmp_path),
            }),
            patch.object(rpc, "exchange_refresh_token", return_value="fake-token"),
            patch.object(rpc, "list_remote_files", return_value=["some/file.jsonl"]),
            patch.object(rpc, "_http_get_bytes", side_effect=urllib.error.HTTPError(
                url="https://example.com/file", code=404, msg="Not Found", hdrs={}, fp=None,
            )),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            rc = rpc.main()

        assert rc == 1
        assert "DOWNLOAD_ERROR" in err.getvalue()

    def test_http_404_error_included_in_summary(self, tmp_path):
        out = io.StringIO()
        with (
            patch.dict(os.environ, {
                "PULL_DRY_RUN": "false",
                "AZURE_CLIENT_ID": "fake-client",
                "MSA_REFRESH_TOKEN": "fake-refresh",
                "LOCAL_SYNC_TARGET": str(tmp_path),
            }),
            patch.object(rpc, "exchange_refresh_token", return_value="fake-token"),
            patch.object(rpc, "list_remote_files", return_value=["some/file.jsonl"]),
            patch.object(rpc, "_http_get_bytes", side_effect=urllib.error.HTTPError(
                url="https://example.com/file", code=404, msg="Not Found", hdrs={}, fp=None,
            )),
            redirect_stdout(out),
            redirect_stderr(io.StringIO()),
        ):
            rpc.main()

        summary = _extract_summary(out.getvalue())
        assert summary.get("errors_by_type", {}).get("DOWNLOAD_ERROR", 0) >= 1


# ── A4: successful download ───────────────────────────────────────────────────

class TestA4SuccessfulDownload:
    """Mocked successful download returns exit 0 with correct summary counts."""

    def test_single_file_download_exits_zero(self, tmp_path):
        out = io.StringIO()
        with (
            patch.dict(os.environ, {
                "PULL_DRY_RUN": "false",
                "AZURE_CLIENT_ID": "fake-client",
                "MSA_REFRESH_TOKEN": "fake-refresh",
                "LOCAL_SYNC_TARGET": str(tmp_path),
            }),
            patch.object(rpc, "exchange_refresh_token", return_value="fake-token"),
            patch.object(rpc, "list_remote_files", return_value=["tiddlers_1.jsonl"]),
            patch.object(rpc, "_http_get_bytes", return_value=b'{"id":"t1"}\n'),
            redirect_stdout(out),
            redirect_stderr(io.StringIO()),
        ):
            rc = rpc.main()
        assert rc == 0

    def test_multiple_files_downloaded_count_is_correct(self, tmp_path):
        files = ["f1.jsonl", "f2.jsonl", "f3.jsonl"]
        out = io.StringIO()
        with (
            patch.dict(os.environ, {
                "PULL_DRY_RUN": "false",
                "AZURE_CLIENT_ID": "fake-client",
                "MSA_REFRESH_TOKEN": "fake-refresh",
                "LOCAL_SYNC_TARGET": str(tmp_path),
            }),
            patch.object(rpc, "exchange_refresh_token", return_value="fake-token"),
            patch.object(rpc, "list_remote_files", return_value=files),
            patch.object(rpc, "_http_get_bytes", return_value=b"content"),
            redirect_stdout(out),
            redirect_stderr(io.StringIO()),
        ):
            rpc.main()

        summary = _extract_summary(out.getvalue())
        assert summary["downloaded"] == len(files)
        assert summary["errors"] == []


# ── A8: secret governance ─────────────────────────────────────────────────────

class TestA8SecretGovernance:
    """AZURE_CLIENT_ID and MSA_REFRESH_TOKEN must not appear in stdout/stderr."""

    _CLIENT = "SENTINEL_CLIENT_ID_S0117_XYZ"
    _TOKEN = "SENTINEL_REFRESH_TOKEN_S0117_ABC"

    def test_client_id_absent_from_dry_run_output(self):
        _, stdout, stderr = _run_main({
            "PULL_DRY_RUN": "true",
            "AZURE_CLIENT_ID": self._CLIENT,
            "MSA_REFRESH_TOKEN": self._TOKEN,
        })
        assert self._CLIENT not in stdout
        assert self._CLIENT not in stderr

    def test_refresh_token_absent_from_dry_run_output(self):
        _, stdout, stderr = _run_main({
            "PULL_DRY_RUN": "true",
            "AZURE_CLIENT_ID": self._CLIENT,
            "MSA_REFRESH_TOKEN": self._TOKEN,
        })
        assert self._TOKEN not in stdout
        assert self._TOKEN not in stderr

    def test_refresh_token_absent_from_auth_error_output(self):
        out = io.StringIO()
        err = io.StringIO()
        with (
            patch.dict(os.environ, {
                "PULL_DRY_RUN": "false",
                "AZURE_CLIENT_ID": self._CLIENT,
                "MSA_REFRESH_TOKEN": self._TOKEN,
            }),
            patch("urllib.request.urlopen", side_effect=_http_error(401)),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            rpc.main()
        assert self._TOKEN not in out.getvalue()
        assert self._TOKEN not in err.getvalue()

    def test_client_id_absent_from_missing_credentials_error(self):
        out = io.StringIO()
        err = io.StringIO()
        with (
            patch.dict(os.environ, {
                "PULL_DRY_RUN": "false",
                "AZURE_CLIENT_ID": "",
                "MSA_REFRESH_TOKEN": self._TOKEN,
            }),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            rpc.main()
        assert self._TOKEN not in out.getvalue()
        assert self._TOKEN not in err.getvalue()
