#!/usr/bin/env python3
"""Pull session candidates from the OneDrive remote outbox to local staging.

Architecture (bilateral, NOT symmetric):
  LOCAL data/out/local/  →  push mirror  →  OneDrive approot:/tiddly-data-converter/
  OneDrive _remote_outbox/sessions/  →  pull (this script)  →  data/tmp/remote_inbox/
  data/tmp/remote_inbox/  →  admission gate  →  data/out/local/sessions/

Rules:
- Only files under _remote_outbox/sessions/ on OneDrive are pulled.
- Files are staged in data/tmp/remote_inbox/ — never written directly to canon.
- The allowlist prevents pulling tiddlers_*.jsonl or any non-session artifact.
- AGENT_DIRECT_CANON_WRITE must remain false.
- Secrets (AZURE_CLIENT_ID, MSA_REFRESH_TOKEN) are runtime only — never .env.

Env vars (non-sensitive, loadable from .env):
  MSA_TENANT                  consumers | common | <tenant-id>
  ONEDRIVE_PROJECT_ROOT_NAME  subfolder under approot (default: tiddly-data-converter)
  ONEDRIVE_ROOT_MODE          approot | drive (default: approot)
  REMOTE_INBOX_DIR            local staging dir (default: data/tmp/remote_inbox)
  SYNC_DRY_RUN                true | false (default: true)

Secrets (runtime only):
  AZURE_CLIENT_ID
  MSA_REFRESH_TOKEN
"""

from __future__ import annotations

import json
import os
import re
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
    REPO_ROOT,
    as_display_path,
    resolve_repo_path,
)
from diagnostic_governance import (  # noqa: E402
    is_diagnostic_artifact,
    SESSION_ARTIFACT_RE as _SESSION_ARTIFACT_RE,
)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
TOKEN_URL_TMPL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"

# Only pull from this remote prefix (relative to the project root folder).
REMOTE_OUTBOX_PREFIX = "_remote_outbox/sessions"

# Default local staging directory for pulled candidates.
DEFAULT_REMOTE_INBOX = REPO_ROOT / "data" / "tmp" / "remote_inbox"

# Allowlist: session artifacts (mXX-sNN-<slug>.md.json).
# Diagnostic artifacts are handled via is_diagnostic_artifact() from diagnostic_governance.
_ALLOWED_FILENAME_RE = _SESSION_ARTIFACT_RE

# Denylist: these filename patterns are always rejected regardless of path.
_CANON_SHARD_RE = re.compile(r"^tiddlers_\d+\.jsonl$")

# Protected local paths — pulled files must never overwrite these.
_PROTECTED_LOCAL_PREFIXES: tuple[str, ...] = (
    "tiddlers_",
    "enriched",
    "ai",
    "microsoft_copilot",
    "reverse_html",
    "audit",
)


# ---------------------------------------------------------------------------
# .env loader
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class PullConfig:
    tenant: str
    client_id: str
    refresh_token: str
    project_root_name: str
    root_mode: str
    inbox_dir: Path
    dry_run: bool


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
    inbox_val = _env("REMOTE_INBOX_DIR") or None
    inbox_dir = resolve_repo_path(inbox_val, DEFAULT_REMOTE_INBOX)
    return PullConfig(
        tenant=_env("MSA_TENANT", "consumers"),
        client_id=_env("AZURE_CLIENT_ID"),
        refresh_token=_env("MSA_REFRESH_TOKEN"),
        project_root_name=_env("ONEDRIVE_PROJECT_ROOT_NAME", "tiddly-data-converter"),
        root_mode=_env("ONEDRIVE_ROOT_MODE", "approot"),
        inbox_dir=inbox_dir,
        dry_run=_bool_env("SYNC_DRY_RUN", True),
    )


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@dataclass
class PullStats:
    listed: int = 0
    pulled: int = 0
    skipped_allowlist: int = 0
    skipped_denylist: int = 0
    skipped_already_present: int = 0
    errors: list[str] = field(default_factory=list)
    errors_by_type: dict[str, int] = field(default_factory=dict)

    def add_error(self, error_type: str, message: str) -> None:
        self.errors_by_type[error_type] = self.errors_by_type.get(error_type, 0) + 1
        self.errors.append(message)


# ---------------------------------------------------------------------------
# Graph path encoding (shared logic)
# ---------------------------------------------------------------------------

def _encode_segment(segment: str) -> str:
    return quote(segment, safe="")


def _encode_rel(rel: str) -> str:
    return "/".join(_encode_segment(s) for s in rel.replace("\\", "/").split("/"))


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

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
# Allowlist / denylist checks
# ---------------------------------------------------------------------------

def _is_allowed_outbox_file(filename: str) -> tuple[bool, str]:
    """Return (allowed, reason) for a candidate remote filename.

    Accepts two artifact families:
    - session_artifact:    mXX-sNN-<slug>.md.json
    - diagnostic_artifact: diagnostico-tematico-NN-slug.md.json,
                           mXX-micro-ciclo-sNNN-sNNN-diagnostico.md.json,
                           mXX-meso-ciclo-sNNN-sNNN-diagnostico.md.json,
                           diagnostico-proyecto-NN-slug.md.json,
                           mXX-diagnostico-proyecto-slug.md.json,
                           diagnostico-sesion-sNNN-slug.md.json

    Canon shards, env files, and unknown artifacts are rejected.
    """
    # Reject canon shards unconditionally
    if _CANON_SHARD_RE.match(filename):
        return False, "denylist_canon_shard"

    # Reject .env and credential files
    if filename == ".env" or filename.startswith(".env."):
        return False, "denylist_credentials"

    # Reject Windows ADS files
    if ":" in filename:
        return False, "denylist_ads_zone_identifier"

    # Session artifact (mXX-sNN-<slug>.md.json)
    if _ALLOWED_FILENAME_RE.match(filename):
        return True, ""

    # Diagnostic artifact (non-session, governed by diagnostic_governance)
    if is_diagnostic_artifact(filename):
        return True, ""

    return False, "allowlist_not_session_or_diagnostic_artifact"


def _is_protected_local_path(local_path: Path, inbox_dir: Path) -> bool:
    """Return True if the file would overwrite a protected local area."""
    try:
        rel = str(local_path.relative_to(inbox_dir)).replace("\\", "/")
    except ValueError:
        return True  # outside inbox — reject
    for prefix in _PROTECTED_LOCAL_PREFIXES:
        if rel.startswith(prefix):
            return True
    return False


# ---------------------------------------------------------------------------
# Remote listing
# ---------------------------------------------------------------------------

def _list_outbox_files(root_base: str, project_name: str, token: str) -> list[dict]:
    """List files under _remote_outbox/sessions/ on OneDrive.

    Returns a list of Graph item dicts (name, id, @microsoft.graph.downloadUrl, size).
    """
    encoded_project = _encode_segment(project_name)
    encoded_outbox = _encode_rel(REMOTE_OUTBOX_PREFIX)
    url = f"{root_base}:/{encoded_project}/{encoded_outbox}:/children"
    try:
        page = _http_json(url, headers=_auth(token))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return []  # outbox does not exist yet — not an error
        raise

    items: list[dict] = []
    while True:
        for item in page.get("value", []):
            if "folder" not in item:  # files only
                items.append(item)
        next_link = page.get("@odata.nextLink")
        if not next_link:
            break
        page = _http_json(next_link, headers=_auth(token))
    return items


def _root_base(cfg: PullConfig) -> str:
    if cfg.root_mode == "drive":
        return f"{GRAPH_BASE}/me/drive/root"
    return f"{GRAPH_BASE}/me/drive/special/approot"


# ---------------------------------------------------------------------------
# Pull orchestration
# ---------------------------------------------------------------------------

def run_dry_run(cfg: PullConfig, items: list[dict], stats: PullStats) -> None:
    for item in items:
        name = item.get("name", "")
        size = item.get("size", 0)
        allowed, reason = _is_allowed_outbox_file(name)
        if not allowed:
            print(f"  [dry-run] skip   {name}  reason={reason}")
            if reason.startswith("denylist"):
                stats.skipped_denylist += 1
            else:
                stats.skipped_allowlist += 1
            continue
        dest = cfg.inbox_dir / name
        if dest.exists():
            print(f"  [dry-run] exists {name}  ({size} B) — already in inbox")
            stats.skipped_already_present += 1
        else:
            print(f"  [dry-run] pull   {name}  ({size} B) → {as_display_path(cfg.inbox_dir)}/")
            stats.pulled += 1


def run_live(cfg: PullConfig, items: list[dict], token: str, stats: PullStats) -> None:
    cfg.inbox_dir.mkdir(parents=True, exist_ok=True)
    for item in items:
        name = item.get("name", "")
        size = item.get("size", 0)
        allowed, reason = _is_allowed_outbox_file(name)
        if not allowed:
            print(f"  skip     {name}  reason={reason}")
            if reason.startswith("denylist"):
                stats.skipped_denylist += 1
            else:
                stats.skipped_allowlist += 1
            continue

        dest = cfg.inbox_dir / name
        if _is_protected_local_path(dest, cfg.inbox_dir):
            print(f"  reject   {name}  reason=protected_local_path")
            stats.add_error("LOCAL_SAFETY_ERROR", f"{name}: would write outside allowed inbox area")
            continue

        if dest.exists():
            print(f"  exists   {name}  ({size} B) — skipping (already staged)")
            stats.skipped_already_present += 1
            continue

        # Prefer direct download URL if provided by Graph listing
        download_url = item.get("@microsoft.graph.downloadUrl")
        if not download_url:
            # Construct from item id
            item_id = item.get("id", "")
            download_url = f"{GRAPH_BASE}/me/drive/items/{_encode_segment(item_id)}/content"

        try:
            content = _http_get_bytes(download_url, _auth(token))
            dest.write_bytes(content)
            print(f"  pulled   {name}  ({len(content)} B)")
            stats.pulled += 1
        except urllib.error.HTTPError as exc:
            error_type = "AUTH_ERROR" if exc.code in (401, 403) else "TRANSIENT_GRAPH_ERROR"
            stats.add_error(error_type, f"{name}: HTTP {exc.code}")
            print(f"  error {error_type}: {name}: HTTP {exc.code}", file=sys.stderr)
        except Exception as exc:
            stats.add_error("TRANSIENT_GRAPH_ERROR", f"{name}: {exc}")
            print(f"  error   {name}: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    cfg = load_config()

    print(f"remote_outbox : {REMOTE_OUTBOX_PREFIX}")
    print(f"project       : {cfg.project_root_name}")
    print(f"root_mode     : {cfg.root_mode}")
    print(f"inbox_dir     : {as_display_path(cfg.inbox_dir)}")
    print(f"dry_run       : {cfg.dry_run}")
    print()
    print("NOTE: This pull is NOT symmetric. It only fetches from _remote_outbox/sessions/")
    print("      and stages files in data/tmp/remote_inbox/ — canon is never overwritten.")
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
        # In dry-run we can't list remote files without auth; show policy and exit.
        print("  [dry-run] Would list files under:")
        print(f"            OneDrive approot:/{cfg.project_root_name}/{REMOTE_OUTBOX_PREFIX}/")
        print(f"  [dry-run] Allowed session artifacts:    mXX-sNN-<slug>.md.json")
        print(f"  [dry-run] Allowed diagnostic artifacts: diagnostico-tematico-NN-slug.md.json")
        print(f"  [dry-run]                               mXX-micro-ciclo-sNNN-sNNN-diagnostico.md.json")
        print(f"  [dry-run]                               mXX-meso-ciclo-sNNN-sNNN-diagnostico.md.json")
        print(f"  [dry-run]                               diagnostico-proyecto-NN-slug.md.json")
        print(f"  [dry-run]                               mXX-diagnostico-proyecto-slug.md.json")
        print(f"  [dry-run]                               diagnostico-sesion-sNNN-slug.md.json")
        print(f"  [dry-run] Staging target: {as_display_path(cfg.inbox_dir)}/")
        print(f"  [dry-run] Admission gate: AGENT_ADMISSION_SCRIPT (session) / manual placement (diagnostic)")
        print(f"  [dry-run] Canon overwrite: NEVER (AGENT_DIRECT_CANON_WRITE=false)")
        stats.listed = 0
        summary = {
            "dry_run": True,
            "remote_outbox": REMOTE_OUTBOX_PREFIX,
            "inbox_dir": as_display_path(cfg.inbox_dir),
            "listed": 0,
            "pulled": 0,
            "skipped_allowlist": 0,
            "skipped_denylist": 0,
            "skipped_already_present": 0,
            "errors_by_type": {},
            "errors": [],
        }
        print()
        print(json.dumps(summary, indent=2))
        return 0

    print("Authenticating via MSA refresh token...")
    try:
        token = exchange_refresh_token(cfg)
    except Exception as exc:
        stats.add_error("AUTH_ERROR", f"auth failed: {exc}")
        print(f"  error AUTH_ERROR: {exc}", file=sys.stderr)
        print(json.dumps({"status": "fail", "errors_by_type": stats.errors_by_type}, indent=2))
        return 1

    root_base = _root_base(cfg)
    print(f"Listing {REMOTE_OUTBOX_PREFIX}...")
    try:
        items = _list_outbox_files(root_base, cfg.project_root_name, token)
    except urllib.error.HTTPError as exc:
        error_type = "AUTH_ERROR" if exc.code in (401, 403) else "TRANSIENT_GRAPH_ERROR"
        stats.add_error(error_type, f"listing failed: HTTP {exc.code}")
        print(f"  error {error_type}: listing failed: HTTP {exc.code}", file=sys.stderr)
        print(json.dumps({"status": "fail", "errors_by_type": stats.errors_by_type}, indent=2))
        return 1
    except Exception as exc:
        stats.add_error("TRANSIENT_GRAPH_ERROR", f"listing failed: {exc}")
        print(f"  error: listing failed: {exc}", file=sys.stderr)
        print(json.dumps({"status": "fail", "errors_by_type": stats.errors_by_type}, indent=2))
        return 1

    stats.listed = len(items)
    print(f"  {stats.listed} file(s) found in remote outbox\n")

    run_live(cfg, items, token, stats)

    summary = {
        "remote_outbox": REMOTE_OUTBOX_PREFIX,
        "inbox_dir": as_display_path(cfg.inbox_dir),
        "dry_run": cfg.dry_run,
        "listed": stats.listed,
        "pulled": stats.pulled,
        "skipped_allowlist": stats.skipped_allowlist,
        "skipped_denylist": stats.skipped_denylist,
        "skipped_already_present": stats.skipped_already_present,
        "errors_by_type": stats.errors_by_type,
        "errors": stats.errors,
    }
    print()
    print(json.dumps(summary, indent=2))

    return 1 if stats.errors else 0


if __name__ == "__main__":
    sys.exit(main())
