#!/usr/bin/env python3
"""S0186 Unit J (subunit J.2) -- governed cleanup/retention surface for the
``data/tmp`` lifecycle problem diagnosed in J's PREIMPACT/J.1/J.2.

This module extends ``quiescence_state.py``'s read-only classification
(which only names ownership) with a retention judgment for each owned
surface, built from the same kind of direct evidence J.2 used by hand:

- ``session_admission``: a canon-snapshot run is SUPERSEDED_HISTORY once
  every record it holds is shown to already exist, byte-identical, in
  current live Canon (never assumed from age or name).
- ``reconstruction`` / ``html_export``: each run mixes a small, undurable
  report/manifest with a large, reconstructible canon/export payload.
- ``sanitation``: J.2 found that most ``backup-*`` directories here are not
  production data at all -- they are a second test-fixture leak
  (``tests/test_canon_sanitation.py`` called ``apply_elimination_plan(...,
  confirm=True)`` without ``backup_dir=``, defaulting to the real
  ``DEFAULT_SANITATION_DIR``; fixed separately). Detected here by shape
  (single tiny shard) rather than hardcoded dates, so it keeps working if
  the leak recurs from a different call site.
- ``session_sync``: cross-checked against its own durable audit twin under
  ``data/out/local/audit/session_sync/``.

Three capabilities, each independently invokable and none destructive on
its own except the last, which requires an explicit authorization phrase
bound to a freshly-recomputed plan hash:

1. ``build_retention_report()`` -- read-only, extends quiescence_state.
2. ``extract_unique_evidence()`` -- copies small, undurable evidence
   (never deletes a source) to a durable home under
   ``data/out/local/audit/tmp_lifecycle/extracted_evidence/``.
3. ``dry_run_cleanup()`` / ``execute_cleanup()`` -- productive cleanup of
   whatever the retention report classifies DELETE_CANDIDATE. ``dry_run``
   never writes. ``execute`` requires the exact phrase
   ``f"{AUTHORIZATION_PHRASE_PREFIX} {plan_hash}"`` where ``plan_hash`` is
   the hash of the dry-run just produced -- a stale or hand-typed hash is
   rejected, mirroring ``canon_content_recovery.py``'s authorization
   contract.
"""

from __future__ import annotations

import hashlib
from collections import Counter
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
    REPO_ROOT,
    DEFAULT_CANON_DIR,
    DEFAULT_AUDIT_DIR,
    DEFAULT_TMP_DIR,
    HISTORICAL_TMP_ROOT,
    as_display_path,
    sorted_canon_shards,
)
import quiescence_state  # noqa: E402
from admit_session_candidates import _canon_hash  # noqa: E402

# S0187 D20: TMP_ROOT is the CURRENT/ACTIVE tmp authority this module governs
# -- previously a hardcoded REPO_ROOT-relative literal, meaning this
# retention/lifecycle tooling was silently observing the pre-binding root
# rather than the workspace-active one that recent writers (session_sync.py,
# material_inventory.py, admit_session_candidates.py, stage_modal_delta.py)
# already resolve to. HISTORICAL_TMP_ROOT (imported above, re-exported here)
# is available for a future reconciliation tool to deliberately inspect
# pre-binding material -- it is NEVER substituted for TMP_ROOT automatically.
TMP_ROOT = DEFAULT_TMP_DIR
ADMISSIONS_AUDIT_DIR = DEFAULT_AUDIT_DIR / "admissions"
SESSION_SYNC_AUDIT_DIR = DEFAULT_AUDIT_DIR / "session_sync"
LIFECYCLE_AUDIT_DIR = DEFAULT_AUDIT_DIR / "tmp_lifecycle"
EXTRACTED_EVIDENCE_ROOT = LIFECYCLE_AUDIT_DIR / "extracted_evidence"
RECEIPTS_DIR = LIFECYCLE_AUDIT_DIR / "receipts"

AUTHORIZATION_PHRASE_PREFIX = "CONFIRM TMP LIFECYCLE CLEANUP"

# Heuristic thresholds for distinguishing a real per-shard sanitation backup
# from a test-fixture leak (J.2 found real backups are either full 38-shard
# canon copies of several MB per shard, or at minimum hold plausible record
# content; leaked test fixtures hold a handful of synthetic records in a
# single shard under 4KB). Deliberately shape-based, not date-based, so this
# keeps detecting the leak if it recurs from a different call site.
_SANITATION_TEST_LEAK_MAX_BYTES = 4096
_SANITATION_TEST_LEAK_MAX_SHARDS = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _dir_bytes(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def _dir_files(path: Path) -> int:
    return sum(1 for p in path.rglob("*") if p.is_file())


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _iter_shard_records(shard: Path) -> list[dict[str, Any]]:
    records = []
    for line in shard.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def canon_records_by_id(canon_dir: Path) -> dict[str, dict[str, Any]]:
    """Load every ``id -> record`` in ``canon_dir``. Used only for supersede

    comparisons; never used to mutate anything.
    """
    index: dict[str, dict[str, Any]] = {}
    for shard in sorted_canon_shards(canon_dir):
        for record in _iter_shard_records(shard):
            record_id = record.get("id")
            if record_id:
                index[str(record_id)] = record
    return index


# --------------------------------------------------------------------------
# Identity-aware comparator (S0186 Unit J subunit J.2, residual investigation).
# A byte-for-byte "superseded" check alone is too strict: it cannot tell
# deliberate, governed record removal or evolution apart from genuine loss.
# Every exemption below is grounded in a real, inspectable contract found in
# this repo's own data -- never a blanket "assume it's fine because it's old"
# rule.
# --------------------------------------------------------------------------

_CONTENT_BODY_MARKER = "# Contenido principal"

# Record ids known, from direct evidence (data/tmp/sanitation/sanitation-*.json
# plan files, which name the exact record_id + a human-confirmed
# reason="user_selected"), to have been deliberately removed by a governed
# sanitation operation. Not a heuristic -- each entry is a literal citation.
KNOWN_SANITATION_REMOVALS: dict[str, dict[str, str]] = {
    "aafec109-c197-5979-b9ac-5bd8636650f6": {
        "removed_by": "data/tmp/sanitation/sanitation-20260901220923.json",
        "reason": "user_selected search_title (renumbered '08.' predecessor of ab0f1850, deliberately deleted after renumbering)",
    },
    "4667737e-bac0-583f-91ba-53ecc9ac10de": {
        "removed_by": "data/tmp/sanitation/sanitation-20260901221017.json and sanitation-20260901232743.json",
        "reason": "user_selected search_title, removed twice on 2026-09-01 then re-admitted; present again in current live Canon",
    },
}

# A same-id content difference that a human has explicitly reviewed and
# accepted as a closed, governed finding -- not deleted evidence, not
# assumed benign, but a documented residual provenance gap with a durable
# forensic capsule preserving everything needed to reconstruct the
# investigation. Each entry MUST cite the capsule and its verified hash;
# an entry here without one is a policy violation, not a valid exemption.
ACCEPTED_PROVENANCE_GAPS: dict[str, dict[str, str]] = {
    "ab0f1850-e42c-5dcf-a85a-0e786e590147": {
        "finding": "AB0F1850_UNEXPLAINED_CONTENT_TRANSITION",
        "status": "ACCEPTED_RESIDUAL_PROVENANCE_GAP",
        "forensic_capsule": "data/out/local/audit/tmp_lifecycle/forensic_capsules/ab0f1850/",
        "capsule_manifest_hash": "f3f7b497634a0c1023a7ddd773d93e6680f8a67fc79930520f464b79d2001b64",
        "accepted_at": "2026-09-08",
        "accepted_by": "human, S0186 IMPACTO Unidad J Subunidad J.2",
    },
}


def _content_body(text: Any) -> str | None:
    """Same contract as validate_productive_equivalence.py's

    ``_extract_content_body``: strip the identity/metadata header (title,
    id, tags, source fields) that a governed rename necessarily changes,
    leaving only the substantive body used to test whether two ids are the
    same underlying document.
    """
    if not isinstance(text, str) or not text:
        return None
    index = text.find(_CONTENT_BODY_MARKER)
    return text[index:] if index != -1 else text


def build_content_body_index(canon_index: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for record_id, record in canon_index.items():
        body = _content_body(record.get("text"))
        if not body:
            continue
        digest = sha256_bytes(body.encode("utf-8"))
        index.setdefault(digest, []).append(record_id)
    return index


def _not_yet_frozen_session_deliverable_tag(record: dict[str, Any]) -> str | None:
    """Contractual, not heuristic: a session-deliverable record carries both

    a ``layer:session`` tag and a ``status:local_admitted`` tag (see
    aa606426...'s ``tags`` -- the same governed session-deliverable family
    documented in quiescence_state.py's ``_SESSION_DIR_RE``). ``local_admitted``
    is one of several statuses observed in this Canon (others include
    ``archival``, ``derived``, ``exit``, ``stop``, ``term``) -- it specifically
    means the deliverable has not been frozen/archived, and is therefore
    still subject to legitimate content growth as its owning session
    progresses toward its own closure, whether that session is the currently
    active one or one that was still open at an earlier snapshot's time (a
    frozen/archival-tagged deliverable would NOT qualify here, and a
    real difference on one of those would correctly stay unexplained).
    """
    tags = {t.lower() for t in (record.get("tags") or []) if isinstance(t, str)}
    if "layer:session" in tags and "status:local_admitted" in tags:
        session_tag = next((t for t in record.get("tags") or [] if isinstance(t, str) and t.lower().startswith("session:")), None)
        return session_tag or "layer:session"
    return None


def classify_record_diff(
    old_record: dict[str, Any],
    current_index: dict[str, dict[str, Any]],
    content_body_index: dict[str, list[str]],
) -> tuple[str, dict[str, Any] | None]:
    """One record's disposition relative to current live Canon. Returns

    ``(category, detail)`` where category is one of the six contractual
    classes and ``detail`` carries the evidence for anything beyond a plain
    exact match.
    """
    old_id = str(old_record.get("id") or "")
    current_record = current_index.get(old_id)
    if current_record is not None:
        if current_record.get("text") == old_record.get("text") and current_record.get("content") == old_record.get("content"):
            return "EXACT_CURRENT_MATCH", None
        source_fields = current_record.get("source_fields") or {}
        if source_fields.get("is_current_repo_artifact") == "true" or current_record.get("role_primary") == "code":
            # Contractual, not heuristic: "code" is one of exactly 5 defined
            # role_primary values (code/log/config/glossary/evidence, see
            # tests/test_classification_characterization.py's VALID_ROLES) and
            # is specifically the taxonomy class for repository source/config
            # files (characterize_repo_artifacts.py:is_code_like). Two
            # ingestion vintages exist -- the newer one additionally sets
            # source_fields.is_current_repo_artifact -- but role_primary is
            # the stable, universal marker across both. This class of record
            # is expected to change as the underlying repo file changes; a
            # real content document (role_primary=="evidence", e.g. ab0f1850)
            # never qualifies here.
            return "EXPECTED_METADATA_EVOLUTION", {
                "sub_reason": "repo_artifact_refresh",
                "role_primary": current_record.get("role_primary"),
                "artifact_family": source_fields.get("artifact_family"),
                "repo_path": source_fields.get("repo_path") or current_record.get("title"),
            }
        session_tag = _not_yet_frozen_session_deliverable_tag(current_record)
        if session_tag:
            return "EXPECTED_METADATA_EVOLUTION", {
                "sub_reason": "session_deliverable_pre_freeze_evolution",
                "session_tag": session_tag,
                "artifact_family": source_fields.get("artifact_family"),
            }
        if old_id in ACCEPTED_PROVENANCE_GAPS:
            # A human has explicitly reviewed this exact same-id content
            # difference and accepted it as closed, with a durable, hash-
            # verified forensic capsule preserving everything needed to
            # reconstruct the investigation (see ACCEPTED_PROVENANCE_GAPS's
            # docstring). This is never assumed benign on its own -- an
            # entry only exists here after that review actually happened.
            return "EXPECTED_METADATA_EVOLUTION", {
                "sub_reason": "accepted_residual_provenance_gap",
                **ACCEPTED_PROVENANCE_GAPS[old_id],
            }
        return "UNEXPLAINED_CONTENT_DIFFERENCE", {
            "old_text_len": len(old_record.get("text") or ""),
            "current_text_len": len(current_record.get("text") or ""),
        }
    # old_id absent from current Canon.
    if old_id in KNOWN_SANITATION_REMOVALS:
        return "SUPERSEDED_CANON_STATE", KNOWN_SANITATION_REMOVALS[old_id]
    body = _content_body(old_record.get("text"))
    if body:
        digest = sha256_bytes(body.encode("utf-8"))
        candidates = content_body_index.get(digest, [])
        if len(candidates) == 1:
            return "EXPECTED_IDENTITY_MIGRATION", {"migrated_to": candidates[0]}
    return "UNIQUE_HISTORICAL_CONTENT", {"text_len": len(old_record.get("text") or "")}


def classify_snapshot_identity_aware(
    snapshot_dir: Path,
    current_index: dict[str, dict[str, Any]],
    content_body_index: dict[str, list[str]],
) -> dict[str, Any]:
    """Identity-aware disposition of every record in ``snapshot_dir`` against

    current live Canon. Never deletes, moves or edits anything.
    """
    counts: dict[str, int] = {}
    unexplained: list[str] = []
    unique_historical: list[str] = []
    total = 0
    for shard in sorted_canon_shards(snapshot_dir):
        for record in _iter_shard_records(shard):
            record_id = record.get("id")
            if not record_id:
                continue
            total += 1
            category, detail = classify_record_diff(record, current_index, content_body_index)
            counts[category] = counts.get(category, 0) + 1
            if category == "UNEXPLAINED_CONTENT_DIFFERENCE":
                unexplained.append(str(record_id))
            elif category == "UNIQUE_HISTORICAL_CONTENT":
                unique_historical.append(str(record_id))
    return {
        "record_count": total,
        "exact_matches": counts.get("EXACT_CURRENT_MATCH", 0),
        "identity_migrations": counts.get("EXPECTED_IDENTITY_MIGRATION", 0),
        "expected_metadata_evolution": counts.get("EXPECTED_METADATA_EVOLUTION", 0),
        "superseded_records": counts.get("SUPERSEDED_CANON_STATE", 0),
        "unique_historical_records": counts.get("UNIQUE_HISTORICAL_CONTENT", 0),
        "unexplained_differences": counts.get("UNEXPLAINED_CONTENT_DIFFERENCE", 0),
        "unexplained_ids": unexplained,
        "unique_historical_ids": unique_historical,
    }


def is_snapshot_superseded_by_current_canon(
    snapshot_dir: Path,
    current_canon_dir: Path = DEFAULT_CANON_DIR,
    *,
    current_index: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """True only when every record ``snapshot_dir`` holds already exists,

    byte-identical on ``text``/``content``, in ``current_canon_dir``. Never
    assumed from age, run naming, or a same-named "durable twin" directory
    -- J.2 found that assumption wrong once (session_admission's canon/ is
    canon_after, not a duplicate of the durable canon_before backup).
    """
    current = current_index if current_index is not None else canon_records_by_id(current_canon_dir)
    checked = 0
    missing: list[str] = []
    mismatched: list[str] = []
    for shard in sorted_canon_shards(snapshot_dir):
        for record in _iter_shard_records(shard):
            record_id = str(record.get("id") or "")
            if not record_id:
                continue
            checked += 1
            current_record = current.get(record_id)
            if current_record is None:
                missing.append(record_id)
                continue
            if current_record.get("text") != record.get("text") or current_record.get("content") != record.get("content"):
                mismatched.append(record_id)
    return {
        "checked_ids": checked,
        "missing_from_current": missing,
        "mismatched_content": mismatched,
        "superseded": checked > 0 and not missing and not mismatched,
    }


# --------------------------------------------------------------------------
# session_admission: canon_before (durable, data/out) vs canon_after
# (ephemeral, data/tmp) -- see J.2-A. Classified per run from the compact
# admit report, not from directory-name similarity.
# --------------------------------------------------------------------------

def classify_session_admission(
    *,
    current_index: dict[str, dict[str, Any]] | None = None,
    content_body_index: dict[str, list[str]] | None = None,
) -> list[dict[str, Any]]:
    root = TMP_ROOT / "session_admission"
    if not root.is_dir():
        return []
    current = current_index if current_index is not None else canon_records_by_id(DEFAULT_CANON_DIR)
    body_index = content_body_index if content_body_index is not None else build_content_body_index(current)
    entries: list[dict[str, Any]] = []
    for run in sorted(p for p in root.iterdir() if p.is_dir()):
        run_id = run.name
        report = _load_json(ADMISSIONS_AUDIT_DIR / f"{run_id}.json") or {}
        canon_dir = run / "canon"
        reverse_dir = run / "reverse_html"
        bulk_bytes = 0
        unique_files: list[Path] = []
        if canon_dir.is_dir():
            bulk_bytes += _dir_bytes(canon_dir)
        if reverse_dir.is_dir():
            for f in reverse_dir.iterdir():
                if not f.is_file():
                    continue
                if f.name.endswith(".reverse-report.json"):
                    unique_files.append(f)
                else:
                    bulk_bytes += f.stat().st_size
        identity_check = (
            classify_snapshot_identity_aware(canon_dir, current, body_index)
            if canon_dir.is_dir()
            else {"record_count": 0, "unexplained_differences": 0, "unexplained_ids": [], "unique_historical_records": 0, "unique_historical_ids": []}
        )
        clean = not identity_check["unexplained_differences"] and not identity_check["unique_historical_records"]
        entries.append({
            "root": "session_admission",
            "run_id": run_id,
            "path": as_display_path(run),
            "canon_modified": report.get("canon_modified"),
            "canon_before_hash": report.get("canon_before_hash"),
            "canon_after_hash": report.get("canon_after_hash"),
            "durable_backup_present": (REPO_ROOT / "data/out/local/audit/admissions/backups" / run_id).is_dir(),
            "bulk_bytes": bulk_bytes,
            "unique_files": [as_display_path(f) for f in unique_files],
            "unique_bytes": sum(f.stat().st_size for f in unique_files),
            "identity_aware_check": identity_check,
            "retention_class": "SUPERSEDED_HISTORY" if clean else "INVESTIGATE_UNIQUE_CONTENT",
            "proposed_action_bulk": "DELETE_CANDIDATE" if clean else "INVESTIGATE",
            "proposed_action_unique": "EXTRACT_THEN_DELETE" if unique_files else None,
        })
    return entries


# --------------------------------------------------------------------------
# reconstruction / html_export: bulk canon/export payload + small per-run
# reports never duplicated durably (J.2-B).
# --------------------------------------------------------------------------

def classify_reconstruction(
    *,
    current_index: dict[str, dict[str, Any]] | None = None,
    content_body_index: dict[str, list[str]] | None = None,
) -> list[dict[str, Any]]:
    root = TMP_ROOT / "reconstruction"
    if not root.is_dir():
        return []
    current = current_index if current_index is not None else canon_records_by_id(DEFAULT_CANON_DIR)
    body_index = content_body_index if content_body_index is not None else build_content_body_index(current)
    entries: list[dict[str, Any]] = []
    for run in sorted(p for p in root.iterdir() if p.is_dir()):
        bulk_bytes = 0
        unique_files: list[Path] = []
        identity_checks = []
        for child in run.iterdir():
            if child.is_dir() and child.name in ("canon_before", "canon_after"):
                bulk_bytes += _dir_bytes(child)
                identity_checks.append(classify_snapshot_identity_aware(child, current, body_index))
            elif child.is_file():
                unique_files.append(child)
        clean = all(
            not c["unexplained_differences"] and not c["unique_historical_records"] for c in identity_checks
        ) if identity_checks else True
        entries.append({
            "root": "reconstruction",
            "run_id": run.name,
            "path": as_display_path(run),
            "bulk_bytes": bulk_bytes,
            "unique_files": [as_display_path(f) for f in unique_files],
            "unique_bytes": sum(f.stat().st_size for f in unique_files),
            "identity_aware_checks": identity_checks,
            "retention_class": "SUPERSEDED_HISTORY" if clean else "INVESTIGATE_UNIQUE_CONTENT",
            "proposed_action_bulk": "DELETE_CANDIDATE" if clean else "INVESTIGATE",
            "proposed_action_unique": "EXTRACT_THEN_DELETE" if unique_files else None,
        })
    return entries


def classify_html_export() -> list[dict[str, Any]]:
    root = TMP_ROOT / "html_export"
    if not root.is_dir():
        return []
    entries: list[dict[str, Any]] = []
    for run in sorted(p for p in root.iterdir() if p.is_dir()):
        bulk_bytes = 0
        unique_files: list[Path] = []
        for f in run.iterdir():
            if not f.is_file():
                continue
            if "manifest" in f.name and f.suffix == ".json":
                unique_files.append(f)
            else:
                bulk_bytes += f.stat().st_size
        entries.append({
            "root": "html_export",
            "run_id": run.name,
            "path": as_display_path(run),
            "bulk_bytes": bulk_bytes,
            "unique_files": [as_display_path(f) for f in unique_files],
            "unique_bytes": sum(f.stat().st_size for f in unique_files),
            # a raw export is always regenerable from current Canon on demand
            "retention_class": "RECONSTRUCTIBLE_BULK",
            "proposed_action_bulk": "DELETE_CANDIDATE",
            "proposed_action_unique": "EXTRACT_THEN_DELETE" if unique_files else None,
        })
    return entries


# --------------------------------------------------------------------------
# Direct patch operations: a one-off script applied a governed before/after
# patch directly to one or more Canon shards (dry-run + apply manifest
# pair), outside the admission/sanitation/recovery pipelines' own default
# paths. Detected generically by MANIFEST SCHEMA (operation + mode + source
# + candidate + source_sha256 + candidate_sha256 + changed_ids +
# canon_modified fields), not by hardcoded operation names -- any future
# one-off patch following this same shape is picked up automatically. The
# manifest itself is always small and kept; the backup/candidate shard
# copies it references are evaluated record-by-record with the same
# identity-aware comparator used everywhere else in this module, and are
# only proposed for deletion when every record in them is fully explained
# against current live Canon.
# --------------------------------------------------------------------------

_DIRECT_PATCH_MANIFEST_FIELDS = ("operation", "mode", "source", "candidate", "source_sha256", "candidate_sha256", "changed_ids", "canon_modified")


def classify_direct_patch_operations(
    *,
    current_index: dict[str, dict[str, Any]] | None = None,
    content_body_index: dict[str, list[str]] | None = None,
) -> list[dict[str, Any]]:
    current = current_index if current_index is not None else canon_records_by_id(DEFAULT_CANON_DIR)
    body_index = content_body_index if content_body_index is not None else build_content_body_index(current)
    entries: list[dict[str, Any]] = []
    seen_manifests: set[Path] = set()
    seen_refs: set[Path] = set()
    for manifest_path in TMP_ROOT.rglob("*.json"):
        manifest = _load_json(manifest_path)
        if not manifest or not all(k in manifest for k in _DIRECT_PATCH_MANIFEST_FIELDS):
            continue
        if manifest_path in seen_manifests:
            continue
        seen_manifests.add(manifest_path)
        entries.append({
            "root": "direct_patch_manifest",
            "run_id": manifest_path.stem,
            "path": as_display_path(manifest_path),
            "bytes": manifest_path.stat().st_size,
            "operation": manifest.get("operation"),
            "mode": manifest.get("mode"),
            "canon_modified": manifest.get("canon_modified"),
            "changed_ids": manifest.get("changed_ids"),
            "retention_class": "DURABLE_EVIDENCE",
            "proposed_action_bulk": "KEEP",
            "proposed_action_unique": None,
            "rationale": "small, complete governance record (hashes, changed ids, timestamp) of a direct patch operation",
        })
        for field in ("backup", "candidate"):
            ref = manifest.get(field)
            if not ref:
                continue
            ref_path = REPO_ROOT / ref
            if not ref_path.is_file():
                continue
            try:
                ref_path.relative_to(TMP_ROOT)
            except ValueError:
                continue
            if ref_path in seen_refs:
                continue
            seen_refs.add(ref_path)
            counts = Counter()
            unexplained: list[str] = []
            unique_hist: list[str] = []
            for record in _iter_shard_records(ref_path):
                category, _detail = classify_record_diff(record, current, body_index)
                counts[category] += 1
                if category == "UNEXPLAINED_CONTENT_DIFFERENCE":
                    unexplained.append(str(record.get("id")))
                elif category == "UNIQUE_HISTORICAL_CONTENT":
                    unique_hist.append(str(record.get("id")))
            fully_explained = not unexplained and not unique_hist
            entries.append({
                "root": "direct_patch_manifest",
                "run_id": f"{manifest_path.stem}/{field}",
                "path": as_display_path(ref_path),
                "bytes": ref_path.stat().st_size,
                "manifest": as_display_path(manifest_path),
                "record_disposition_counts": dict(counts),
                "unexplained_ids": unexplained,
                "unique_historical_ids": unique_hist,
                "retention_class": "SUPERSEDED_HISTORY" if fully_explained else "INVESTIGATE_UNIQUE_CONTENT",
                "proposed_action_bulk": "DELETE_CANDIDATE" if fully_explained else "INVESTIGATE",
                "proposed_action_unique": None,
                "rationale": (
                    f"every record in this {field} shard copy is exact-matched or an already-explained "
                    "evolution class against current live Canon; the operation's own manifest already "
                    "records what changed and why"
                    if fully_explained else
                    f"{len(unexplained)} unexplained + {len(unique_hist)} unique-historical record(s) -- do not delete"
                ),
            })
    return entries


# --------------------------------------------------------------------------
# Promoted evidence: any data/tmp path that some governed step has already
# additively copied, byte-verified, to a durable home under
# data/out/local/audit/ and recorded in a *promotion_receipt*.json there.
# Detected generically by scanning for that receipt shape (records with
# source/destination/sha256_source/sha256_destination/verified fields), not
# by hardcoding which paths were promoted -- any future promotion is picked
# up automatically the next time this runs.
# --------------------------------------------------------------------------

def classify_promoted_evidence(*, exclude_top_level_dirs: set[Path] | None = None) -> list[dict[str, Any]]:
    """Groups by top-level data/tmp directory (not per-file) so the result

    matches every other classifier's directory-level DELETE_CANDIDATE
    convention -- a directory is only proposed whole when EVERY file it
    currently contains has a verified promotion record; a partially-promoted
    directory is left INVESTIGATE rather than guessed at.

    ``exclude_top_level_dirs`` skips any directory a more specific classifier
    (e.g. classify_direct_patch_operations, which understands a manifest's
    KEEP-vs-DELETE_CANDIDATE split within one directory) already covers --
    otherwise the same physical bytes would be double-counted under two
    different, disagreeing verdicts.
    """
    exclude = exclude_top_level_dirs or set()
    by_dir: dict[Path, dict[str, Any]] = {}
    for receipt_path in DEFAULT_AUDIT_DIR.rglob("*promotion_receipt*.json"):
        receipt = _load_json(receipt_path)
        if not receipt or not isinstance(receipt.get("records"), list):
            continue
        for record in receipt["records"]:
            required = ("source", "destination", "sha256_source", "sha256_destination", "verified")
            if not all(k in record for k in required) or not record["verified"]:
                continue
            source_path = REPO_ROOT / record["source"]
            if not source_path.is_file():
                continue
            try:
                rel = source_path.relative_to(TMP_ROOT)
            except ValueError:
                continue
            dest_path = REPO_ROOT / record["destination"]
            still_verified = dest_path.is_file() and sha256_file(dest_path) == record["sha256_destination"] == sha256_file(source_path)
            top_level_dir = TMP_ROOT / rel.parts[0]
            if top_level_dir in exclude:
                continue
            bucket = by_dir.setdefault(top_level_dir, {"promoted_files": set(), "receipts": set(), "all_verified": True})
            bucket["promoted_files"].add(source_path)
            bucket["receipts"].add(receipt_path)
            bucket["all_verified"] = bucket["all_verified"] and still_verified

    entries: list[dict[str, Any]] = []
    for top_level_dir, bucket in by_dir.items():
        if not top_level_dir.is_dir():
            continue
        actual_files = {p for p in top_level_dir.rglob("*") if p.is_file()}
        fully_covered = bucket["all_verified"] and actual_files <= bucket["promoted_files"]
        entries.append({
            "root": "promoted_evidence",
            "run_id": top_level_dir.name,
            "path": as_display_path(top_level_dir),
            "bytes": _dir_bytes(top_level_dir),
            "promoted_file_count": len(bucket["promoted_files"]),
            "actual_file_count": len(actual_files),
            "receipts": sorted(as_display_path(p) for p in bucket["receipts"]),
            "retention_class": "SUPERSEDED_HISTORY" if fully_covered else "INVESTIGATE_UNIQUE_CONTENT",
            "proposed_action_bulk": "DELETE_CANDIDATE" if fully_covered else "INVESTIGATE",
            "proposed_action_unique": None,
            "rationale": (
                f"every file in this directory ({len(actual_files)}) has a hash-verified promotion "
                f"receipt; the durable copies re-verified byte-identical just now"
                if fully_covered else
                f"only {len(bucket['promoted_files'])}/{len(actual_files)} files have a verified "
                "promotion record, or re-verification failed -- do not delete until fully covered"
            ),
        })
    return entries


# --------------------------------------------------------------------------
# canonical_quality: operator_menu.py:option_canon_quality()'s Rust quality
# doctor. Diagnostic-only by the tool's own printed contract ("No escribe
# data/out/local; solo emite reportes bajo data/tmp/canonical_quality") --
# every run is two small, compact JSON reports, never a bulk Canon
# snapshot. Detected generically (any quality-* run dir under this root),
# not hardcoded to the one run that happens to exist today.
# --------------------------------------------------------------------------

def classify_canonical_quality() -> list[dict[str, Any]]:
    root = TMP_ROOT / "canonical_quality"
    if not root.is_dir():
        return []
    entries: list[dict[str, Any]] = []
    for run in sorted(p for p in root.iterdir() if p.is_dir()):
        files = [f for f in run.iterdir() if f.is_file()]
        size = sum(f.stat().st_size for f in files)
        entries.append({
            "root": "canonical_quality",
            "run_id": run.name,
            "path": as_display_path(run),
            "bytes": size,
            "file_count": len(files),
            "owner": "operator_menu.py:option_canon_quality (src/rust/doctor canonical-line-gate + deep-node-inspect)",
            "retention_class": "DURABLE_EVIDENCE",
            "proposed_action_bulk": "KEEP",
            "proposed_action_unique": None,
            "rationale": (
                "point-in-time Canon quality diagnostic; the tool's own contract is read-only "
                "against Canon and emits only small compact reports here, never a bulk snapshot. "
                "Not reconstructible byte-for-byte (re-running today reports on TODAY's Canon, not "
                "this historical state) but small enough (KB-scale per run) to retain as compact "
                "historical audit evidence rather than delete."
            ),
        })
    return entries


# --------------------------------------------------------------------------
# Ad-hoc reverse_tiddlers (Go bridge, src/go/bridge/reverse_tiddlers.go)
# manual verification bundles: detected by REPORT SCHEMA (mode +
# store_policy + html_input_path + canon_input_path + output_html_path),
# never by hardcoded filename, since these are by nature one-off
# invocations with custom output paths outside the tool's own default
# convention (path_governance.DEFAULT_REVERSE_HTML/_REPORT). A companion
# *.export.manifest.json elsewhere under data/tmp whose source_html_path
# matches this report's output_html_path is a round-trip verification of
# the same output and is grouped into the same bundle.
# --------------------------------------------------------------------------

_REVERSE_REPORT_REQUIRED_FIELDS = ("mode", "store_policy", "html_input_path", "canon_input_path", "output_html_path")


def _resolve_repo_relative(raw_path: str) -> Path:
    """These Go-tool-emitted paths are relative to the tool's own CWD, not

    REPO_ROOT -- but every one observed ends in a REPO_ROOT-relative tail
    once leading '../' segments are stripped, so strip them and resolve
    against REPO_ROOT rather than guessing the tool's exact CWD.
    """
    parts = [p for p in Path(raw_path).parts if p != ".."]
    return REPO_ROOT / Path(*parts) if parts else REPO_ROOT


def find_reverse_verification_bundles(tmp_root: Path = TMP_ROOT) -> list[dict[str, Any]]:
    bundles: list[dict[str, Any]] = []
    export_manifests = list(tmp_root.rglob("*.export.manifest.json"))
    for report_path in tmp_root.glob("*.json"):
        report = _load_json(report_path)
        if not report or not all(k in report for k in _REVERSE_REPORT_REQUIRED_FIELDS):
            continue
        canon_input = _resolve_repo_relative(report["canon_input_path"])
        output_html = _resolve_repo_relative(report["output_html_path"])
        companions: list[Path] = []
        for manifest_path in export_manifests:
            manifest = _load_json(manifest_path)
            if not manifest:
                continue
            source_html = manifest.get("source_html_path")
            if source_html and _resolve_repo_relative(source_html).resolve() == output_html.resolve():
                companions.append(manifest_path.parent)
        bundles.append({
            "report_path": report_path,
            "report": report,
            "canon_input_path": canon_input,
            "canon_input_still_exists": canon_input.exists(),
            "output_html_path": output_html,
            "output_html_still_exists": output_html.exists(),
            "companion_verification_dirs": companions,
        })
    return bundles


def classify_reverse_verification_bundles() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for bundle in find_reverse_verification_bundles():
        report_path: Path = bundle["report_path"]
        report_bytes = report_path.stat().st_size
        entries.append({
            "root": "reverse_verification_bundle",
            "run_id": report_path.stem,
            "path": as_display_path(report_path),
            "bytes": report_bytes,
            "owner": "src/go/bridge/cmd/reverse_tiddlers (manual invocation, custom output paths outside the tool's own default convention)",
            "mode": bundle["report"].get("mode"),
            "canon_input_path": as_display_path(bundle["canon_input_path"]),
            "canon_input_still_exists": bundle["canon_input_still_exists"],
            "retention_class": "DURABLE_EVIDENCE",
            "proposed_action_bulk": "KEEP",
            "proposed_action_unique": None,
            "rationale": "compact report (KB-scale) of a one-off manual reverse-verification run; retained regardless of the bulk payload's fate",
        })
        if bundle["output_html_still_exists"]:
            html_path = bundle["output_html_path"]
            superseded = not bundle["canon_input_still_exists"]
            entries.append({
                "root": "reverse_verification_bundle",
                "run_id": report_path.stem + "/output_html",
                "path": as_display_path(html_path),
                "bytes": html_path.stat().st_size,
                "owner": "src/go/bridge/cmd/reverse_tiddlers output (manual invocation)",
                "retention_class": "SUPERSEDED_HISTORY" if superseded else "INVESTIGATE_UNIQUE_CONTENT",
                "proposed_action_bulk": "DELETE_CANDIDATE" if superseded else "INVESTIGATE",
                "proposed_action_unique": None,
                "rationale": (
                    f"output of {report_path.name}; its canon_input_path "
                    f"({'no longer exists -- the historical Canon state it captured is already gone' if superseded else 'still exists on disk'}) "
                    "and nothing in this repo's source references this output path downstream"
                ),
            })
        for companion_dir in bundle["companion_verification_dirs"]:
            size = _dir_bytes(companion_dir)
            superseded = not bundle["canon_input_still_exists"]
            entries.append({
                "root": "reverse_verification_bundle",
                "run_id": companion_dir.name,
                "path": as_display_path(companion_dir),
                "bytes": size,
                "owner": "src/go/bridge (round-trip re-export verification of the same manual bundle's output_html)",
                "retention_class": "SUPERSEDED_HISTORY" if superseded else "INVESTIGATE_UNIQUE_CONTENT",
                "proposed_action_bulk": "DELETE_CANDIDATE" if superseded else "INVESTIGATE",
                "proposed_action_unique": None,
                "rationale": f"round-trip verification export of {report_path.name}'s output_html; same supersession status as that output",
            })
    return entries


# --------------------------------------------------------------------------
# sanitation: shape-based test-leak detection (J.2 found the leak by shape,
# not by date -- this must keep working if it recurs).
# --------------------------------------------------------------------------

def classify_sanitation(
    *,
    current_index: dict[str, dict[str, Any]] | None = None,
    content_body_index: dict[str, list[str]] | None = None,
) -> list[dict[str, Any]]:
    root = TMP_ROOT / "sanitation"
    if not root.is_dir():
        return []
    current = current_index if current_index is not None else canon_records_by_id(DEFAULT_CANON_DIR)
    body_index = content_body_index if content_body_index is not None else build_content_body_index(current)
    entries: list[dict[str, Any]] = []
    reports = sorted(root.glob("sanitation-*.json"))
    for backup in sorted(p for p in root.iterdir() if p.is_dir() and p.name.startswith("backup-")):
        shards = sorted_canon_shards(backup)
        size = _dir_bytes(backup)
        is_test_leak = len(shards) <= _SANITATION_TEST_LEAK_MAX_SHARDS and size <= _SANITATION_TEST_LEAK_MAX_BYTES
        matching_report = None
        if not is_test_leak:
            # a real backup's stamp (backup-<stamp>) matches a sanitation
            # plan file saved around the same run; look for one within a
            # tight window rather than assuming exact equality.
            stamp = backup.name.removeprefix("backup-")
            for report_path in reports:
                report_stamp = report_path.stem.removeprefix("sanitation-")
                if abs(int(report_stamp) - int(stamp)) < 200 if stamp.isdigit() and report_stamp.isdigit() else False:
                    matching_report = report_path
                    break
        identity_check = (
            {"record_count": 0, "unexplained_differences": 0, "unexplained_ids": [], "unique_historical_records": 0, "unique_historical_ids": []}
            if is_test_leak
            else classify_snapshot_identity_aware(backup, current, body_index)
        )
        clean = not identity_check["unexplained_differences"] and not identity_check["unique_historical_records"]
        if is_test_leak:
            retention_class = "EPHEMERAL_TEST"
            proposed_action = "DELETE_CANDIDATE"
            rationale = (
                f"shape matches the test-fixture leak in tests/test_canon_sanitation.py "
                f"(apply_elimination_plan(..., confirm=True) called without backup_dir=, "
                f"defaulting to DEFAULT_SANITATION_DIR) -- {len(shards)} shard(s), {size} bytes, "
                f"below the real-backup floor. Fixed at the source; existing leaked artifacts "
                f"are pure synthetic test content, zero production or rollback value."
            )
        elif clean:
            retention_class = "SUPERSEDED_HISTORY"
            proposed_action = "DELETE_CANDIDATE"
            rationale = (
                f"real production sanitation backup ({len(shards)} shard(s), {size} bytes); "
                f"every record it holds is identity-aware-explained (exact match, identity migration, "
                f"expected metadata/session evolution, or the deliberately-sanitized record itself) "
                f"against current live Canon; compact report "
                f"{'found: ' + as_display_path(matching_report) if matching_report else 'NOT found'}"
            )
        else:
            retention_class = "INVESTIGATE_UNIQUE_CONTENT"
            proposed_action = "INVESTIGATE"
            rationale = (
                f"real production backup carries {identity_check['unexplained_differences']} unexplained "
                f"and/or {identity_check['unique_historical_records']} unique-historical record(s) "
                f"(ids: {identity_check['unexplained_ids'] + identity_check['unique_historical_ids']}); do not delete"
            )
        entries.append({
            "root": "sanitation",
            "run_id": backup.name,
            "path": as_display_path(backup),
            "shard_count": len(shards),
            "bytes": size,
            "is_test_fixture_leak": is_test_leak,
            "matching_report": as_display_path(matching_report) if matching_report else None,
            "identity_aware_check": identity_check,
            "retention_class": retention_class,
            "proposed_action_bulk": proposed_action,
            "proposed_action_unique": None,
            "rationale": rationale,
        })
    return entries


# --------------------------------------------------------------------------
# session_sync: cross-checked against its own durable audit twin.
# --------------------------------------------------------------------------

def _active_admission_dependency(run_dir: Path) -> dict[str, Any] | None:
    """Does any admission report cite a candidate_file inside run_dir with

    no later report showing the same candidate already applied
    (canon_modified=true) or explicitly rejected? Found and required after
    S0186 Unit J.2's second cleanup precondition check caught exactly this:
    a session_sync entry whose durable twin (summary.json, a small
    manifest) existed, but whose real candidate files were the sole source
    for an admission still being validated, not yet applied or rejected.
    Never assume a durable twin alone means safe -- session_sync is the one
    root among these that can still be actively written to by a concurrent
    workflow.
    """
    run_dir_resolved = run_dir.resolve()
    hits: list[tuple[str, dict[str, Any]]] = []
    for report_path in sorted(ADMISSIONS_AUDIT_DIR.glob("*.json")):
        report = _load_json(report_path)
        if not report:
            continue
        candidate_file = str(report.get("candidate_file") or "")
        if not candidate_file:
            continue
        candidate_path = (REPO_ROOT / candidate_file).resolve()
        try:
            candidate_path.relative_to(run_dir_resolved)
        except ValueError:
            continue
        hits.append((report_path.name, report))
    if not hits:
        return None
    hits.sort(key=lambda h: h[1].get("timestamp") or h[0])
    latest_name, latest_report = hits[-1]
    if latest_report.get("canon_modified") is True:
        return None  # already applied -- no longer a pending dependency
    return {
        "latest_report": latest_name,
        "eligible_count": latest_report.get("eligible_count"),
        "canon_modified": latest_report.get("canon_modified"),
        "status": latest_report.get("status"),
        "reference_count": len(hits),
    }


def _session_sync_source_canon_hash(durable_twin: Path) -> str | None:
    summary = _load_json(durable_twin / "summary.json")
    return summary.get("source_canon_hash") if summary else None


def classify_session_sync(
    *,
    active_session_id: str = "S0186",
    current_canon_hash: str | None = None,
) -> list[dict[str, Any]]:
    root = TMP_ROOT / "session_sync"
    if not root.is_dir():
        return []
    current_canon_hash = current_canon_hash or _canon_hash(DEFAULT_CANON_DIR)
    entries: list[dict[str, Any]] = []
    for entry in sorted(p for p in root.iterdir() if p.is_dir()):
        durable_twin = SESSION_SYNC_AUDIT_DIR / entry.name
        durable_present = durable_twin.is_dir() and any(durable_twin.iterdir())
        session_label = quiescence_state._session_label(entry.name)
        is_active_session = session_label == active_session_id
        size = _dir_bytes(entry)
        active_dependency = _active_admission_dependency(entry)
        source_canon_hash = _session_sync_source_canon_hash(durable_twin) if durable_present else None
        # A same-named-session entry is only genuinely CURRENT if its
        # candidates were computed against the Canon that exists right now
        # (or it has an active pending-admission dependency, checked first).
        # An old session_sync run for the active session with a stale
        # source_canon_hash is exactly as superseded as any other historical
        # sync -- the session's own tag alone is not evidence of liveness.
        # This is what caught S0186's own 4-day-old canonization-check runs.
        is_fresh_for_active_session = is_active_session and source_canon_hash == current_canon_hash
        if active_dependency is not None:
            retention_class = "CURRENT_OPERATIONAL"
            proposed_action = "RETAIN_UNTIL_J_CLOSE"
            reason = "active_admission_dependency"
        elif is_fresh_for_active_session:
            retention_class = "CURRENT_OPERATIONAL"
            proposed_action = "RETAIN_UNTIL_J_CLOSE"
            reason = "active_session_and_source_canon_hash_matches_current"
        elif durable_present:
            retention_class = "SUPERSEDED_HISTORY"
            proposed_action = "DELETE_CANDIDATE"
            reason = (
                "active_session_tag_but_source_canon_hash_stale_and_no_admission_activity"
                if is_active_session else "durable_twin_present"
            )
        else:
            retention_class = "INVESTIGATE_NO_DURABLE_TWIN"
            proposed_action = "INVESTIGATE"
            reason = "no_durable_twin"
        entries.append({
            "root": "session_sync",
            "run_id": entry.name,
            "path": as_display_path(entry),
            "bytes": size,
            "durable_twin_present": durable_present,
            "durable_twin_path": as_display_path(durable_twin) if durable_present else None,
            "source_canon_hash": source_canon_hash,
            "current_canon_hash": current_canon_hash,
            "source_canon_hash_matches_current": source_canon_hash == current_canon_hash,
            "active_admission_dependency": active_dependency,
            "retention_class": retention_class,
            "proposed_action_bulk": proposed_action,
            "proposed_action_unique": None,
            "reason": reason,
        })
    return entries


# --------------------------------------------------------------------------
# Aggregate report
# --------------------------------------------------------------------------

def build_retention_report() -> dict[str, Any]:
    """Read-only. Never creates, deletes, moves or truncates a path."""
    current_index = canon_records_by_id(DEFAULT_CANON_DIR)
    body_index = build_content_body_index(current_index)
    current_canon_hash_value = _canon_hash(DEFAULT_CANON_DIR)
    session_admission = classify_session_admission(current_index=current_index, content_body_index=body_index)
    reconstruction = classify_reconstruction(current_index=current_index, content_body_index=body_index)
    html_export = classify_html_export()
    sanitation = classify_sanitation(current_index=current_index, content_body_index=body_index)
    session_sync = classify_session_sync(current_canon_hash=current_canon_hash_value)
    canonical_quality = classify_canonical_quality()
    reverse_verification_bundles = classify_reverse_verification_bundles()
    direct_patch_operations = classify_direct_patch_operations(current_index=current_index, content_body_index=body_index)
    # entry["path"] is as_display_path(manifest_path): relative to REPO_ROOT
    # when the manifest happens to live under it, else an absolute string --
    # TMP_ROOT itself may now be either, so resolve robustly rather than
    # assuming a literal "data/tmp" prefix (that assumption broke silently
    # for any entry found once TMP_ROOT moved off REPO_ROOT).
    direct_patch_dirs: set[Path] = set()
    for entry in direct_patch_operations:
        entry_path = Path(entry["path"])
        if not entry_path.is_absolute():
            entry_path = REPO_ROOT / entry_path
        try:
            top_level_name = entry_path.relative_to(TMP_ROOT).parts[0]
        except (ValueError, IndexError):
            continue
        direct_patch_dirs.add(TMP_ROOT / top_level_name)
    promoted_evidence = classify_promoted_evidence(exclude_top_level_dirs=direct_patch_dirs)

    def _bytes_by_action(entries: list[dict[str, Any]], bytes_key: str) -> dict[str, int]:
        totals: dict[str, int] = {}
        for entry in entries:
            action = entry.get("proposed_action_bulk") or "INVESTIGATE"
            totals[action] = totals.get(action, 0) + entry.get(bytes_key, 0)
            unique_action = entry.get("proposed_action_unique")
            if unique_action:
                totals[unique_action] = totals.get(unique_action, 0) + entry.get("unique_bytes", 0)
        return totals

    totals: dict[str, int] = {}
    for entries, bytes_key in (
        (session_admission, "bulk_bytes"),
        (reconstruction, "bulk_bytes"),
        (html_export, "bulk_bytes"),
        (sanitation, "bytes"),
        (canonical_quality, "bytes"),
        (reverse_verification_bundles, "bytes"),
        (direct_patch_operations, "bytes"),
        (promoted_evidence, "bytes"),
    ):
        for action, value in _bytes_by_action(entries, bytes_key).items():
            totals[action] = totals.get(action, 0) + value
    for entry in session_sync:
        action = entry["proposed_action_bulk"]
        totals[action] = totals.get(action, 0) + entry["bytes"]

    return {
        "schema_version": "tmp-lifecycle-governance-retention-report/v2",
        "generated_at": utc_now(),
        # S0187 D20: explicit visibility for which tmp root this report just
        # scanned and whether it currently exists -- an absent/empty active
        # root must be visible as such, never silently substituted with
        # historical_tmp_root.
        "active_tmp_root": {"path": str(TMP_ROOT), "exists": TMP_ROOT.is_dir()},
        "historical_tmp_root": str(HISTORICAL_TMP_ROOT),
        "canon_index_size": len(current_index),
        "current_canon_hash": current_canon_hash_value,
        "session_admission": session_admission,
        "reconstruction": reconstruction,
        "html_export": html_export,
        "sanitation": sanitation,
        "session_sync": session_sync,
        "canonical_quality": canonical_quality,
        "reverse_verification_bundles": reverse_verification_bundles,
        "direct_patch_operations": direct_patch_operations,
        "promoted_evidence": promoted_evidence,
        "totals_bytes_by_proposed_action": totals,
        "paths_created": 0,
        "paths_deleted": 0,
    }


# --------------------------------------------------------------------------
# Evidence extraction -- additive only, never deletes a source.
# --------------------------------------------------------------------------

@dataclass
class ExtractionRecord:
    source: str
    destination: str
    bytes: int
    sha256_source: str
    sha256_destination: str
    verified: bool
    already_extracted: bool


def extract_unique_evidence(report: dict[str, Any] | None = None, *, execute: bool = False) -> dict[str, Any]:
    """Copy every file classified EXTRACT_THEN_DELETE to a durable home

    under ``data/out/local/audit/tmp_lifecycle/extracted_evidence/``,
    preserving its relative path under ``data/tmp/``, and verify the copy
    byte-for-byte. Never deletes or modifies the source. ``execute=False``
    lists what would be copied without writing anything.
    """
    report = report or build_retention_report()
    candidates: list[Path] = []
    for group_key in ("session_admission", "reconstruction", "html_export"):
        for entry in report.get(group_key, []):
            for rel in entry.get("unique_files") or []:
                candidates.append(REPO_ROOT / rel)
    for entry in report.get("sanitation", []):
        rel = entry.get("matching_report")
        if rel:
            candidates.append(REPO_ROOT / rel)

    records: list[ExtractionRecord] = []
    for source in candidates:
        if not source.is_file():
            continue
        try:
            rel_to_tmp = source.relative_to(TMP_ROOT)
            destination = EXTRACTED_EVIDENCE_ROOT / rel_to_tmp
        except ValueError:
            # sanitation reports live directly under data/tmp/sanitation, already covered above
            destination = EXTRACTED_EVIDENCE_ROOT / source.relative_to(REPO_ROOT)
        source_hash = sha256_file(source)
        already = destination.is_file() and sha256_file(destination) == source_hash
        if execute and not already:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        dest_hash = sha256_file(destination) if destination.is_file() and (execute or already) else ""
        records.append(ExtractionRecord(
            source=as_display_path(source),
            destination=as_display_path(destination),
            bytes=source.stat().st_size,
            sha256_source=source_hash,
            sha256_destination=dest_hash,
            verified=(dest_hash == source_hash) if dest_hash else False,
            already_extracted=already,
        ))

    result = {
        "schema_version": "tmp-lifecycle-evidence-extraction/v1",
        "generated_at": utc_now(),
        "executed": execute,
        "candidate_count": len(records),
        "extracted_count": sum(1 for r in records if r.verified and not r.already_extracted),
        "already_extracted_count": sum(1 for r in records if r.already_extracted),
        "total_bytes": sum(r.bytes for r in records),
        "records": [r.__dict__ for r in records],
    }
    if execute:
        RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
        receipt_path = RECEIPTS_DIR / f"extraction-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.json"
        receipt_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        result["receipt_path"] = as_display_path(receipt_path)
    return result


# --------------------------------------------------------------------------
# Productive cleanup: dry-run always safe; execute is phrase-gated.
# --------------------------------------------------------------------------

def _delete_candidate_paths(report: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for entry in report.get("session_admission", []):
        if entry["proposed_action_bulk"] == "DELETE_CANDIDATE":
            items.append({
                "path": entry["path"], "root": "session_admission", "run_id": entry["run_id"],
                "bytes": entry["bulk_bytes"], "classification": entry["retention_class"],
                "note": "canon/ + *.derived.html only -- unique reverse-report.json must be extracted first and excluded from this path's deletion by deleting canon/ and reverse_html/*.derived.html individually, not the run directory wholesale, unless extraction is already verified",
            })
    for entry in report.get("reconstruction", []):
        if entry["proposed_action_bulk"] == "DELETE_CANDIDATE":
            items.append({
                "path": entry["path"], "root": "reconstruction", "run_id": entry["run_id"],
                "bytes": entry["bulk_bytes"], "classification": entry["retention_class"],
                "note": "canon_before/ + canon_after/ only, not the run directory's report files",
            })
    for entry in report.get("html_export", []):
        if entry["proposed_action_bulk"] == "DELETE_CANDIDATE":
            items.append({
                "path": entry["path"], "root": "html_export", "run_id": entry["run_id"],
                "bytes": entry["bulk_bytes"], "classification": entry["retention_class"],
                "note": "export.jsonl + export.log only, not manifest.json",
            })
    for entry in report.get("sanitation", []):
        if entry["proposed_action_bulk"] == "DELETE_CANDIDATE":
            items.append({
                "path": entry["path"], "root": "sanitation", "run_id": entry["run_id"],
                "bytes": entry["bytes"], "classification": entry["retention_class"],
                "note": entry["rationale"],
            })
    for entry in report.get("session_sync", []):
        if entry["proposed_action_bulk"] == "DELETE_CANDIDATE":
            items.append({
                "path": entry["path"], "root": "session_sync", "run_id": entry["run_id"],
                "bytes": entry["bytes"], "classification": entry["retention_class"],
                "note": f"{entry.get('reason', '')} -- durable twin at {entry['durable_twin_path']}",
            })
    for entry in report.get("reverse_verification_bundles", []):
        if entry["proposed_action_bulk"] == "DELETE_CANDIDATE":
            items.append({
                "path": entry["path"], "root": "reverse_verification_bundle", "run_id": entry["run_id"],
                "bytes": entry["bytes"], "classification": entry["retention_class"],
                "note": entry["rationale"],
            })
    for entry in report.get("direct_patch_operations", []):
        if entry["proposed_action_bulk"] == "DELETE_CANDIDATE":
            items.append({
                "path": entry["path"], "root": "direct_patch_manifest", "run_id": entry["run_id"],
                "bytes": entry["bytes"], "classification": entry["retention_class"],
                "note": entry["rationale"],
            })
    for entry in report.get("promoted_evidence", []):
        if entry["proposed_action_bulk"] == "DELETE_CANDIDATE":
            items.append({
                "path": entry["path"], "root": "promoted_evidence", "run_id": entry["run_id"],
                "bytes": entry["bytes"], "classification": entry["retention_class"],
                "note": entry["rationale"],
            })
    return items


def _plan_hash(items: list[dict[str, Any]]) -> str:
    canonical = json.dumps(
        [{"path": i["path"], "bytes": i["bytes"]} for i in sorted(items, key=lambda i: i["path"])],
        sort_keys=True, separators=(",", ":"),
    )
    return sha256_bytes(canonical.encode("utf-8"))


def _unique_file_already_extracted(source: Path) -> bool:
    if not source.is_file():
        return False
    try:
        rel_to_tmp = source.relative_to(TMP_ROOT)
        destination = EXTRACTED_EVIDENCE_ROOT / rel_to_tmp
    except ValueError:
        destination = EXTRACTED_EVIDENCE_ROOT / source.relative_to(REPO_ROOT)
    return destination.is_file() and sha256_file(destination) == sha256_file(source)


def dry_run_cleanup(report: dict[str, Any] | None = None) -> dict[str, Any]:
    """Never deletes anything. Computes exactly what an execute_cleanup call

    with the returned ``plan_hash`` would remove.
    """
    report = report or build_retention_report()
    items = _delete_candidate_paths(report)
    plan_hash = _plan_hash(items)
    unextracted_unique = 0
    for group in ("session_admission", "reconstruction", "html_export"):
        for entry in report.get(group, []):
            if entry.get("proposed_action_unique") != "EXTRACT_THEN_DELETE":
                continue
            for rel in entry.get("unique_files") or []:
                if not _unique_file_already_extracted(REPO_ROOT / rel):
                    unextracted_unique += (REPO_ROOT / rel).stat().st_size
    return {
        "schema_version": "tmp-lifecycle-dry-run/v1",
        "generated_at": utc_now(),
        "plan_hash": plan_hash,
        "authorization_phrase": f"{AUTHORIZATION_PHRASE_PREFIX} {plan_hash}",
        "item_count": len(items),
        "total_bytes": sum(i["bytes"] for i in items),
        "items": items,
        "unextracted_unique_evidence_bytes": unextracted_unique,
        "warning_unextracted_evidence": (
            "unique evidence has not been fully extracted -- run extract_unique_evidence(execute=True) first"
            if unextracted_unique else None
        ),
        "executed": False,
    }


def execute_cleanup(authorization_phrase: str, *, dry_run_plan: dict[str, Any] | None = None) -> dict[str, Any]:
    """Deletes exactly the paths in a freshly-recomputed dry run whose

    plan_hash matches the one embedded in ``authorization_phrase``. Refuses
    if the live state has drifted from the plan (paths changed size, new
    DELETE_CANDIDATEs appeared, etc.) -- the human must re-run the dry-run
    and re-authorize, never partially apply a stale plan.
    """
    fresh = dry_run_cleanup()
    expected_phrase = fresh["authorization_phrase"]
    if authorization_phrase != expected_phrase:
        return {
            "status": "rejected",
            "reason": "authorization_phrase does not match a freshly-recomputed dry-run plan_hash",
            "expected_phrase": expected_phrase,
            "received_phrase": authorization_phrase,
            "executed": False,
        }
    if dry_run_plan is not None and dry_run_plan.get("plan_hash") != fresh["plan_hash"]:
        return {
            "status": "rejected",
            "reason": "live state has drifted since the dry-run plan was shown to the human; re-run dry_run_cleanup",
            "executed": False,
        }
    if fresh["unextracted_unique_evidence_bytes"]:
        return {
            "status": "rejected",
            "reason": "unique evidence not yet extracted; run extract_unique_evidence(execute=True) first",
            "executed": False,
        }

    deleted: list[dict[str, Any]] = []
    for item in fresh["items"]:
        path = REPO_ROOT / item["path"]
        bytes_before = item["bytes"]
        if path.exists():
            shutil.rmtree(path) if path.is_dir() else path.unlink()
        deleted.append({**item, "bytes_before": bytes_before, "deleted_at": utc_now(), "deletion_status": "deleted"})

    receipt = {
        "schema_version": "tmp-lifecycle-cleanup-receipt/v1",
        "plan_hash": fresh["plan_hash"],
        "executed_at": utc_now(),
        "deleted_count": len(deleted),
        "bytes_reclaimed": sum(d["bytes_before"] for d in deleted),
        "deletions": deleted,
    }
    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
    receipt_path = RECEIPTS_DIR / f"cleanup-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, ensure_ascii=False), encoding="utf-8")
    receipt["receipt_path"] = as_display_path(receipt_path)
    receipt["status"] = "ok"
    receipt["executed"] = True
    return receipt
