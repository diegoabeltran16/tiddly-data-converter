#!/usr/bin/env python3
"""Publish one non-session diagnostic artifact to OneDrive via Graph.

This is intentionally not a mirror. It uploads exactly one local diagnostic
artifact from:

  data/out/local/sessions/06_diagnoses/<family>/<file>.md.json

to the OneDrive project-relative path:

  sessions/06_diagnoses/<family>/<file>.md.json

It never deletes remote files and does not inspect REMOTE_DELETE_EXTRANEOUS.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from diagnostic_governance import validate_full_path  # noqa: E402
from path_governance import (  # noqa: E402
    DEFAULT_LOCAL_OUT_DIR,
    DEFAULT_SESSIONS_DIR,
    REPO_ROOT,
    as_display_path,
)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
TOKEN_URL_TMPL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"

SIMPLE_UPLOAD_LIMIT = 4 * 1024 * 1024
CHUNK_SIZE = 10 * 1024 * 1024
TRANSIENT_HTTP_CODES: frozenset[int] = frozenset({408, 429, 500, 502, 503, 504})
MAX_RETRIES = 4
BASE_BACKOFF_SECONDS = 2

LOCAL_DIAG_PREFIX = "data/out/local/sessions/06_diagnoses/"
REMOTE_DIAG_PREFIX = "sessions/06_diagnoses/"


@dataclass(frozen=True)
class PublishConfig:
    tenant: str
    client_id: str
    refresh_token: str
    project_root_name: str
    root_mode: str
    create_dirs: bool
    conflict_behavior: str
    dry_run: bool


@dataclass(frozen=True)
class PublishPaths:
    local_file: Path
    local_relative_path: str
    remote_relative_path: str


def _load_dotenv(path: Path) -> None:
    """Load key=value pairs from .env without overriding existing variables."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip()


def _env(key: str, default: str = "") -> str:
    val = os.environ.get(key, "").strip()
    return val or default


def _bool_env(key: str, default: bool) -> bool:
    val = _env(key).lower()
    if val in ("true", "1", "yes"):
        return True
    if val in ("false", "0", "no"):
        return False
    return default


def load_config(*, dry_run: bool) -> PublishConfig:
    _load_dotenv(REPO_ROOT / ".env")
    return PublishConfig(
        tenant=_env("MSA_TENANT", "consumers"),
        client_id=_env("AZURE_CLIENT_ID"),
        refresh_token=_env("MSA_REFRESH_TOKEN"),
        project_root_name=_env("ONEDRIVE_PROJECT_ROOT_NAME", "tiddly-data-converter"),
        root_mode=_env("ONEDRIVE_ROOT_MODE", "approot"),
        create_dirs=_bool_env("REMOTE_CREATE_MISSING_DIRS", True),
        conflict_behavior=_env("REMOTE_CONFLICT_BEHAVIOR", "replace"),
        dry_run=dry_run,
    )


def _resolve_local_file(path_value: str) -> Path:
    normalized = path_value.replace("\\", "/")
    if ".." in normalized.split("/"):
        raise ValueError("local_file contains path traversal")
    candidate = Path(path_value)
    if candidate.is_absolute():
        return candidate.resolve()
    return (REPO_ROOT / candidate).resolve()


def _normalize_remote_relative_path(path_value: str) -> str:
    rel = path_value.replace("\\", "/").strip()
    if not rel:
        raise ValueError("remote_relative_path is empty")
    if rel.startswith("/") or Path(rel).is_absolute():
        raise ValueError("remote_relative_path must be relative")
    parts = rel.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError("remote_relative_path contains an unsafe path segment")
    if rel.startswith("data/out/local/"):
        raise ValueError("remote_relative_path must be project-relative, not data/out/local-relative")
    if not rel.startswith(REMOTE_DIAG_PREFIX):
        raise ValueError(f"remote_relative_path must start with {REMOTE_DIAG_PREFIX}")
    return rel


def validate_json_file(local_file: Path) -> None:
    try:
        with local_file.open(encoding="utf-8") as fh:
            json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValueError(f"local_file is not valid JSON: line {exc.lineno} column {exc.colno}") from exc


def validate_publish_paths(
    local_file_arg: str,
    remote_relative_path_arg: str,
    *,
    local_out_dir: Path = DEFAULT_LOCAL_OUT_DIR,
    sessions_root: Path = DEFAULT_SESSIONS_DIR,
) -> PublishPaths:
    local_file = _resolve_local_file(local_file_arg)
    if not local_file.is_file():
        raise ValueError(f"local_file does not exist: {as_display_path(local_file)}")

    valid, reason = validate_full_path(str(local_file), sessions_root)
    if not valid:
        raise ValueError(f"local_file is not a governed diagnostic path: {reason}")

    remote_relative_path = _normalize_remote_relative_path(remote_relative_path_arg)
    remote_as_local_path = local_out_dir / remote_relative_path
    valid, reason = validate_full_path(str(remote_as_local_path), sessions_root)
    if not valid:
        raise ValueError(f"remote_relative_path is not a governed diagnostic path: {reason}")

    try:
        local_relative_path = local_file.relative_to(local_out_dir.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"local_file must be under {as_display_path(local_out_dir)}") from exc

    if not local_relative_path.startswith(REMOTE_DIAG_PREFIX):
        raise ValueError(f"local_file must be under {LOCAL_DIAG_PREFIX}")

    if local_relative_path != remote_relative_path:
        raise ValueError(
            "local_file and remote_relative_path must preserve the mirror-relative mapping: "
            f"{local_relative_path} != {remote_relative_path}"
        )

    validate_json_file(local_file)
    return PublishPaths(
        local_file=local_file,
        local_relative_path=local_relative_path,
        remote_relative_path=remote_relative_path,
    )


def encode_graph_path_segment(segment: str) -> str:
    return quote(segment, safe="")


def encode_graph_rel_path(rel: str) -> str:
    return "/".join(encode_graph_path_segment(seg) for seg in rel.replace("\\", "/").split("/"))


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _http_json(
    url: str,
    *,
    method: str = "GET",
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> dict:
    req = urllib.request.Request(url, data=data, method=method)
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read() or b"{}")


def _http_put_raw(url: str, data: bytes, headers: dict[str, str]) -> None:
    req = urllib.request.Request(url, data=data, method="PUT")
    for key, value in headers.items():
        req.add_header(key, value)
    with urllib.request.urlopen(req):
        pass


def exchange_refresh_token(cfg: PublishConfig) -> str:
    token_url = TOKEN_URL_TMPL.format(tenant=cfg.tenant)
    body = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "client_id": cfg.client_id,
        "refresh_token": cfg.refresh_token,
        "scope": "Files.ReadWrite.AppFolder offline_access",
    }).encode()
    result = _http_json(
        token_url,
        method="POST",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if "access_token" not in result:
        raise RuntimeError(f"Token exchange failed: {result.get('error_description', 'unknown error')}")
    return result["access_token"]


def _root_base(cfg: PublishConfig) -> str:
    if cfg.root_mode == "drive":
        return f"{GRAPH_BASE}/me/drive/root"
    return f"{GRAPH_BASE}/me/drive/special/approot"


def _graph_item_url(cfg: PublishConfig, rel_path: str, suffix: str = "") -> str:
    return f"{_root_base(cfg)}:/{encode_graph_rel_path(rel_path)}{suffix}"


def _project_remote_path(cfg: PublishConfig, remote_relative_path: str) -> str:
    if not cfg.project_root_name:
        return remote_relative_path
    return f"{cfg.project_root_name}/{remote_relative_path}"


def _ensure_folder_at_path(cfg: PublishConfig, token: str, folder_path: str, parent_path: str, name: str) -> None:
    try:
        item = _http_json(_graph_item_url(cfg, folder_path), headers=_auth(token))
        if "folder" not in item:
            raise RuntimeError(f"remote path component is not a folder: {folder_path}")
        return
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        if not cfg.create_dirs:
            raise RuntimeError(f"remote folder is missing and REMOTE_CREATE_MISSING_DIRS=false: {folder_path}") from exc

    if parent_path:
        children_url = _graph_item_url(cfg, parent_path, ":/children")
    else:
        children_url = f"{_root_base(cfg)}/children"
    _http_json(
        children_url,
        method="POST",
        data=json.dumps({
            "name": name,
            "folder": {},
            "@microsoft.graph.conflictBehavior": "fail",
        }).encode(),
        headers={**_auth(token), "Content-Type": "application/json"},
    )


def ensure_remote_parent_dirs(cfg: PublishConfig, token: str, remote_relative_path: str) -> None:
    if cfg.project_root_name:
        if "/" in cfg.project_root_name or ".." in cfg.project_root_name.split("/"):
            raise RuntimeError("ONEDRIVE_PROJECT_ROOT_NAME must be a single folder name")
        _ensure_folder_at_path(cfg, token, cfg.project_root_name, "", cfg.project_root_name)
        current = cfg.project_root_name
    else:
        current = ""

    parent_rel = str(Path(remote_relative_path).parent).replace("\\", "/")
    if parent_rel in ("", "."):
        return

    for segment in parent_rel.split("/"):
        target = f"{current}/{segment}" if current else segment
        _ensure_folder_at_path(cfg, token, target, current, segment)
        current = target


def remote_file_exists(cfg: PublishConfig, token: str, remote_relative_path: str) -> bool:
    try:
        _http_json(_graph_item_url(cfg, _project_remote_path(cfg, remote_relative_path)), headers=_auth(token))
        return True
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        raise


def _upload_simple(cfg: PublishConfig, token: str, local_file: Path, remote_relative_path: str) -> None:
    url = _graph_item_url(cfg, _project_remote_path(cfg, remote_relative_path), ":/content")
    _http_put_raw(
        url,
        local_file.read_bytes(),
        {**_auth(token), "Content-Type": "application/octet-stream"},
    )


def _upload_large(cfg: PublishConfig, token: str, local_file: Path, remote_relative_path: str) -> None:
    session = _http_json(
        _graph_item_url(cfg, _project_remote_path(cfg, remote_relative_path), ":/createUploadSession"),
        method="POST",
        data=json.dumps({
            "item": {"@microsoft.graph.conflictBehavior": cfg.conflict_behavior}
        }).encode(),
        headers={**_auth(token), "Content-Type": "application/json"},
    )
    upload_url = session["uploadUrl"]
    size = local_file.stat().st_size
    offset = 0
    with local_file.open("rb") as fh:
        while offset < size:
            chunk = fh.read(CHUNK_SIZE)
            end = offset + len(chunk) - 1
            req = urllib.request.Request(upload_url, data=chunk, method="PUT")
            req.add_header("Content-Length", str(len(chunk)))
            req.add_header("Content-Range", f"bytes {offset}-{end}/{size}")
            with urllib.request.urlopen(req):
                pass
            offset += len(chunk)


def upload_file(cfg: PublishConfig, token: str, local_file: Path, remote_relative_path: str) -> str:
    if cfg.conflict_behavior == "skip" and remote_file_exists(cfg, token, remote_relative_path):
        return "skipped"

    if local_file.stat().st_size <= SIMPLE_UPLOAD_LIMIT:
        _upload_simple(cfg, token, local_file, remote_relative_path)
    else:
        _upload_large(cfg, token, local_file, remote_relative_path)
    return "uploaded"


def upload_file_with_retry(cfg: PublishConfig, token: str, local_file: Path, remote_relative_path: str) -> str:
    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return upload_file(cfg, token, local_file, remote_relative_path)
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code in TRANSIENT_HTTP_CODES and attempt < MAX_RETRIES:
                retry_after = 0
                try:
                    retry_after = int(exc.headers.get("Retry-After", 0) or 0)
                except (TypeError, ValueError):
                    pass
                wait = max(retry_after, BASE_BACKOFF_SECONDS ** attempt)
                print(f"upload retry {attempt}/{MAX_RETRIES - 1}: HTTP {exc.code}")
                time.sleep(wait)
                continue
            raise
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("upload retry loop exited unexpectedly")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish one governed diagnostic artifact to OneDrive without remote deletes.",
    )
    parser.add_argument("--local-file", required=True, help="Local diagnostic file under data/out/local/sessions/06_diagnoses/")
    parser.add_argument("--remote-relative-path", required=True, help="OneDrive project-relative destination under sessions/06_diagnoses/")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print the target without publishing")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        paths = validate_publish_paths(args.local_file, args.remote_relative_path)
        cfg = load_config(dry_run=args.dry_run)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if cfg.root_mode not in {"approot", "drive"}:
        print("error: ONEDRIVE_ROOT_MODE must be approot or drive", file=sys.stderr)
        return 2
    if cfg.conflict_behavior not in {"replace", "skip"}:
        print("error: REMOTE_CONFLICT_BEHAVIOR must be replace or skip", file=sys.stderr)
        return 2

    print(f"local_file          : {as_display_path(paths.local_file)}")
    print(f"local_relative_path : {paths.local_relative_path}")
    print(f"remote_relative_path: {paths.remote_relative_path}")
    print(f"root_mode           : {cfg.root_mode}")
    print(f"project             : {cfg.project_root_name}")
    print(f"create_dirs         : {cfg.create_dirs}")
    print(f"conflict            : {cfg.conflict_behavior}")
    print(f"dry_run             : {cfg.dry_run}")
    print("delete_remote       : false")
    print()
    print("mapping:")
    print(f"  Local    {LOCAL_DIAG_PREFIX}")
    print(f"  OneDrive {REMOTE_DIAG_PREFIX}")
    print()

    if cfg.dry_run:
        summary = {
            "dry_run": True,
            "status": "validated",
            "local_file": as_display_path(paths.local_file),
            "remote_relative_path": paths.remote_relative_path,
            "project_root": cfg.project_root_name,
            "delete_remote": False,
        }
        print(json.dumps(summary, indent=2))
        return 0

    if not cfg.client_id:
        print("error: AZURE_CLIENT_ID is required for live mode", file=sys.stderr)
        return 1
    if not cfg.refresh_token:
        print("error: MSA_REFRESH_TOKEN is required for live mode", file=sys.stderr)
        return 1

    print("Authenticating via MSA refresh token...")
    try:
        token = exchange_refresh_token(cfg)
        ensure_remote_parent_dirs(cfg, token, paths.remote_relative_path)
        result = upload_file_with_retry(cfg, token, paths.local_file, paths.remote_relative_path)
    except urllib.error.HTTPError as exc:
        error_type = "AUTH_ERROR" if exc.code == 401 else "PERMISSION_ERROR" if exc.code == 403 else "GRAPH_ERROR"
        print(f"error {error_type}: HTTP {exc.code}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    summary = {
        "dry_run": False,
        "status": result,
        "local_file": as_display_path(paths.local_file),
        "remote_relative_path": paths.remote_relative_path,
        "project_root": cfg.project_root_name,
        "delete_remote": False,
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
