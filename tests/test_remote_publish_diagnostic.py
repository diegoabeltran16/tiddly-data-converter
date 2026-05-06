#!/usr/bin/env python3
"""Tests for punctual OneDrive diagnostic publication."""

from __future__ import annotations

import sys
import urllib.error
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = REPO_ROOT / "python_scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import remote_publish_diagnostic as publish


def _make_diagnostic(tmp_path: Path, filename: str = "diagnostico-tematico-08-chunks-ai.md.json") -> tuple[Path, Path, Path]:
    local_out = tmp_path / "data" / "out" / "local"
    sessions_root = local_out / "sessions"
    local_file = sessions_root / "06_diagnoses" / "tema" / filename
    local_file.parent.mkdir(parents=True)
    local_file.write_text('{"title":"diagnostico","type":"text/markdown","text":"ok"}', encoding="utf-8")
    return local_out, sessions_root, local_file


def test_validate_publish_paths_accepts_required_local_remote_equivalence(tmp_path: Path):
    local_out, sessions_root, local_file = _make_diagnostic(tmp_path)

    paths = publish.validate_publish_paths(
        str(local_file),
        "sessions/06_diagnoses/tema/diagnostico-tematico-08-chunks-ai.md.json",
        local_out_dir=local_out,
        sessions_root=sessions_root,
    )

    assert paths.local_relative_path == "sessions/06_diagnoses/tema/diagnostico-tematico-08-chunks-ai.md.json"
    assert paths.remote_relative_path == paths.local_relative_path


def test_validate_publish_paths_rejects_remote_data_out_local_prefix(tmp_path: Path):
    local_out, sessions_root, local_file = _make_diagnostic(tmp_path)

    with pytest.raises(ValueError, match="project-relative"):
        publish.validate_publish_paths(
            str(local_file),
            "data/out/local/sessions/06_diagnoses/tema/diagnostico-tematico-08-chunks-ai.md.json",
            local_out_dir=local_out,
            sessions_root=sessions_root,
        )


def test_validate_publish_paths_rejects_remote_outside_diagnoses(tmp_path: Path):
    local_out, sessions_root, local_file = _make_diagnostic(tmp_path)

    with pytest.raises(ValueError, match="sessions/06_diagnoses"):
        publish.validate_publish_paths(
            str(local_file),
            "sessions/05_propuesta_de_sesion/diagnostico-tematico-08-chunks-ai.md.json",
            local_out_dir=local_out,
            sessions_root=sessions_root,
        )


def test_validate_publish_paths_rejects_mismatched_mapping(tmp_path: Path):
    local_out, sessions_root, local_file = _make_diagnostic(tmp_path)

    with pytest.raises(ValueError, match="preserve the mirror-relative mapping"):
        publish.validate_publish_paths(
            str(local_file),
            "sessions/06_diagnoses/tema/diagnostico-tematico-09-otro.md.json",
            local_out_dir=local_out,
            sessions_root=sessions_root,
        )


def test_validate_publish_paths_rejects_invalid_json(tmp_path: Path):
    local_out, sessions_root, local_file = _make_diagnostic(tmp_path)
    local_file.write_text("{not json", encoding="utf-8")

    with pytest.raises(ValueError, match="not valid JSON"):
        publish.validate_publish_paths(
            str(local_file),
            "sessions/06_diagnoses/tema/diagnostico-tematico-08-chunks-ai.md.json",
            local_out_dir=local_out,
            sessions_root=sessions_root,
        )


def test_upload_file_replace_uses_project_relative_content_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    _, _, local_file = _make_diagnostic(tmp_path)
    cfg = publish.PublishConfig(
        tenant="consumers",
        client_id="client",
        refresh_token="refresh",
        project_root_name="tiddly-data-converter",
        root_mode="approot",
        create_dirs=True,
        conflict_behavior="replace",
        dry_run=False,
    )
    calls: list[tuple[str, bytes]] = []

    def fake_put(url: str, data: bytes, headers: dict[str, str]) -> None:
        calls.append((url, data))

    monkeypatch.setattr(publish, "_http_put_raw", fake_put)

    result = publish.upload_file(
        cfg,
        "token",
        local_file,
        "sessions/06_diagnoses/tema/diagnostico-tematico-08-chunks-ai.md.json",
    )

    assert result == "uploaded"
    assert len(calls) == 1
    assert "tiddly-data-converter/sessions/06_diagnoses/tema/diagnostico-tematico-08-chunks-ai.md.json:/content" in calls[0][0]


def test_upload_file_skip_does_not_put_when_remote_exists(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    _, _, local_file = _make_diagnostic(tmp_path)
    cfg = publish.PublishConfig(
        tenant="consumers",
        client_id="client",
        refresh_token="refresh",
        project_root_name="tiddly-data-converter",
        root_mode="approot",
        create_dirs=True,
        conflict_behavior="skip",
        dry_run=False,
    )

    monkeypatch.setattr(publish, "_http_json", lambda *args, **kwargs: {"file": {}})

    def fail_put(*args, **kwargs):
        raise AssertionError("skip mode must not upload when remote file exists")

    monkeypatch.setattr(publish, "_http_put_raw", fail_put)

    result = publish.upload_file(
        cfg,
        "token",
        local_file,
        "sessions/06_diagnoses/tema/diagnostico-tematico-08-chunks-ai.md.json",
    )

    assert result == "skipped"


def test_remote_file_exists_returns_false_on_404(monkeypatch: pytest.MonkeyPatch):
    cfg = publish.PublishConfig(
        tenant="consumers",
        client_id="client",
        refresh_token="refresh",
        project_root_name="tiddly-data-converter",
        root_mode="approot",
        create_dirs=True,
        conflict_behavior="replace",
        dry_run=False,
    )

    def fake_json(*args, **kwargs):
        raise urllib.error.HTTPError(url="", code=404, msg="Not found", hdrs=None, fp=None)

    monkeypatch.setattr(publish, "_http_json", fake_json)

    assert not publish.remote_file_exists(
        cfg,
        "token",
        "sessions/06_diagnoses/tema/diagnostico-tematico-08-chunks-ai.md.json",
    )
