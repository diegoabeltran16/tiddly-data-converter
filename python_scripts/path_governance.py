#!/usr/bin/env python3
"""Shared local/remote paths for data/in, data/out, and local reverse outputs."""

from __future__ import annotations

import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def repo_path(relative_path: str) -> Path:
    return (REPO_ROOT / relative_path).resolve()


DEFAULT_INPUT_HTML = repo_path("data/in/tiddly-data-converter (Saved).html")
DEFAULT_OUT_DIR = repo_path("data/out")
DEFAULT_LOCAL_OUT_DIR = repo_path("data/out/local")
DEFAULT_REMOTE_OUT_DIR = repo_path("data/out/remote")
DEFAULT_CANON_DIR = DEFAULT_LOCAL_OUT_DIR
DEFAULT_ENRICHED_DIR = DEFAULT_LOCAL_OUT_DIR / "enriched"
DEFAULT_AI_DIR = DEFAULT_LOCAL_OUT_DIR / "ai"
DEFAULT_AI_REPORTS_DIR = DEFAULT_AI_DIR / "reports"
DEFAULT_AUDIT_DIR = DEFAULT_LOCAL_OUT_DIR / "audit"
DEFAULT_REVERSE_HTML_DIR = repo_path("data/out/local/reverse_html")
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
    ):
        directory.mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    ensure_runtime_directories()
    print(
        json.dumps(
            {
                "repo_root": str(REPO_ROOT),
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
            },
            indent=2,
        )
    )
