#!/usr/bin/env python3
"""Shared local/remote paths for data/in, data/out, and local reverse outputs."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def repo_path(relative_path: str) -> Path:
    return (REPO_ROOT / relative_path).resolve()


# ── Workspace/data root resolution (S0187 Unit D) ────────────────────────────
#
# `data/in/` (bootstrap templates + committed workspace-in-git material) stays
# pinned to the repository checkout: its classification is unresolved (see
# D04/D-H2 evidence under
# data/out/local/audit/s0187_impacto_unidad_d_diagnosticar_preparar_storage/).
#
# `data/refs/` (external reference corpus) was repo-pinned through D20, but
# D22 reclassified it as WORKSPACE REFERENCE MATERIAL, not repository-side
# input -- see D22 evidence. It now follows WORKSPACE_ROOT like out/ and tmp/
# (REFS != CANON, REFS != CORE RUNTIME STATE). When WORKSPACE_ROOT falls back
# to its default (REPO_DATA_DIR, no override/config), DEFAULT_REFS_DIR
# resolves to REPO_DATA_DIR/"refs" automatically -- the exact same location
# it always used -- so this is a strict generalization, not a second
# configuration surface.
#
# `out/` (canon, sessions, audit, inventory, derived layers) and `tmp/`
# (transient working state) are the portable unit: they may resolve to a
# different physical location without changing workspace identity or Canon
# authority. WORKSPACE_ROOT governs only that portable unit.
#
# Resolution order (highest precedence first):
#   1. TDC_WORKSPACE_ROOT environment variable -- ephemeral runtime override,
#      never persisted, intended for future short-lived/agent runtimes.
#   2. workspace_storage.json persisted config -- durable, non-secret, user
#      chosen location. Lives with the software checkout so it can be found
#      regardless of where the data root currently is.
#   3. Default: REPO_ROOT/data -- today's behavior, unchanged.
#
# The config file holds only a filesystem locator and descriptive fields.
# It must never hold credentials/tokens -- see D5 boundary
# (CONFIGURATION != CREDENTIALS != AUTHORITY).
REPO_DATA_DIR = repo_path("data")
WORKSPACE_ROOT_ENV_VAR = "TDC_WORKSPACE_ROOT"
WORKSPACE_CONFIG_FILE = REPO_ROOT / ".tdc" / "workspace_storage.json"
_NON_SECRET_CONFIG_KEYS = {"workspace", "storage_type", "workspace_root", "updated_at"}


def load_workspace_storage_config() -> dict:
    """Read the persisted, non-secret workspace/storage config (best-effort)."""
    if not WORKSPACE_CONFIG_FILE.exists():
        return {}
    try:
        with WORKSPACE_CONFIG_FILE.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def save_workspace_storage_config(workspace_root: Path) -> Path:
    """Persist the chosen workspace root. Non-secret fields only (D5 boundary)."""
    payload = {
        "workspace": "tdc-development",
        "storage_type": "filesystem",
        "workspace_root": str(Path(workspace_root).expanduser().resolve()),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    assert set(payload) <= _NON_SECRET_CONFIG_KEYS
    WORKSPACE_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with WORKSPACE_CONFIG_FILE.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return WORKSPACE_CONFIG_FILE


def resolve_workspace_root() -> tuple[Path, str]:
    """Resolve the active root for out/ and tmp/, and how it was decided."""
    env_value = os.environ.get(WORKSPACE_ROOT_ENV_VAR)
    if env_value:
        return Path(env_value).expanduser().resolve(), "runtime_override_env"
    config_value = load_workspace_storage_config().get("workspace_root")
    if config_value:
        return Path(config_value).expanduser().resolve(), "persisted_config"
    return REPO_DATA_DIR, "default_repo_relative"


WORKSPACE_ROOT, WORKSPACE_ROOT_SOURCE = resolve_workspace_root()


class WorkspaceRootUnavailableError(RuntimeError):
    """Raised when the resolved workspace root is not reachable on disk.

    EXPLICIT CONFIGURATION FAILURE != PERMISSION TO FALL BACK: a caller must
    never catch this to silently retry against REPO_DATA_DIR or any other
    default -- doing so would produce split-brain storage (some writes
    landing at the configured root when it happens to be mounted, others
    silently landing elsewhere when it is not)."""


def require_reachable_workspace_root(root: Path | None = None) -> Path:
    """Fail closed if the (resolved or given) workspace root is not a real,
    reachable directory -- e.g. an external drive that is unmounted."""
    target = root if root is not None else WORKSPACE_ROOT
    if not target.is_dir():
        raise WorkspaceRootUnavailableError(
            f"Configured workspace root is not reachable: {target}. "
            "Refusing to silently fall back to the default location."
        )
    return target


def current_workspace_status() -> dict:
    """Human-readable snapshot for the terminal UX (D6) -- no secrets."""
    return {
        "workspace": "tdc-development",
        "storage_type": "filesystem",
        "workspace_root": str(WORKSPACE_ROOT),
        "workspace_root_source": WORKSPACE_ROOT_SOURCE,
        "is_default_location": WORKSPACE_ROOT == REPO_DATA_DIR,
        "workspace_root_exists": WORKSPACE_ROOT.exists(),
        "fixed_repo_data_dir": str(REPO_DATA_DIR),
        "config_file": str(WORKSPACE_CONFIG_FILE),
    }


DEFAULT_INPUT_HTML = REPO_DATA_DIR / "in" / "tiddly-data-converter (Saved).html"
DEFAULT_REFS_DIR = WORKSPACE_ROOT / "refs"
DEFAULT_OUT_DIR = WORKSPACE_ROOT / "out"
DEFAULT_LOCAL_OUT_DIR = DEFAULT_OUT_DIR / "local"
DEFAULT_REMOTE_OUT_DIR = DEFAULT_OUT_DIR / "remote"
DEFAULT_TMP_DIR = WORKSPACE_ROOT / "tmp"
# S0187 D20: the ACTIVE/CURRENT tmp authority for this deployment is
# DEFAULT_TMP_DIR above (TMP_OWNERSHIP = WORKSPACE_SCOPED, adopted for the
# current local deployment -- not a universal claim that a future runtime
# must materialize tmp physically beside durable state). HISTORICAL_TMP_ROOT
# names the pre-binding, repo-pinned tmp surface explicitly and permanently
# -- it exists so historical material can be inspected on purpose, and must
# never be used as a silent fallback when DEFAULT_TMP_DIR is unavailable.
HISTORICAL_TMP_ROOT = REPO_DATA_DIR / "tmp"
DEFAULT_CANON_DIR = DEFAULT_LOCAL_OUT_DIR
DEFAULT_ENRICHED_DIR = DEFAULT_LOCAL_OUT_DIR / "enriched"
DEFAULT_AI_DIR = DEFAULT_LOCAL_OUT_DIR / "ai"
DEFAULT_AI_REPORTS_DIR = DEFAULT_AI_DIR / "reports"
DEFAULT_AUDIT_DIR = DEFAULT_LOCAL_OUT_DIR / "audit"
DEFAULT_REVERSE_HTML_DIR = DEFAULT_LOCAL_OUT_DIR / "reverse_html"
DEFAULT_REVERSE_HTML = DEFAULT_REVERSE_HTML_DIR / "tiddly-data-converter.derived.html"
DEFAULT_REVERSE_REPORT = DEFAULT_REVERSE_HTML_DIR / "reverse-report.json"
DEFAULT_EXPORT_DIR = DEFAULT_LOCAL_OUT_DIR / "export"
DEFAULT_MICROSOFT_COPILOT_DIR = DEFAULT_LOCAL_OUT_DIR / "microsoft_copilot"
DEFAULT_COPILOT_AGENT_DIR = DEFAULT_MICROSOFT_COPILOT_DIR / "copilot_agent"
DEFAULT_PROPOSALS_FILE = DEFAULT_LOCAL_OUT_DIR / "proposals.jsonl"
DEFAULT_SESSIONS_DIR = DEFAULT_LOCAL_OUT_DIR / "sessions"
CANON_SHARD_FILENAME_RE = re.compile(r"^tiddlers_(\d+)\.jsonl$")


def resolve_repo_path(path_value: str | None, default_path: Path) -> Path:
    if not path_value:
        return default_path
    candidate = Path(path_value)
    if candidate.is_absolute():
        return candidate.resolve()
    return (REPO_ROOT / candidate).resolve()


def as_display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


class NotWorkspaceRelativeError(ValueError):
    """Raised by as_workspace_locator() for a path outside WORKSPACE_ROOT.

    WORKSPACE_RELATIVE_LOCATOR MUST BE RELATIVE BY CONSTRUCTION (S0187
    D23-A): a silent absolute-path fallback here would let a declarative
    contract (registry/bundle) accidentally store a physical mount path
    (e.g. "/mnt/toshiba_linux/...") -- reproducing the exact coupling this
    helper exists to prevent. Fail closed instead."""


def as_workspace_locator(path: Path) -> str:
    """Return the WORKSPACE_ROOT-relative locator for a governed path.

    DECLARED LOCATOR != RESOLVED PHYSICAL PATH (S0187 D23-A): registry/bundle
    files declare *where something lives inside the workspace* (e.g.
    "out/local"), independent of where WORKSPACE_ROOT is currently mounted.
    Use this for anything compared against a stored locator; use the
    governed DEFAULT_* Path objects directly for physical existence checks.

    Raises NotWorkspaceRelativeError for any path not under WORKSPACE_ROOT --
    strict by design, unlike as_display_path()'s absolute-path fallback.
    """
    try:
        return str(path.relative_to(WORKSPACE_ROOT))
    except ValueError:
        raise NotWorkspaceRelativeError(
            f"{path} is not under WORKSPACE_ROOT ({WORKSPACE_ROOT}); "
            "as_workspace_locator() only accepts workspace-owned paths."
        ) from None


# ── Logical locator <-> physical workspace path (S0187 P7-C, D1) ─────────────
#
# The vocabulary stored in Canon (source_path/provenance_ref/source_position),
# in source_fields_contract.ALLOWED_SOURCE_PATH_PREFIXES and in Rust/Go
# contracts is "data/out/local/<tail>". That string is a LOGICAL LOCATOR: the
# stable name of an object inside the workspace's out/local surface,
# independent of where the workspace is mounted. The physical location of the
# same object is DEFAULT_LOCAL_OUT_DIR / <tail>.
#
#   LOGICAL_LOCATOR != PHYSICAL_PATH     REPO_ROOT != WORKSPACE_ROOT
#   DISPLAY_PATH != PERSISTED_LOCATOR    (as_display_path is presentation only)
#
# Note the namespace differs from as_workspace_locator()'s "out/local/...": the
# stored vocabulary keeps the historical "data/" head; it is NOT migrated.
LOGICAL_LOCATOR_NAMESPACE = "data/out/local"


class LogicalLocatorError(ValueError):
    """A value is not a valid locator in the stored namespace, or a physical
    path is not owned by the workspace's out/local surface. Fail closed."""


def _locator_tail(locator: str) -> tuple[str, ...]:
    if not isinstance(locator, str) or not locator:
        raise LogicalLocatorError(f"logical locator must be a non-empty string: {locator!r}")
    value = locator.replace("\\", "/")
    if value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        raise LogicalLocatorError(f"logical locator must not be an absolute path: {locator!r}")
    if value.endswith("/"):
        value = value[:-1]
    parts = value.split("/")
    if ".." in parts:
        raise LogicalLocatorError(f"logical locator must not contain '..': {locator!r}")
    namespace = LOGICAL_LOCATOR_NAMESPACE.split("/")
    if parts[: len(namespace)] != namespace:
        raise LogicalLocatorError(
            f"{locator!r} is outside the logical namespace {LOGICAL_LOCATOR_NAMESPACE!r}"
        )
    tail = tuple(parts[len(namespace):])
    if any(segment in ("", ".") for segment in tail):
        raise LogicalLocatorError(f"logical locator has empty or '.' segments: {locator!r}")
    return tail


def resolve_logical_locator(locator: str) -> Path:
    """Physical path (under DEFAULT_LOCAL_OUT_DIR) of a stored logical locator.

    Deterministic and layout-independent: the result only depends on the
    governed workspace root. Raises LogicalLocatorError for locators outside
    "data/out/local", with '..' components, or that escape the workspace
    (including through symlinks)."""
    physical = DEFAULT_LOCAL_OUT_DIR.joinpath(*_locator_tail(locator))
    base = os.path.realpath(DEFAULT_LOCAL_OUT_DIR)
    real = os.path.realpath(physical)
    if real != base and not real.startswith(base + os.sep):
        raise LogicalLocatorError(f"{locator!r} resolves outside the workspace out/local surface")
    return physical


def as_logical_locator(path: Path | str) -> str:
    """Stored logical locator ("data/out/local/<tail>") of a physical path.

    Only absolute paths under DEFAULT_LOCAL_OUT_DIR are accepted: repo-owned
    paths, relative paths, '..' components and other workspace surfaces raise
    LogicalLocatorError (never an absolute-path fallback)."""
    candidate = Path(path)
    if not candidate.is_absolute():
        raise LogicalLocatorError(f"a physical path must be absolute: {str(path)!r}")
    if ".." in candidate.parts:
        raise LogicalLocatorError(f"physical path must not contain '..': {str(path)!r}")
    try:
        tail = candidate.relative_to(DEFAULT_LOCAL_OUT_DIR)
    except ValueError:
        raise LogicalLocatorError(
            f"{str(path)!r} is not under the workspace out/local surface ({DEFAULT_LOCAL_OUT_DIR})"
        ) from None
    return "/".join((LOGICAL_LOCATOR_NAMESPACE, *tail.parts))


def canonical_logical_locator(value: Path | str) -> str:
    """Canonical logical locator of either representation, for comparison.

    A stored locator string is validated and normalised; an absolute physical
    path under the current workspace is converted. Two records that refer to
    the same workspace object compare equal regardless of which representation
    they persisted (S0187 D5, comparison only -- nothing is rewritten)."""
    if isinstance(value, Path) or (isinstance(value, str) and value.startswith("/")):
        return as_logical_locator(value)
    return "/".join((LOGICAL_LOCATOR_NAMESPACE, *_locator_tail(value)))


def canon_shard_sort_key(path: Path) -> tuple[int, int, str]:
    match = CANON_SHARD_FILENAME_RE.match(path.name)
    if match:
        return (0, int(match.group(1)), path.name)
    return (1, 0, path.name)


def sorted_canon_shards(canon_dir: Path) -> list[Path]:
    return sorted(canon_dir.glob("tiddlers_*.jsonl"), key=canon_shard_sort_key)


def proposals_path() -> Path:
    return DEFAULT_PROPOSALS_FILE


def ensure_runtime_directories() -> None:
    for directory in (
        DEFAULT_OUT_DIR,
        DEFAULT_LOCAL_OUT_DIR,
        DEFAULT_REMOTE_OUT_DIR,
        DEFAULT_TMP_DIR,
        DEFAULT_CANON_DIR,
        DEFAULT_ENRICHED_DIR,
        DEFAULT_AI_DIR,
        DEFAULT_AI_REPORTS_DIR,
        DEFAULT_AUDIT_DIR,
        DEFAULT_REVERSE_HTML_DIR,
        DEFAULT_EXPORT_DIR,
        DEFAULT_MICROSOFT_COPILOT_DIR,
        DEFAULT_COPILOT_AGENT_DIR,
        DEFAULT_SESSIONS_DIR,
        DEFAULT_SESSIONS_DIR / "00_contratos",
        DEFAULT_SESSIONS_DIR / "01_procedencia",
        DEFAULT_SESSIONS_DIR / "02_detalles_de_sesion",
        DEFAULT_SESSIONS_DIR / "03_hipotesis",
        DEFAULT_SESSIONS_DIR / "04_balance_de_sesion",
        DEFAULT_SESSIONS_DIR / "05_propuesta_de_sesion",
        DEFAULT_SESSIONS_DIR / "06_diagnoses" / "sesion",
        DEFAULT_SESSIONS_DIR / "06_diagnoses" / "tema",
        DEFAULT_SESSIONS_DIR / "06_diagnoses" / "module",
        DEFAULT_SESSIONS_DIR / "06_diagnoses" / "micro-ciclo",
        DEFAULT_SESSIONS_DIR / "06_diagnoses" / "meso-ciclo",
        DEFAULT_SESSIONS_DIR / "06_diagnoses" / "proyecto",
    ):
        directory.mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    ensure_runtime_directories()
    print(
        json.dumps(
            {
                "repo_root": str(REPO_ROOT),
                "workspace_status": current_workspace_status(),
                "default_input_html": as_display_path(DEFAULT_INPUT_HTML),
                "default_out_dir": as_display_path(DEFAULT_OUT_DIR),
                "default_local_out_dir": as_display_path(DEFAULT_LOCAL_OUT_DIR),
                "default_remote_out_dir": as_display_path(DEFAULT_REMOTE_OUT_DIR),
                "default_canon_dir": as_display_path(DEFAULT_CANON_DIR),
                "default_enriched_dir": as_display_path(DEFAULT_ENRICHED_DIR),
                "default_ai_dir": as_display_path(DEFAULT_AI_DIR),
                "default_audit_dir": as_display_path(DEFAULT_AUDIT_DIR),
                "default_reverse_html_dir": as_display_path(DEFAULT_REVERSE_HTML_DIR),
                "default_reverse_html": as_display_path(DEFAULT_REVERSE_HTML),
                "default_reverse_report": as_display_path(DEFAULT_REVERSE_REPORT),
                "default_export_dir": as_display_path(DEFAULT_EXPORT_DIR),
                "default_microsoft_copilot_dir": as_display_path(DEFAULT_MICROSOFT_COPILOT_DIR),
                "default_proposals_file": as_display_path(DEFAULT_PROPOSALS_FILE),
                "default_sessions_dir": as_display_path(DEFAULT_SESSIONS_DIR),
                "default_tmp_dir": as_display_path(DEFAULT_TMP_DIR),
                "historical_tmp_root": str(HISTORICAL_TMP_ROOT),
                "default_refs_dir": as_display_path(DEFAULT_REFS_DIR),
            },
            indent=2,
        )
    )
