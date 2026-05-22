#!/usr/bin/env python3
"""Session title normalisation for tiddly-data-converter.

Audits session artifact titles in the staging area and the canon, builds
dry-run normalisation plans, and applies them with explicit confirmation
and automatic backup.

Operates only on the ``title`` field.  IDs, text, relations, tags,
source_path and all other fields are never touched.
"""

from __future__ import annotations

import json
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from path_governance import (  # noqa: E402
    DEFAULT_CANON_DIR,
    REPO_ROOT,
    as_display_path,
    sorted_canon_shards,
)
from session_artifact_governance import (  # noqa: E402
    FAMILY_BY_RELATIVE_ROOT,
    classify_artifact_family,
)
from session_title_policy import (  # noqa: E402
    TitleClassification,
    classify_title,
)

DEFAULT_SESSIONS_DIR = REPO_ROOT / "data" / "out" / "local" / "sessions"
DEFAULT_AUDIT_DIR = REPO_ROOT / "data" / "out" / "local" / "audit"
DEFAULT_BACKUP_DIR = REPO_ROOT / "data" / "out" / "local" / "backups"

# ── Dataclasses ───────────────────────────────────────────────────────────────


@dataclass
class NormalizationEntry:
    """Single title that was audited."""
    source: str             # "canon" | "staging"
    artifact_path: str      # shard filename (canon) or relative sessions path (staging)
    line_number: int        # 1-based line in shard; 0 for staging files
    artifact_family: str
    record_id: str          # empty for staging entries
    current_title: str
    proposed_title: str | None
    issue: str
    status: str             # "canonical" | "normalizable" | "manual_review" | "blocked"


@dataclass
class NormalizationPlan:
    """Dry-run plan for normalising session artifact titles."""
    run_id: str
    timestamp: str
    canon_hash_before: str
    total_checked: int
    entries: list[NormalizationEntry]
    normalizable_count: int
    manual_review_count: int
    blocked_count: int
    collision_check_done: bool
    dry_run: bool = True
    applied: bool = False
    backup_dir: str = ""
    applied_count: int = 0


# ── Internal helpers ──────────────────────────────────────────────────────────

def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _stamp_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def _canon_hash(canon_dir: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    for shard in sorted_canon_shards(canon_dir):
        digest.update(shard.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(shard.read_bytes())
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def _entry_to_dict(e: NormalizationEntry) -> dict[str, Any]:
    return {
        "source": e.source,
        "artifact_path": e.artifact_path,
        "line_number": e.line_number,
        "artifact_family": e.artifact_family,
        "record_id": e.record_id,
        "current_title": e.current_title,
        "proposed_title": e.proposed_title,
        "issue": e.issue,
        "status": e.status,
    }


def _plan_to_dict(plan: NormalizationPlan) -> dict[str, Any]:
    return {
        "run_id": plan.run_id,
        "timestamp": plan.timestamp,
        "canon_hash_before": plan.canon_hash_before,
        "total_checked": plan.total_checked,
        "normalizable_count": plan.normalizable_count,
        "manual_review_count": plan.manual_review_count,
        "blocked_count": plan.blocked_count,
        "collision_check_done": plan.collision_check_done,
        "dry_run": plan.dry_run,
        "applied": plan.applied,
        "backup_dir": plan.backup_dir,
        "applied_count": plan.applied_count,
        "entries": [_entry_to_dict(e) for e in plan.entries],
    }


def _entry_from_dict(d: dict[str, Any]) -> NormalizationEntry:
    return NormalizationEntry(
        source=d.get("source", ""),
        artifact_path=d.get("artifact_path", ""),
        line_number=int(d.get("line_number") or 0),
        artifact_family=d.get("artifact_family", ""),
        record_id=d.get("record_id", ""),
        current_title=d.get("current_title", ""),
        proposed_title=d.get("proposed_title"),
        issue=d.get("issue", ""),
        status=d.get("status", ""),
    )


# ── Session family detection for canon records ────────────────────────────────

# Reverse map: family key → first folder tuple key in FAMILY_BY_RELATIVE_ROOT
_FAMILY_FROM_TITLE_KEYWORDS: dict[str, str] = {
    "Contrato de sesión":    "contrato_de_sesion",
    "Procedencia de sesión": "procedencia_de_sesion",
    "Sesión ":               "detalles_de_sesion",    # space prevents matching "Propuesta de sesión"
    "Detalles de sesión":    "detalles_de_sesion",
    "Hipótesis de sesión":   "hipotesis_de_sesion",
    "Balance de sesión":     "balance_de_sesion",
    "Propuesta de sesión":   "propuesta_de_sesion",
    "Diagnóstico de sesión": "diagnostico_de_sesion",
}


def _family_from_canon_title(title: str) -> str | None:
    """Heuristically determine family from a canon record title."""
    for keyword, family in _FAMILY_FROM_TITLE_KEYWORDS.items():
        if keyword in title:
            return family
    return None


# ── Public API ────────────────────────────────────────────────────────────────

def audit_sessions_dir(
    sessions_dir: Path = DEFAULT_SESSIONS_DIR,
) -> list[NormalizationEntry]:
    """Audit all .md.json artifacts in the sessions staging area.

    Returns one NormalizationEntry per file, regardless of title status.
    """
    entries: list[NormalizationEntry] = []

    for f in sorted(sessions_dir.rglob("*.md.json")):
        # Determine family from folder
        fspec = classify_artifact_family(f, sessions_dir)
        if fspec is None:
            continue  # unknown family — skip
        family = fspec.family

        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                raw = raw[0] if raw else {}
            title = str(raw.get("title", ""))
        except (OSError, json.JSONDecodeError, IndexError):
            continue

        cls = classify_title(title, family)
        entries.append(NormalizationEntry(
            source="staging",
            artifact_path=str(f.relative_to(sessions_dir)),
            line_number=0,
            artifact_family=family,
            record_id="",
            current_title=title,
            proposed_title=cls.proposed_title,
            issue=cls.issue,
            status=cls.status,
        ))

    return entries


def audit_canon(
    canon_dir: Path = DEFAULT_CANON_DIR,
) -> list[NormalizationEntry]:
    """Audit all session artifact titles in the live canon shards.

    Returns one NormalizationEntry per session-family record found.
    """
    entries: list[NormalizationEntry] = []

    for shard in sorted_canon_shards(canon_dir):
        with shard.open("r", encoding="utf-8") as fh:
            for line_no, raw_line in enumerate(fh, start=1):
                stripped = raw_line.strip()
                if not stripped:
                    continue
                try:
                    rec = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                if not isinstance(rec, dict):
                    continue

                title = str(rec.get("title", ""))
                if "🌀" not in title:
                    continue

                family = _family_from_canon_title(title)
                if family is None:
                    continue

                cls = classify_title(title, family)
                if cls.status == "not_applicable":
                    continue

                entries.append(NormalizationEntry(
                    source="canon",
                    artifact_path=shard.name,
                    line_number=line_no,
                    artifact_family=family,
                    record_id=str(rec.get("id", "")),
                    current_title=title,
                    proposed_title=cls.proposed_title,
                    issue=cls.issue,
                    status=cls.status,
                ))

    return entries


def build_normalization_plan(
    entries: list[NormalizationEntry],
    canon_dir: Path = DEFAULT_CANON_DIR,
) -> NormalizationPlan:
    """Build a dry-run normalisation plan from audit entries.

    Performs collision detection: if two different canon records (by record_id)
    would normalise to the same proposed title, both are marked ``blocked``.
    """
    run_id = f"titlenorm-{_stamp_now()}"

    # Collision check within canon entries
    proposed_to_ids: dict[str, list[str]] = {}
    for e in entries:
        if e.source == "canon" and e.status == "normalizable" and e.proposed_title:
            proposed_to_ids.setdefault(e.proposed_title, []).append(e.record_id)

    collisions: set[str] = {
        pt for pt, ids in proposed_to_ids.items()
        if len(set(ids)) > 1  # different IDs → collision
    }

    # Mark collisions as blocked
    resolved: list[NormalizationEntry] = []
    for e in entries:
        if (e.source == "canon"
                and e.status == "normalizable"
                and e.proposed_title in collisions):
            resolved.append(NormalizationEntry(
                **{**e.__dict__, "status": "blocked", "issue": "collision," + e.issue}
            ))
        else:
            resolved.append(e)

    normalizable_count = sum(1 for e in resolved if e.status == "normalizable")
    manual_review_count = sum(1 for e in resolved if e.status == "manual_review")
    blocked_count = sum(1 for e in resolved if e.status == "blocked")

    return NormalizationPlan(
        run_id=run_id,
        timestamp=_iso_now(),
        canon_hash_before=_canon_hash(canon_dir),
        total_checked=len(resolved),
        entries=resolved,
        normalizable_count=normalizable_count,
        manual_review_count=manual_review_count,
        blocked_count=blocked_count,
        collision_check_done=True,
        dry_run=True,
        applied=False,
    )


def apply_normalization_plan(
    plan: NormalizationPlan,
    canon_dir: Path = DEFAULT_CANON_DIR,
    sessions_dir: Path = DEFAULT_SESSIONS_DIR,
    backup_dir: Path | None = None,
    confirm: bool = False,
) -> tuple[bool, str, NormalizationPlan]:
    """Apply a normalisation plan to staging (.md.json) files only.

    Safety contract:
    - ``confirm=False`` (default): dry-run, no writes.
    - ``confirm=True``: backs up canon shards, then applies normalizable staging
      entries only.  Only the ``title`` field is modified; all other fields are
      preserved.

    Canon records are intentionally skipped during apply.  Canon shards contain
    pipeline-derived identity fields (``key``, ``id``, ``canonical_slug``,
    ``version_id``) that are derived from ``title``.  Changing only ``title``
    without recomputing those fields would break the ``canon_preflight --mode
    strict`` integrity check.  To fix titles in the live canon, fix them in
    staging first; the next pipeline run (or admission cycle) will recompute all
    derived fields correctly.

    Returns ``(success, message, updated_plan)``.
    """
    normalizable = [e for e in plan.entries if e.status == "normalizable"]
    staging_normalizable = [e for e in normalizable if e.source == "staging"]

    if not staging_normalizable:
        canon_skipped = len([e for e in normalizable if e.source == "canon"])
        if canon_skipped:
            msg = (
                f"0 entradas staging normalizables "
                f"({canon_skipped} canon omitidas — requieren re-pipeline)"
            )
        else:
            msg = "no hay entradas normalizables en el plan"
        return False, msg, plan

    if not confirm:
        plan.dry_run = True
        return (
            True,
            f"dry-run: se normalizarían {len(staging_normalizable)} título(s) de staging, sin escritura",
            plan,
        )

    # --- Backup canon shards first (safety reference point) ---
    stamp = _stamp_now()
    effective_backup_dir = backup_dir or (DEFAULT_BACKUP_DIR / f"titlenorm-{stamp}")
    effective_backup_dir.mkdir(parents=True, exist_ok=True)
    for shard in sorted_canon_shards(canon_dir):
        shutil.copy2(shard, effective_backup_dir / shard.name)

    applied_count = 0

    # Canon entries are intentionally skipped — see docstring.

    # --- Apply staging entries ---
    for e in staging_normalizable:
        artifact_path = sessions_dir / e.artifact_path
        if not artifact_path.exists():
            continue
        try:
            raw = json.loads(artifact_path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                if raw:
                    raw[0]["title"] = e.proposed_title
            elif isinstance(raw, dict):
                raw["title"] = e.proposed_title
            _write_json(artifact_path, raw)
            applied_count += 1
        except (OSError, json.JSONDecodeError):
            continue

    plan.dry_run = False
    plan.applied = True
    plan.backup_dir = as_display_path(effective_backup_dir)
    plan.applied_count = applied_count

    return (
        True,
        f"normalizados {applied_count} título(s); backup en {as_display_path(effective_backup_dir)}",
        plan,
    )


def save_plan(plan: NormalizationPlan, out_dir: Path = DEFAULT_AUDIT_DIR) -> Path:
    """Persist a plan to disk and return the file path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    plan_path = out_dir / f"{plan.run_id}.json"
    _write_json(plan_path, _plan_to_dict(plan))
    return plan_path


def load_last_plan(out_dir: Path = DEFAULT_AUDIT_DIR) -> NormalizationPlan | None:
    """Load the most recently created normalisation plan, or None."""
    if not out_dir.exists():
        return None
    plan_files = sorted(
        out_dir.glob("titlenorm-*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not plan_files:
        return None
    try:
        with plan_files[0].open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return NormalizationPlan(
        run_id=str(data.get("run_id", "")),
        timestamp=str(data.get("timestamp", "")),
        canon_hash_before=str(data.get("canon_hash_before", "")),
        total_checked=int(data.get("total_checked") or 0),
        entries=[_entry_from_dict(e) for e in (data.get("entries") or [])],
        normalizable_count=int(data.get("normalizable_count") or 0),
        manual_review_count=int(data.get("manual_review_count") or 0),
        blocked_count=int(data.get("blocked_count") or 0),
        collision_check_done=bool(data.get("collision_check_done", False)),
        dry_run=bool(data.get("dry_run", True)),
        applied=bool(data.get("applied", False)),
        backup_dir=str(data.get("backup_dir") or ""),
        applied_count=int(data.get("applied_count") or 0),
    )


def format_audit_report(entries: list[NormalizationEntry]) -> str:
    """Return a human-readable summary table of audit entries."""
    if not entries:
        return "Sin entradas de auditoría."

    normalizable = [e for e in entries if e.status == "normalizable"]
    manual = [e for e in entries if e.status == "manual_review"]
    blocked = [e for e in entries if e.status == "blocked"]
    canonical_n = sum(1 for e in entries if e.status == "canonical")

    lines = [
        f"Auditoría de títulos — {len(entries)} entrada(s)",
        f"  canonical:     {canonical_n}",
        f"  normalizable:  {len(normalizable)}",
        f"  manual_review: {len(manual)}",
        f"  blocked:       {len(blocked)}",
        "",
    ]

    if normalizable:
        lines.append("── Normalizables ─────────────────────────────────────────────────────────")
        for e in normalizable:
            src = f"{e.artifact_path}:{e.line_number}" if e.source == "canon" else e.artifact_path
            lines.append(f"  [{e.source}] {src}")
            lines.append(f"    actual:   {e.current_title[:100]}")
            lines.append(f"    propuesto: {e.proposed_title or ''[:100]}")
            lines.append(f"    razón:    {e.issue}")

    if manual:
        lines.append("")
        lines.append("── Revisión manual ───────────────────────────────────────────────────────")
        for e in manual:
            src = f"{e.artifact_path}:{e.line_number}" if e.source == "canon" else e.artifact_path
            lines.append(f"  [{e.source}] {src}")
            lines.append(f"    título: {e.current_title[:100]}")

    if blocked:
        lines.append("")
        lines.append("── Bloqueados ────────────────────────────────────────────────────────────")
        for e in blocked:
            src = f"{e.artifact_path}:{e.line_number}" if e.source == "canon" else e.artifact_path
            lines.append(f"  [{e.source}] {src}  razón: {e.issue}")

    return "\n".join(lines)
