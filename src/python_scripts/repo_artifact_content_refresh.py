#!/usr/bin/env python3
"""Governed body-content refresh for is_current_repo_artifact Canon records (S0186 Closure Prep, Lane A).

Narrow, single-purpose writer. It does exactly one thing: for Canon records
whose ``source_fields.is_current_repo_artifact == "true"``, refresh the
embedded fenced code block inside ``text`` so it matches the live worktree
file again, when ``characterize_repo_artifacts.compare_content()`` finds a
``substantive_diff``.

Why this exists: METADATA_WRITER_DISCOVERY (S0186 Closure Prep, prior pass)
found that the only real, historically-proven repo-metadata writer
(``repo_metadata_admission_gate.py``, S0148->S0149/S0151) only ever writes
``source_fields.*`` bookkeeping fields -- its apply loop never assigns to
``record['text']``. No script anywhere in the codebase performed a body-
content refresh. This module fills exactly that gap, and only that gap.

Governed flow (S0186 Closure Prep Track B, step B6):

    DISCOVER -> PLAN -> DRY-RUN -> PROJECTED CANON -> STRICT + REVERSE-
    PREFLIGHT projected -> PREPARE ROLLBACK SNAPSHOT -> HUMAN AUTHORIZATION
    -> APPLY -> RECEIPT -> VALIDATE LIVE CANON -> ROLLBACK

Non-negotiable contracts, reused rather than reimplemented:

  * currentness authority: ``characterize_repo_artifacts.compare_content()``
    exclusively, against the LIVE worktree, every time. Never
    ``s0146_repo_artifact_classification.jsonl`` -- that cache is not read
    anywhere in this module.
  * identity: ``id``/``key``/``title``/``canonical_slug`` are NEVER changed
    by this writer -- a content refresh never touches identity. (Identity
    correction, e.g. fixing a typo'd title/repo_path, is a structurally
    different typed change -- "Lane B" -- explicitly out of scope here; see
    S0186 Closure Prep's Lane B investigation.)
  * version_id: recomputed via the SAME official formula
    ``normalize_session_titles._recompute_version_id`` already uses
    (sha256 of canonical_json({key, title, text, created, modified})) --
    imported directly, never re-derived by hand.
  * scope discovery: LIVE every call. Never a hardcoded record-id list.

Allowed changed fields for a Lane A operation: ``text``, ``modified``,
``version_id``. ``modified`` must advance because ``text`` changed --
freezing it would make the record's own last-modified marker lie about the
content it carries. ``created`` never changes (original admission time,
unaffected by a later content refresh). Everything else (id, key, title,
canonical_slug, relations, tags, source_tags, normalized_tags,
source_fields.* other than nothing -- source_fields is NOT touched by this
writer at all) must remain byte-identical; any other observed change
aborts the operation.

Known, explicitly-flagged limitation: some repo-artifact records also
carry a derived ``content.plain`` projection of ``text`` (produced by an
unrelated pipeline stage). This writer does not attempt to recompute that
projection -- its exact contract was not identified in this investigation,
and ``compare_content()`` (the sole currentness authority used throughout
this session) never reads it. Left untouched deliberately rather than
guessed at.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from characterize_repo_artifacts import (  # noqa: E402
    FENCE_RE,
    compare_content,
    load_canon,
)
from normalize_session_titles import _recompute_version_id  # noqa: E402
from path_governance import sorted_canon_shards  # noqa: E402

DEFAULT_CANON_DIR = REPO_ROOT / "data" / "out" / "local"
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "out" / "local" / "audit" / "repo_artifact_content_refresh"

ALLOWED_CHANGED_TOP_LEVEL_FIELDS = frozenset({"text", "version_id", "content"})
IDENTITY_FIELDS = ("id", "key", "title", "canonical_slug")

APPLY_TOKEN = "APPLY REPO ARTIFACT CONTENT REFRESH"


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _tw_timestamp_now() -> str:
    """17-digit TiddlyWiki-style timestamp, matching the format already used

    across the codebase (generate_session_deliverables.py, admit_session_
    candidates.py, canon_sanitation.py, etc: %Y%m%d%H%M%S + 3-digit ms).
    """
    now = datetime.now(timezone.utc)
    return now.strftime("%Y%m%d%H%M%S") + f"{now.microsecond // 1000:03d}"


def stable_json(value: Any, *, indent: int | None = None) -> str:
    if indent is None:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=indent)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def official_canon_hash(canon_dir: Path) -> str:
    """Reuses the exact algorithm of admit_session_candidates._canon_hash()

    (basename + NUL + bytes + NUL per shard, numeric shard order) --
    imported indirectly via path_governance.sorted_canon_shards to avoid a
    circular import with admit_session_candidates.py, but bit-for-bit the
    same contract, verified against it directly in tests.
    """
    digest = hashlib.sha256()
    for shard in sorted_canon_shards(canon_dir):
        digest.update(shard.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(shard.read_bytes())
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def _resolve_repo_path_for_compare(record: dict[str, Any], repo_path: str, repo_root: Path) -> tuple[str, str, str, str]:
    """Try repo_path as-is, then retry with a src/ prefix (the known gotcha

    from S0186 Closure Cut Stage 2: many repo-artifact records store paths
    relative to src/ without the prefix, and compare_content() does not
    fall back on its own).
    """
    comparison, canon_hash, worktree_hash = compare_content(record, repo_path, repo_root)
    resolved = repo_path
    if comparison == "not_applicable" and repo_path and not repo_path.startswith("src/"):
        retry_path = f"src/{repo_path}"
        c2, ch2, wh2 = compare_content(record, retry_path, repo_root)
        if c2 != "not_applicable":
            comparison, canon_hash, worktree_hash, resolved = c2, ch2, wh2, retry_path
    return comparison, canon_hash, worktree_hash, resolved


@dataclass
class DiscoveredStaleRecord:
    canon_record_id: str
    repo_path: str
    resolved_repo_path: str
    before_text_hash: str
    live_source_hash: str
    shard: str
    line_number: int
    is_multi_block_document: bool = False


def discover_live_stale(canon_dir: Path = DEFAULT_CANON_DIR, repo_root: Path = REPO_ROOT) -> list[DiscoveredStaleRecord]:
    """DISCOVER step. Scans LIVE Canon + LIVE worktree every call -- never a

    hardcoded id list, never s0146's cache.

    A record compare_content() calls substantive_diff is re-checked with
    the MULTI_BLOCK_DOCUMENT comparator whenever Go's real ExtractCodeBlocks
    finds more than one block in its text -- compare_content()'s single-
    block model is not meaningful for those, and was proven (2026-09-08) to
    produce false positives for exactly this document shape. A record the
    multi-block comparator finds already current is correctly excluded
    here, not silently carried forward as "stale."
    """
    canon_glob = str(canon_dir / "tiddlers_*.jsonl")
    records = load_canon(canon_glob)
    stale: list[DiscoveredStaleRecord] = []
    normalize_scratch = DEFAULT_OUT_DIR / "_discovery_multi_block_scratch"
    for rec in records:
        source_fields = rec.get("source_fields") or {}
        if str(source_fields.get("is_current_repo_artifact") or "").lower() != "true":
            continue
        repo_path = str(source_fields.get("repo_path") or "")
        if not repo_path:
            continue
        comparison, canon_hash, worktree_hash, resolved = _resolve_repo_path_for_compare(rec, repo_path, repo_root)
        if comparison != "substantive_diff":
            continue

        is_multi_block = False
        if count_go_code_blocks(rec, normalize_scratch) > 1:
            is_multi_block = True
            mb = classify_multi_block_currentness(rec, resolved, repo_root)
            if mb["comparison"] in ("exact_match", "normalized_newline_match"):
                continue  # correctly current -- do not carry forward as stale
            if mb["comparison"] != "substantive_diff":
                continue  # not_applicable (e.g. unexpected trailer) -- do not guess, exclude rather than misclassify
            canon_hash = mb.get("wrapped_content_hash", canon_hash)
            worktree_hash = mb.get("live_hash", worktree_hash)

        stale.append(
            DiscoveredStaleRecord(
                canon_record_id=str(rec.get("id") or ""),
                repo_path=repo_path,
                resolved_repo_path=resolved,
                before_text_hash=canon_hash,
                live_source_hash=worktree_hash,
                shard=str(rec.get("_canon_shard") or ""),
                line_number=int(rec.get("_jsonl_source_line") or 0),
                is_multi_block_document=is_multi_block,
            )
        )
    return stale


def _splice_fenced_content(old_text: str, live_text: str) -> tuple[str | None, str]:
    """Replace the first fenced code block's inner content with live_text,

    preserving everything else in old_text (preamble, fence markers,
    language tag) byte-for-byte. Returns (new_text_or_None, reason) --
    None if no fenced block was found (caller must BLOCK, never guess).
    """
    match = FENCE_RE.search(old_text)
    if match is None:
        return None, "no_fenced_code_block_found"
    new_text = old_text[: match.start(1)] + live_text + old_text[match.end(1) :]
    return new_text, "ok"


# ---------------------------------------------------------------------------
# MULTI_BLOCK_DOCUMENT_REFRESH -- a separate, narrow, typed lane.
#
# S0186 Closure Prep (2026-09-08): 7 .github/instructions/*.md repo-artifact
# records were flagged substantive_diff by compare_content(), but direct
# investigation with the OFFICIAL Go ExtractCodeBlocks (never a Python
# regex as a semantic substitute) proved compare_content()'s verdict was a
# false positive for all 7: these records' `text` wraps an ENTIRE live file
# (preamble + one outer "```lang\n...\n```" fence) whose OWN content
# legitimately contains several further nested fenced examples. Go's
# ExtractCodeBlocks has no concept of "outer wrapper" -- it flatly,
# sequentially pairs every ``` marker it finds, so `first_code_block()`
# (which compare_content() uses, prioritizing content.code_blocks[0] when
# present) ends up comparing a small internal fragment against the WHOLE
# live file. All 7 were independently confirmed (block-by-block: same
# count, same sizes, same order, AND a direct byte-exact whole-region
# string comparison) to already be 100% current -- zero characters of
# actual drift. This lane exists to (a) detect this document class
# correctly so it is never again misclassified via the single-block
# model, and (b) provide a REAL, evidence-based replacement mechanism for
# the day one of these documents genuinely does drift.
# ---------------------------------------------------------------------------


def _find_whole_wrapped_region(text: str) -> tuple[str, str, str, str] | None:
    """Pure string search (no regex) for the outer fence wrapping an entire

    live file. Returns (preamble, fence_open_line, wrapped_content,
    trailer) or None if no fence pair exists. This reading is ONLY valid
    for documents independently confirmed multi-block by
    count_go_code_blocks() -- it is never used as a substitute for
    compare_content() on ordinary single-fence records, and never assumes
    "first block" / "largest block" / arbitrary concatenation: it is the
    literal span from the first fence's opening line to the text's final
    ``` marker, evidenced (not assumed) to correspond to "the whole live
    file" for this document class.
    """
    first_fence_pos = text.find("```")
    if first_fence_pos == -1:
        return None
    fence_open_line_end = text.find("\n", first_fence_pos)
    if fence_open_line_end == -1:
        return None
    fence_open_line_end += 1
    last_fence_pos = text.rfind("```")
    if last_fence_pos <= fence_open_line_end:
        return None
    preamble = text[:first_fence_pos]
    fence_open_line = text[first_fence_pos:fence_open_line_end]
    wrapped_content = text[fence_open_line_end:last_fence_pos]
    if wrapped_content.endswith("\n"):
        wrapped_content = wrapped_content[:-1]
    trailer = text[last_fence_pos + 3 :]
    return preamble, fence_open_line, wrapped_content, trailer


def count_go_code_blocks(record: dict[str, Any], work_dir: Path) -> int:
    """Authoritative multi-block detection via the REAL Go ExtractCodeBlocks

    (canon_preflight --mode normalize) -- never a Python regex count,
    which is already proven to disagree with Go's own sequential
    fence-pairing semantics (see the reverted FENCE_RE change).
    """
    normalized = _run_canon_normalize([record], work_dir)
    if not normalized:
        return 0
    blocks = normalized[0].get("content", {}).get("code_blocks", [])
    return len(blocks) if isinstance(blocks, list) else 0


def classify_multi_block_currentness(
    record: dict[str, Any], repo_path: str, repo_root: Path
) -> dict[str, Any]:
    """MULTI_BLOCK_DOCUMENT comparator. For documents with >1 Go-extracted

    code block, compares the WHOLE wrapped region (one unit) against the
    live file -- the model empirically demonstrated correct for this
    document class -- instead of compare_content()'s first-block-vs-
    whole-file model, which is not meaningful once a document contains
    more than one real block.
    """
    from characterize_repo_artifacts import comparable_text, sha256_text

    text = record.get("text") or ""
    region = _find_whole_wrapped_region(text)
    if region is None:
        return {"comparison": "not_applicable", "reason": "no_fence_region_found"}
    preamble, fence_open_line, wrapped_content, trailer = region
    if trailer.strip():
        return {"comparison": "not_applicable", "reason": "unexpected_trailer_after_closing_fence"}
    live_path = repo_root / repo_path
    if not live_path.is_file():
        return {"comparison": "not_applicable", "reason": "live_file_missing"}
    live_text = live_path.read_text(encoding="utf-8", errors="replace")
    if wrapped_content == live_text:
        comparison = "exact_match"
    elif comparable_text(wrapped_content) == comparable_text(live_text):
        comparison = "normalized_newline_match"
    else:
        comparison = "substantive_diff"
    return {
        "comparison": comparison,
        "preamble": preamble,
        "fence_open_line": fence_open_line,
        "wrapped_content_hash": sha256_text(wrapped_content),
        "live_hash": sha256_text(live_text),
        "live_text": live_text,
    }


def _splice_whole_region(old_text: str, live_text: str) -> tuple[str | None, str]:
    """Replace the ENTIRE wrapped region (all nested blocks + interstitial

    prose) with a fresh read of the live file, as one atomic unit --
    preserving the preamble and trailer byte-for-byte. Interstitial prose
    between examples is never separately tracked or reconstructed: it is
    simply part of the live file's own content, carried over automatically
    by replacing the whole region from one single live read.
    """
    region = _find_whole_wrapped_region(old_text)
    if region is None:
        return None, "no_whole_region_found"
    preamble, fence_open_line, _wrapped_content, trailer = region
    if trailer.strip():
        return None, "unexpected_trailer_after_closing_fence"
    new_text = preamble + fence_open_line + live_text + "\n```" + trailer
    return new_text, "ok"


def verify_block_correspondence(
    new_record: dict[str, Any], live_text_for_wrapping: str, preamble: str, fence_open_line: str, work_dir: Path
) -> dict[str, Any]:
    """Demonstrates block correspondence (B9's explicit requirement) by

    independently normalizing (a) the actual spliced record and (b) a
    synthetic record built by wrapping the SAME live text the same way,
    then comparing Go's own ExtractCodeBlocks output between the two:
    same block count, same sizes, in the same order. This is evidence,
    not an assumption -- if Go's real parser disagrees with itself between
    these two constructions, something about the splice is wrong and this
    must be surfaced, not hidden.
    """
    synthetic = dict(new_record)
    synthetic["text"] = preamble + fence_open_line + live_text_for_wrapping + "\n```"
    synthetic.pop("content", None)
    # Two SEPARATE normalize calls, not one combined input: Go's
    # LoadCanonSource runs an unconditional strict pre-check before mode
    # dispatch (even for --mode normalize) that rejects duplicate ids --
    # and `synthetic` deliberately shares `new_record`'s id (dict(new_record)).
    (actual_normalized,) = _run_canon_normalize([new_record], work_dir / "actual")
    (synthetic_normalized,) = _run_canon_normalize([synthetic], work_dir / "synthetic")
    actual_blocks = actual_normalized.get("content", {}).get("code_blocks", [])
    synthetic_blocks = synthetic_normalized.get("content", {}).get("code_blocks", [])
    actual_sizes = [b.get("byte_count") for b in actual_blocks] if isinstance(actual_blocks, list) else []
    synthetic_sizes = [b.get("byte_count") for b in synthetic_blocks] if isinstance(synthetic_blocks, list) else []
    actual_texts = [b.get("text") for b in actual_blocks] if isinstance(actual_blocks, list) else []
    synthetic_texts = [b.get("text") for b in synthetic_blocks] if isinstance(synthetic_blocks, list) else []
    return {
        "block_count_matches": len(actual_sizes) == len(synthetic_sizes),
        "block_sizes_match_in_order": actual_sizes == synthetic_sizes,
        "block_text_matches_in_order": actual_texts == synthetic_texts,
        "actual_block_count": len(actual_sizes),
    }


@dataclass
class PlanEntry:
    canon_record_id: str
    repo_path: str
    comparison_status: str
    before_text_hash: str
    live_source_hash: str
    projected_text_hash: str | None
    before_version_id: str
    projected_version_id: str | None
    fields_expected_to_change: list[str]
    fields_expected_to_remain_identical: list[str]
    intended_action: str
    shard: str
    line_number: int
    new_text: str | None = None
    new_modified: str | None = None
    block_reason: str | None = None
    is_multi_block_document: bool = False
    block_correspondence: dict[str, Any] | None = None


@dataclass
class RefreshPlan:
    schema_version: str
    plan_id: str
    plan_hash: str
    generated_at: str
    canon_before_hash: str
    canon_before_records: int
    entries: list[PlanEntry]
    ready_count: int
    blocked_count: int

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "plan_hash": self.plan_hash,
            "generated_at": self.generated_at,
            "canon_before_hash": self.canon_before_hash,
            "canon_before_records": self.canon_before_records,
            "ready_count": self.ready_count,
            "blocked_count": self.blocked_count,
            "entries": [
                {
                    "canon_record_id": e.canon_record_id,
                    "repo_path": e.repo_path,
                    "comparison_status": e.comparison_status,
                    "before_text_hash": e.before_text_hash,
                    "live_source_hash": e.live_source_hash,
                    "projected_text_hash": e.projected_text_hash,
                    "before_version_id": e.before_version_id,
                    "projected_version_id": e.projected_version_id,
                    "fields_expected_to_change": e.fields_expected_to_change,
                    "fields_expected_to_remain_identical": e.fields_expected_to_remain_identical,
                    "intended_action": e.intended_action,
                    "block_reason": e.block_reason,
                    "is_multi_block_document": e.is_multi_block_document,
                    "block_correspondence": e.block_correspondence,
                }
                for e in self.entries
            ],
        }


def build_plan(canon_dir: Path = DEFAULT_CANON_DIR, repo_root: Path = REPO_ROOT) -> RefreshPlan:
    """PLAN step. Pure computation, no filesystem writes."""
    canon_before_hash = official_canon_hash(canon_dir)
    canon_glob = str(canon_dir / "tiddlers_*.jsonl")
    canon_records = load_canon(canon_glob)
    canon_before_records = len(canon_records)
    by_id = {str(r.get("id") or ""): r for r in canon_records}

    stale = discover_live_stale(canon_dir, repo_root)
    entries: list[PlanEntry] = []
    for item in stale:
        rec = by_id[item.canon_record_id]
        old_text = rec.get("text") or ""
        live_path = repo_root / item.resolved_repo_path
        try:
            live_text = live_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            entries.append(
                PlanEntry(
                    canon_record_id=item.canon_record_id,
                    repo_path=item.repo_path,
                    comparison_status="substantive_diff",
                    before_text_hash=item.before_text_hash,
                    live_source_hash=item.live_source_hash,
                    projected_text_hash=None,
                    before_version_id=str(rec.get("version_id") or ""),
                    projected_version_id=None,
                    fields_expected_to_change=[],
                    fields_expected_to_remain_identical=sorted(set(rec.keys()) - {"text"}),
                    intended_action="BLOCKED",
                    shard=item.shard,
                    line_number=item.line_number,
                    block_reason="live_source_unreadable",
                )
            )
            continue

        if item.is_multi_block_document:
            new_text, reason = _splice_whole_region(old_text, live_text)
        else:
            new_text, reason = _splice_fenced_content(old_text, live_text)
        if new_text is None:
            entries.append(
                PlanEntry(
                    canon_record_id=item.canon_record_id,
                    repo_path=item.repo_path,
                    comparison_status="substantive_diff",
                    before_text_hash=item.before_text_hash,
                    live_source_hash=item.live_source_hash,
                    projected_text_hash=None,
                    before_version_id=str(rec.get("version_id") or ""),
                    projected_version_id=None,
                    fields_expected_to_change=[],
                    fields_expected_to_remain_identical=sorted(set(rec.keys()) - {"text"}),
                    intended_action="BLOCKED",
                    shard=item.shard,
                    line_number=item.line_number,
                    block_reason=reason,
                )
            )
            continue

        block_correspondence: dict[str, Any] | None = None
        if item.is_multi_block_document:
            # Verify via the MULTI_BLOCK comparator (whole-region vs live),
            # never compare_content()'s single-block model -- and
            # additionally demonstrate block correspondence (B9): Go's own
            # ExtractCodeBlocks must agree between the actual spliced record
            # and an independently-built synthetic wrapping of the same
            # live text.
            probe_record = dict(rec)
            probe_record["text"] = new_text
            mb = classify_multi_block_currentness(probe_record, item.resolved_repo_path, repo_root)
            verify_comparison = mb["comparison"]
            verify_canon_hash = mb.get("wrapped_content_hash", "")
            if verify_comparison in ("exact_match", "normalized_newline_match"):
                region = _find_whole_wrapped_region(new_text)
                if region is not None:
                    preamble, fence_open_line, _wc, _tr = region
                    block_correspondence = verify_block_correspondence(
                        probe_record, live_text, preamble, fence_open_line,
                        DEFAULT_OUT_DIR / "_plan_multi_block_scratch",
                    )
                    if not (block_correspondence["block_count_matches"] and block_correspondence["block_text_matches_in_order"]):
                        verify_comparison = "substantive_diff"
        else:
            # Self-verify the splice against the SAME authority used for discovery,
            # rather than trusting hand-derived newline arithmetic.
            probe_record = dict(rec)
            probe_record["text"] = new_text
            probe_record.pop("content", None)  # force FENCE_RE fallback, not a stale content.code_blocks
            verify_comparison, verify_canon_hash, _verify_worktree_hash, _ = _resolve_repo_path_for_compare(
                probe_record, item.repo_path, repo_root
            )
        if verify_comparison not in ("exact_match", "normalized_newline_match"):
            entries.append(
                PlanEntry(
                    canon_record_id=item.canon_record_id,
                    repo_path=item.repo_path,
                    comparison_status="substantive_diff",
                    before_text_hash=item.before_text_hash,
                    live_source_hash=item.live_source_hash,
                    projected_text_hash=None,
                    before_version_id=str(rec.get("version_id") or ""),
                    projected_version_id=None,
                    fields_expected_to_change=[],
                    fields_expected_to_remain_identical=sorted(set(rec.keys()) - {"text"}),
                    intended_action="BLOCKED",
                    shard=item.shard,
                    line_number=item.line_number,
                    block_reason=f"post_splice_verification_failed:{verify_comparison}",
                )
            )
            continue

        # `modified` is deliberately NOT bumped. No official contract requires
        # it to advance when text changes -- grepped src/go/canon/*.go for any
        # rule relating Modified to Text/Created: none exists. The actual
        # codebase precedent (canon_content_recovery.py's version_id
        # recomputation, normalize_session_titles.py's identity update) both
        # read/leave the record's OWN existing `modified` untouched even when
        # `text` (or identity) genuinely changes. Bumping it here would have
        # been an intuition-based choice this frontier explicitly asked not
        # to make without contractual evidence -- there is none, so `modified`
        # is preserved, matching the demonstrated precedent.
        unchanged_modified = rec.get("modified")
        new_version_id = _recompute_version_id(
            str(rec.get("key") or ""),
            str(rec.get("title") or ""),
            new_text,
            rec.get("created"),
            unchanged_modified,
        )
        entries.append(
            PlanEntry(
                canon_record_id=item.canon_record_id,
                repo_path=item.repo_path,
                comparison_status="substantive_diff",
                before_text_hash=item.before_text_hash,
                live_source_hash=item.live_source_hash,
                projected_text_hash=verify_canon_hash,
                before_version_id=str(rec.get("version_id") or ""),
                projected_version_id=new_version_id,
                fields_expected_to_change=["text", "version_id"],
                fields_expected_to_remain_identical=sorted(set(rec.keys()) - {"text", "version_id"}),
                intended_action="MULTI_BLOCK_DOCUMENT_REFRESH" if item.is_multi_block_document else "REPO_ARTIFACT_CONTENT_REFRESH",
                is_multi_block_document=item.is_multi_block_document,
                block_correspondence=block_correspondence,
                shard=item.shard,
                line_number=item.line_number,
                new_text=new_text,
                new_modified=unchanged_modified,
            )
        )

    ready = [e for e in entries if e.block_reason is None]
    blocked = [e for e in entries if e.block_reason is not None]
    generated_at = _iso_now()
    # Deliberately excludes projected_version_id/new_modified/new_text from the
    # hash body: those are freshly (and correctly) regenerated on every
    # build_plan() call by design (a real, honest "now" timestamp), so binding
    # them would make plan_hash non-deterministic even with ZERO real drift --
    # defeating the entire point of comparing hashes to detect drift. What
    # actually signals drift is the observed STATE (Canon's current content,
    # the live repo file's current content), which these fields capture.
    plan_body = {
        "canon_before_hash": canon_before_hash,
        "entries": [
            {
                "canon_record_id": e.canon_record_id,
                "repo_path": e.repo_path,
                "before_text_hash": e.before_text_hash,
                "live_source_hash": e.live_source_hash,
                "projected_text_hash": e.projected_text_hash,
                "intended_action": e.intended_action,
                "block_reason": e.block_reason,
            }
            for e in entries
        ],
    }
    plan_hash = "sha256:" + sha256_bytes(stable_json(plan_body).encode("utf-8"))
    plan_id = "rac_refresh_" + plan_hash.split(":", 1)[1][:16]

    return RefreshPlan(
        schema_version="repo-artifact-content-refresh-plan/v1",
        plan_id=plan_id,
        plan_hash=plan_hash,
        generated_at=generated_at,
        canon_before_hash=canon_before_hash,
        canon_before_records=canon_before_records,
        entries=entries,
        ready_count=len(ready),
        blocked_count=len(blocked),
    )


def _run_canon_preflight(mode: str, input_path: Path) -> dict[str, Any]:
    go_dir = REPO_ROOT / "src" / "go" / "canon"
    result = subprocess.run(
        ["go", "run", "./cmd/canon_preflight", "--mode", mode, "--input", str(input_path.resolve())],
        cwd=go_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "mode": mode,
        "exit_code": result.returncode,
        "passed": result.returncode == 0,
        "stdout_tail": result.stdout[-2000:],
        "stderr_tail": result.stderr[-2000:],
    }


def _run_canon_normalize(records: list[dict[str, Any]], work_dir: Path) -> list[dict[str, Any]]:
    """Runs the OFFICIAL Go normalize step on exactly the given records --

    never a Python reimplementation of DeriveContentPlain/ExtractCodeBlocks.
    Called on an ISOLATED subset (only the records this plan actually
    touches), never on a whole shard, so normalize's own side effect of
    also correcting unrelated pre-existing content drift elsewhere in the
    same shard can never leak into this operation's scope (B2: normalize
    must not hide unrelated mutations).
    """
    if not records:
        return []
    work_dir.mkdir(parents=True, exist_ok=True)
    raw_path = work_dir / "pre_normalize.jsonl"
    normalized_path = work_dir / "post_normalize.jsonl"
    raw_path.write_text("".join(stable_json(r) + "\n" for r in records), encoding="utf-8")
    go_dir = REPO_ROOT / "src" / "go" / "canon"
    result = subprocess.run(
        ["go", "run", "./cmd/canon_preflight", "--mode", "normalize", "--input", str(raw_path.resolve()), "--output", str(normalized_path.resolve())],
        cwd=go_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"official canon_preflight --mode normalize failed: {result.stderr[-2000:]}")
    normalized = [json.loads(line) for line in normalized_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(normalized) != len(records):
        raise RuntimeError(
            f"canon_preflight --mode normalize returned {len(normalized)} line(s) for {len(records)} input line(s)"
        )
    # NormalizeCanonJSONL is a streaming, line-by-line transform (Go source
    # confirmed no sorting/reordering) -- positional order is preserved.
    # Deliberately NOT re-matched by id: two callers-supplied records may
    # legitimately share an id (e.g. verify_block_correspondence's synthetic
    # probe), which would silently collapse an id-keyed lookup to one entry.
    return normalized


def classify_normalize_scope(before: dict[str, Any], pre_normalize: dict[str, Any], post_normalize: dict[str, Any]) -> dict[str, Any]:
    """B2: compare before -> projected pre-normalize -> projected

    post-normalize, and classify every modified field as DIRECT_REFRESH
    (this writer's own {text, modified, version_id} change),
    REQUIRED_DERIVATION (a contractual consequence of that change, applied
    by the official normalize step -- expected to be exactly `content`),
    or UNEXPECTED (anything else -- must never happen; a non-empty result
    here means this operation is not safe to apply).
    """
    direct_refresh = {k for k in set(before) | set(pre_normalize) if before.get(k) != pre_normalize.get(k)}
    derivation_candidates = {k for k in set(pre_normalize) | set(post_normalize) if pre_normalize.get(k) != post_normalize.get(k)}
    required_derivation = derivation_candidates & {"content"}
    unexpected = derivation_candidates - required_derivation
    return {
        "direct_refresh": sorted(direct_refresh),
        "required_derivation": sorted(required_derivation),
        "unexpected": sorted(unexpected),
    }


def build_projected_canon(plan: RefreshPlan, canon_dir: Path, out_dir: Path) -> tuple[Path, list[dict[str, Any]]]:
    """Copy real Canon shards into a scratch dir and apply only the READY

    (non-blocked) plan entries there, running each through the official
    Go normalize step (isolated to just those records) before writing.
    Never touches real Canon. Returns (projected_dir, scope_classifications).
    """
    projected_dir = out_dir / plan.plan_id / "projected_canon"
    if projected_dir.exists():
        shutil.rmtree(projected_dir)
    projected_dir.mkdir(parents=True, exist_ok=True)
    for shard in sorted_canon_shards(canon_dir):
        shutil.copy2(shard, projected_dir / shard.name)

    by_shard: dict[str, list[PlanEntry]] = {}
    for e in plan.entries:
        if e.block_reason is not None:
            continue
        by_shard.setdefault(e.shard, []).append(e)

    # Phase 1: splice text/modified/version_id in-memory for every touched
    # record, keeping a {id: (before, pre_normalize)} map for classification.
    before_by_id: dict[str, dict[str, Any]] = {}
    pre_normalize_by_id: dict[str, dict[str, Any]] = {}
    for shard_name, entries in by_shard.items():
        shard_path = projected_dir / shard_name
        by_id = {e.canon_record_id: e for e in entries}
        for raw in shard_path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            record = json.loads(raw)
            entry = by_id.get(str(record.get("id") or ""))
            if entry is None:
                continue
            before_by_id[entry.canon_record_id] = dict(record)
            spliced = dict(record)
            spliced["text"] = entry.new_text
            spliced["version_id"] = entry.projected_version_id
            pre_normalize_by_id[entry.canon_record_id] = spliced

    # Phase 2: run the OFFICIAL normalize step once, on exactly this isolated set.
    ordered_ids = list(pre_normalize_by_id.keys())
    pre_normalize_records = [pre_normalize_by_id[i] for i in ordered_ids]
    normalize_work_dir = out_dir / plan.plan_id / "normalize"
    post_normalize_records = _run_canon_normalize(pre_normalize_records, normalize_work_dir)
    post_normalize_by_id = {str(r.get("id") or ""): r for r in post_normalize_records}

    # Phase 3: classify scope (B2) and write the post-normalize records back.
    scope_classifications: list[dict[str, Any]] = []
    for record_id in ordered_ids:
        scope = classify_normalize_scope(before_by_id[record_id], pre_normalize_by_id[record_id], post_normalize_by_id[record_id])
        scope_classifications.append({"canon_record_id": record_id, **scope})

    for shard_name, entries in by_shard.items():
        shard_path = projected_dir / shard_name
        by_id = {e.canon_record_id: e for e in entries}
        lines = shard_path.read_text(encoding="utf-8").splitlines(keepends=True)
        new_lines = []
        for raw in lines:
            if not raw.strip():
                new_lines.append(raw)
                continue
            record = json.loads(raw)
            entry = by_id.get(str(record.get("id") or ""))
            if entry is None:
                new_lines.append(raw if raw.endswith("\n") else raw + "\n")
                continue
            new_lines.append(stable_json(post_normalize_by_id[entry.canon_record_id]) + "\n")
        shard_path.write_text("".join(new_lines), encoding="utf-8")

    return projected_dir, scope_classifications


def validate_projected_canon(plan: RefreshPlan, canon_dir: Path = DEFAULT_CANON_DIR, out_dir: Path = DEFAULT_OUT_DIR) -> dict[str, Any]:
    """PROJECTED CANON + official NORMALIZE + STRICT + REVERSE-PREFLIGHT

    step. Read-only against real Canon: builds a scratch copy, mutates
    only that (splice, then official Go normalize, isolated to the touched
    records only), runs the official Go canon_preflight binary against the
    scratch copy.
    """
    projected_dir, scope_classifications = build_projected_canon(plan, canon_dir, out_dir)
    strict = _run_canon_preflight("strict", projected_dir)
    reverse = _run_canon_preflight("reverse-preflight", projected_dir)
    projected_hash = official_canon_hash(projected_dir)
    unexpected_total = sum(len(s["unexpected"]) for s in scope_classifications)
    return {
        "projected_canon_dir": str(projected_dir),
        "projected_canon_after_hash": projected_hash,
        "projected_strict": strict,
        "projected_reverse_preflight": reverse,
        "normalize_scope_classifications": scope_classifications,
        "unexpected_normalized_changes": unexpected_total,
        "all_passed": strict["passed"] and reverse["passed"] and unexpected_total == 0,
    }


def prepare_rollback_snapshot(plan: RefreshPlan, canon_dir: Path, out_dir: Path) -> Path:
    """PREPARE ROLLBACK SNAPSHOT step. Copies real shards that WOULD be

    touched, before any real write. Safe to call any time (read-only
    against real Canon; only copies FROM it).
    """
    backup_dir = out_dir / plan.plan_id / "backups" / "canon_before_apply"
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    touched_shards = sorted({e.shard for e in plan.entries if e.block_reason is None})
    manifest_shards = []
    for shard_name in touched_shards:
        source = canon_dir / shard_name
        dest = backup_dir / shard_name
        shutil.copy2(source, dest)
        manifest_shards.append({"source": str(source), "backup": str(dest), "sha256": sha256_bytes(source.read_bytes())})
    manifest = {
        "schema": "repo-artifact-content-refresh-rollback-manifest/v1",
        "plan_id": plan.plan_id,
        "plan_hash": plan.plan_hash,
        "created_at": _iso_now(),
        "backup_dir": str(backup_dir),
        "shards": manifest_shards,
    }
    (out_dir / plan.plan_id / "backups" / "rollback_manifest.json").write_text(
        stable_json(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return backup_dir


def _apply_entry_to_record(record: dict[str, Any], entry: PlanEntry) -> dict[str, Any]:
    """Pure mutation step, isolated for direct unit testing of the scope

    guard. Applies exactly {text, version_id} and raises RuntimeError if the
    resulting record differs from the input in any other field -- the same
    check apply_plan() relies on. `modified` is deliberately untouched (see
    build_plan()'s comment: no contract requires it, and the codebase's own
    precedent leaves it alone even when text changes).
    """
    before_snapshot = dict(record)
    record["text"] = entry.new_text
    record["version_id"] = entry.projected_version_id
    changed_fields = {k for k in record if record.get(k) != before_snapshot.get(k)}
    unexpected = changed_fields - ALLOWED_CHANGED_TOP_LEVEL_FIELDS
    if unexpected:
        raise RuntimeError(f"unexpected field mutation outside allowed scope: {sorted(unexpected)}")
    return record


def apply_plan(
    plan: RefreshPlan,
    *,
    canon_dir: Path = DEFAULT_CANON_DIR,
    repo_root: Path = REPO_ROOT,
    out_dir: Path = DEFAULT_OUT_DIR,
    apply_token: str | None = None,
) -> dict[str, Any]:
    """APPLY step. Recomputes the plan fresh and rejects on ANY drift

    (repo file changed, Canon changed) before writing a single byte --
    same discipline as tmp_lifecycle_governance.execute_cleanup() and
    repo_metadata_admission_gate.py's apply_s0149/s0151_metadata().

    NOT invoked in the S0186 Closure Prep frontier that authorized this
    module's construction -- authorized only through projected validation.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    def blocked(reason: str, **extra: Any) -> dict[str, Any]:
        report = {
            "schema": "repo-artifact-content-refresh-apply-report/v1",
            "plan_id": plan.plan_id,
            "apply_executed": False,
            "apply_blocked": True,
            "block_reason": reason,
            "canon_modified": False,
            **extra,
        }
        return report

    if apply_token != APPLY_TOKEN:
        return blocked("invalid_or_missing_apply_token")

    fresh_plan = build_plan(canon_dir, repo_root)
    if fresh_plan.plan_hash != plan.plan_hash:
        return blocked(
            "plan_drift_detected_recompute_before_reauthorizing",
            bound_plan_hash=plan.plan_hash,
            fresh_plan_hash=fresh_plan.plan_hash,
        )

    ready_entries = [e for e in plan.entries if e.block_reason is None]
    if not ready_entries:
        return blocked("no_ready_entries")

    # Build + validate the projected canon (splice -> official normalize ->
    # strict -> reverse-preflight) ONCE, then apply to real Canon EXACTLY
    # the same post-normalize records it just validated -- never re-derived
    # separately, so what gets written is byte-for-byte what was checked.
    projected_dir, scope_classifications = build_projected_canon(plan, canon_dir, out_dir)
    strict = _run_canon_preflight("strict", projected_dir)
    reverse = _run_canon_preflight("reverse-preflight", projected_dir)
    unexpected_total = sum(len(s["unexpected"]) for s in scope_classifications)
    validation = {
        "projected_strict": strict,
        "projected_reverse_preflight": reverse,
        "normalize_scope_classifications": scope_classifications,
        "unexpected_normalized_changes": unexpected_total,
        "all_passed": strict["passed"] and reverse["passed"] and unexpected_total == 0,
    }
    if not validation["all_passed"]:
        return blocked("projected_preflight_failed", validation=validation)

    prepare_rollback_snapshot(plan, canon_dir, out_dir)

    before_tree = official_canon_hash(canon_dir)
    by_shard: dict[str, list[PlanEntry]] = {}
    for e in ready_entries:
        by_shard.setdefault(e.shard, []).append(e)

    applied_records: list[dict[str, Any]] = []
    for shard_name, entries in by_shard.items():
        shard_path = canon_dir / shard_name
        projected_shard_path = projected_dir / shard_name
        projected_by_id = {
            str(r.get("id") or ""): r
            for r in (json.loads(line) for line in projected_shard_path.read_text(encoding="utf-8").splitlines() if line.strip())
        }
        by_id = {e.canon_record_id: e for e in entries}
        lines = shard_path.read_text(encoding="utf-8").splitlines(keepends=True)
        new_lines = []
        for raw in lines:
            if not raw.strip():
                new_lines.append(raw)
                continue
            record = json.loads(raw)
            entry = by_id.get(str(record.get("id") or ""))
            if entry is None:
                new_lines.append(raw if raw.endswith("\n") else raw + "\n")
                continue
            final_record = projected_by_id[entry.canon_record_id]
            changed_fields = {k for k in set(record) | set(final_record) if record.get(k) != final_record.get(k)}
            unexpected = changed_fields - ALLOWED_CHANGED_TOP_LEVEL_FIELDS
            if unexpected:
                raise RuntimeError(f"unexpected field mutation outside allowed scope: {sorted(unexpected)}")
            applied_records.append({"canon_record_id": entry.canon_record_id, "shard": shard_name, "changed_fields": sorted(changed_fields)})
            new_lines.append(stable_json(final_record) + "\n")
        shard_path.write_text("".join(new_lines), encoding="utf-8")

    after_tree = official_canon_hash(canon_dir)
    receipt = {
        "schema": "repo-artifact-content-refresh-apply-report/v1",
        "plan_id": plan.plan_id,
        "plan_hash": plan.plan_hash,
        "apply_executed": True,
        "apply_blocked": False,
        "records_modified": len(applied_records),
        "applied_records": applied_records,
        "canon_before_hash": before_tree,
        "canon_after_hash": after_tree,
        "canon_modified": before_tree != after_tree,
        "rollback_available": True,
        "timestamp": _iso_now(),
    }
    (out_dir / plan.plan_id / "apply_report.json").write_text(stable_json(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def validate_live_canon(plan: RefreshPlan, canon_dir: Path = DEFAULT_CANON_DIR, repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """VALIDATE LIVE CANON step -- post-apply. Re-runs compare_content() over

    every id this plan touched and confirms none remain substantive_diff.
    """
    canon_glob = str(canon_dir / "tiddlers_*.jsonl")
    records = {str(r.get("id") or ""): r for r in load_canon(canon_glob)}
    results = []
    for e in plan.entries:
        if e.block_reason is not None:
            continue
        rec = records.get(e.canon_record_id)
        if rec is None:
            results.append({"canon_record_id": e.canon_record_id, "status": "MISSING_AFTER_APPLY"})
            continue
        comparison, _, _, _ = _resolve_repo_path_for_compare(rec, e.repo_path, repo_root)
        results.append({"canon_record_id": e.canon_record_id, "status": comparison})
    remaining_stale = [r for r in results if r["status"] == "substantive_diff"]
    return {"checked": len(results), "remaining_substantive_diff": len(remaining_stale), "results": results}


def rollback(plan_id: str, out_dir: Path = DEFAULT_OUT_DIR, canon_dir: Path = DEFAULT_CANON_DIR) -> dict[str, Any]:
    """ROLLBACK step. Restores exactly the shards this plan's backup

    manifest recorded, byte-for-byte.
    """
    manifest_path = out_dir / plan_id / "backups" / "rollback_manifest.json"
    if not manifest_path.exists():
        return {"rollback_executed": False, "rollback_blocked": True, "block_reason": "missing_rollback_manifest"}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    restored = []
    for item in manifest.get("shards", []):
        source = Path(item["source"])
        backup = Path(item["backup"])
        if not backup.exists():
            continue
        shutil.copy2(backup, source)
        restored.append(str(source))
    return {"rollback_executed": bool(restored), "restored_shards": restored, "canon_modified": bool(restored)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canon-dir", type=Path, default=DEFAULT_CANON_DIR)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("mode", choices=("discover", "plan", "validate-projected"))
    args = parser.parse_args(argv)

    if args.mode == "discover":
        stale = discover_live_stale(args.canon_dir, args.repo_root)
        print(stable_json([s.__dict__ for s in stale], indent=2))
    elif args.mode == "plan":
        plan = build_plan(args.canon_dir, args.repo_root)
        print(stable_json(plan.to_json(), indent=2))
    elif args.mode == "validate-projected":
        plan = build_plan(args.canon_dir, args.repo_root)
        result = validate_projected_canon(plan, args.canon_dir, args.out_dir)
        print(stable_json({"plan_id": plan.plan_id, **result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
