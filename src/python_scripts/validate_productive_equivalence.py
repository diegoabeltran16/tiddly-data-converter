#!/usr/bin/env python3
"""Validate governed derivative equivalence against a living local canon.

The validator is deliberately a gate, never a derivative producer.  Version
two retains a historical baseline to expose removals and unexpected changes,
but resolves every candidate record against the canon that is current when the
comparison runs.  A new or changed record is therefore non-blocking only when
its stable canonical identity and canonical ``version_id`` both resolve.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from build_repo_metadata_patch_preview import fields_for_lane as _official_fields_for_lane
from rag_derivation_plan import canonical_snapshot
from rag_derivation_profile import stable_json
from rag_derivative_writers import require_nonproductive_evidence_target


CONTRACT_SCHEMA_VERSION = "productive-equivalence-contract/v2"
REPORT_SCHEMA_VERSION = "productive-equivalence-report/v2"
FAMILY_PATTERNS = {
    "enriched": ("enriched", "tiddlers_enriched_*.jsonl"),
    "ai": ("ai", "tiddlers_ai_*.jsonl"),
    "chunks_ai": ("ai", "chunks_ai_*.jsonl"),
    "semantic_text": ("semantic_text", "*_semantic_text_records.jsonl"),
}
DEFAULT_FAMILIES = ("enriched", "ai", "chunks_ai", "semantic_text", "microsoft_copilot")
OPERATIONAL_KEYS = {
    "run_id",
    "session",
    "generated_from_session",
    "updated_at",
    "created_at",
    "output_root",
    "manifest_path",
    "transaction_id",
    "authority_state",
    "producer_execution_mode",
    "productive_write",
    "productive_regeneration_executed",
    "canon_modified",
    "productive_derivatives_modified",
    "mtime",
}
VERSION_IN_SEMANTIC_TEXT = re.compile(r"^version_id:\s*(\S+)", re.MULTILINE)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _hash_file(path: Path | None) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path and path.exists() else None


def _iter_jsonl_records(paths: list[Path]):
    for path in paths:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError(f"{path}:{line_number} invalid JSON: {error.msg}") from error
                if not isinstance(value, dict):
                    raise ValueError(f"{path}:{line_number} is not a JSON object")
                yield value, path, line_number


def _copilot_records(root: Path) -> list[dict[str, Any]]:
    path = root / "microsoft_copilot" / "entities.json"
    if not path.exists():
        return []
    value = _load_json(path)
    if isinstance(value, dict) and isinstance(value.get("entities"), list):
        return [record for record in value["entities"] if isinstance(record, dict)]
    if isinstance(value, list):
        return [record for record in value if isinstance(record, dict)]
    raise ValueError(f"{path} must contain an entities list")


def _record_id(record: dict[str, Any], family: str) -> str | None:
    key = record.get("chunk_id") if family == "chunks_ai" else (record.get("id") or record.get("node_id") or record.get("tiddler_id"))
    return str(key).strip() if key is not None and str(key).strip() else None


def _source_id(record: dict[str, Any], family: str) -> str | None:
    if family == "chunks_ai":
        key = record.get("source_id") or (record.get("source_anchor") or {}).get("canon_id")
    elif family == "microsoft_copilot":
        key = record.get("id") or (record.get("canon_ref") or {}).get("id")
    else:
        key = record.get("id") or (record.get("source_anchor") or {}).get("canon_id")
    return str(key).strip() if key is not None and str(key).strip() else None


def _legacy_semantic_version(record: dict[str, Any]) -> str | None:
    match = VERSION_IN_SEMANTIC_TEXT.search(str(record.get("semantic_text") or ""))
    return match.group(1) if match else None


def _source_version(record: dict[str, Any], family: str) -> tuple[str | None, str]:
    """Return the source revision and how it was represented by this layer.

    ``semantic_text`` is consulted only for a historical AI baseline whose
    producer predates the explicit field.  New projections expose the version
    directly; this compatibility path is never used as authority over canon.
    """

    candidates: list[tuple[Any, str]] = []
    if family == "chunks_ai":
        candidates.append((record.get("source_version_id"), "source_version_id"))
    elif family == "microsoft_copilot":
        candidates.extend(
            (
                (record.get("version_id"), "version_id"),
                (record.get("content_hash"), "content_hash"),
                ((record.get("canon_ref") or {}).get("content_hash"), "canon_ref.content_hash"),
            )
        )
    else:
        candidates.extend(((record.get("version_id"), "version_id"), (record.get("source_version_id"), "source_version_id")))
    for value, source in candidates:
        if value is not None and str(value).strip():
            return str(value).strip(), source
    legacy = _legacy_semantic_version(record)
    return (legacy, "legacy_semantic_text") if legacy else (None, "missing")


def _normalize(value: Any, baseline_root: Path, staging_root: Path, *, key: str | None = None) -> Any:
    if key in OPERATIONAL_KEYS:
        return None
    if isinstance(value, dict):
        return {
            child_key: _normalize(child_value, baseline_root, staging_root, key=child_key)
            for child_key, child_value in value.items()
            if child_key not in OPERATIONAL_KEYS
        }
    if isinstance(value, list):
        return [_normalize(item, baseline_root, staging_root, key=key) for item in value]
    if isinstance(value, str):
        result = value
        for root in (baseline_root.resolve(), staging_root.resolve()):
            result = result.replace(str(root), "<DERIVATION_ROOT>")
        if key and key.endswith("_path"):
            result = result.replace("/preview/", "/<DERIVATION_ROOT>/").replace("/staging/", "/<DERIVATION_ROOT>/")
        return result
    return value


def _digest(value: Any) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


_LEGACY_REDACTION_MARKER_RE = re.compile(r"\[+RAG_TAG_BLOCKED\](?:_TAG_BLOCKED\])*")


def _is_pure_redaction_marker(chunk: str) -> bool:
    """A differing hunk is "pure marker" when stripping every occurrence of

    the ``[RAG_TAG_BLOCKED]`` safety-redaction marker (including the
    nested/corrupted historical rendering a fixed producer bug used to emit)
    leaves no letters or digits behind. An empty hunk, or one containing no
    marker at all, is never pure marker -- it is either absent content or
    genuinely unrelated text.
    """

    if not chunk:
        return False
    stripped = _LEGACY_REDACTION_MARKER_RE.sub("", chunk)
    if stripped == chunk:
        return False
    return not any(character.isalnum() for character in stripped)


_MARKER_ALNUM = re.sub(r"[^0-9A-Za-z]", "", "RAG_TAG_BLOCKED")
_MIN_TRUSTED_MARKER_FRAGMENT_LENGTH = 8


def _is_marker_derived_fragment(text: str) -> bool:
    """True when ``text``'s letters/digits are themselves a long-enough

    run of the marker's own literal characters (``RAGTAGBLOCKED``) to be
    explained purely by marker-text self-overlap, rather than by real
    content. Guarded by a minimum length so a short, coincidental overlap
    (a genuine word like "tag") is never mistaken for this.
    """

    alnum_only = re.sub(r"[^0-9A-Za-z]", "", text)
    return len(alnum_only) >= _MIN_TRUSTED_MARKER_FRAGMENT_LENGTH and alnum_only in _MARKER_ALNUM


def _matches_with_marker_wildcards(marked_text: str, other_text: str) -> bool:
    """True when ``other_text`` is exactly ``marked_text`` with each marker

    occurrence standing in for some run of real content that ``other_text``
    carries at that same position -- e.g. ``marked_text`` = "estado de
    [RAG_TAG_BLOCKED]" and ``other_text`` = "estado de canon". This covers
    two (or more) redacted terms sitting close enough together that the
    token diff merges them, and the short connective word between them
    (``de``), into one hunk: that hunk is still fully explained by the
    marker if treating each marker as a wildcard reproduces the other side
    exactly.
    """

    if _LEGACY_REDACTION_MARKER_RE.search(marked_text) is None:
        return False
    segments = _LEGACY_REDACTION_MARKER_RE.split(marked_text)
    pattern = r"(?:.|\n)+?".join(re.escape(segment) for segment in segments)
    return re.fullmatch(pattern, other_text) is not None


def _hunk_is_marker_substitution(previous_chunk: str, current_chunk: str) -> bool:
    return (
        _is_pure_redaction_marker(previous_chunk)
        or _is_pure_redaction_marker(current_chunk)
        or _matches_with_marker_wildcards(current_chunk, previous_chunk)
        or _matches_with_marker_wildcards(previous_chunk, current_chunk)
    )


def _hunk_is_marker_substitution_or_pure_addition(previous_chunk: str, current_chunk: str) -> bool:
    """Marker substitution, or content present on the current side with

    nothing at all on the previous side -- pure growth, such as a new
    ``# Relaciones canonicas`` section reflecting a canonical relation H
    legitimately applied after the baseline was produced. Never tolerates a
    hunk with real content on the *previous* side and nothing (or different
    real content) on the current side -- that is a removal or an alteration,
    not growth, and must still block.
    """

    return _hunk_is_marker_substitution(previous_chunk, current_chunk) or previous_chunk == ""


_TOKEN_SPLIT_RE = re.compile(r"(\W+)", re.UNICODE)


def _content_diff_is_tolerable(previous_text: Any, current_text: Any, hunk_is_tolerable) -> bool:
    """True when every differing hunk between the two texts, per a token

    diff, satisfies ``hunk_is_tolerable(previous_chunk, current_chunk)``.
    Shared engine behind ``_redaction_only_difference`` (marker
    substitutions only) and the broader growth check used for governed,
    strictly additive derivative evolution (marker substitutions or pure
    insertions). The diff runs over word/separator tokens (splitting on runs
    of non-word characters, keeping the separators as their own tokens, so
    no fidelity is lost) rather than raw characters -- semantic_text can run
    to several KB, and a character-level diff over thousands of records is
    prohibitively slow, while a token-level diff over the same content is
    not. Splitting on non-word runs (not just whitespace) matters: many
    redacted terms sit inside long hyphenated slugs or paths
    (``m04-s0174-...``, ``canon-bootstrap``) with no internal whitespace, so
    a whitespace-only split would keep the whole slug as one token and make
    an isolated marker substitution look like it touched unrelated
    surrounding text.
    """

    if previous_text == current_text:
        return True
    if not isinstance(previous_text, str) or not isinstance(current_text, str):
        return False
    previous_tokens = _TOKEN_SPLIT_RE.split(previous_text)
    current_tokens = _TOKEN_SPLIT_RE.split(current_text)
    # autojunk's popular-element heuristic only ever makes this diff coarser
    # (larger, not smaller, differing hunks), which can only make the
    # tolerance check below *stricter* -- never hide a real content change --
    # while making this practical on documents with heavily repeated
    # boilerplate tokens (field labels, punctuation, common words).
    matcher = difflib.SequenceMatcher(a=previous_tokens, b=current_tokens)
    # Consecutive non-"equal" opcodes are merged into one hunk before the
    # tolerance check runs: difflib sometimes fragments a single logical
    # change (one term becoming the marker, or one section being inserted)
    # into adjacent delete/insert pairs at an arbitrary token boundary, and
    # checking either half alone would wrongly fail even though the
    # combined change is tolerable as a whole. An "equal" span sitting
    # *inside* such a run is not treated as a trustworthy anchor when it is
    # (a) punctuation-only (brackets, commas, spaces -- no letters or
    # digits), which can coincidentally align with punctuation that used to
    # sit right after the redacted term, or (b) itself just a fragment of
    # the marker's own literal text, which happens when two redacted terms
    # sit close enough together that one marker's characters coincidentally
    # line up with another's -- e.g. two adjacent occurrences of the same
    # redacted term produce ".../[RAG_TAG_BLOCKED]-x/[RAG_TAG_BLOCKED]-x",
    # and the differ can align the partial text "/[RAG_TAG_BLOCKED" across
    # both occurrences as if it were real shared content. Only an "equal"
    # span with real content unrelated to the marker -- or one seen before
    # any run has started -- ends a run; either untrustworthy kind seen
    # mid-run is folded into it instead.
    previous_run: list[str] = []
    current_run: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            equal_text = "".join(previous_tokens[i1:i2])
            if (previous_run or current_run) and (
                not any(character.isalnum() for character in equal_text)
                or _is_marker_derived_fragment(equal_text)
            ):
                previous_run.append(equal_text)
                current_run.append(equal_text)
                continue
            if previous_run or current_run:
                if not hunk_is_tolerable("".join(previous_run), "".join(current_run)):
                    return False
                previous_run, current_run = [], []
            continue
        previous_run.append("".join(previous_tokens[i1:i2]))
        current_run.append("".join(current_tokens[j1:j2]))
    if previous_run or current_run:
        if not hunk_is_tolerable("".join(previous_run), "".join(current_run)):
            return False
    return True


def _redaction_only_difference(previous_text: Any, current_text: Any) -> bool:
    """True when a same-canon-version semantic_text divergence is fully

    attributable to the RAG safety-redaction marker covering more, fewer, or
    different vocabulary than it did when the historical baseline was
    produced -- never to any other content change. The corpus-wide set of
    not-yet-safety-reviewed tags only grows as governance work classifies
    more of it; each newly flagged tag makes the *same*, unchanged producer
    blank out more (or different) mentions of it in already-derived text.
    That is expected evolution of the redaction policy's scope, not a
    regression, so long as every differing span is explainable purely by the
    marker appearing on at least one side. Falls back to a whole-text
    wildcard match (the same test ``_matches_with_marker_wildcards`` applies
    to one merged hunk, applied here to the entire text) when the token-diff
    hunks alone are inconclusive: three or more redacted terms close
    together in the same list can make difflib align text across the wrong
    occurrences, which no per-hunk anchor-trust rule can fully anticipate,
    while treating every marker in the whole text as a wildcard and asking
    "does the other side match exactly" sidesteps hunk alignment entirely.
    """

    if _content_diff_is_tolerable(previous_text, current_text, _hunk_is_marker_substitution):
        return True
    if not isinstance(previous_text, str) or not isinstance(current_text, str):
        return False
    return _matches_with_marker_wildcards(current_text, previous_text) or _matches_with_marker_wildcards(
        previous_text, current_text
    )


def _content_diff_is_non_regressive(previous_text: Any, current_text: Any) -> bool:
    """True when every difference is a redaction-marker substitution or pure

    growth (content present now that had no counterpart before) -- never a
    removal or an alteration of existing content. Broader than
    ``_redaction_only_difference``: it also covers a legitimately-applied
    canonical relation (from H's relational Apply) or a governed metadata
    promotion showing up as brand-new lines the July baseline could not have
    had. Still fails closed on anything that removes or changes existing
    content, exactly like the narrower check.
    """

    return _content_diff_is_tolerable(previous_text, current_text, _hunk_is_marker_substitution_or_pure_addition)


def _is_strict_superset_growth(previous_value: Any, current_value: Any) -> bool:
    """True when ``current_value`` is a list that contains every element of

    ``previous_value`` (also a list) and at least one more -- e.g.
    ``retrieval_hints`` gaining a newly-promoted metadata value. Anything
    else (an element removed, changed, reordered into a different set, or
    either side not a list) is not tolerated -- only unambiguous, lossless
    growth is.
    """

    if not isinstance(previous_value, list) or not isinstance(current_value, list):
        return False
    previous_set = set(previous_value)
    current_set = set(current_value)
    return previous_set < current_set


# semantic_text_builder.normalize_family's own contract: this is the literal
# value it returns whenever no artifact_family classification is present
# (see semantic_text_builder.py, normalize_family: "if not family: return
# 'unknown'") -- an absence-of-knowledge sentinel, never an affirmative
# classification. Referenced by that contract, not chosen ad hoc; if another
# producer establishes a similarly-documented placeholder sentinel for a
# retrieval_hints-contributing field, it belongs in this set too.
_RETRIEVAL_HINT_PLACEHOLDER_VALUES = frozenset({"unknown"})


def _placeholder_pair(old: Any, new: Any, placeholder_values: frozenset[str] = _RETRIEVAL_HINT_PLACEHOLDER_VALUES) -> tuple[str, str] | None:
    if (
        isinstance(old, str)
        and isinstance(new, str)
        and old in placeholder_values
        and new not in placeholder_values
    ):
        return (old, new)
    return None


def _extract_placeholder_pair_from_list(
    previous_value: Any, current_value: Any, placeholder_values: frozenset[str] = _RETRIEVAL_HINT_PLACEHOLDER_VALUES
) -> tuple[str, str] | None:
    """If ``current_value`` is ``previous_value`` (both lists) with exactly

    one contractual placeholder (see ``_RETRIEVAL_HINT_PLACEHOLDER_VALUES``,
    or the caller-supplied ``placeholder_values`` set for a different
    documented sentinel) replaced by exactly one concrete value and nothing
    else changed, return that ``(old, new)`` pair; otherwise ``None``.
    Changing the list's length, swapping more than one element, or
    replacing one placeholder with another (or with nothing) all return
    ``None`` and so keep the surrounding record a regression.
    """

    if not isinstance(previous_value, list) or not isinstance(current_value, list):
        return None
    if len(previous_value) != len(current_value):
        return None
    removed = set(previous_value) - set(current_value)
    added = set(current_value) - set(previous_value)
    if len(removed) != 1 or len(added) != 1:
        return None
    (removed_value,) = removed
    (added_value,) = added
    return _placeholder_pair(removed_value, added_value, placeholder_values)


def _extract_placeholder_pair_from_dict(
    previous_value: Any, current_value: Any, placeholder_values: frozenset[str] = _RETRIEVAL_HINT_PLACEHOLDER_VALUES
) -> tuple[str, str] | None:
    """Same contract as ``_extract_placeholder_pair_from_list``, for a dict

    (e.g. ``embedding_metadata``) with the identical key set where every
    changed key changes to the *same* ``(old, new)`` pair -- e.g.
    ``artifact_family`` and ``semantic_family`` both resolving from
    "unknown" to the same real classification together, from one governed
    admission. Different keys resolving to different pairs, a changed key
    set, or a non-placeholder change on any key all return ``None``.
    """

    if not isinstance(previous_value, dict) or not isinstance(current_value, dict):
        return None
    if set(previous_value.keys()) != set(current_value.keys()):
        return None
    # Values can be unhashable (nested dicts/lists), so compare pairs by
    # equality rather than collecting them into a set.
    changed_pairs: list[tuple[Any, Any]] = []
    for key in previous_value:
        old, new = previous_value[key], current_value[key]
        if old == new:
            continue
        if not changed_pairs or changed_pairs[0] != (old, new):
            changed_pairs.append((old, new))
        if len(changed_pairs) > 1:
            return None
    if len(changed_pairs) != 1:
        return None
    old, new = changed_pairs[0]
    return _placeholder_pair(old, new, placeholder_values)


# semantic_text_builder.build_semantic_text_record's own contract: sections
# are joined as ``"\n\n".join(heading + "\n" + lines)``, so every section
# body in a rendered semantic_text starts at a line matching ``^# `` (a
# top-level heading; sub-bullets and prose never start a line this way in
# practice because redact_terms_for_rag only ever substitutes inline, never
# at column zero with this exact prefix).
_SECTION_HEADING_RE = re.compile(r"(?m)^# .+$")
_SOURCE_FIELDS_HEADING = "# Procedencia / source_fields"


def _split_semantic_text_sections(text: Any) -> tuple[list[str], dict[str, str]] | None:
    """Split a rendered ``semantic_text`` string into its ordered top-level

    sections, keyed by heading. Returns ``None`` (never a guess) when
    ``text`` is not a string, carries no recognizable heading, or repeats a
    heading -- any of which make a structural, section-aware comparison
    unsafe, and the caller must fail closed instead.
    """

    if not isinstance(text, str):
        return None
    matches = list(_SECTION_HEADING_RE.finditer(text))
    if not matches:
        return None
    order: list[str] = []
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        heading = match.group().strip()
        if heading in sections:
            return None
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[heading] = text[start:end]
        order.append(heading)
    return order, sections


def _parse_key_value_lines(body: str) -> dict[str, str] | None:
    """Parse a section body into an ordered ``{key: value}`` mapping, one

    entry per non-blank line of the ``"key: value"`` shape every
    ``sf_lines``/identity-line entry in ``semantic_text_builder.py`` emits.
    Returns ``None`` (fail closed) the moment a line does not match --
    e.g. a multi-line wrapped value, or a section that is not a flat
    key/value listing at all -- rather than guess at its structure.
    """

    fields: dict[str, str] = {}
    for line in body.split("\n"):
        if not line.strip():
            continue
        if ": " not in line:
            return None
        key, value = line.split(": ", 1)
        if key in fields:
            return None
        fields[key] = value
    return fields


# The fixed, evidence-derived set of source_fields keys semantic_text may
# legitimately stop rendering when a record's Canon source_fields are
# replaced by a narrower, governed admission contract (e.g. a thematic
# diagnostic admitted over a pre-existing same-id/same-content record):
# these five are the standard generic-import field set
# (created/modified/tags/tmap.id/type) that a minimal admission contract
# (session_origin/provenance_ref/canonical_status/artifact_family/
# source_path) does not carry forward. Never extended ad hoc -- any other
# key disappearing still fails closed.
_TEMPLATE_PRUNE_ALLOWED_KEYS = frozenset({"created", "modified", "tags", "tmap.id", "type"})

# role_primary's own "not yet classified" sentinel (parallel to
# semantic_text_builder.normalize_family's "unknown" for artifact_family,
# but a distinct value and a distinct field -- kept as its own set rather
# than folded into _RETRIEVAL_HINT_PLACEHOLDER_VALUES so the existing,
# already-governed placeholder_resolved category's behavior is untouched).
_ROLE_PRIMARY_PLACEHOLDER_VALUES = frozenset({"unclassified"})


def _tolerable_template_prune(previous_body: str, current_body: str) -> bool:
    """True when the only difference in a source_fields section body is the

    disappearance of zero-or-more lines whose key is in
    ``_TEMPLATE_PRUNE_ALLOWED_KEYS`` -- no key added, no key removed outside
    that fixed set -- and every surviving shared key's value is either
    unchanged or a redaction-marker substitution (the same tolerance
    ``redaction_only`` already applies elsewhere). Fails closed on any
    other addition, removal, or value change.
    """

    previous_fields = _parse_key_value_lines(previous_body)
    current_fields = _parse_key_value_lines(current_body)
    if previous_fields is None or current_fields is None:
        return False
    removed = set(previous_fields) - set(current_fields)
    added = set(current_fields) - set(previous_fields)
    if added or not removed or not removed <= _TEMPLATE_PRUNE_ALLOWED_KEYS:
        return False
    for key in set(previous_fields) & set(current_fields):
        if previous_fields[key] == current_fields[key]:
            continue
        if not _hunk_is_marker_substitution(previous_fields[key], current_fields[key]):
            return False
    return True


def _semantic_projection_policy_evolution(previous_text: Any, current_text: Any) -> bool:
    """SEMANTIC_PROJECTION_POLICY_EVOLUTION: a same-canon-version semantic_text

    divergence fully explained, section by section, by (a) the permitted
    metadata/template pruning in the source_fields section
    (``_tolerable_template_prune``) and (b) ordinary marker-substitution or
    pure-addition growth (``_content_diff_is_non_regressive``) everywhere
    else. Requires the exact same ordered set of section headings on both
    sides -- no section wholesale added, removed, or reordered -- and fails
    closed the moment any single section fails its own tolerance check.
    """

    if previous_text == current_text:
        return True
    previous_split = _split_semantic_text_sections(previous_text)
    current_split = _split_semantic_text_sections(current_text)
    if previous_split is None or current_split is None:
        return False
    previous_order, previous_sections = previous_split
    current_order, current_sections = current_split
    if previous_order != current_order:
        return False
    for heading in previous_order:
        previous_body = previous_sections[heading]
        current_body = current_sections[heading]
        if previous_body == current_body:
            continue
        if heading == _SOURCE_FIELDS_HEADING:
            if not _tolerable_template_prune(previous_body, current_body):
                return False
        elif not _content_diff_is_non_regressive(previous_body, current_body):
            return False
    return True


# The official Lane B (repo-metadata "historical review") admission surface
# -- called directly, never reimplemented -- so this validator only ever
# trusts field names that module actually assigns. ``moved_to_candidate``
# is conditional on the row carrying one, so it is probed with a synthetic
# truthy value to include it in the returned key set.
_LANE_B_LIFECYCLE_FIXED_TRANSITIONS = {
    "authority_level": "historical_snapshot",
    "is_current_repo_artifact": "false",
    "repo_lifecycle_state": "historical_snapshot",
}
_LANE_B_LIFECYCLE_ALLOWED_TOUCH_KEYS = frozenset(_LANE_B_LIFECYCLE_FIXED_TRANSITIONS) | {"moved_to_candidate"}
_LANE_B_LIFECYCLE_VALUE_TRANSITIONS = frozenset(
    {
        ("current_verified", "historical_snapshot"),
        ("true", "false"),
        ("current_repo_artifact", "historical_snapshot"),
    }
)
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _lane_b_lifecycle_field_names() -> frozenset[str]:
    base = _official_fields_for_lane({}, "lane_b_historical_review", "unknown")
    with_move = _official_fields_for_lane({"moved_to_candidate": "x"}, "lane_b_historical_review", "unknown")
    return frozenset(base) | frozenset(with_move)


def _tolerable_lane_b_lifecycle_transition(previous_body: str, current_body: str) -> bool:
    """True when a source_fields section's only differences are exactly the

    authorized Lane B historical-review transition: ``authority_level``,
    ``is_current_repo_artifact`` and ``repo_lifecycle_state`` all changing
    together to their fixed Lane B target values, plus an optional newly
    added ``moved_to_candidate`` reference (a well-formed UUID). Compared
    line by line (not by parsing a key/value dict) because the corpus-wide
    safety-redaction vocabulary can legitimately blank out a *key* name
    itself (e.g. a newly-flagged tag that happens to collide with
    "authority_level") -- when that happens the value pairing is still the
    authoritative signal, since the fixed transition set is specific enough
    that no unrelated field is expected to carry the exact same three
    values together. A key that is *not* redacted must still name one of
    the fixed lane fields; only a fully marker-redacted key skips that
    check. No line may be removed; a partial lifecycle transition (only
    one or two of the three fixed pairs) is never tolerated; anything
    beyond that fails closed.
    """

    # Real, meaningful use of the official contract (never reimplemented):
    # if a future Lane B revision ever drops one of these field names, this
    # validator must stop trusting them rather than silently keep matching
    # on stale assumptions.
    if not _LANE_B_LIFECYCLE_ALLOWED_TOUCH_KEYS <= _lane_b_lifecycle_field_names():
        return False
    previous_lines = [line for line in previous_body.split("\n") if line.strip()]
    current_lines = [line for line in current_body.split("\n") if line.strip()]
    matcher = difflib.SequenceMatcher(a=previous_lines, b=current_lines)
    # Consecutive non-"equal" opcodes are merged into one run before
    # pairing: alphabetical sort places the new "moved_to_candidate" line
    # between two of the three changing lines, so difflib emits one
    # replace-shaped run covering an unequal number of removed/added lines
    # rather than a clean separate insert -- mirroring the same
    # run-merging discipline ``_content_diff_is_tolerable`` already applies
    # at the token level.
    runs: list[tuple[list[str], list[str]]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        runs.append((previous_lines[i1:i2], current_lines[j1:j2]))
    changed_pairs: list[tuple[str, str]] = []
    added_lines: list[str] = []
    for removed_segment, added_segment in runs:
        segment_added = list(added_segment)
        if len(segment_added) > len(removed_segment):
            # Extract exactly the surplus lines as candidate additions
            # (moved_to_candidate), preferring ones that already look like
            # a well-formed reference line, before falling back to
            # positional surplus -- either way the remainder must still
            # pair up 1:1 with the removed lines below.
            surplus = len(segment_added) - len(removed_segment)
            preferred = [
                line
                for line in segment_added
                if ": " in line and _UUID_RE.match(line.split(": ", 1)[1])
            ]
            extracted: list[str] = []
            remaining = list(segment_added)
            for line in preferred:
                if len(extracted) >= surplus:
                    break
                extracted.append(line)
                remaining.remove(line)
            if len(extracted) != surplus:
                return False
            added_lines.extend(extracted)
            segment_added = remaining
        if len(segment_added) != len(removed_segment):
            return False
        for old_line, new_line in zip(removed_segment, segment_added):
            if ": " not in old_line or ": " not in new_line:
                return False
            old_key, old_value = old_line.split(": ", 1)
            new_key, new_value = new_line.split(": ", 1)
            key_is_ambiguous = _is_pure_redaction_marker(old_key) or _is_pure_redaction_marker(new_key)
            if not key_is_ambiguous and (old_key != new_key or old_key not in _LANE_B_LIFECYCLE_FIXED_TRANSITIONS):
                return False
            changed_pairs.append((old_value, new_value))
    if set(changed_pairs) != _LANE_B_LIFECYCLE_VALUE_TRANSITIONS or len(changed_pairs) != len(_LANE_B_LIFECYCLE_VALUE_TRANSITIONS):
        return False
    if len(added_lines) > 1:
        return False
    if added_lines:
        (added_line,) = added_lines
        if ": " not in added_line:
            return False
        added_key, added_value = added_line.split(": ", 1)
        key_is_ambiguous = _is_pure_redaction_marker(added_key)
        if not key_is_ambiguous and added_key != "moved_to_candidate":
            return False
        if not _UUID_RE.match(added_value):
            return False
    return True


def _non_versioned_canon_projection_evolution(previous_text: Any, current_text: Any) -> bool:
    """NON_VERSIONED_CANON_PROJECTION_EVOLUTION: a same-canon-version

    semantic_text divergence fully explained, section by section, by (a)
    the authorized Lane B lifecycle transition in the source_fields section
    (``_tolerable_lane_b_lifecycle_transition``) and (b) ordinary
    marker-substitution or pure-addition growth everywhere else. Same
    structural discipline as ``_semantic_projection_policy_evolution``:
    identical ordered section headings required, fails closed per section.
    """

    if previous_text == current_text:
        return True
    previous_split = _split_semantic_text_sections(previous_text)
    current_split = _split_semantic_text_sections(current_text)
    if previous_split is None or current_split is None:
        return False
    previous_order, previous_sections = previous_split
    current_order, current_sections = current_split
    if previous_order != current_order:
        return False
    for heading in previous_order:
        previous_body = previous_sections[heading]
        current_body = current_sections[heading]
        if previous_body == current_body:
            continue
        if heading == _SOURCE_FIELDS_HEADING:
            if not _tolerable_lane_b_lifecycle_transition(previous_body, current_body):
                return False
        elif not _content_diff_is_non_regressive(previous_body, current_body):
            return False
    return True


_CONTENT_BODY_MARKER = "# Contenido principal"
_SIMILARITY_WORD_RE = re.compile(r"\w{4,}", re.UNICODE)
_IDENTITY_MIGRATION_SIMILARITY_FLOOR = 0.6


def _extract_content_body(semantic_text: Any) -> str | None:
    """The substantive body of a record, stripped of the identity/metadata

    header sections (title, id, canonical_slug, version_id, tags, source
    fields) that a governed rename or renumbering necessarily changes. Only
    this body is used to test whether a removed record and a newly-added
    one are the same underlying document.
    """

    if not isinstance(semantic_text, str):
        return None
    index = semantic_text.find(_CONTENT_BODY_MARKER)
    return semantic_text[index:] if index != -1 else semantic_text


def _content_word_set(content: str) -> set[str]:
    return set(_SIMILARITY_WORD_RE.findall(content.casefold()))


def _coarse_content_similarity(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def _build_identity_migration_map(
    baseline_surfaces: dict[str, dict[str, dict[str, Any]]],
    staging_surfaces: dict[str, dict[str, dict[str, Any]]],
    families: tuple[str, ...],
) -> dict[str, str]:
    """Positive, deterministic evidence that a removed id and a newly-added

    id are the same governed document under a new identity -- never a
    guess. A removed id migrates only when: (1) canon no longer has it under
    the old id (structurally true for every "removed" candidate here, since
    "removed" already means absent from the current-canon-backed staging
    surface); (2) exactly one currently-added id has a content body that is
    ``_redaction_only_difference``-equivalent to the removed id's content
    body (i.e. identical modulo the same, already-audited safety-redaction
    evolution -- never modulo any other change); and (3) that candidate is
    unique. Two or more candidates that both qualify, zero candidates, or a
    candidate whose content differs by anything beyond redaction, all leave
    the id classified as a real removal (fail-closed). A cheap word-overlap
    prefilter keeps this tractable (candidates otherwise number in the
    thousands) without weakening the exact check that actually decides.
    """

    reference_family = next((family for family in ("ai", "enriched") if family in families), None)
    if reference_family is None:
        return {}
    baseline = baseline_surfaces.get(reference_family, {})
    staging = staging_surfaces.get(reference_family, {})
    removed_ids = sorted(set(baseline) - set(staging))
    added_ids = sorted(set(staging) - set(baseline))
    if not removed_ids or not added_ids:
        return {}

    candidate_contents: dict[str, str] = {}
    candidate_word_sets: dict[str, set[str]] = {}
    for added_id in added_ids:
        content = _extract_content_body(staging[added_id].get("semantic_text_raw"))
        if not content:
            continue
        candidate_contents[added_id] = content
        candidate_word_sets[added_id] = _content_word_set(content)

    migration_map: dict[str, str] = {}
    for removed_id in removed_ids:
        removed_content = _extract_content_body(baseline[removed_id].get("semantic_text_raw"))
        if not removed_content:
            continue
        removed_words = _content_word_set(removed_content)
        matches = [
            candidate_id
            for candidate_id, candidate_content in candidate_contents.items()
            if _coarse_content_similarity(removed_words, candidate_word_sets[candidate_id])
            >= _IDENTITY_MIGRATION_SIMILARITY_FLOOR
            and _redaction_only_difference(removed_content, candidate_content)
        ]
        if len(matches) == 1:
            migration_map[removed_id] = matches[0]
    return migration_map


def _signature(record: dict[str, Any], family: str, root: Path) -> dict[str, Any]:
    """Create a compact, version-aware projection for one derivative record."""

    semantic = _normalize(record.get("semantic_text"), root, root, key="semantic_text")
    metadata = _normalize(record.get("promoted_metadata") or record.get("embedding_metadata"), root, root, key="metadata")
    rag_filter = _normalize(record.get("rag_filters") or record.get("rag_allowed_tags") or record.get("rag_safe_tags"), root, root, key="rag_filter")
    source_anchor = record.get("source_anchor") or {}
    # Shard and line move when canon is compacted; canonical identity does not.
    compact_anchor = {"canon_id": source_anchor.get("canon_id")} if isinstance(source_anchor, dict) else None
    chunk_fields = {
        key: _normalize(record.get(key), root, root, key=key)
        for key in ("text", "chunk_index", "chunk_total", "source_id", "within_hard_max")
    }
    chunk_fields["source_anchor"] = compact_anchor
    retrieval_hints = _normalize(record.get("retrieval_hints") or record.get("retrieval_terms"), root, root, key="retrieval_hints")
    source_version, version_representation = _source_version(record, family)
    return {
        "id": _record_id(record, family),
        "source_id": _source_id(record, family),
        "version_id": source_version,
        "version_representation": version_representation,
        "title": record.get("title"),
        "canonical_slug": record.get("canonical_slug") or record.get("source_canonical_slug"),
        "artifact_family": record.get("artifact_family"),
        "semantic_text_hash": hashlib.sha256(str(semantic).encode("utf-8")).hexdigest(),
        "retrieval_hints_hash": _digest(retrieval_hints),
        "metadata_hash": _digest(metadata),
        "rag_filter_hash": _digest(rag_filter),
        "chunk_fields_hash": _digest(chunk_fields),
        "schema_version": record.get("schema_version"),
        "within_hard_max": record.get("within_hard_max"),
        "semantic_text_raw": semantic,
        "retrieval_hints_raw": retrieval_hints,
        "metadata_raw": metadata,
        "non_semantic_logical_hash": _digest(
            {
                "retrieval_hints": retrieval_hints,
                "metadata": metadata,
                "rag_filter": rag_filter,
                "chunk_fields": chunk_fields,
                "schema_version": record.get("schema_version"),
            }
        ),
        "core_non_semantic_hash": _digest(
            {
                "metadata": metadata,
                "rag_filter": rag_filter,
                "chunk_fields": chunk_fields,
                "schema_version": record.get("schema_version"),
            }
        ),
        "logical_hash": _digest(
            {
                "semantic_text": semantic,
                "retrieval_hints": retrieval_hints,
                "metadata": metadata,
                "rag_filter": rag_filter,
                "chunk_fields": chunk_fields,
                "schema_version": record.get("schema_version"),
            }
        ),
    }


def _logical_records(root: Path, *, families: tuple[str, ...]) -> tuple[dict[str, dict[str, dict[str, Any]]], dict[str, dict[str, list[str]]]]:
    surfaces: dict[str, dict[str, dict[str, Any]]] = {}
    issues: dict[str, dict[str, list[str]]] = {}
    for family in families:
        indexed: dict[str, dict[str, Any]] = {}
        family_issues = {"duplicate_record": [], "identity_mismatch": [], "family_mismatch": [], "chunk_hard_max": []}
        if family == "microsoft_copilot":
            rows = ((record, root / "microsoft_copilot" / "entities.json", number) for number, record in enumerate(_copilot_records(root), start=1))
        else:
            relative, pattern = FAMILY_PATTERNS[family]
            rows = _iter_jsonl_records(sorted((root / relative).glob(pattern)))
        for record, path, line_number in rows:
            record_id = _record_id(record, family) or f"<missing-id>:{path.name}:{line_number}"
            if record_id in indexed:
                family_issues["duplicate_record"].append(record_id)
                continue
            signature = _signature(record, family, root)
            indexed[record_id] = signature
            if signature["id"] is None or signature["source_id"] is None or (family != "chunks_ai" and signature["id"] != signature["source_id"]):
                family_issues["identity_mismatch"].append(record_id)
            explicit_family = signature.get("artifact_family")
            if explicit_family and explicit_family != family:
                family_issues["family_mismatch"].append(record_id)
            if family == "chunks_ai" and signature.get("within_hard_max") is not True:
                family_issues["chunk_hard_max"].append(record_id)
        surfaces[family] = indexed
        issues[family] = family_issues
    return surfaces, issues


def build_canonical_index(canon_dir: Path | str) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Read the current canon once and report invalid authority conditions."""

    root = Path(canon_dir).resolve()
    files = sorted(root.glob("tiddlers_*.jsonl"), key=lambda item: item.name)
    if not files:
        raise FileNotFoundError(f"no canon shards found in {root}")
    index: dict[str, dict[str, Any]] = {}
    issues: dict[str, list[str]] = {"parse_errors": [], "empty_ids": [], "duplicate_ids": [], "empty_versions": [], "invalid_records": []}
    records = 0
    for path in files:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                records += 1
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as error:
                    issues["parse_errors"].append(f"{path.name}:{line_number}:{error.msg}")
                    continue
                if not isinstance(value, dict):
                    issues["invalid_records"].append(f"{path.name}:{line_number}")
                    continue
                record_id = str(value.get("id") or "").strip()
                if not record_id:
                    issues["empty_ids"].append(f"{path.name}:{line_number}")
                    continue
                if record_id in index:
                    issues["duplicate_ids"].append(record_id)
                    continue
                version_id = str(value.get("version_id") or "").strip()
                if not version_id:
                    issues["empty_versions"].append(record_id)
                index[record_id] = {
                    "version_id": version_id or None,
                    "title": value.get("title"),
                    "canonical_slug": value.get("canonical_slug"),
                    "artifact_family": value.get("artifact_family") or (value.get("source_fields") or {}).get("artifact_family"),
                    "present": True,
                }
    snapshot = canonical_snapshot(root)
    counts = {name: len(values) for name, values in issues.items()}
    return index, {
        "canon_dir": str(root),
        "canon_hash": snapshot["source_canon_hash"],
        "shards": len(files),
        "records_seen": records,
        "records_indexed": len(index),
        "valid": not any(counts.values()),
        "issue_counts": counts,
    }


def _new_family_report(family: str, baseline_count: int, current_count: int) -> tuple[dict[str, Any], dict[str, list[str]]]:
    report = {
        "family": family,
        "baseline_records": baseline_count,
        "current_records": current_count,
        "records_compared": 0,
        "unchanged_shared_records": 0,
        "added_from_current_canon": 0,
        "canonical_updates": 0,
        "removed_historical_records": 0,
        "identity_migrated_records": 0,
        "unexpected_semantic_regressions": 0,
        "redaction_vocabulary_evolution": 0,
        "additive_derivative_evolution": 0,
        "placeholder_resolved": 0,
        "semantic_projection_policy_evolution": 0,
        "non_versioned_canon_projection_evolution": 0,
        "invalid_version_transitions": 0,
        "invalid_canonical_membership": 0,
        "identity_mismatches": 0,
        "schema_mismatches": 0,
        "family_mismatches": 0,
        "duplicate_records": 0,
        "chunk_mismatches": 0,
        "chunks_above_hard_max": 0,
        "equivalence_status": "equivalent",
        "blocking": False,
    }
    evidence = {key: [] for key in (
        "unchanged_shared_records", "added_from_current_canon", "canonical_updates", "removed_historical_records",
        "identity_migrated_records",
        "unexpected_semantic_regressions", "redaction_vocabulary_evolution", "additive_derivative_evolution", "placeholder_resolved",
        "semantic_projection_policy_evolution", "non_versioned_canon_projection_evolution", "invalid_version_transitions",
        "invalid_canonical_membership", "identity_mismatches",
        "schema_mismatches", "family_mismatches", "duplicate_records", "chunk_mismatches", "chunks_above_hard_max",
    )}
    return report, evidence


def _evidence_id(signature: dict[str, Any], fallback: str) -> str:
    return str(signature.get("source_id") or signature.get("id") or fallback)


def _family_report(
    family: str,
    baseline: dict[str, dict[str, Any]],
    staging: dict[str, dict[str, Any]],
    baseline_issues: dict[str, list[str]],
    staging_issues: dict[str, list[str]],
    canon: dict[str, dict[str, Any]],
    migration_map: dict[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    migration_map = migration_map or {}
    report, evidence = _new_family_report(family, len(baseline), len(staging))
    for key in ("duplicate_record", "identity_mismatch", "family_mismatch", "chunk_hard_max"):
        destination = {
            "duplicate_record": "duplicate_records",
            "identity_mismatch": "identity_mismatches",
            "family_mismatch": "family_mismatches",
            "chunk_hard_max": "chunks_above_hard_max",
        }[key]
        values = sorted(set(baseline_issues.get(key, []) + staging_issues.get(key, [])))
        report[destination] += len(values)
        evidence[destination].extend(values)

    for record_id in sorted(set(baseline) - set(staging)):
        # migration_map is keyed by canon id (built from a semantic_text-
        # bearing reference family). For enriched/ai/microsoft_copilot,
        # record_id already *is* the canon id. For chunks_ai, record_id is a
        # chunk id ("<canon_id>::chunk::N") -- a chunk vanishing when its
        # source document's identity was governed-migrated is the same
        # migration, observed one derivative layer down, not a separate
        # loss: the whole document's content was already verified
        # equivalent, so every one of its chunks is covered by that same
        # proof. Falling back to the record's own source_id (identical to
        # record_id for the other three families, the chunk's canon id for
        # chunks_ai) is what makes this reclassification apply consistently
        # instead of only to three of the four families.
        baseline_signature = baseline[record_id]
        source_id = baseline_signature.get("source_id") or record_id
        migrated_to = migration_map.get(record_id) or migration_map.get(source_id)
        if migrated_to:
            report["identity_migrated_records"] += 1
            evidence["identity_migrated_records"].append(f"{_evidence_id(baseline_signature, record_id)}->{migrated_to}")
        else:
            report["removed_historical_records"] += 1
            evidence["removed_historical_records"].append(_evidence_id(baseline_signature, record_id))

    for record_id in sorted(staging):
        current = staging[record_id]
        current_id = _evidence_id(current, record_id)
        source_id = current.get("source_id")
        canon_record = canon.get(str(source_id)) if source_id else None
        if canon_record is None:
            report["invalid_canonical_membership"] += 1
            evidence["invalid_canonical_membership"].append(current_id)
            continue
        if not current.get("version_id") or current.get("version_id") != canon_record.get("version_id"):
            report["invalid_version_transitions"] += 1
            evidence["invalid_version_transitions"].append(current_id)
            continue

        previous = baseline.get(record_id)
        if previous is None:
            report["added_from_current_canon"] += 1
            evidence["added_from_current_canon"].append(current_id)
            continue

        report["records_compared"] += 1
        if previous.get("schema_version") != current.get("schema_version"):
            report["schema_mismatches"] += 1
            evidence["schema_mismatches"].append(current_id)
            continue
        if previous.get("version_id") == current.get("version_id"):
            logical_changed = previous.get("logical_hash") != current.get("logical_hash")
            chunk_changed = False
            if family == "chunks_ai" and previous.get("chunk_fields_hash") != current.get("chunk_fields_hash"):
                report["chunk_mismatches"] += 1
                evidence["chunk_mismatches"].append(current_id)
                chunk_changed = True
                logical_changed = True
            if logical_changed:
                # A same-canon-version divergence confined to semantic_text,
                # with every other derived component byte-identical, is
                # expected evolution -- not a regression -- when it is fully
                # explainable by the corpus-wide safety-redaction vocabulary
                # having grown (or shrunk) since the baseline was produced.
                # Any other change (chunk fields, metadata, unrelated text)
                # still blocks exactly as before.
                redaction_only = (
                    not chunk_changed
                    and previous.get("non_semantic_logical_hash") == current.get("non_semantic_logical_hash")
                    and _redaction_only_difference(previous.get("semantic_text_raw"), current.get("semantic_text_raw"))
                )
                # Broader, still fail-closed evolution: every other hashed
                # component besides retrieval_hints is byte-identical,
                # retrieval_hints only ever gained entries (a governed
                # metadata promotion), and semantic_text differs only by
                # redaction and/or pure additions (e.g. a new "Relaciones
                # canonicas" line reflecting a canonical relation H legitimately
                # applied). Anything removed, altered, or otherwise
                # unexplained on any of these axes still blocks.
                additive_growth = (
                    not chunk_changed
                    and not redaction_only
                    and previous.get("core_non_semantic_hash") == current.get("core_non_semantic_hash")
                    and (
                        previous.get("retrieval_hints_hash") == current.get("retrieval_hints_hash")
                        or _is_strict_superset_growth(previous.get("retrieval_hints_raw"), current.get("retrieval_hints_raw"))
                    )
                    and _content_diff_is_non_regressive(previous.get("semantic_text_raw"), current.get("semantic_text_raw"))
                )
                # A third, still fail-closed evolution: a governed admission
                # (e.g. repo-metadata classification) resolved a contractual
                # placeholder (see _RETRIEVAL_HINT_PLACEHOLDER_VALUES) into a
                # concrete value. The exact same (old, new) pair must be
                # independently discoverable from metadata and/or
                # retrieval_hints (agreeing if both changed), rag_filter and
                # chunk_fields must be untouched, and semantic_text must
                # differ only by that same substitution (plus, as always,
                # redaction/pure-addition). A dict with two keys resolving to
                # two *different* pairs, an ambiguous or absent pair, or any
                # residual unexplained difference all fail closed below.
                placeholder_resolved = False
                if not chunk_changed and not redaction_only and not additive_growth:
                    metadata_pair = _extract_placeholder_pair_from_dict(previous.get("metadata_raw"), current.get("metadata_raw"))
                    retrieval_pair = _extract_placeholder_pair_from_list(previous.get("retrieval_hints_raw"), current.get("retrieval_hints_raw"))
                    metadata_ok = previous.get("metadata_hash") == current.get("metadata_hash") or metadata_pair is not None
                    retrieval_ok = previous.get("retrieval_hints_hash") == current.get("retrieval_hints_hash") or retrieval_pair is not None
                    candidate_pairs = {pair for pair in (metadata_pair, retrieval_pair) if pair is not None}
                    if metadata_ok and retrieval_ok and len(candidate_pairs) == 1:
                        (old_value, new_value) = next(iter(candidate_pairs))
                        rest_unchanged = (
                            previous.get("rag_filter_hash") == current.get("rag_filter_hash")
                            and previous.get("chunk_fields_hash") == current.get("chunk_fields_hash")
                        )
                        semantic_ok = previous.get("semantic_text_raw") == current.get("semantic_text_raw") or _content_diff_is_tolerable(
                            previous.get("semantic_text_raw"),
                            current.get("semantic_text_raw"),
                            lambda p, c: _hunk_is_marker_substitution_or_pure_addition(p, c) or (p == old_value and c == new_value),
                        )
                        placeholder_resolved = rest_unchanged and semantic_ok
                # A fourth, still fail-closed evolution: role_primary's own
                # "unclassified" sentinel (see _ROLE_PRIMARY_PLACEHOLDER_VALUES)
                # resolving into a concrete classification, discoverable the
                # same way placeholder_resolved discovers a retrieval-hint
                # placeholder, combined with the permitted source_fields
                # template pruning that same governed re-admission produces
                # (see _semantic_projection_policy_evolution). rag_filter and
                # chunk_fields must still be untouched.
                semantic_projection_policy_evolution = False
                if not chunk_changed and not redaction_only and not additive_growth and not placeholder_resolved:
                    role_metadata_pair = _extract_placeholder_pair_from_dict(
                        previous.get("metadata_raw"), current.get("metadata_raw"), _ROLE_PRIMARY_PLACEHOLDER_VALUES
                    )
                    role_retrieval_pair = _extract_placeholder_pair_from_list(
                        previous.get("retrieval_hints_raw"), current.get("retrieval_hints_raw"), _ROLE_PRIMARY_PLACEHOLDER_VALUES
                    )
                    role_metadata_ok = previous.get("metadata_hash") == current.get("metadata_hash") or role_metadata_pair is not None
                    role_retrieval_ok = (
                        previous.get("retrieval_hints_hash") == current.get("retrieval_hints_hash") or role_retrieval_pair is not None
                    )
                    role_candidate_pairs = {pair for pair in (role_metadata_pair, role_retrieval_pair) if pair is not None}
                    if (
                        role_metadata_ok
                        and role_retrieval_ok
                        and len(role_candidate_pairs) <= 1
                        and previous.get("rag_filter_hash") == current.get("rag_filter_hash")
                        and previous.get("chunk_fields_hash") == current.get("chunk_fields_hash")
                    ):
                        semantic_projection_policy_evolution = _semantic_projection_policy_evolution(
                            previous.get("semantic_text_raw"), current.get("semantic_text_raw")
                        )
                # A fifth, still fail-closed evolution: a Lane B governed
                # historical-review reclassification (repo-metadata
                # admission) changes only non-versioned canon lifecycle
                # fields -- never text/version_id -- but those fields are
                # rendered in semantic_text's source_fields section. Every
                # other hashed component must be byte-identical.
                non_versioned_canon_projection_evolution = False
                if (
                    not chunk_changed
                    and not redaction_only
                    and not additive_growth
                    and not placeholder_resolved
                    and not semantic_projection_policy_evolution
                    and previous.get("metadata_hash") == current.get("metadata_hash")
                    and previous.get("retrieval_hints_hash") == current.get("retrieval_hints_hash")
                    and previous.get("rag_filter_hash") == current.get("rag_filter_hash")
                    and previous.get("chunk_fields_hash") == current.get("chunk_fields_hash")
                ):
                    non_versioned_canon_projection_evolution = _non_versioned_canon_projection_evolution(
                        previous.get("semantic_text_raw"), current.get("semantic_text_raw")
                    )
                if redaction_only:
                    report["redaction_vocabulary_evolution"] += 1
                    evidence["redaction_vocabulary_evolution"].append(current_id)
                elif additive_growth:
                    report["additive_derivative_evolution"] += 1
                    evidence["additive_derivative_evolution"].append(current_id)
                elif placeholder_resolved:
                    report["placeholder_resolved"] += 1
                    evidence["placeholder_resolved"].append(current_id)
                elif semantic_projection_policy_evolution:
                    report["semantic_projection_policy_evolution"] += 1
                    evidence["semantic_projection_policy_evolution"].append(current_id)
                elif non_versioned_canon_projection_evolution:
                    report["non_versioned_canon_projection_evolution"] += 1
                    evidence["non_versioned_canon_projection_evolution"].append(current_id)
                else:
                    report["unexpected_semantic_regressions"] += 1
                    evidence["unexpected_semantic_regressions"].append(current_id)
            else:
                report["unchanged_shared_records"] += 1
                evidence["unchanged_shared_records"].append(current_id)
            continue

        # The historical baseline differs, but the staging revision is exactly
        # the current canonical revision.  Structural violations were checked
        # above, so the permitted content projection matrix applies.
        report["canonical_updates"] += 1
        evidence["canonical_updates"].append(current_id)

    blocking_fields = (
        "removed_historical_records", "unexpected_semantic_regressions", "invalid_version_transitions",
        "invalid_canonical_membership", "identity_mismatches", "schema_mismatches", "family_mismatches",
        "duplicate_records", "chunk_mismatches", "chunks_above_hard_max",
    )
    report["blocking"] = any(report[field] for field in blocking_fields)
    report["equivalence_status"] = "not_equivalent" if report["blocking"] else "equivalent"
    for values in evidence.values():
        values.sort()
    return report, evidence


def _record_counts(surfaces: dict[str, dict[str, dict[str, Any]]]) -> dict[str, int]:
    return {family: len(records) for family, records in surfaces.items()}


def _union_evolution_ids(evidence: dict[str, dict[str, list[str]]]) -> dict[str, list[str]]:
    result: dict[str, set[str]] = {}
    for family_values in evidence.values():
        for classification, values in family_values.items():
            result.setdefault(classification, set()).update(values)
    return {classification: sorted(values) for classification, values in result.items()}


def build_equivalence_report(
    baseline_root: Path | str,
    staging_root: Path | str,
    *,
    canon_dir: Path | str | None = None,
    staging_manifest_path: Path | str | None = None,
    baseline_manifest_path: Path | str | None = None,
    baseline_source_type: str | None = None,
    families: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    baseline = Path(baseline_root).resolve()
    staging = Path(staging_root).resolve()
    canon_root = Path(canon_dir).resolve() if canon_dir else (Path(__file__).resolve().parents[2] / "data" / "out" / "local")
    compared_families = tuple(families or DEFAULT_FAMILIES)
    unknown = sorted(set(compared_families) - set(FAMILY_PATTERNS) - {"microsoft_copilot"})
    if unknown:
        raise ValueError(f"unknown equivalence families: {', '.join(unknown)}")
    canon_index, canon_summary = build_canonical_index(canon_root)
    baseline_surfaces, baseline_issues = _logical_records(baseline, families=compared_families)
    staging_surfaces, staging_issues = _logical_records(staging, families=compared_families)
    # Computed once from whichever family carries semantic_text (identity is
    # a property of the underlying canon document, not of any one derived
    # family) and then applied uniformly: the same removed id is either a
    # governed rename everywhere or a real removal everywhere.
    migration_map = _build_identity_migration_map(baseline_surfaces, staging_surfaces, compared_families)
    family_reports: dict[str, dict[str, Any]] = {}
    family_evidence: dict[str, dict[str, list[str]]] = {}
    for family in compared_families:
        report, evidence = _family_report(
            family,
            baseline_surfaces.get(family, {}),
            staging_surfaces.get(family, {}),
            baseline_issues.get(family, {}),
            staging_issues.get(family, {}),
            canon_index,
            migration_map,
        )
        family_reports[family] = report
        family_evidence[family] = evidence
    evolution_ids = _union_evolution_ids(family_evidence)
    evolution = {
        "additions": len(evolution_ids.get("added_from_current_canon", [])),
        "updates": len(evolution_ids.get("canonical_updates", [])),
        "removals": len(evolution_ids.get("removed_historical_records", [])),
        "identity_migrated": len(evolution_ids.get("identity_migrated_records", [])),
        "regressions": len(evolution_ids.get("unexpected_semantic_regressions", [])),
        "redaction_vocabulary_evolution": len(evolution_ids.get("redaction_vocabulary_evolution", [])),
        "additive_derivative_evolution": len(evolution_ids.get("additive_derivative_evolution", [])),
        "placeholder_resolved": len(evolution_ids.get("placeholder_resolved", [])),
        "semantic_projection_policy_evolution": len(evolution_ids.get("semantic_projection_policy_evolution", [])),
        "non_versioned_canon_projection_evolution": len(evolution_ids.get("non_versioned_canon_projection_evolution", [])),
    }
    failed = [family for family, result in family_reports.items() if result["blocking"]]
    canonical_invalid = canon_summary["valid"] is not True
    blocking = bool(failed or canonical_invalid)
    if blocking:
        status = "not_equivalent"
    elif (
        evolution["additions"]
        or evolution["updates"]
        or evolution["redaction_vocabulary_evolution"]
        or evolution["additive_derivative_evolution"]
        or evolution["placeholder_resolved"]
        or evolution["semantic_projection_policy_evolution"]
        or evolution["non_versioned_canon_projection_evolution"]
        or evolution["identity_migrated"]
    ):
        status = "equivalent_with_expected_canonical_evolution"
    else:
        status = "equivalent"
    baseline_manifest = Path(baseline_manifest_path).resolve() if baseline_manifest_path else None
    staging_manifest = Path(staging_manifest_path).resolve() if staging_manifest_path else None
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "contract_schema_version": CONTRACT_SCHEMA_VERSION,
        "baseline": {
            "source_type": baseline_source_type or "historical_derivative_staging",
            "staging_root": str(baseline),
            "manifest_hash": _hash_file(baseline_manifest),
            "record_counts": _record_counts(baseline_surfaces),
        },
        "current": {
            "staging_root": str(staging),
            "canon_dir": str(canon_root),
            "canon_hash": canon_summary["canon_hash"],
            "staging_manifest_hash": _hash_file(staging_manifest),
            "record_counts": _record_counts(staging_surfaces),
        },
        "canonical_index": canon_summary,
        "normalization": {
            "operational_fields_ignored": sorted(OPERATIONAL_KEYS),
            "path_roots_normalized": True,
            "chunk_source_anchor": "canon_id_only",
            "version_resolution": {
                "current": ["version_id", "source_version_id", "content_hash"],
                "historical_compatibility": "semantic_text version_id only when no explicit field exists",
            },
        },
        "families": family_reports,
        "compared_families": list(compared_families),
        "evolution": evolution,
        "equivalence_status": status,
        "blocking": blocking,
        "failed_families": failed + (["canonical_index"] if canonical_invalid else []),
        "_evolution_ids": {"families": family_evidence, "global": evolution_ids},
    }
    return report


def _public_report(report: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in report.items() if not key.startswith("_")}


def write_report(path: Path | str, report: dict[str, Any]) -> Path:
    target = require_nonproductive_evidence_target(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(stable_json(_public_report(report), indent=2) + "\n", encoding="utf-8")
    return target


def write_evolution_evidence(summary_path: Path | str, ids_path: Path | str, report: dict[str, Any]) -> tuple[Path, Path]:
    summary_target = require_nonproductive_evidence_target(summary_path)
    ids_target = require_nonproductive_evidence_target(ids_path)
    summary_target.parent.mkdir(parents=True, exist_ok=True)
    ids_target.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "schema_version": "canonical-evolution-summary/v1",
        "contract_schema_version": report["contract_schema_version"],
        "report_schema_version": report["schema_version"],
        "current": report["current"],
        "canonical_index": report["canonical_index"],
        "evolution": report["evolution"],
        "equivalence_status": report["equivalence_status"],
        "blocking": report["blocking"],
        "families": {
            family: {
                key: value
                for key, value in result.items()
                if key not in {"family", "equivalence_status", "blocking"}
            }
            for family, result in report["families"].items()
        },
    }
    identifiers = {
        "schema_version": "canonical-evolution-identifiers/v1",
        "contract_schema_version": report["contract_schema_version"],
        "report_schema_version": report["schema_version"],
        "global": report["_evolution_ids"]["global"],
        "families": report["_evolution_ids"]["families"],
    }
    summary_target.write_text(stable_json(summary, indent=2) + "\n", encoding="utf-8")
    ids_target.write_text(stable_json(identifiers, indent=2) + "\n", encoding="utf-8")
    return summary_target, ids_target


def report_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Equivalencia productiva gobernada",
        "",
        f"- Contrato: `{report['contract_schema_version']}`",
        f"- Estado: `{report['equivalence_status']}`",
        f"- Bloqueante: `{str(report['blocking']).lower()}`",
        f"- Altas canónicas válidas: `{report['evolution']['additions']}`",
        f"- Actualizaciones canónicas válidas: `{report['evolution']['updates']}`",
        f"- Pérdidas históricas: `{report['evolution']['removals']}`",
        f"- Regresiones inesperadas: `{report['evolution']['regressions']}`",
        f"- Evolución de vocabulario de redacción (no bloqueante): `{report['evolution']['redaction_vocabulary_evolution']}`",
        f"- Evolución aditiva de derivados (no bloqueante): `{report['evolution']['additive_derivative_evolution']}`",
        f"- Placeholders resueltos (no bloqueante): `{report['evolution']['placeholder_resolved']}`",
        f"- Evolución de política de proyección semántica (no bloqueante): `{report['evolution']['semantic_projection_policy_evolution']}`",
        f"- Evolución de proyección canónica no versionada (no bloqueante): `{report['evolution']['non_versioned_canon_projection_evolution']}`",
        f"- Migraciones de identidad (no bloqueante): `{report['evolution']['identity_migrated']}`",
        "",
        "| Familia | Base | Actual | Sin cambio | Altas | Actualizaciones | Pérdidas | Regresiones | Estado |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for result in report["families"].values():
        lines.append(
            f"| {result['family']} | {result['baseline_records']} | {result['current_records']} | "
            f"{result['unchanged_shared_records']} | {result['added_from_current_canon']} | "
            f"{result['canonical_updates']} | {result['removed_historical_records']} | "
            f"{result['unexpected_semantic_regressions']} | {result['equivalence_status']} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate derivative equivalence against a historical baseline and current canon.")
    parser.add_argument("--preview-root", "--baseline-root", dest="baseline_root", required=True)
    parser.add_argument("--staging-root", required=True)
    parser.add_argument("--canon-dir", default="data/out/local")
    parser.add_argument("--staging-manifest")
    parser.add_argument("--baseline-manifest")
    parser.add_argument("--baseline-source-type")
    parser.add_argument("--report", required=True)
    parser.add_argument("--report-md")
    parser.add_argument("--evolution-summary")
    parser.add_argument("--evolution-ids")
    parser.add_argument("--family", action="append", dest="families", help="Limit comparison to one logical family; repeatable")
    args = parser.parse_args()
    report = build_equivalence_report(
        args.baseline_root,
        args.staging_root,
        canon_dir=args.canon_dir,
        staging_manifest_path=args.staging_manifest,
        baseline_manifest_path=args.baseline_manifest,
        baseline_source_type=args.baseline_source_type,
        families=args.families,
    )
    report_path = write_report(args.report, report)
    summary_path = args.evolution_summary or str(report_path.with_name("canonical_evolution_summary.json"))
    ids_path = args.evolution_ids or str(report_path.with_name("canonical_evolution_ids.json"))
    write_evolution_evidence(summary_path, ids_path, report)
    if args.report_md:
        target = require_nonproductive_evidence_target(args.report_md)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(report_markdown(report), encoding="utf-8")
    print(stable_json(_public_report(report), indent=2))
    return 0 if not report["blocking"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
