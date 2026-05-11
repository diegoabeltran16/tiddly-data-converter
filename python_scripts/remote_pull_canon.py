#!/usr/bin/env python3
"""Download OneDrive AppFolder project root → data/out/local/.

Reverse direction of remote_mirror_out_local.py.
Downloads tiddly-data-converter/ from OneDrive AppFolder into LOCAL_SYNC_TARGET
(default: data/out/local/).

Path mapping:
  OneDrive: tiddly-data-converter/sessions/06_diagnoses/tema/file.md.json
  Local:    data/out/local/sessions/06_diagnoses/tema/file.md.json

Used as step 2 of the remote diagnostic workflow:
  1. Checkout repo
  2. Pull canon (this script)
  3. Read canon + sessions
  4. Generate diagnostic
  5. Validate + publish via remote_publish_diagnostic.py

Non-sensitive env vars:
  LOCAL_SYNC_TARGET           destination root (default: data/out/local/)
  MSA_TENANT                  consumers | common | <tenant-id>
  ONEDRIVE_PROJECT_ROOT_NAME  subfolder under approot to download from
  ONEDRIVE_ROOT_MODE          approot | drive (default: approot)
  PULL_CONFLICT_BEHAVIOR      replace | skip (default: skip — safe default)
  PULL_CREATE_MISSING_DIRS    true | false (default: true)
  PULL_DRY_RUN                true | false (default: true)

Secrets (runtime only — never store in .env):
  AZURE_CLIENT_ID
  AZURE_TENANT_ID
  MSA_REFRESH_TOKEN
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from path_governance import (  # noqa: E402
    DEFAULT_LOCAL_OUT_DIR,
    REPO_ROOT,
    as_display_path,
    resolve_repo_path,
)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
TOKEN_URL_TMPL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class PullConfig:
    target: Path
    tenant: str
    client_id: str
    refresh_token: str
    project_root_name: str
    root_mode: str
    create_dirs: bool
    conflict_behavior: str  # replace | skip
    dry_run: bool


@dataclass
class PullStats:
    downloaded: int = 0
    skipped: int = 0
    errors_by_type: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def add_error(self, error_type: str, message: str) -> None:
        self.errors_by_type[error_type] = self.errors_by_type.get(error_type, 0) + 1
        self.errors.append(message)


def _load_dotenv(path: Path) -> None:
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


def load_config() -> PullConfig:
    _load_dotenv(REPO_ROOT / ".env")
    target_val = _env("LOCAL_SYNC_TARGET") or None
    target = resolve_repo_path(target_val, DEFAULT_LOCAL_OUT_DIR)
    return PullConfig(
        target=target,
        tenant=_env("MSA_TENANT", "consumers"),
        client_id=_env("AZURE_CLIENT_ID"),
        refresh_token=_env("MSA_REFRESH_TOKEN"),
        project_root_name=_env("ONEDRIVE_PROJECT_ROOT_NAME", "tiddly-data-converter"),
        root_mode=_env("ONEDRIVE_ROOT_MODE", "approot"),
        create_dirs=_bool_env("PULL_CREATE_MISSING_DIRS", True),
        conflict_behavior=_env("PULL_CONFLICT_BEHAVIOR", "skip"),
        dry_run=_bool_env("PULL_DRY_RUN", True),
    )


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _http_json(url: str, *, headers: dict[str, str] | None = None) -> dict:
    req = urllib.request.Request(url)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def _http_get_bytes(url: str, headers: dict[str, str]) -> bytes:
    req = urllib.request.Request(url)
    for k, v in headers.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req) as resp:
        return resp.read()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def exchange_refresh_token(cfg: PullConfig) -> str:
    token_url = TOKEN_URL_TMPL.format(tenant=cfg.tenant)
    body = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "client_id": cfg.client_id,
        "refresh_token": cfg.refresh_token,
        "scope": "Files.ReadWrite.AppFolder offline_access",
    }).encode()
    req = urllib.request.Request(token_url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
    if "access_token" not in result:
        raise RuntimeError(
            f"Token exchange failed: {result.get('error_description', result)}"
        )
    return result["access_token"]


# ---------------------------------------------------------------------------
# Graph helpers
# ---------------------------------------------------------------------------

def _root_base(cfg: PullConfig) -> str:
    if cfg.root_mode == "drive":
        return f"{GRAPH_BASE}/me/drive/root"
    return f"{GRAPH_BASE}/me/drive/special/approot"


def _encode_segment(s: str) -> str:
    return quote(s, safe="")


def _encode_rel_path(rel: str) -> str:
    return "/".join(_encode_segment(p) for p in rel.replace("\\", "/").split("/"))


def list_remote_files(
    root_base: str,
    project_root: str,
    token: str,
    folder_rel: str = "",
) -> list[str]:
    """Recursively list all file paths relative to the project root."""
    result: list[str] = []

    if folder_rel:
        encoded_folder = _encode_rel_path(folder_rel)
        url = f"{root_base}:/{_encode_segment(project_root)}/{encoded_folder}:/children"
    else:
        url = f"{root_base}:/{_encode_segment(project_root)}:/children"

    try:
        page = _http_json(url, headers=_auth(token))
    except urllib.error.HTTPError:
        return result

    while True:
        for item in page.get("value", []):
            rel = f"{folder_rel}/{item['name']}" if folder_rel else item["name"]
            if "folder" in item:
                result.extend(list_remote_files(root_base, project_root, token, rel))
            else:
                result.append(rel)
        next_link = page.get("@odata.nextLink")
        if not next_link:
            break
        page = _http_json(next_link, headers=_auth(token))

    return result


def download_file(
    root_base: str,
    project_root: str,
    rel: str,
    target: Path,
    token: str,
    create_dirs: bool,
) -> None:
    """Download one file from OneDrive to target/rel."""
    encoded_rel = _encode_rel_path(rel)
    url = f"{root_base}:/{_encode_segment(project_root)}/{encoded_rel}:/content"
    data = _http_get_bytes(url, _auth(token))
    local_path = target / rel
    if create_dirs:
        local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_bytes(data)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    cfg = load_config()

    print(f"target      : {as_display_path(cfg.target)}")
    print(f"root_mode   : {cfg.root_mode}")
    print(f"project     : {cfg.project_root_name}")
    print(f"conflict    : {cfg.conflict_behavior}")
    print(f"dry_run     : {cfg.dry_run}")
    print()

    if not cfg.dry_run:
        if not cfg.client_id:
            print("error: AZURE_CLIENT_ID is required for live mode", file=sys.stderr)
            return 1
        if not cfg.refresh_token:
            print("error: MSA_REFRESH_TOKEN is required for live mode", file=sys.stderr)
            return 1

    stats = PullStats()

    if cfg.dry_run:
        print("[dry-run] pull from OneDrive — skipping authentication")
        summary = {
            "target": as_display_path(cfg.target),
            "project_root": cfg.project_root_name,
            "dry_run": True,
            "remote_file_count": 0,
            "downloaded": 0,
            "skipped": 0,
            "errors_by_type": {},
            "errors": [],
        }
        print(json.dumps(summary, indent=2))
        return 0

    print("Authenticating via MSA refresh token...")
    try:
        token = exchange_refresh_token(cfg)
    except Exception as exc:
        stats.add_error("AUTH_ERROR", str(exc))
        print(f"  error AUTH_ERROR: {exc}", file=sys.stderr)
        print(json.dumps({"dry_run": False, "downloaded": 0, "errors": stats.errors}, indent=2))
        return 1

    root_base = _root_base(cfg)
    print(f"Listing remote files under '{cfg.project_root_name}'...")
    try:
        remote_files = list_remote_files(root_base, cfg.project_root_name, token)
    except Exception as exc:
        stats.add_error("LIST_ERROR", str(exc))
        print(f"  error LIST_ERROR: {exc}", file=sys.stderr)
        print(json.dumps({"dry_run": False, "downloaded": 0, "errors": stats.errors}, indent=2))
        return 1

    print(f"  {len(remote_files)} file(s) found on OneDrive\n")

    for rel in sorted(remote_files):
        local_path = cfg.target / rel
        if cfg.conflict_behavior == "skip" and local_path.exists():
            print(f"  skip    {rel}")
            stats.skipped += 1
            continue
        try:
            download_file(root_base, cfg.project_root_name, rel, cfg.target, token, cfg.create_dirs)
            print(f"  download  {rel}")
            stats.downloaded += 1
        except urllib.error.HTTPError as exc:
            error_type = "AUTH_ERROR" if exc.code in (401, 403) else "DOWNLOAD_ERROR"
            msg = f"{rel}: HTTP {exc.code}"
            stats.add_error(error_type, msg)
            print(f"  error {error_type}: {msg}", file=sys.stderr)
        except Exception as exc:
            msg = f"{rel}: {exc}"
            stats.add_error("DOWNLOAD_ERROR", msg)
            print(f"  error DOWNLOAD_ERROR: {msg}", file=sys.stderr)

    summary = {
        "target": as_display_path(cfg.target),
        "project_root": cfg.project_root_name,
        "dry_run": cfg.dry_run,
        "remote_file_count": len(remote_files),
        "downloaded": stats.downloaded,
        "skipped": stats.skipped,
        "errors_by_type": stats.errors_by_type,
        "errors": stats.errors,
    }
    print()
    print(json.dumps(summary, indent=2))
    return 1 if stats.errors else 0


if __name__ == "__main__":
    sys.exit(main())
