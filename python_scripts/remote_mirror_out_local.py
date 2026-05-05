#!/usr/bin/env python3
"""Mirror data/out/local/ to OneDrive via Microsoft Graph API.

Auth: exchanges MSA_REFRESH_TOKEN for an access_token using AZURE_CLIENT_ID
and MSA_TENANT. Resolves the approot (or drive root per ONEDRIVE_ROOT_MODE),
creates ONEDRIVE_PROJECT_ROOT_NAME if missing, and replicates LOCAL_SYNC_SOURCE
(default: data/out/local/) recursively.

MVP exclusions — data/in/, data/tmp/, data/out/remote/ are naturally excluded
because the source root is data/out/local/ only.

Sync mode: local_primary — local canon is authoritative; remote is a replica.

Non-sensitive env vars (loadable from .env or shell environment):
  LOCAL_SYNC_SOURCE           source root (default: data/out/local/)
  AGENT_PRIMARY_READ_ROOT     informational
  AGENT_SESSION_ROOT          informational
  AGENT_DIRECT_CANON_WRITE    must be false; admission goes through admit_session_candidates.py
  AGENT_ADMISSION_SCRIPT      informational
  MSA_TENANT                  OAuth tenant — consumers | common | <tenant-id>
  ONEDRIVE_PROJECT_ROOT_NAME  subfolder under approot to sync into
  ONEDRIVE_ROOT_MODE          approot | drive  (default: approot)
  REMOTE_CREATE_MISSING_DIRS  true | false     (default: true)
  REMOTE_CONFLICT_BEHAVIOR    replace | skip   (default: replace)
  REMOTE_DELETE_EXTRANEOUS    true | false     (default: false)
  REMOTE_SYNC_MODE            local_primary    (informational)
  SYNC_DRY_RUN                true | false     (default: true)

Secrets (from environment — never store in plain-text .env in production):
  AZURE_CLIENT_ID             app registration client ID
  AZURE_TENANT_ID             Azure AD tenant ID (informational)
  MSA_REFRESH_TOKEN           offline_access refresh token
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

# Files up to this size use a single PUT; larger files use an upload session.
SIMPLE_UPLOAD_LIMIT = 4 * 1024 * 1024   # 4 MB
CHUNK_SIZE = 10 * 1024 * 1024            # 10 MB per chunk in upload sessions


# ---------------------------------------------------------------------------
# .env loader — stdlib only, no python-dotenv dependency
# ---------------------------------------------------------------------------

def _load_dotenv(path: Path) -> None:
    """Load key=value pairs from path into os.environ. Existing vars win."""
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


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class MirrorConfig:
    source: Path
    tenant: str
    client_id: str
    refresh_token: str
    project_root_name: str
    root_mode: str           # approot | drive
    create_dirs: bool
    conflict_behavior: str   # replace | skip
    delete_extraneous: bool
    dry_run: bool
    sync_mode: str           # local_primary
    verbose: bool = False


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


def load_config() -> MirrorConfig:
    _load_dotenv(REPO_ROOT / ".env")

    src_val = _env("LOCAL_SYNC_SOURCE") or None
    source = resolve_repo_path(src_val, DEFAULT_LOCAL_OUT_DIR)

    return MirrorConfig(
        source=source,
        tenant=_env("MSA_TENANT", "consumers"),
        client_id=_env("AZURE_CLIENT_ID"),
        refresh_token=_env("MSA_REFRESH_TOKEN"),
        project_root_name=_env("ONEDRIVE_PROJECT_ROOT_NAME", "tiddly-data-converter"),
        root_mode=_env("ONEDRIVE_ROOT_MODE", "approot"),
        create_dirs=_bool_env("REMOTE_CREATE_MISSING_DIRS", True),
        conflict_behavior=_env("REMOTE_CONFLICT_BEHAVIOR", "replace"),
        delete_extraneous=_bool_env("REMOTE_DELETE_EXTRANEOUS", False),
        dry_run=_bool_env("SYNC_DRY_RUN", True),
        sync_mode=_env("REMOTE_SYNC_MODE", "local_primary"),
    )


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@dataclass
class MirrorStats:
    uploaded: int = 0
    skipped: int = 0
    deleted: int = 0
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# HTTP helpers (urllib only)
# ---------------------------------------------------------------------------

def _http_json(
    url: str,
    *,
    method: str = "GET",
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> dict:
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def _http_put_raw(url: str, data: bytes, headers: dict[str, str]) -> None:
    req = urllib.request.Request(url, data=data, method="PUT")
    for k, v in headers.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req):
        pass


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def exchange_refresh_token(cfg: MirrorConfig) -> str:
    """Exchange MSA_REFRESH_TOKEN for a short-lived access_token."""
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
        raise RuntimeError(
            f"Token exchange failed: {result.get('error_description', result)}"
        )
    return result["access_token"]


# ---------------------------------------------------------------------------
# Drive helpers
# ---------------------------------------------------------------------------

def _root_base(cfg: MirrorConfig) -> str:
    if cfg.root_mode == "drive":
        return f"{GRAPH_BASE}/me/drive/root"
    return f"{GRAPH_BASE}/me/drive/special/approot"


def resolve_project_folder(cfg: MirrorConfig, token: str) -> str:
    """Ensure the project subfolder exists; return its Graph path prefix."""
    root = _root_base(cfg)
    if not cfg.project_root_name:
        return root

    folder_check_url = f"{root}:/{cfg.project_root_name}"
    try:
        _http_json(folder_check_url, headers=_auth(token))
    except urllib.error.HTTPError as exc:
        if exc.code == 404 and cfg.create_dirs:
            _http_json(
                f"{root}/children",
                method="POST",
                data=json.dumps({
                    "name": cfg.project_root_name,
                    "folder": {},
                    "@microsoft.graph.conflictBehavior": "replace",
                }).encode(),
                headers={**_auth(token), "Content-Type": "application/json"},
            )
        else:
            raise

    return f"{root}:/{cfg.project_root_name}"


def upload_file(remote_prefix: str, rel: str, path: Path, token: str) -> None:
    rel = rel.replace("\\", "/")
    size = path.stat().st_size

    if size <= SIMPLE_UPLOAD_LIMIT:
        _http_put_raw(
            f"{remote_prefix}/{rel}:/content",
            path.read_bytes(),
            {**_auth(token), "Content-Type": "application/octet-stream"},
        )
        return

    # Large file — upload session with chunked PUT
    session = _http_json(
        f"{remote_prefix}/{rel}:/createUploadSession",
        method="POST",
        data=json.dumps({
            "item": {"@microsoft.graph.conflictBehavior": "replace"}
        }).encode(),
        headers={**_auth(token), "Content-Type": "application/json"},
    )
    upload_url = session["uploadUrl"]
    offset = 0
    with path.open("rb") as fh:
        while offset < size:
            chunk = fh.read(CHUNK_SIZE)
            end = offset + len(chunk) - 1
            req = urllib.request.Request(upload_url, data=chunk, method="PUT")
            req.add_header("Content-Length", str(len(chunk)))
            req.add_header("Content-Range", f"bytes {offset}-{end}/{size}")
            with urllib.request.urlopen(req):
                pass
            offset += len(chunk)


def list_remote_files(remote_prefix: str, token: str, folder_rel: str = "") -> set[str]:
    """Recursively enumerate all file paths relative to remote_prefix."""
    result: set[str] = set()
    url = f"{remote_prefix}{'/' + folder_rel if folder_rel else ''}/children"
    try:
        page = _http_json(url, headers=_auth(token))
    except urllib.error.HTTPError:
        return result

    while True:
        for item in page.get("value", []):
            rel = f"{folder_rel}/{item['name']}" if folder_rel else item["name"]
            if "folder" in item:
                result |= list_remote_files(remote_prefix, token, rel)
            else:
                result.add(rel)
        next_link = page.get("@odata.nextLink")
        if not next_link:
            break
        page = _http_json(next_link, headers=_auth(token))

    return result


# ---------------------------------------------------------------------------
# Mirror orchestration
# ---------------------------------------------------------------------------

def collect_local_files(source: Path) -> list[tuple[str, Path]]:
    return [
        (str(p.relative_to(source)).replace("\\", "/"), p)
        for p in sorted(source.rglob("*"))
        if p.is_file()
    ]


def run_dry_run(cfg: MirrorConfig, local_files: list[tuple[str, Path]]) -> MirrorStats:
    stats = MirrorStats()
    for rel, path in local_files:
        size_kb = path.stat().st_size // 1024
        print(f"  [dry-run] upload  {rel}  ({size_kb} KB)")
        stats.uploaded += 1
    if cfg.delete_extraneous:
        print("  [dry-run] delete-extraneous: remote listing skipped in dry-run")
    return stats


def run_live(cfg: MirrorConfig, local_files: list[tuple[str, Path]]) -> MirrorStats:
    stats = MirrorStats()

    print("Authenticating via MSA refresh token...")
    token = exchange_refresh_token(cfg)

    print(f"Resolving project folder '{cfg.project_root_name}' under {cfg.root_mode}...")
    remote_prefix = resolve_project_folder(cfg, token)

    for rel, path in local_files:
        try:
            if cfg.conflict_behavior == "skip":
                try:
                    _http_json(f"{remote_prefix}/{rel}", headers=_auth(token))
                    if cfg.verbose:
                        print(f"  skip    {rel}")
                    stats.skipped += 1
                    continue
                except urllib.error.HTTPError as exc:
                    if exc.code != 404:
                        raise

            upload_file(remote_prefix, rel, path, token)
            if cfg.verbose:
                print(f"  upload  {rel}")
            stats.uploaded += 1
        except Exception as exc:  # noqa: BLE001
            msg = f"{rel}: {exc}"
            stats.errors.append(msg)
            print(f"  error   {msg}", file=sys.stderr)

    if cfg.delete_extraneous:
        print("Listing remote files for prune...")
        remote_files = list_remote_files(remote_prefix, token)
        local_rels = {rel for rel, _ in local_files}
        for rel in sorted(remote_files - local_rels):
            try:
                req = urllib.request.Request(
                    f"{remote_prefix}/{rel}", method="DELETE"
                )
                req.add_header("Authorization", f"Bearer {token}")
                with urllib.request.urlopen(req):
                    pass
                if cfg.verbose:
                    print(f"  delete  {rel}")
                stats.deleted += 1
            except Exception as exc:  # noqa: BLE001
                msg = f"delete {rel}: {exc}"
                stats.errors.append(msg)
                print(f"  error   {msg}", file=sys.stderr)

    return stats


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    cfg = load_config()

    print(f"source      : {as_display_path(cfg.source)}")
    print(f"root_mode   : {cfg.root_mode}")
    print(f"project     : {cfg.project_root_name}")
    print(f"conflict    : {cfg.conflict_behavior}")
    print(f"delete_extr.: {cfg.delete_extraneous}")
    print(f"dry_run     : {cfg.dry_run}")
    print(f"sync_mode   : {cfg.sync_mode}")
    print()

    if not cfg.source.exists():
        if cfg.dry_run:
            print("source does not exist — nothing to mirror (dry-run)")
            print(json.dumps({"dry_run": True, "uploaded": 0, "skipped": 0, "deleted": 0, "errors": []}, indent=2))
            return 0
        print(f"error: source does not exist: {cfg.source}", file=sys.stderr)
        return 1

    if not cfg.dry_run:
        if not cfg.client_id:
            print("error: AZURE_CLIENT_ID is required for live mode", file=sys.stderr)
            return 1
        if not cfg.refresh_token:
            print("error: MSA_REFRESH_TOKEN is required for live mode", file=sys.stderr)
            return 1

    local_files = collect_local_files(cfg.source)
    print(f"  {len(local_files)} file(s) in source\n")

    stats = run_dry_run(cfg, local_files) if cfg.dry_run else run_live(cfg, local_files)

    summary = {
        "source": as_display_path(cfg.source),
        "project_root": cfg.project_root_name,
        "dry_run": cfg.dry_run,
        "uploaded": stats.uploaded,
        "skipped": stats.skipped,
        "deleted": stats.deleted,
        "errors": stats.errors,
    }
    print()
    print(json.dumps(summary, indent=2))

    return 1 if stats.errors else 0


if __name__ == "__main__":
    sys.exit(main())
