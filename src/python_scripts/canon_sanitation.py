#!/usr/bin/env python3
"""Canon sanitation module for tiddly-data-converter.

Provides tools for detecting non-conforming lines in canon shards, searching
by ID or title, building dry-run elimination plans, and applying plans with
explicit human confirmation and automatic backup.

Designed for safe, traceable, human-in-the-loop canon cleanup.
No writes occur unless a plan is explicitly applied with confirm=True.
"""

from __future__ import annotations

import json
import re
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


DEFAULT_SANITATION_DIR = REPO_ROOT / "data" / "tmp" / "sanitation"

REQUIRED_CANON_FIELDS = ("id", "title")

# Non-conformity reasons
REASON_INVALID_JSON = "invalid_json"
REASON_MISSING_ID = "missing_id"
REASON_MISSING_TITLE = "missing_title"
REASON_DUPLICATE_ID = "duplicate_id"
REASON_MISSING_TEXT = "missing_text"
REASON_USER_SELECTED = "user_selected"  # Added in S0122: target chosen via search


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class NonConformingLine:
    """A single non-conforming entry detected in a canon shard."""
    index: int            # 1-based display index for user selection
    shard: str            # shard filename, e.g. "tiddlers_1.jsonl"
    line_no: int          # 1-based line number within shard
    record_id: str        # "" when unknown
    title: str            # "" when unknown
    reason: str           # one of the REASON_* constants
    description: str      # human-readable detail


@dataclass
class EliminationPlan:
    """Dry-run plan for eliminating selected canon lines."""
    run_id: str
    timestamp: str
    canon_dir: str
    canon_hash_before: str
    selected_indices: list[int]
    targets: list[NonConformingLine]
    dry_run: bool = True
    applied: bool = False
    backup_dir: str = ""
    canon_hash_after: str = ""
    removed_count: int = 0
    source_kind: str = "scan"   # "scan" | "search_id" | "search_title"  (S0122)
    query: str = ""              # search fragment when source_kind != "scan"  (S0122)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _stamp_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def _safe_str(value: Any) -> str:
    return "" if value is None else str(value)


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


def _nonconforming_to_dict(nc: NonConformingLine) -> dict[str, Any]:
    return {
        "index": nc.index,
        "shard": nc.shard,
        "line_no": nc.line_no,
        "record_id": nc.record_id,
        "title": nc.title,
        "reason": nc.reason,
        "description": nc.description,
    }


def _plan_to_dict(plan: EliminationPlan) -> dict[str, Any]:
    return {
        "run_id": plan.run_id,
        "timestamp": plan.timestamp,
        "canon_dir": plan.canon_dir,
        "canon_hash_before": plan.canon_hash_before,
        "selected_indices": plan.selected_indices,
        "targets": [_nonconforming_to_dict(t) for t in plan.targets],
        "dry_run": plan.dry_run,
        "applied": plan.applied,
        "backup_dir": plan.backup_dir,
        "canon_hash_after": plan.canon_hash_after,
        "removed_count": plan.removed_count,
        "source_kind": plan.source_kind,
        "query": plan.query,
    }


# ── Public API ────────────────────────────────────────────────────────────────

def scan_canon_for_nonconforming(
    canon_dir: Path = DEFAULT_CANON_DIR,
) -> list[NonConformingLine]:
    """Scan all canon shards and return a list of non-conforming lines.

    Detects:
    - Lines that cannot be parsed as JSON
    - Lines missing a non-empty ``id`` field
    - Lines missing a non-empty ``title`` field
    - Lines missing a ``text`` field entirely
    - Duplicate IDs within the canon (second occurrence flagged)

    Returns lines in shard order; ``index`` is 1-based for user selection.
    """
    results: list[NonConformingLine] = []
    seen_ids: dict[str, tuple[str, int]] = {}  # id → (shard, line_no)
    global_index = 1

    for shard_path in sorted_canon_shards(canon_dir):
        with shard_path.open("r", encoding="utf-8") as fh:
            for line_no, raw in enumerate(fh, start=1):
                stripped = raw.strip()
                if not stripped:
                    continue

                try:
                    record = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    results.append(NonConformingLine(
                        index=global_index,
                        shard=shard_path.name,
                        line_no=line_no,
                        record_id="",
                        title="",
                        reason=REASON_INVALID_JSON,
                        description=f"JSON inválido: {exc}",
                    ))
                    global_index += 1
                    continue

                if not isinstance(record, dict):
                    results.append(NonConformingLine(
                        index=global_index,
                        shard=shard_path.name,
                        line_no=line_no,
                        record_id="",
                        title="",
                        reason=REASON_INVALID_JSON,
                        description="La línea no es un objeto JSON",
                    ))
                    global_index += 1
                    continue

                rec_id = _safe_str(record.get("id"))
                rec_title = _safe_str(record.get("title"))

                # Missing ID
                if not rec_id:
                    results.append(NonConformingLine(
                        index=global_index,
                        shard=shard_path.name,
                        line_no=line_no,
                        record_id="",
                        title=rec_title[:80] if rec_title else "",
                        reason=REASON_MISSING_ID,
                        description="Campo 'id' ausente o vacío",
                    ))
                    global_index += 1
                    continue

                # Missing title
                if not rec_title:
                    results.append(NonConformingLine(
                        index=global_index,
                        shard=shard_path.name,
                        line_no=line_no,
                        record_id=rec_id,
                        title="",
                        reason=REASON_MISSING_TITLE,
                        description="Campo 'title' ausente o vacío",
                    ))
                    global_index += 1
                    continue

                # Missing text field
                if "text" not in record:
                    results.append(NonConformingLine(
                        index=global_index,
                        shard=shard_path.name,
                        line_no=line_no,
                        record_id=rec_id,
                        title=rec_title[:80],
                        reason=REASON_MISSING_TEXT,
                        description="Campo 'text' ausente",
                    ))
                    global_index += 1
                    continue

                # Duplicate ID
                if rec_id in seen_ids:
                    prev_shard, prev_line = seen_ids[rec_id]
                    results.append(NonConformingLine(
                        index=global_index,
                        shard=shard_path.name,
                        line_no=line_no,
                        record_id=rec_id,
                        title=rec_title[:80],
                        reason=REASON_DUPLICATE_ID,
                        description=(
                            f"ID duplicado (primera aparición: {prev_shard}:{prev_line})"
                        ),
                    ))
                    global_index += 1
                    continue

                seen_ids[rec_id] = (shard_path.name, line_no)

    return results


def search_canon_by_id(
    id_fragment: str,
    canon_dir: Path = DEFAULT_CANON_DIR,
) -> list[dict[str, Any]]:
    """Return all canon records whose ``id`` field contains the fragment (case-insensitive)."""
    fragment_lower = id_fragment.lower().strip()
    matches: list[dict[str, Any]] = []
    for shard_path in sorted_canon_shards(canon_dir):
        with shard_path.open("r", encoding="utf-8") as fh:
            for line_no, raw in enumerate(fh, start=1):
                stripped = raw.strip()
                if not stripped:
                    continue
                try:
                    record = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                rec_id = _safe_str(record.get("id"))
                if fragment_lower in rec_id.lower():
                    matches.append({
                        "shard": shard_path.name,
                        "line_no": line_no,
                        "id": rec_id,
                        "title": _safe_str(record.get("title"))[:100],
                    })
    return matches


def search_canon_by_title(
    title_fragment: str,
    canon_dir: Path = DEFAULT_CANON_DIR,
) -> list[dict[str, Any]]:
    """Return all canon records whose ``title`` contains the fragment (case-insensitive)."""
    fragment_lower = title_fragment.lower().strip()
    matches: list[dict[str, Any]] = []
    for shard_path in sorted_canon_shards(canon_dir):
        with shard_path.open("r", encoding="utf-8") as fh:
            for line_no, raw in enumerate(fh, start=1):
                stripped = raw.strip()
                if not stripped:
                    continue
                try:
                    record = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                rec_title = _safe_str(record.get("title"))
                if fragment_lower in rec_title.lower():
                    matches.append({
                        "shard": shard_path.name,
                        "line_no": line_no,
                        "id": _safe_str(record.get("id")),
                        "title": rec_title[:100],
                    })
    return matches


def parse_index_selection(raw: str, max_index: int) -> tuple[list[int], list[str]]:
    """Parse a user selection string like ``"1,3,5-7"`` into a sorted list of indices.

    Returns (selected_indices, errors).  Out-of-range values are reported as errors.
    """
    selected: set[int] = set()
    errors: list[str] = []

    for part in raw.replace(" ", "").split(","):
        if not part:
            continue
        range_match = re.fullmatch(r"(\d+)-(\d+)", part)
        if range_match:
            start, end = int(range_match.group(1)), int(range_match.group(2))
            if start > end:
                errors.append(f"rango inválido: {part}")
                continue
            for i in range(start, end + 1):
                if 1 <= i <= max_index:
                    selected.add(i)
                else:
                    errors.append(f"índice fuera de rango: {i} (máx {max_index})")
        elif re.fullmatch(r"\d+", part):
            i = int(part)
            if 1 <= i <= max_index:
                selected.add(i)
            else:
                errors.append(f"índice fuera de rango: {i} (máx {max_index})")
        else:
            errors.append(f"token no reconocido: {part!r}")

    return sorted(selected), errors


def build_elimination_plan(
    selected_indices: list[int],
    non_conforming: list[NonConformingLine],
    canon_dir: Path = DEFAULT_CANON_DIR,
) -> EliminationPlan:
    """Build a dry-run elimination plan for the selected non-conforming indices.

    The plan is NOT applied — it is a manifest of what WOULD be removed.
    Call :func:`apply_elimination_plan` with ``confirm=True`` to execute it.
    """
    index_set = set(selected_indices)
    targets = [nc for nc in non_conforming if nc.index in index_set]
    run_id = f"sanitation-{_stamp_now()}"
    return EliminationPlan(
        run_id=run_id,
        timestamp=_iso_now(),
        canon_dir=as_display_path(canon_dir),
        canon_hash_before=_canon_hash(canon_dir),
        selected_indices=sorted(index_set),
        targets=targets,
        dry_run=True,
        applied=False,
    )


def build_elimination_plan_from_search(
    selected_indices: list[int],
    search_results: list[dict[str, Any]],
    source_kind: str,
    query: str,
    canon_dir: Path = DEFAULT_CANON_DIR,
) -> EliminationPlan:
    """Build a dry-run elimination plan from search results.

    ``search_results`` is the output of :func:`search_canon_by_id` or
    :func:`search_canon_by_title`, indexed 1-based for ``selected_indices``.

    ``source_kind`` should be ``"search_id"`` or ``"search_title"``.
    ``query`` is the fragment that was searched for.

    The plan is NOT applied — it is a manifest of what WOULD be removed.
    Call :func:`apply_elimination_plan` with ``confirm=True`` to execute it.
    """
    index_set = set(selected_indices)
    targets: list[NonConformingLine] = []
    for i, item in enumerate(search_results, start=1):
        if i in index_set:
            targets.append(NonConformingLine(
                index=i,
                shard=_safe_str(item.get("shard")),
                line_no=int(item.get("line_no") or 0),
                record_id=_safe_str(item.get("id")),
                title=_safe_str(item.get("title"))[:80],
                reason=REASON_USER_SELECTED,
                description=f"{source_kind} query={query!r}",
            ))
    run_id = f"sanitation-{_stamp_now()}"
    return EliminationPlan(
        run_id=run_id,
        timestamp=_iso_now(),
        canon_dir=as_display_path(canon_dir),
        canon_hash_before=_canon_hash(canon_dir),
        selected_indices=sorted(index_set),
        targets=targets,
        dry_run=True,
        applied=False,
        source_kind=source_kind,
        query=query,
    )


def format_search_results_numbered(results: list[dict[str, Any]]) -> str:
    """Return a numbered table string for displaying search results with 1-based indices."""
    if not results:
        return "Sin resultados."
    lines_out = ["  #   Shard                 Línea  ID                             Título"]
    lines_out.append("  " + "-" * 78)
    for i, item in enumerate(results, start=1):
        shard = _safe_str(item.get("shard"))[:20]
        line_no = item.get("line_no", 0)
        rec_id = _safe_str(item.get("id"))[:30]
        title = _safe_str(item.get("title"))[:35]
        lines_out.append(f"  {i:<3}  {shard:<20}  {line_no:<5}  {rec_id:<30}  {title}")
    return "\n".join(lines_out)


def save_plan(plan: EliminationPlan, out_dir: Path = DEFAULT_SANITATION_DIR) -> Path:
    """Persist a plan to disk and return the file path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    plan_path = out_dir / f"{plan.run_id}.json"
    _write_json(plan_path, _plan_to_dict(plan))
    return plan_path


def load_last_plan(out_dir: Path = DEFAULT_SANITATION_DIR) -> EliminationPlan | None:
    """Load the most recently created sanitation plan, or None if none exist."""
    if not out_dir.exists():
        return None
    plan_files = sorted(out_dir.glob("sanitation-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not plan_files:
        return None
    try:
        with plan_files[0].open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    targets = [
        NonConformingLine(
            index=t.get("index", 0),
            shard=t.get("shard", ""),
            line_no=t.get("line_no", 0),
            record_id=t.get("record_id", ""),
            title=t.get("title", ""),
            reason=t.get("reason", ""),
            description=t.get("description", ""),
        )
        for t in data.get("targets") or []
    ]
    return EliminationPlan(
        run_id=_safe_str(data.get("run_id")),
        timestamp=_safe_str(data.get("timestamp")),
        canon_dir=_safe_str(data.get("canon_dir")),
        canon_hash_before=_safe_str(data.get("canon_hash_before")),
        selected_indices=list(data.get("selected_indices") or []),
        targets=targets,
        dry_run=bool(data.get("dry_run", True)),
        applied=bool(data.get("applied", False)),
        backup_dir=_safe_str(data.get("backup_dir")),
        canon_hash_after=_safe_str(data.get("canon_hash_after")),
        removed_count=int(data.get("removed_count") or 0),
        source_kind=_safe_str(data.get("source_kind")) or "scan",
        query=_safe_str(data.get("query")),
    )


def apply_elimination_plan(
    plan: EliminationPlan,
    canon_dir: Path = DEFAULT_CANON_DIR,
    backup_dir: Path | None = None,
    confirm: bool = False,
) -> tuple[bool, str, EliminationPlan]:
    """Apply a previously-built elimination plan to the live canon.

    Safety contract:
    - ``confirm=False`` (default): dry-run only, no writes.
    - ``confirm=True``: creates a backup, then removes the targeted lines.
    - If any validation error is detected the plan is NOT applied.

    Returns ``(success, message, updated_plan)``.
    """
    if not plan.targets:
        return False, "el plan no tiene objetivos (targets vacíos)", plan

    # Verify plan matches current canon state
    current_hash = _canon_hash(canon_dir)
    if plan.canon_hash_before and plan.canon_hash_before != current_hash:
        return (
            False,
            (
                "el hash del canon actual no coincide con el hash del plan; "
                "el canon pudo haber cambiado desde que se generó el plan"
            ),
            plan,
        )

    if not confirm:
        # Dry-run: report what would happen, no writes
        plan.dry_run = True
        plan.applied = False
        return (
            True,
            f"dry-run: se eliminarían {len(plan.targets)} línea(s), sin escritura",
            plan,
        )

    # Real application: backup first
    stamp = _stamp_now()
    effective_backup_dir = backup_dir or (DEFAULT_SANITATION_DIR / f"backup-{stamp}")
    effective_backup_dir.mkdir(parents=True, exist_ok=True)
    for shard_path in sorted_canon_shards(canon_dir):
        shutil.copy2(shard_path, effective_backup_dir / shard_path.name)

    # Build set of (shard, line_no) to remove
    targets_by_shard: dict[str, set[int]] = {}
    for t in plan.targets:
        targets_by_shard.setdefault(t.shard, set()).add(t.line_no)

    removed_count = 0
    for shard_path in sorted_canon_shards(canon_dir):
        to_remove = targets_by_shard.get(shard_path.name, set())
        if not to_remove:
            continue
        kept: list[str] = []
        with shard_path.open("r", encoding="utf-8") as fh:
            for line_no, raw in enumerate(fh, start=1):
                stripped = raw.strip()
                if stripped and line_no in to_remove:
                    removed_count += 1
                    continue
                kept.append(raw.rstrip("\n"))

        with shard_path.open("w", encoding="utf-8") as fh:
            for kept_line in kept:
                fh.write(kept_line + "\n")

    plan.dry_run = False
    plan.applied = True
    plan.backup_dir = as_display_path(effective_backup_dir)
    plan.canon_hash_after = _canon_hash(canon_dir)
    plan.removed_count = removed_count

    return (
        True,
        f"eliminadas {removed_count} línea(s); backup en {as_display_path(effective_backup_dir)}",
        plan,
    )


def format_nonconforming_summary(items: list[NonConformingLine]) -> str:
    """Return a multi-line table string for displaying non-conforming items."""
    if not items:
        return "No se encontraron líneas no conformes."
    lines_out = ["  #  Shard                 Línea  Razón                Detalle / título"]
    lines_out.append("  " + "-" * 78)
    for nc in items:
        shard = nc.shard[:20]
        reason = nc.reason[:20]
        detail = (nc.title or nc.description)[:40]
        lines_out.append(
            f"  {nc.index:<3}  {shard:<20}  {nc.line_no:<5}  {reason:<20}  {detail}"
        )
    return "\n".join(lines_out)
