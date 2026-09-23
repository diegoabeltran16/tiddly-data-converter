#!/usr/bin/env python3
"""Governed recovery of canonical content whose authority is proven from

certified historical evidence.

This is deliberately narrow. It exists to resolve exactly three contractual
classes of Canon damage, all demonstrated (not hypothesized) during S0186
Unit I's RAG equivalence investigation and its aftermath:

  RESTORE_MISSING_SAME_ID
      A record that was historically canonical disappeared from Canon
      CURRENT under an unidentified process, but a certified historical
      backup proves its identity and content. Restore it under the exact
      same id -- never a new one.

  REPAIR_EXISTING_TARGET_FROM_PROVEN_PREDECESSOR
      Canon CURRENT already contains the correct target of a governed
      reorganization (e.g. a bibliography renumbering), but that target's
      content is empty. A certified historical predecessor proves what the
      content should be. Recover only the content fields onto the existing
      CURRENT identity -- never reintroduce the predecessor as a second
      record, never silently replace the whole record.

  RECOMPUTE_INVALID_VERSION_ID
      Canon CURRENT already contains the correct target, but its
      version_id was computed with a since-fixed, non-contractual shape
      and `canon_preflight --mode strict` proves it inconsistent. Recompute
      ONLY version_id, exclusively from the target's own CURRENT fields via
      the same identity contract every other producer uses -- never a
      manually-supplied value, never any other field.

This module is NOT a general Canon editor, patch engine, or migration
framework. RESTORE_MISSING_SAME_ID and REPAIR_EXISTING_TARGET accept only
certified evidence (paths under the governed `data/out/local/audit/` tree,
or an explicitly-labelled corroborating `data/in/` artifact for MODE A),
never freely-supplied text; RECOMPUTE_INVALID_VERSION_ID accepts no
external evidence at all -- it is a pure function of the target's own
CURRENT record. Every operation is planned, dry-run-able, bound to a
one-shot authorization, and reversible byte-for-byte.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from rag_derivation_profile import stable_json  # noqa: E402
from normalize_session_titles import _recompute_version_id as _tdc_recompute_version_id  # noqa: E402
from path_governance import DEFAULT_AUDIT_DIR, DEFAULT_LOCAL_OUT_DIR  # noqa: E402

SCHEMA_PLAN = "canon-content-recovery-plan/v1"
SCHEMA_AUTHORIZATION = "canon-content-recovery-authorization/v1"
SCHEMA_APPLY_RECEIPT = "canon-content-recovery-apply-receipt/v1"
SCHEMA_ROLLBACK = "canon-content-recovery-rollback/v1"

MODE_RESTORE_MISSING_SAME_ID = "RESTORE_MISSING_SAME_ID"
MODE_REPAIR_EXISTING_TARGET = "REPAIR_EXISTING_TARGET_FROM_PROVEN_PREDECESSOR"
# Narrow third mode (S0186 Unit I, version_id contract-violation correction):
# a CURRENT record's version_id was computed with a since-fixed, incorrect
# shape and no longer matches the TDC identity contract. This mode
# recomputes ONLY version_id, exclusively from the target's own CURRENT
# fields via the same contract every other producer uses -- never a
# manually-supplied value, never any other field. It is not a general
# "recompute any derived field" tool.
MODE_RECOMPUTE_INVALID_VERSION_ID = "RECOMPUTE_INVALID_VERSION_ID"
VALID_MODES = (MODE_RESTORE_MISSING_SAME_ID, MODE_REPAIR_EXISTING_TARGET, MODE_RECOMPUTE_INVALID_VERSION_ID)

REASON_HISTORICAL_CANON_RECORD_MISSING = "HISTORICAL_CANON_RECORD_MISSING"
REASON_CURRENT_TARGET_CONTENT_EMPTY = "CURRENT_TARGET_CONTENT_EMPTY"
REASON_GOVERNED_CONTENT_RECOVERY = "GOVERNED_CONTENT_RECOVERY"
REASON_VERSION_ID_CONTRACT_VIOLATION = "VERSION_ID_CONTRACT_VIOLATION"
VALID_REASON_CODES = (
    REASON_HISTORICAL_CANON_RECORD_MISSING,
    REASON_CURRENT_TARGET_CONTENT_EMPTY,
    REASON_GOVERNED_CONTENT_RECOVERY,
    REASON_VERSION_ID_CONTRACT_VIOLATION,
)

# S0187 D23-A: these were hardcoded REPO_ROOT-relative literals -- dead at
# the real operator_menu.py call site (which passes its own governed
# DEFAULT_CANON_DIR explicitly), but live as this script's own --canon-dir
# CLI default for direct standalone invocation. Migrated to preserve that
# capability without narrowing its configurability.
DEFAULT_CANON_DIR = DEFAULT_LOCAL_OUT_DIR
CERTIFIED_EVIDENCE_ROOT = DEFAULT_AUDIT_DIR
# data/in is deliberately repo-pinned, never workspace-relative -- unchanged.
CORROBORATING_EVIDENCE_ROOT = REPO_ROOT / "data" / "in"
CANON_GO_DIR = REPO_ROOT / "src" / "go" / "canon"

# Fields MODE B may copy from a proven predecessor. Everything else on the
# CURRENT target -- identity, title, tags, relations, position -- is the
# authoritative, governed-reorganization state and is never overwritten.
RECOVERABLE_CONTENT_FIELDS = ("text", "content", "modality")
RECOMPUTED_FIELDS = ("version_id",)

AUTHORIZATION_PHRASE_PREFIX = "CONFIRM CANON CONTENT RECOVERY"


class RecoveryPlanError(ValueError):
    """A candidate operation fails a MODE A/B invariant; no plan is built."""


class RecoveryAuthorizationError(ValueError):
    """An authorization does not bind to the plan/canon/sources presented."""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_path(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _record_hash(record: dict[str, Any]) -> str:
    return sha256_bytes(stable_json(record).encode("utf-8"))


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _canon_shards(canon_dir: Path) -> list[Path]:
    return sorted(Path(p) for p in glob.glob(str(canon_dir / "tiddlers_*.jsonl")))


def _iter_shard_records(path: Path) -> list[dict[str, Any]]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}: non-object canon line")
        records.append(value)
    return records


def load_canon_index(canon_dir: Path) -> dict[str, tuple[dict[str, Any], Path]]:
    """Map every canon id to its record and owning shard. Duplicate ids in

    CURRENT canon are a pre-existing integrity fault this tool refuses to
    build a plan against.
    """

    index: dict[str, tuple[dict[str, Any], Path]] = {}
    for shard in _canon_shards(canon_dir):
        for record in _iter_shard_records(shard):
            record_id = str(record.get("id") or "")
            if not record_id:
                continue
            if record_id in index:
                raise RecoveryPlanError(f"duplicate canon id already present before planning: {record_id}")
            index[record_id] = (record, shard)
    return index


def canon_snapshot(canon_dir: Path) -> dict[str, Any]:
    shards = _canon_shards(canon_dir)
    digest = hashlib.sha256()
    records = 0
    for shard in shards:
        content = shard.read_bytes()
        digest.update(content)
        records += sum(1 for line in content.splitlines() if line.strip())
    return {"hash": digest.hexdigest(), "records": records, "shards": len(shards)}


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _is_record_empty(record: dict[str, Any]) -> bool:
    text = record.get("text")
    content = record.get("content")
    return not text and not content


# ---------------------------------------------------------------------------
# Evidence resolution
# ---------------------------------------------------------------------------


@dataclass
class RecoverySource:
    path: str
    artifact_type: str
    artifact_sha256: str
    record_id: str
    record_hash: str
    version_hash: str | None
    timestamp: str | None
    provenance_classification: str  # "certified" | "corroborating"

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "artifact_type": self.artifact_type,
            "artifact_sha256": self.artifact_sha256,
            "record_id": self.record_id,
            "record_hash": self.record_hash,
            "version_hash": self.version_hash,
            "timestamp": self.timestamp,
            "provenance_classification": self.provenance_classification,
        }


def _find_record_in_jsonl(path: Path, record_id: str) -> dict[str, Any] | None:
    for record in _iter_shard_records(path):
        if str(record.get("id") or "") == record_id:
            return record
    return None


def resolve_certified_source(
    path: Path, record_id: str, *, certified_root: Path = CERTIFIED_EVIDENCE_ROOT
) -> RecoverySource:
    """Load a record from a certified evidence artifact (must live under

    ``certified_root``, ``data/out/local/audit/`` by default) and prove it
    actually contains ``record_id``.
    """

    if not path.exists():
        raise RecoveryPlanError(f"source artifact does not exist: {path}")
    if not _is_under(path, certified_root):
        raise RecoveryPlanError(
            f"source artifact is not certified evidence (must be under {certified_root}): {path}"
        )
    record = _find_record_in_jsonl(path, record_id)
    if record is None:
        raise RecoveryPlanError(f"record {record_id} not found in certified source {path}")
    artifact_sha256 = sha256_path(path)
    timestamp = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return RecoverySource(
        path=str(path),
        artifact_type="certified_audit_evidence",
        artifact_sha256=artifact_sha256,
        record_id=record_id,
        record_hash=_record_hash(record),
        version_hash=record.get("version_id"),
        timestamp=timestamp,
        provenance_classification="certified",
    )


def _extract_comparable_payload(raw: Any) -> Any:
    """Best-effort structural normalization for corroboration only: parse

    JSON where possible, and unwrap the common TiddlyWiki single-tiddler
    export shape (a one-item list whose ``text`` field is itself a JSON
    string) one level deep. Never used to accept content on its own --
    only to prove a corroborating artifact agrees with a certified one.
    """

    value = raw
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return raw
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict) and "text" in value[0]:
        inner = value[0]["text"]
        if isinstance(inner, str):
            try:
                return json.loads(inner)
            except json.JSONDecodeError:
                return value
    return value


def check_corroborating_source(
    corroborating_path: Path,
    certified_source: RecoverySource,
    *,
    corroborating_root: Path = CORROBORATING_EVIDENCE_ROOT,
) -> dict[str, Any]:
    """Verify a `data/in/`-shaped artifact structurally agrees with the

    certified source's own record content. Raises if it exists but
    disagrees -- corroboration must corroborate, never silently be ignored.
    """

    if not corroborating_path.exists():
        raise RecoveryPlanError(f"corroborating artifact does not exist: {corroborating_path}")
    if not _is_under(corroborating_path, corroborating_root):
        raise RecoveryPlanError(
            f"corroborating artifact must be under {corroborating_root}: {corroborating_path}"
        )
    raw_corroborating = corroborating_path.read_bytes()
    corroborating_payload = _extract_comparable_payload(raw_corroborating)
    certified_record_obj = _find_record_in_jsonl(Path(certified_source.path), certified_source.record_id)
    certified_payload = _extract_comparable_payload(certified_record_obj.get("text")) if certified_record_obj else None
    agrees = certified_payload is not None and certified_payload == corroborating_payload
    if not agrees:
        raise RecoveryPlanError(
            f"corroborating artifact {corroborating_path} does not structurally match certified source "
            f"{certified_source.path} for record {certified_source.record_id}"
        )
    return {
        "path": str(corroborating_path),
        "artifact_type": "corroborating_data_in",
        "artifact_sha256": sha256_bytes(raw_corroborating),
        "record_id": certified_source.record_id,
        "record_hash": None,
        "version_hash": None,
        "timestamp": datetime.fromtimestamp(corroborating_path.stat().st_mtime, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "provenance_classification": "corroborating",
        "agrees_with_certified": True,
    }


def check_no_divergent_sources(record_id: str, candidate_paths: list[Path]) -> None:
    """If more than one certified artifact is offered for the same record

    id, every one of them must agree on content. Divergence is exactly the
    kind of ambiguity this tool refuses to resolve automatically.
    """

    hashes: dict[str, Path] = {}
    for path in candidate_paths:
        record = _find_record_in_jsonl(path, record_id)
        if record is None:
            continue
        record_hash = _record_hash(record)
        if hashes and record_hash not in hashes:
            (other_hash, other_path) = next(iter(hashes.items()))
            raise RecoveryPlanError(
                f"divergent certified evidence for {record_id}: {other_path} (hash {other_hash[:12]}...) "
                f"disagrees with {path} (hash {record_hash[:12]}...)"
            )
        hashes.setdefault(record_hash, path)


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------


@dataclass
class RecoveryOperation:
    operation_id: str
    operation_mode: str
    source_record_id: str
    target_record_id: str
    source_artifact: str
    source_artifact_sha256: str
    source_record_hash: str
    target_before_exists: bool
    target_before_hash: str | None
    expected_target_after_hash: str
    expected_identity: str
    expected_record_count_delta: int
    affected_shard: str
    provenance_evidence: list[dict[str, Any]]
    ambiguity_status: str
    authorization_required: bool
    rollback_snapshot: str | None
    reason_code: str
    recovered_record: dict[str, Any] = field(repr=False)
    fields_preserved_from_current: list[str] = field(default_factory=list)
    fields_recovered_from_history: list[str] = field(default_factory=list)
    fields_recomputed: list[str] = field(default_factory=list)
    fields_untouched: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "operation_mode": self.operation_mode,
            "source_record_id": self.source_record_id,
            "target_record_id": self.target_record_id,
            "source_artifact": self.source_artifact,
            "source_artifact_sha256": self.source_artifact_sha256,
            "source_record_hash": self.source_record_hash,
            "target_before_exists": self.target_before_exists,
            "target_before_hash": self.target_before_hash,
            "expected_target_after_hash": self.expected_target_after_hash,
            "expected_identity": self.expected_identity,
            "expected_record_count_delta": self.expected_record_count_delta,
            "affected_shard": self.affected_shard,
            "provenance_evidence": self.provenance_evidence,
            "ambiguity_status": self.ambiguity_status,
            "authorization_required": self.authorization_required,
            "rollback_snapshot": self.rollback_snapshot,
            "reason_code": self.reason_code,
            "fields_preserved_from_current": self.fields_preserved_from_current,
            "fields_recovered_from_history": self.fields_recovered_from_history,
            "fields_recomputed": self.fields_recomputed,
            "fields_untouched": self.fields_untouched,
        }


def _operation_id(mode: str, target_id: str, source_record_hash: str = "", expected_after_hash: str = "") -> str:
    # Deterministic: the same claimed recovery (mode + target + source
    # content + the resulting record it commits to) always yields the same
    # operation id, so re-planning is idempotent and an authorization's
    # binding is reproducible. expected_after_hash is included -- not just
    # mode/target/source -- because that is the actual binding-relevant
    # commitment of the operation; two operations that agree on
    # mode+target+source but would materialize a DIFFERENT record (e.g. a
    # different recoverable_fields selection) must never collide onto the
    # same operation id, since plan_id and every authorization bind to
    # these ids as the identity of "what will be mutated".
    return "ccr_op_" + hashlib.sha256(
        f"{mode}:{target_id}:{source_record_hash}:{expected_after_hash}".encode()
    ).hexdigest()[:16]


def build_restore_missing_operation(
    *,
    target_record_id: str,
    certified_source_path: Path,
    canon_dir: Path = DEFAULT_CANON_DIR,
    corroborating_source_path: Path | None = None,
    other_certified_paths_for_divergence_check: list[Path] | None = None,
    certified_root: Path = CERTIFIED_EVIDENCE_ROOT,
    corroborating_root: Path = CORROBORATING_EVIDENCE_ROOT,
) -> RecoveryOperation:
    """MODE A: RESTORE_MISSING_SAME_ID."""

    canon_index = load_canon_index(canon_dir)

    # Invariant 1: target absent from CURRENT canon.
    if target_record_id in canon_index:
        raise RecoveryPlanError(
            f"target {target_record_id} already exists in CURRENT canon; STALE plan, refusing RESTORE_MISSING_SAME_ID"
        )

    source = resolve_certified_source(certified_source_path, target_record_id, certified_root=certified_root)

    # Invariant 2: source id == target id (resolve_certified_source already
    # only finds a record whose own id matches, so this holds by construction).
    if source.record_id != target_record_id:
        raise RecoveryPlanError("source record id does not match target id")

    # Invariant 8: no divergent certified sources for this id.
    divergence_candidates = [certified_source_path] + list(other_certified_paths_for_divergence_check or [])
    check_no_divergent_sources(target_record_id, divergence_candidates)

    recovered_record = _find_record_in_jsonl(certified_source_path, target_record_id)
    assert recovered_record is not None

    # Invariant 6: no title/key/canonical_slug collision with a different id.
    for identity_field in ("title", "key", "canonical_slug"):
        value = recovered_record.get(identity_field)
        if not value:
            continue
        for other_id, (other_record, _) in canon_index.items():
            if other_record.get(identity_field) == value:
                raise RecoveryPlanError(
                    f"{identity_field} collision: recovered record's {identity_field}={value!r} "
                    f"already belongs to a different CURRENT id {other_id}"
                )

    # Invariant 7: recovered record satisfies the current minimum schema
    # (must at least carry id/title/text-or-content); a fuller schema
    # upgrade is out of this tool's narrow scope and is left as an explicit,
    # visible field-preservation record rather than silently patched.
    if not recovered_record.get("id") or not recovered_record.get("title"):
        raise RecoveryPlanError("recovered record fails minimum schema (missing id or title)")

    provenance_evidence = [source.to_dict()]
    if corroborating_source_path is not None:
        provenance_evidence.append(
            check_corroborating_source(corroborating_source_path, source, corroborating_root=corroborating_root)
        )

    # Affected shard: reuse the shard name the record historically lived in
    # when a same-named shard already exists in CURRENT canon; otherwise the
    # lowest-numbered existing shard, keeping shard topology stable.
    shards = _canon_shards(canon_dir)
    historical_shard_name = None
    # infer from source_anchor if present in the recovered record
    anchor = recovered_record.get("source_anchor")
    if isinstance(anchor, dict) and anchor.get("shard_file"):
        historical_shard_name = str(anchor["shard_file"])
    affected_shard = str(canon_dir / historical_shard_name) if historical_shard_name and (canon_dir / historical_shard_name) in shards else str(shards[0])

    expected_after_hash = _record_hash(recovered_record)

    return RecoveryOperation(
        operation_id=_operation_id(MODE_RESTORE_MISSING_SAME_ID, target_record_id, source.record_hash, expected_after_hash),
        operation_mode=MODE_RESTORE_MISSING_SAME_ID,
        source_record_id=source.record_id,
        target_record_id=target_record_id,
        source_artifact=source.path,
        source_artifact_sha256=source.artifact_sha256,
        source_record_hash=source.record_hash,
        target_before_exists=False,
        target_before_hash=None,
        expected_target_after_hash=expected_after_hash,
        expected_identity=target_record_id,
        expected_record_count_delta=1,
        affected_shard=affected_shard,
        provenance_evidence=provenance_evidence,
        ambiguity_status="none",
        authorization_required=True,
        rollback_snapshot=None,
        reason_code=REASON_HISTORICAL_CANON_RECORD_MISSING,
        recovered_record=recovered_record,
        fields_recovered_from_history=sorted(recovered_record.keys()),
    )


def _repair_record_fields(
    target_record: dict[str, Any],
    predecessor_record: dict[str, Any],
    recoverable_fields: tuple[str, ...] = RECOVERABLE_CONTENT_FIELDS,
) -> tuple[dict[str, Any], list[str]]:
    """Pure MODE B repair step: copy each recoverable field from the

    predecessor onto the target only where it actually differs -- the
    CURRENT target owns everything else, unconditionally. This is the ONE
    materialization used both when a plan is first built
    (``build_repair_existing_operation``) and when a persisted plan is
    reloaded for dry-run/apply (``materialize_recovered_record``), so the
    two can never diverge into a producer-parity bug.
    """

    repaired = dict(target_record)
    recovered: list[str] = []
    for key in recoverable_fields:
        if key in predecessor_record and predecessor_record[key] != target_record.get(key):
            repaired[key] = predecessor_record[key]
            recovered.append(key)
    return repaired, recovered


def _recompute_version_id_if_recovered(record: dict[str, Any], fields_recovered: list[str]) -> bool:
    """Recompute ``version_id`` per the TDC identity contract (S34 §14.5:

    sha256 of canonical_json({key, title, text, created, modified})) --
    the SAME formula the Go canon_preflight strict validator and
    normalize_session_titles.py use, via ``_tdc_recompute_version_id`` --
    never a locally-invented shape. This corrects a real defect: an
    earlier version of this module recomputed version_id from
    {text, content, modality}, which does not match the TDC contract and
    produced a version_id that fails ``canon_preflight --mode strict``.

    Only recomputes when something was actually recovered from history --
    an unmodified target keeps its CURRENT version_id untouched. Mutates
    ``record`` in place and returns whether it recomputed anything, so
    callers can record "version_id" in fields_recomputed consistently.
    """

    if not fields_recovered:
        return False
    record["version_id"] = _tdc_recompute_version_id(
        record.get("key"), record.get("title"), record.get("text"), record.get("created"), record.get("modified")
    )
    return True


def build_repair_existing_operation(
    *,
    target_record_id: str,
    predecessor_record_id: str,
    predecessor_certified_source_path: Path,
    canon_dir: Path = DEFAULT_CANON_DIR,
    recoverable_fields: tuple[str, ...] = RECOVERABLE_CONTENT_FIELDS,
    other_certified_paths_for_divergence_check: list[Path] | None = None,
    certified_root: Path = CERTIFIED_EVIDENCE_ROOT,
) -> RecoveryOperation:
    """MODE B: REPAIR_EXISTING_TARGET_FROM_PROVEN_PREDECESSOR.

    The predecessor id is supplied explicitly by the caller (a human/session
    decision, e.g. "this bibliography item was renumbered"), never inferred
    by fuzzy content matching -- this tool verifies a claimed continuity, it
    does not discover one.
    """

    canon_index = load_canon_index(canon_dir)

    # Invariant 1: target exists in CURRENT canon.
    if target_record_id not in canon_index:
        raise RecoveryPlanError(f"target {target_record_id} does not exist in CURRENT canon")
    target_record, target_shard = canon_index[target_record_id]

    # Invariant 2: target is empty under the contractual definition.
    if not _is_record_empty(target_record):
        raise RecoveryPlanError(
            f"target {target_record_id} is not empty; REPAIR_EXISTING_TARGET_FROM_PROVEN_PREDECESSOR "
            "only applies to a content-empty CURRENT target"
        )

    # Invariant 8: the predecessor must not itself still be a live CURRENT
    # canon identity -- this operation repairs a target, it never
    # reintroduces the predecessor as a second record.
    if predecessor_record_id in canon_index:
        raise RecoveryPlanError(
            f"predecessor {predecessor_record_id} is still present in CURRENT canon; "
            "REPAIR_EXISTING_TARGET_FROM_PROVEN_PREDECESSOR never reintroduces it as a second record"
        )
    if predecessor_record_id == target_record_id:
        raise RecoveryPlanError("predecessor id must differ from target id")

    # Invariant 3+4: predecessor has non-empty, certified content.
    source = resolve_certified_source(predecessor_certified_source_path, predecessor_record_id, certified_root=certified_root)
    predecessor_record = _find_record_in_jsonl(predecessor_certified_source_path, predecessor_record_id)
    assert predecessor_record is not None
    if _is_record_empty(predecessor_record):
        raise RecoveryPlanError(f"predecessor {predecessor_record_id} is itself empty; nothing to recover from")

    # Invariant 5 (divergence guard): every certified copy of the
    # predecessor offered must agree on content.
    divergence_candidates = [predecessor_certified_source_path] + list(other_certified_paths_for_divergence_check or [])
    check_no_divergent_sources(predecessor_record_id, divergence_candidates)

    # Build the repaired record: only RECOVERABLE fields come from history;
    # everything else on the CURRENT target -- identity, title, tags,
    # relations, position -- is the governed-reorganization state and is
    # kept exactly as-is.
    repaired_record, fields_recovered = _repair_record_fields(target_record, predecessor_record, recoverable_fields)
    fields_preserved: list[str] = []
    fields_untouched: list[str] = []
    for key in set(predecessor_record) | set(target_record):
        if key in recoverable_fields or key in RECOMPUTED_FIELDS:
            continue
        target_value = target_record.get(key)
        predecessor_value = predecessor_record.get(key)
        if key in target_record and predecessor_value != target_value and key in predecessor_record:
            fields_preserved.append(key)
        else:
            fields_untouched.append(key)

    # Invariant 9/10: only recoverable + recomputed fields may actually
    # change; identity fields must be byte-identical to the CURRENT target.
    for identity_field in ("id", "title", "key", "canonical_slug", "relations", "tags", "section_path", "order_in_document", "document_id"):
        if repaired_record.get(identity_field) != target_record.get(identity_field):
            raise RecoveryPlanError(
                f"internal invariant violation: identity field {identity_field!r} would change; refusing"
            )

    recomputed_fields: list[str] = []
    if _recompute_version_id_if_recovered(repaired_record, fields_recovered):
        recomputed_fields.append("version_id")

    expected_after_hash = _record_hash(repaired_record)
    provenance_evidence = [source.to_dict()]

    return RecoveryOperation(
        operation_id=_operation_id(MODE_REPAIR_EXISTING_TARGET, target_record_id, source.record_hash, expected_after_hash),
        operation_mode=MODE_REPAIR_EXISTING_TARGET,
        source_record_id=predecessor_record_id,
        target_record_id=target_record_id,
        source_artifact=source.path,
        source_artifact_sha256=source.artifact_sha256,
        source_record_hash=source.record_hash,
        target_before_exists=True,
        target_before_hash=_record_hash(target_record),
        expected_target_after_hash=expected_after_hash,
        expected_identity=target_record_id,
        expected_record_count_delta=0,
        affected_shard=str(target_shard),
        provenance_evidence=provenance_evidence,
        ambiguity_status="none",
        authorization_required=True,
        rollback_snapshot=None,
        reason_code=REASON_CURRENT_TARGET_CONTENT_EMPTY,
        recovered_record=repaired_record,
        fields_preserved_from_current=sorted(fields_preserved),
        fields_recovered_from_history=sorted(fields_recovered),
        fields_recomputed=sorted(recomputed_fields),
        fields_untouched=sorted(fields_untouched),
    )


def build_recompute_invalid_version_id_operation(
    *,
    target_record_id: str,
    canon_dir: Path = DEFAULT_CANON_DIR,
) -> RecoveryOperation:
    """MODE C: RECOMPUTE_INVALID_VERSION_ID.

    Corrects a CURRENT record whose stored version_id no longer matches
    the TDC identity contract (S34 Sec 14.5: sha256 of canonical_json({key,
    title, text, created, modified})) -- the same formula
    ``src/go/canon/identity.go:ComputeVersionID`` and
    ``normalize_session_titles._recompute_version_id`` use. The new value
    is derived exclusively from the target's own CURRENT fields; no
    external evidence, no manually-supplied value, and no other field may
    change. Refuses to build a plan when the stored value is already
    contract-consistent -- this corrects a demonstrated inconsistency, it
    is not a general "touch every version_id" tool.
    """

    canon_index = load_canon_index(canon_dir)

    # Invariant 1: target exists in CURRENT canon.
    if target_record_id not in canon_index:
        raise RecoveryPlanError(f"target {target_record_id} does not exist in CURRENT canon")
    target_record, target_shard = canon_index[target_record_id]

    stored_version_id = target_record.get("version_id")
    recomputed_version_id = _tdc_recompute_version_id(
        target_record.get("key"),
        target_record.get("title"),
        target_record.get("text"),
        target_record.get("created"),
        target_record.get("modified"),
    )

    # Invariant 2: the strict identity contract must actually be violated.
    if stored_version_id == recomputed_version_id:
        raise RecoveryPlanError(
            f"target {target_record_id} version_id already matches the identity contract; nothing to recompute"
        )

    repaired_record = dict(target_record)
    repaired_record["version_id"] = recomputed_version_id

    # Invariant 3: literally nothing else may differ. Not a subset of
    # named identity fields (as MODE B checks) -- every single field.
    for key in set(target_record) | set(repaired_record):
        if key == "version_id":
            continue
        if repaired_record.get(key) != target_record.get(key):
            raise RecoveryPlanError(
                f"internal invariant violation: field {key!r} would change; RECOMPUTE_INVALID_VERSION_ID may only touch version_id"
            )

    expected_after_hash = _record_hash(repaired_record)
    provenance_evidence = [
        {
            "type": "self_derived_current_record",
            "path": str(target_shard),
            "source_record_id": target_record_id,
            "provenance_classification": "self_derived_current_record",
            "identity_contract": "src/go/canon/identity.go:ComputeVersionID",
            "python_parity": "normalize_session_titles._recompute_version_id",
            "stored_version_id": stored_version_id,
            "recomputed_version_id": recomputed_version_id,
        }
    ]
    fields_preserved = sorted(key for key in target_record if key != "version_id")

    return RecoveryOperation(
        operation_id=_operation_id(MODE_RECOMPUTE_INVALID_VERSION_ID, target_record_id, _record_hash(target_record), expected_after_hash),
        operation_mode=MODE_RECOMPUTE_INVALID_VERSION_ID,
        source_record_id=target_record_id,
        target_record_id=target_record_id,
        source_artifact=str(target_shard),
        source_artifact_sha256=sha256_path(target_shard),
        source_record_hash=_record_hash(target_record),
        target_before_exists=True,
        target_before_hash=_record_hash(target_record),
        expected_target_after_hash=expected_after_hash,
        expected_identity=target_record_id,
        expected_record_count_delta=0,
        affected_shard=str(target_shard),
        provenance_evidence=provenance_evidence,
        ambiguity_status="none",
        authorization_required=True,
        rollback_snapshot=None,
        reason_code=REASON_VERSION_ID_CONTRACT_VIOLATION,
        recovered_record=repaired_record,
        fields_preserved_from_current=fields_preserved,
        fields_recovered_from_history=[],
        fields_recomputed=["version_id"],
        fields_untouched=[],
    )


def materialize_recovered_record(op_dict: dict[str, Any], canon_dir: Path) -> dict[str, Any]:
    """Reconstruct the recovered/repaired record for an operation loaded

    from a persisted plan file. A plan's ``operations[i].to_dict()``
    deliberately omits ``recovered_record`` (it is re-derived from the
    certified source rather than duplicated into the plan file), so every
    consumer of a *reloaded* plan -- dry-run and Apply alike -- must
    rebuild it. This is the ONE such rebuild: it shares
    ``_repair_record_fields``/``_recompute_version_id_if_recovered`` with
    ``build_repair_existing_operation`` itself, so a plan's
    expected_target_after_hash, dry-run's actual_after_hash, and Apply's
    materialized record can never diverge by construction.
    """

    source_path = Path(op_dict["source_artifact"])
    source_record = _find_record_in_jsonl(source_path, op_dict["source_record_id"])
    if source_record is None:
        raise RecoveryAuthorizationError(
            f"source record {op_dict['source_record_id']!r} not found in {source_path} "
            f"while materializing operation {op_dict['operation_id']}"
        )

    if op_dict["operation_mode"] == MODE_RESTORE_MISSING_SAME_ID:
        return source_record

    if op_dict["operation_mode"] == MODE_RECOMPUTE_INVALID_VERSION_ID:
        # source_artifact/source_record_id are self-referential for this
        # mode (the target's own CURRENT shard/id), so source_record here
        # IS the target record. Recompute version_id from exactly its own
        # material fields -- never any other field.
        repaired_record = dict(source_record)
        repaired_record["version_id"] = _tdc_recompute_version_id(
            repaired_record.get("key"),
            repaired_record.get("title"),
            repaired_record.get("text"),
            repaired_record.get("created"),
            repaired_record.get("modified"),
        )
        return repaired_record

    if op_dict["operation_mode"] != MODE_REPAIR_EXISTING_TARGET:
        raise RecoveryPlanError(f"unknown operation mode: {op_dict['operation_mode']}")

    canon_index = load_canon_index(canon_dir)
    if op_dict["target_record_id"] not in canon_index:
        raise RecoveryAuthorizationError(
            f"target {op_dict['target_record_id']} not found in CURRENT canon "
            f"while materializing operation {op_dict['operation_id']}"
        )
    target_record, _ = canon_index[op_dict["target_record_id"]]

    repaired_record, fields_recovered = _repair_record_fields(target_record, source_record, RECOVERABLE_CONTENT_FIELDS)
    _recompute_version_id_if_recovered(repaired_record, fields_recovered)
    return repaired_record


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------


@dataclass
class RecoveryPlan:
    schema_version: str
    plan_id: str
    created_at: str
    canon_dir: str
    canon_before_hash: str
    canon_before_records: int
    canon_before_shards: int
    operations: list[RecoveryOperation]
    expected_canon_after_count: int
    plan_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "created_at": self.created_at,
            "canon_dir": self.canon_dir,
            "canon_before_hash": self.canon_before_hash,
            "canon_before_records": self.canon_before_records,
            "canon_before_shards": self.canon_before_shards,
            "operations": [op.to_dict() for op in self.operations],
            "expected_canon_after_count": self.expected_canon_after_count,
            "plan_hash": self.plan_hash,
        }


def _plan_hash(unsigned_plan: dict[str, Any]) -> str:
    # plan_hash is meant to represent the plan's binding-relevant content --
    # everything an authorization commits to (canon state, operations, the
    # records they will materialize). "created_at" is pure wall-clock
    # bookkeeping of when the plan was drafted, not a binding fact: two
    # materializations of the exact same recovery request, seconds apart,
    # must produce the exact same plan_hash, or the hash cannot be used to
    # detect real drift. plan_id is also excluded since it is derived from
    # (and would trivially self-reference) this same payload.
    payload = {key: value for key, value in unsigned_plan.items() if key not in ("plan_hash", "plan_id", "created_at")}
    return sha256_bytes(stable_json(payload).encode("utf-8"))


def build_plan(
    canon_dir: Path,
    operations: list[RecoveryOperation],
    *,
    plan_id: str | None = None,
) -> RecoveryPlan:
    if not operations:
        raise RecoveryPlanError("a plan requires at least one operation")
    target_ids = [op.target_record_id for op in operations]
    if len(set(target_ids)) != len(target_ids):
        raise RecoveryPlanError("a plan may not target the same record id twice")
    for op in operations:
        if op.operation_mode not in VALID_MODES:
            raise RecoveryPlanError(f"unknown operation mode: {op.operation_mode}")
        if op.reason_code not in VALID_REASON_CODES:
            raise RecoveryPlanError(f"unknown reason code: {op.reason_code}")
        if op.ambiguity_status != "none":
            raise RecoveryPlanError(
                f"operation {op.operation_id} carries ambiguity_status={op.ambiguity_status!r}; "
                "a plan may only contain fully-resolved operations"
            )

    snapshot = canon_snapshot(canon_dir)
    delta = sum(op.expected_record_count_delta for op in operations)
    resolved_plan_id = plan_id or ("ccr_plan_" + hashlib.sha256(
        (snapshot["hash"] + "".join(op.operation_id for op in operations)).encode()
    ).hexdigest()[:20])
    unsigned = {
        "schema_version": SCHEMA_PLAN,
        "plan_id": resolved_plan_id,
        "created_at": utc_now(),
        "canon_dir": str(canon_dir),
        "canon_before_hash": snapshot["hash"],
        "canon_before_records": snapshot["records"],
        "canon_before_shards": snapshot["shards"],
        "operations": [op.to_dict() for op in operations],
        "expected_canon_after_count": snapshot["records"] + delta,
    }
    plan_hash = _plan_hash(unsigned)
    constructor_fields = {key: value for key, value in unsigned.items() if key != "operations"}
    return RecoveryPlan(**constructor_fields, plan_hash=plan_hash, operations=operations)


def write_plan(plan: RecoveryPlan, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(stable_json(plan.to_dict(), indent=2) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Dry-run / projected validation
# ---------------------------------------------------------------------------


def _apply_operations_to_staging(
    canon_dir: Path, operations: list[RecoveryOperation], staging_dir: Path
) -> dict[str, Path]:
    """Copy every shard into ``staging_dir`` and apply operations there.

    Returns the map of destination shard path -> staged file path for every
    shard that changed. The real canon directory is never touched.
    """

    staging_dir.mkdir(parents=True, exist_ok=True)
    shard_records: dict[Path, list[dict[str, Any]]] = {}
    for shard in _canon_shards(canon_dir):
        shard_records[shard] = _iter_shard_records(shard)

    changed_shards: set[Path] = set()
    for op in operations:
        destination = Path(op.affected_shard)
        if op.operation_mode == MODE_RESTORE_MISSING_SAME_ID:
            records = shard_records.setdefault(destination, [])
            records.append(op.recovered_record)
            records.sort(key=lambda record: str(record.get("id")))
            changed_shards.add(destination)
        elif op.operation_mode in (MODE_REPAIR_EXISTING_TARGET, MODE_RECOMPUTE_INVALID_VERSION_ID):
            records = shard_records.get(destination)
            if records is None:
                raise RecoveryPlanError(f"affected shard vanished before apply: {destination}")
            replaced = False
            for index, record in enumerate(records):
                if str(record.get("id")) == op.target_record_id:
                    records[index] = op.recovered_record
                    replaced = True
                    break
            if not replaced:
                raise RecoveryPlanError(f"target {op.target_record_id} vanished from {destination} before apply")
            changed_shards.add(destination)
        else:
            raise RecoveryPlanError(f"unknown operation mode: {op.operation_mode}")

    staged: dict[str, Path] = {}
    for shard in changed_shards:
        payload = ("\n".join(json.dumps(record, ensure_ascii=False) for record in shard_records[shard]) + "\n").encode(
            "utf-8"
        )
        staged_path = staging_dir / shard.name
        staged_path.write_bytes(payload)
        staged[str(shard)] = staged_path
    return staged


def _strict_validate_records(all_shard_paths: list[Path]) -> None:
    seen_ids: set[str] = set()
    for path in all_shard_paths:
        for record in _iter_shard_records(path):
            record_id = str(record.get("id") or "")
            if not record_id:
                raise RecoveryPlanError(f"{path}: record without id")
            if record_id in seen_ids:
                raise RecoveryPlanError(f"duplicate canon id after projected apply: {record_id}")
            seen_ids.add(record_id)


def dry_run(plan: RecoveryPlan, *, out_dir: Path) -> dict[str, Any]:
    """Build the fully projected post-apply canon in an isolated staging

    directory and validate it exhaustively. Never touches the real canon.
    """

    canon_dir = Path(plan.canon_dir)
    current_snapshot = canon_snapshot(canon_dir)
    if current_snapshot["hash"] != plan.canon_before_hash:
        raise RecoveryAuthorizationError(
            "canon drift detected: plan.canon_before_hash no longer matches CURRENT canon"
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(tempfile.mkdtemp(prefix="canon-content-recovery-dryrun-", dir=out_dir))
    try:
        staged = _apply_operations_to_staging(canon_dir, plan.operations, staging_dir)

        # Build the full projected shard list: unchanged shards read from
        # the real canon, changed ones read from staging.
        projected_paths: list[Path] = []
        for shard in _canon_shards(canon_dir):
            projected_paths.append(staged.get(str(shard), shard))
        # New shard files (only possible for MODE A when affected_shard
        # names a shard that did not previously exist) are already covered
        # by _canon_shards() only if pre-existing; MODE A always reuses an
        # existing shard by construction, so no extra path is needed here.

        _strict_validate_records(projected_paths)

        # Aggregate hash exactly as canon_snapshot() does: sorted by shard
        # name, raw bytes concatenated.
        ordered = sorted(projected_paths, key=lambda p: p.name)
        digest = hashlib.sha256()
        projected_records = 0
        for path in ordered:
            content = path.read_bytes()
            digest.update(content)
            projected_records += sum(1 for line in content.splitlines() if line.strip())
        projected_after_hash = digest.hexdigest()

        # changed_record_ids: exactly the plan's target ids, verified by
        # diffing old vs new record content per shard.
        changed_ids: set[str] = set()
        for shard in _canon_shards(canon_dir):
            if str(shard) not in staged:
                continue
            before_by_id = {str(r.get("id")): r for r in _iter_shard_records(shard)}
            after_by_id = {str(r.get("id")): r for r in _iter_shard_records(staged[str(shard)])}
            for record_id in set(before_by_id) | set(after_by_id):
                if before_by_id.get(record_id) != after_by_id.get(record_id):
                    changed_ids.add(record_id)

        expected_changed_ids = {op.target_record_id for op in plan.operations}
        unexpected_changes = changed_ids - expected_changed_ids
        missing_changes = expected_changed_ids - changed_ids

        per_operation_checks = []
        for op in plan.operations:
            after_records = {
                str(r.get("id")): r
                for path in ordered
                for r in _iter_shard_records(path)
            }
            target_record = after_records.get(op.target_record_id)
            present_once = sum(
                1
                for path in ordered
                for r in _iter_shard_records(path)
                if str(r.get("id")) == op.target_record_id
            )
            per_operation_checks.append(
                {
                    "operation_id": op.operation_id,
                    "target_record_id": op.target_record_id,
                    "present_count": present_once,
                    "present_exactly_once": present_once == 1,
                    "non_empty": bool(target_record and not _is_record_empty(target_record)) if target_record else False,
                    "actual_after_hash": _record_hash(target_record) if target_record else None,
                    "matches_expected_after_hash": (
                        _record_hash(target_record) == op.expected_target_after_hash if target_record else False
                    ),
                }
            )

        report = {
            "schema_version": "canon-content-recovery-dryrun-report/v1",
            "plan_id": plan.plan_id,
            "plan_hash": plan.plan_hash,
            "canon_before": {
                "hash": plan.canon_before_hash,
                "records": plan.canon_before_records,
                "shards": plan.canon_before_shards,
            },
            "projected_canon_after": {
                "hash": projected_after_hash,
                "records": projected_records,
                "shards": len(ordered),
            },
            "expected_canon_after_count": plan.expected_canon_after_count,
            "count_matches_expected": projected_records == plan.expected_canon_after_count,
            "changed_record_ids": sorted(changed_ids),
            "expected_changed_record_ids": sorted(expected_changed_ids),
            "unexpected_changes": sorted(unexpected_changes),
            "missing_changes": sorted(missing_changes),
            "strict_validation": "pass",
            "per_operation": per_operation_checks,
            "canon_modified": False,
        }
        report["overall_status"] = (
            "pass"
            if (
                report["count_matches_expected"]
                and not unexpected_changes
                and not missing_changes
                and all(check["present_exactly_once"] and check["matches_expected_after_hash"] for check in per_operation_checks)
            )
            else "fail"
        )
        return report
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)


def verify_strict_projected_canon(plan: RecoveryPlan, *, out_dir: Path) -> dict[str, Any]:
    """Independently verify the plan's fully projected canon against the

    REAL ``canon_preflight --mode strict`` validator -- not this module's
    own structural checks, but the same authoritative Go tool that
    demonstrates identity-contract violations (the exact tool that caught
    the version_id defect this module exists to correct). Builds a
    complete projected canon directory (every shard; changed ones staged)
    in an isolated, non-productive location and never touches the real
    canon. Independent of, and a stronger check than, ``dry_run``'s own
    ``_strict_validate_records`` (duplicate/missing-id structural checks
    only -- it has no notion of identity-contract consistency).
    """

    canon_dir = Path(plan.canon_dir)
    current_snapshot = canon_snapshot(canon_dir)
    if current_snapshot["hash"] != plan.canon_before_hash:
        raise RecoveryAuthorizationError(
            "canon drift detected: plan.canon_before_hash no longer matches CURRENT canon"
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    projected_dir = Path(tempfile.mkdtemp(prefix="canon-content-recovery-strict-", dir=out_dir))
    staging_dir = projected_dir / "_staged"
    try:
        staged = _apply_operations_to_staging(canon_dir, plan.operations, staging_dir)
        for shard in _canon_shards(canon_dir):
            source = staged.get(str(shard), shard)
            (projected_dir / shard.name).write_bytes(source.read_bytes())
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)

    env = os.environ.copy()
    env.setdefault("GOCACHE", str(Path(tempfile.gettempdir()) / "go-build-canon-content-recovery"))
    result = subprocess.run(
        ["go", "run", "./cmd/canon_preflight", "--mode", "strict", "--input", str(projected_dir)],
        cwd=CANON_GO_DIR,
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )
    try:
        parsed = json.loads(result.stdout) if result.stdout.strip() else {}
    except json.JSONDecodeError:
        parsed = {}

    return {
        "schema_version": "canon-content-recovery-strict-verification/v1",
        "projected_dir": str(projected_dir),
        "returncode": result.returncode,
        "status": "pass" if result.returncode == 0 else "fail",
        "issues": parsed.get("issues", []),
        "lines_read": parsed.get("lines_read"),
        "lines_valid": parsed.get("lines_valid"),
        "stderr": result.stderr,
    }


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


def authorization_phrase(plan: RecoveryPlan) -> str:
    return f"{AUTHORIZATION_PHRASE_PREFIX} {plan.plan_id}"


# ---------------------------------------------------------------------------
# Snapshot preparation (governed preflight -- BEFORE authorization)
# ---------------------------------------------------------------------------


def prepare_snapshot(plan: RecoveryPlan, snapshot_dir: Path) -> Path:
    """Materialize the rollback snapshot for ``plan`` and return its manifest

    path. This is a read-only-on-Canon preflight step that must run BEFORE
    an authorization can be created: an authorization binds to this
    snapshot's own file hash, so the snapshot has to exist first. Backs up
    the CURRENT (unmodified) bytes of every shard the plan will touch --
    nothing about Canon changes here.
    """

    canon_dir = Path(plan.canon_dir)
    current_snapshot = canon_snapshot(canon_dir)
    if current_snapshot["hash"] != plan.canon_before_hash:
        raise RecoveryAuthorizationError(
            "canon drift detected before snapshot preparation: canon_before_hash no longer matches CURRENT canon"
        )
    for op in plan.operations:
        source_path = Path(op.source_artifact)
        if not source_path.exists() or sha256_path(source_path) != op.source_artifact_sha256:
            raise RecoveryAuthorizationError(f"source artifact drift detected for operation {op.operation_id}: {source_path}")

    shards_to_backup = sorted({Path(op.affected_shard) for op in plan.operations}, key=str)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for shard in shards_to_backup:
        backup_name = shard.name
        backup_path = snapshot_dir / backup_name
        backup_path.write_bytes(shard.read_bytes())
        files.append({"path": str(shard), "backup_path": backup_name, "sha256": sha256_path(shard)})
    manifest = {
        "schema_version": SCHEMA_ROLLBACK,
        "snapshot_complete": True,
        "created_at": utc_now(),
        "plan_id": plan.plan_id,
        "plan_hash": plan.plan_hash,
        "canon_before_hash": plan.canon_before_hash,
        # Filled in only at Apply time, in a *separate* receipt -- never by
        # rewriting this manifest, which would change its hash after an
        # authorization has already bound to it.
        "apply_id": None,
        "authorization_id": None,
        "files": files,
    }
    manifest_path = snapshot_dir / "rollback_manifest.json"
    manifest_path.write_text(stable_json(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def _load_snapshot_manifest(snapshot_manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(snapshot_manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != SCHEMA_ROLLBACK or manifest.get("snapshot_complete") is not True:
        raise RecoveryAuthorizationError("invalid or incomplete rollback snapshot")
    return manifest


def _verify_snapshot_integrity(snapshot_manifest_path: Path, manifest: dict[str, Any]) -> None:
    """Every backup file inside the snapshot must still match its own

    recorded hash -- the snapshot is worthless as a rollback point if its
    own backups were tampered with or corrupted after creation.
    """

    snapshot_dir = snapshot_manifest_path.parent
    for item in manifest.get("files") or []:
        backup = snapshot_dir / str(item["backup_path"])
        if not backup.exists() or sha256_path(backup) != item.get("sha256"):
            raise RecoveryAuthorizationError(f"snapshot backup corrupted or missing: {backup}")


def create_authorization(plan: RecoveryPlan, snapshot_manifest_path: Path, phrase: str) -> dict[str, Any]:
    expected = authorization_phrase(plan)
    if phrase != expected:
        raise RecoveryAuthorizationError(f"authorization phrase does not match plan; expected exact phrase: {expected!r}")
    if not snapshot_manifest_path.exists():
        raise RecoveryAuthorizationError(
            f"rollback snapshot does not exist: {snapshot_manifest_path}; run prepare_snapshot() before authorizing"
        )
    manifest = _load_snapshot_manifest(snapshot_manifest_path)
    if manifest.get("plan_id") != plan.plan_id or manifest.get("plan_hash") != plan.plan_hash:
        raise RecoveryAuthorizationError("rollback snapshot does not belong to this plan (plan_id/plan_hash mismatch)")
    if manifest.get("canon_before_hash") != plan.canon_before_hash:
        raise RecoveryAuthorizationError("rollback snapshot canon_before_hash does not match plan")
    _verify_snapshot_integrity(snapshot_manifest_path, manifest)

    authorization_id = "ccr_auth_" + hashlib.sha256(
        f"{plan.plan_id}:{plan.plan_hash}:{utc_now()}".encode()
    ).hexdigest()[:20]
    return {
        "schema_version": SCHEMA_AUTHORIZATION,
        "authorization_id": authorization_id,
        "plan_id": plan.plan_id,
        "plan_hash": plan.plan_hash,
        "canon_before_hash": plan.canon_before_hash,
        "operation_ids": [op.operation_id for op in plan.operations],
        "source_artifact_sha256": [op.source_artifact_sha256 for op in plan.operations],
        "target_before_hashes": [op.target_before_hash for op in plan.operations],
        "rollback_snapshot": str(snapshot_manifest_path),
        "rollback_snapshot_hash": sha256_path(snapshot_manifest_path),
        "created_at": utc_now(),
        "consumed": False,
        "consumed_at": None,
    }


def _verify_authorization_binding(plan: RecoveryPlan, authorization: dict[str, Any]) -> None:
    if authorization.get("plan_id") != plan.plan_id:
        raise RecoveryAuthorizationError("authorization plan_id does not match plan")
    if authorization.get("plan_hash") != plan.plan_hash:
        raise RecoveryAuthorizationError("authorization plan_hash does not match plan (plan drift)")
    if authorization.get("canon_before_hash") != plan.canon_before_hash:
        raise RecoveryAuthorizationError("authorization canon_before_hash does not match plan (canon drift)")
    if authorization.get("operation_ids") != [op.operation_id for op in plan.operations]:
        raise RecoveryAuthorizationError("authorization operation_ids do not match plan operations")
    if authorization.get("source_artifact_sha256") != [op.source_artifact_sha256 for op in plan.operations]:
        raise RecoveryAuthorizationError("authorization source hashes do not match plan (source drift)")
    if authorization.get("target_before_hashes") != [op.target_before_hash for op in plan.operations]:
        raise RecoveryAuthorizationError("authorization target_before_hashes do not match plan (target drift)")


def _verify_snapshot_matches_authorization(authorization: dict[str, Any]) -> dict[str, Any]:
    """Re-verify, just before mutating Canon, that the snapshot referenced

    by the authorization still exists, is unmodified since authorization
    (its file hash still matches ``rollback_snapshot_hash``), and its own
    internal backups are intact. A snapshot silently rebuilt or replaced
    under the same authorization is exactly the drift this blocks -- the
    authorization becomes stale and a new one must be issued.
    """

    snapshot_path = Path(str(authorization.get("rollback_snapshot") or ""))
    if not authorization.get("rollback_snapshot_hash"):
        raise RecoveryAuthorizationError("authorization does not carry a rollback_snapshot_hash")
    if not snapshot_path.exists():
        raise RecoveryAuthorizationError(f"authorized rollback snapshot is missing: {snapshot_path}")
    current_hash = sha256_path(snapshot_path)
    if current_hash != authorization["rollback_snapshot_hash"]:
        raise RecoveryAuthorizationError(
            "rollback snapshot drift detected: snapshot file changed since authorization; "
            "authorization is stale, a new one must be issued"
        )
    manifest = _load_snapshot_manifest(snapshot_path)
    _verify_snapshot_integrity(snapshot_path, manifest)
    return manifest


# ---------------------------------------------------------------------------
# Apply / rollback
# ---------------------------------------------------------------------------


def rollback(
    snapshot_manifest_path: Path,
    *,
    out_dir: Path | None = None,
    apply_id: str | None = None,
    authorization_id: str | None = None,
) -> dict[str, Any]:
    """Restore every backed-up shard byte for byte. Idempotent: rolling
    back an already-restored snapshot succeeds trivially.

    The snapshot manifest itself never records apply_id/authorization_id
    (it is immutable once its hash is bound into an authorization); callers
    that know which apply/authorization triggered this rollback -- such as
    ``apply()``'s own failure path -- may pass them through purely for the
    report.
    """

    manifest = _load_snapshot_manifest(snapshot_manifest_path)
    snapshot_dir = snapshot_manifest_path.parent
    files = manifest.get("files") or []
    already_restored = all(
        Path(item["path"]).exists() and sha256_path(Path(item["path"])) == item.get("sha256") for item in files
    )
    restored = 0
    if not already_restored:
        for item in files:
            destination = Path(str(item["path"]))
            backup = snapshot_dir / str(item["backup_path"])
            if sha256_path(backup) != item.get("sha256"):
                raise RecoveryAuthorizationError(f"rollback backup hash mismatch: {backup}")
            _atomic_write_bytes(destination, backup.read_bytes())
            restored += 1
    exact = all(sha256_path(Path(str(item["path"]))) == item.get("sha256") for item in files)
    report = {
        "schema_version": SCHEMA_ROLLBACK,
        "rolled_back_at": utc_now(),
        "apply_id": apply_id if apply_id is not None else manifest.get("apply_id"),
        "authorization_id": authorization_id if authorization_id is not None else manifest.get("authorization_id"),
        "plan_id": manifest.get("plan_id"),
        "snapshot_manifest_path": str(snapshot_manifest_path),
        "status": "already_restored" if already_restored else ("restored" if exact else "failed"),
        "restored_shards": restored,
        "byte_exact": exact,
        "canon_modified": not exact,
    }
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "rollback_report.json").write_text(stable_json(report, indent=2) + "\n", encoding="utf-8")
    if not exact:
        raise RuntimeError("rollback did not restore the snapshot byte for byte")
    return report


def apply(
    plan: RecoveryPlan,
    authorization: dict[str, Any],
    *,
    out_dir: Path,
    _inject_failure_after_shard_index: int | None = None,
) -> dict[str, Any]:
    """Atomic, all-or-nothing apply.

    The rollback snapshot is NOT created here -- it must already exist and
    be exactly the one the authorization is bound to (see
    ``prepare_snapshot`` / ``create_authorization``). This function only
    re-verifies that binding, still holds, immediately before mutating
    Canon: canon hash, plan hash, source hashes, target-before hashes, and
    the snapshot's own file hash and internal integrity. Any drift on any
    of those blocks the apply outright. Every shard is then staged and the
    full projected result is strictly validated before any real canon file
    is touched -- most failure modes never write anything at all; the only
    remaining window is the promotion step itself, guarded by the
    (already-verified) snapshot.
    """

    canon_dir = Path(plan.canon_dir)
    # Checked before the drift checks below so a replay of an
    # already-applied authorization reports the specific, actionable reason
    # ("already consumed") rather than an incidental later-stage mismatch.
    if authorization.get("consumed") is True:
        raise RecoveryAuthorizationError("authorization already consumed; one-shot authorizations cannot be replayed")
    current_snapshot = canon_snapshot(canon_dir)
    if current_snapshot["hash"] != plan.canon_before_hash:
        raise RecoveryAuthorizationError("canon drift detected before apply: canon_before_hash no longer matches CURRENT canon")
    _verify_authorization_binding(plan, authorization)

    # Re-verify source artifacts have not drifted since planning.
    for op in plan.operations:
        source_path = Path(op.source_artifact)
        if not source_path.exists() or sha256_path(source_path) != op.source_artifact_sha256:
            raise RecoveryAuthorizationError(f"source artifact drift detected for operation {op.operation_id}: {source_path}")

    # Re-verify each target's before-state has not drifted (stale-plan guard).
    canon_index = load_canon_index(canon_dir)
    for op in plan.operations:
        exists = op.target_record_id in canon_index
        if exists != op.target_before_exists:
            raise RecoveryAuthorizationError(
                f"target drift detected for operation {op.operation_id}: existence changed since planning"
            )
        if exists:
            current_hash = _record_hash(canon_index[op.target_record_id][0])
            if current_hash != op.target_before_hash:
                raise RecoveryAuthorizationError(
                    f"target drift detected for operation {op.operation_id}: content changed since planning"
                )

    # The authorized snapshot must still be exactly what it was when
    # authorized -- not rebuilt, not replaced by a different-but-valid one.
    snapshot_manifest_path = Path(str(authorization["rollback_snapshot"]))
    _verify_snapshot_matches_authorization(authorization)

    apply_id = "ccr_apply_" + hashlib.sha256(f"{plan.plan_id}:{authorization['authorization_id']}:{utc_now()}".encode()).hexdigest()[:20]

    # Stage the full projected canon and validate it exhaustively before
    # promoting anything -- catches every failure mode with zero writes to
    # the real canon.
    out_dir.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(tempfile.mkdtemp(prefix="canon-content-recovery-stage-", dir=out_dir))
    try:
        staged = _apply_operations_to_staging(canon_dir, plan.operations, staging_dir)
        # Reuse dry_run's own validation semantics by re-running the same
        # projected-state checks against this exact staged output.
        projected_paths = [staged.get(str(shard), shard) for shard in _canon_shards(canon_dir)]
        _strict_validate_records(projected_paths)

        # Invariant: the record actually about to be promoted must be
        # byte-for-byte the one the plan (and therefore the authorization)
        # committed to. This is the last line of defense against a
        # producer-parity bug between plan-build time and apply time (e.g.
        # a caller passing an operation whose recovered_record was
        # reconstructed incorrectly) -- catch it here, before Canon is
        # ever touched, rather than trusting the caller silently.
        materialized_by_id = {
            str(record.get("id")): record for path in projected_paths for record in _iter_shard_records(path)
        }
        for op in plan.operations:
            materialized = materialized_by_id.get(op.target_record_id)
            if materialized is None or _record_hash(materialized) != op.expected_target_after_hash:
                raise RecoveryAuthorizationError(
                    f"materialized record for operation {op.operation_id} does not match "
                    "expected_target_after_hash sealed in the plan; refusing to promote"
                )

        promoted = 0
        try:
            for destination_str, staged_path in sorted(staged.items()):
                _atomic_write_bytes(Path(destination_str), staged_path.read_bytes())
                promoted += 1
                if _inject_failure_after_shard_index is not None and promoted >= _inject_failure_after_shard_index:
                    raise RuntimeError(f"injected failure after promoting {promoted} shard(s)")
        except Exception:
            rollback_report = rollback(
                snapshot_manifest_path,
                out_dir=out_dir,
                apply_id=apply_id,
                authorization_id=authorization["authorization_id"],
            )
            raise RuntimeError(
                f"apply failed during promotion; automatically rolled back (byte_exact={rollback_report['byte_exact']})"
            ) from None

        after_snapshot = canon_snapshot(canon_dir)
        _strict_validate_records(_canon_shards(canon_dir))

        authorization["consumed"] = True
        authorization["consumed_at"] = utc_now()

        receipt = {
            "schema_version": SCHEMA_APPLY_RECEIPT,
            "apply_id": apply_id,
            "plan_id": plan.plan_id,
            "plan_hash": plan.plan_hash,
            "authorization_id": authorization["authorization_id"],
            "canon_before_hash": plan.canon_before_hash,
            "canon_after_hash": after_snapshot["hash"],
            "canon_after_records": after_snapshot["records"],
            "expected_canon_after_count": plan.expected_canon_after_count,
            "count_matches_expected": after_snapshot["records"] == plan.expected_canon_after_count,
            "operations_applied": [op.operation_id for op in plan.operations],
            "changed_record_ids": sorted({op.target_record_id for op in plan.operations}),
            "rollback_snapshot": str(snapshot_manifest_path),
            "rollback_snapshot_hash": authorization["rollback_snapshot_hash"],
            "applied_at": utc_now(),
            "status": "success",
        }
        return receipt
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _operation_from_request(request: dict[str, Any], canon_dir: Path) -> RecoveryOperation:
    mode = request.get("mode")
    if mode == MODE_RESTORE_MISSING_SAME_ID:
        return build_restore_missing_operation(
            target_record_id=request["target_record_id"],
            certified_source_path=Path(request["certified_source_path"]),
            canon_dir=canon_dir,
            corroborating_source_path=(
                Path(request["corroborating_source_path"]) if request.get("corroborating_source_path") else None
            ),
            other_certified_paths_for_divergence_check=[
                Path(p) for p in request.get("other_certified_paths_for_divergence_check", [])
            ],
        )
    if mode == MODE_REPAIR_EXISTING_TARGET:
        return build_repair_existing_operation(
            target_record_id=request["target_record_id"],
            predecessor_record_id=request["predecessor_record_id"],
            predecessor_certified_source_path=Path(request["predecessor_certified_source_path"]),
            canon_dir=canon_dir,
            other_certified_paths_for_divergence_check=[
                Path(p) for p in request.get("other_certified_paths_for_divergence_check", [])
            ],
        )
    if mode == MODE_RECOMPUTE_INVALID_VERSION_ID:
        return build_recompute_invalid_version_id_operation(
            target_record_id=request["target_record_id"],
            canon_dir=canon_dir,
        )
    raise RecoveryPlanError(f"unknown operation mode in request: {mode!r}")


def _build_plan_from_request_file(request_file: Path, canon_dir: Path) -> RecoveryPlan:
    requests = json.loads(request_file.read_text(encoding="utf-8"))
    if isinstance(requests, dict):
        requests = [requests]
    operations = [_operation_from_request(request, canon_dir) for request in requests]
    return build_plan(canon_dir, operations)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Governed recovery of canonical content proven from certified historical evidence."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    plan_parser = sub.add_parser("plan", help="Build and validate a recovery plan (read-only)")
    plan_parser.add_argument("--request-file", required=True, help="JSON file describing one or more recovery operations")
    plan_parser.add_argument("--canon-dir", default=str(DEFAULT_CANON_DIR))
    plan_parser.add_argument("--out", required=True, help="Where to write the plan JSON")

    dry_parser = sub.add_parser("dry-run", help="Project the plan's effect without touching Canon")
    dry_parser.add_argument("--plan-file", required=True)
    dry_parser.add_argument("--out-dir", required=True)
    dry_parser.add_argument("--report", required=True)

    snapshot_parser = sub.add_parser(
        "prepare-snapshot", help="Materialize the rollback snapshot for a plan (must run before authorize)"
    )
    snapshot_parser.add_argument("--plan-file", required=True)
    snapshot_parser.add_argument("--snapshot-dir", required=True)

    auth_parser = sub.add_parser("authorize", help="Create a one-shot authorization bound to a plan and its snapshot")
    auth_parser.add_argument("--plan-file", required=True)
    auth_parser.add_argument("--snapshot-manifest", required=True, help="Path to the manifest from prepare-snapshot")
    auth_parser.add_argument("--phrase", required=True)
    auth_parser.add_argument("--out", required=True)

    apply_parser = sub.add_parser("apply", help="Apply a plan under its bound authorization")
    apply_parser.add_argument("--plan-file", required=True)
    apply_parser.add_argument("--authorization-file", required=True)
    apply_parser.add_argument("--out-dir", required=True)
    apply_parser.add_argument("--receipt", required=True)

    rollback_parser = sub.add_parser("rollback", help="Restore a snapshot byte for byte")
    rollback_parser.add_argument("--snapshot-manifest", required=True)
    rollback_parser.add_argument("--out-dir", required=True)

    args = parser.parse_args()

    if args.command == "plan":
        try:
            plan = _build_plan_from_request_file(Path(args.request_file), Path(args.canon_dir))
        except (RecoveryPlanError, RecoveryAuthorizationError) as error:
            print(stable_json({"status": "blocked", "error": str(error)}, indent=2))
            return 2
        write_plan(plan, Path(args.out))
        print(stable_json({"status": "ok", "plan_id": plan.plan_id, "plan_hash": plan.plan_hash, "plan_file": args.out}, indent=2))
        return 0

    if args.command == "dry-run":
        plan_dict = json.loads(Path(args.plan_file).read_text(encoding="utf-8"))
        # dry-run only needs the metadata fields already in the plan file
        # for its own drift/hash checks; recovered_record is re-derived
        # from the certified source (via the single shared
        # materialize_recovered_record) so a plan file never has to embed
        # it, and dry-run/apply can never diverge on how they rebuild it.
        canon_dir_from_plan = Path(plan_dict["canon_dir"])
        rebuilt_ops = [
            RecoveryOperation(**{**op_dict, "recovered_record": materialize_recovered_record(op_dict, canon_dir_from_plan)})
            for op_dict in plan_dict["operations"]
        ]
        plan = RecoveryPlan(**{**plan_dict, "operations": rebuilt_ops})
        report = dry_run(plan, out_dir=Path(args.out_dir))
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(stable_json(report, indent=2) + "\n", encoding="utf-8")
        print(stable_json(report, indent=2))
        return 0 if report["overall_status"] == "pass" else 3

    if args.command == "prepare-snapshot":
        plan_dict = json.loads(Path(args.plan_file).read_text(encoding="utf-8"))
        operations = [RecoveryOperation(**{**op, "recovered_record": {}}) for op in plan_dict["operations"]]
        plan = RecoveryPlan(**{**plan_dict, "operations": operations})
        try:
            manifest_path = prepare_snapshot(plan, Path(args.snapshot_dir))
        except RecoveryAuthorizationError as error:
            print(stable_json({"status": "blocked", "error": str(error)}, indent=2))
            return 2
        print(stable_json(
            {"status": "ok", "snapshot_manifest": str(manifest_path), "snapshot_manifest_hash": sha256_path(manifest_path)},
            indent=2,
        ))
        return 0

    if args.command == "authorize":
        plan_dict = json.loads(Path(args.plan_file).read_text(encoding="utf-8"))
        operations = [RecoveryOperation(**{**op, "recovered_record": {}}) for op in plan_dict["operations"]]
        plan = RecoveryPlan(**{**plan_dict, "operations": operations})
        try:
            authorization = create_authorization(plan, Path(args.snapshot_manifest), args.phrase)
        except RecoveryAuthorizationError as error:
            print(stable_json({"status": "blocked", "error": str(error)}, indent=2))
            return 2
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(stable_json(authorization, indent=2) + "\n", encoding="utf-8")
        print(stable_json({"status": "ok", "authorization_id": authorization["authorization_id"], "file": args.out}, indent=2))
        return 0

    if args.command == "rollback":
        report = rollback(Path(args.snapshot_manifest), out_dir=Path(args.out_dir))
        print(stable_json(report, indent=2))
        return 0 if report["byte_exact"] else 1

    parser.error(f"unhandled command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
