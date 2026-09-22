#!/usr/bin/env python3
"""S0186 Unit D — quiescence and TMP lifecycle, read-only.

H-Q-01 (``data/out/local/sessions/03_hipotesis/...``) requires that
``TDC_QUIESCENT`` only be asserted when eight terms are reconstructible by
owner from disk: Canon, relaciones, apply pendiente, autorizaciones,
receipts/rollback, auditoría, estado persistente and TMP.  Each term is
classified ``CURRENTLY_PROVABLE``, ``PARTIALLY_PROVABLE``, ``NOT_PROVABLE`` or
``NOT_APPLICABLE``.  A clean ``git status`` is explicitly insufficient
evidence on its own.

This module owns none of the seven relational/admission terms.  It reads the
outputs of the modules that already own them:

- Canon              -> relation_admission_gate (aggregate_canon_hash, count_canon_records)
- relaciones         -> relation_admission_state.build_state()['reconciliation']
- apply pendiente    -> relation_admission_state.relational_apply_precondition() + build_state()['verdict']
- autorizaciones     -> relation_admission_state.build_state()['apply'] / ['current_authority']
- receipts/rollback  -> relation_admission_state.build_state()['rollback'] + current_relational_authority.resolve_current_relational_authority
- auditoría          -> relation_admission_state.build_audit_index + audit_relation_inventory.audit_canon
- estado persistente -> two immediate build_state() replays with a pinned ``checked_at``, compared byte-for-byte

No production write path of any owner module (``authorize``, ``apply``,
rollback/reverse) is invoked anywhere in this file.

TMP is the one term with no existing owner: no module in this repository
classifies ``data/tmp/`` entries by lifecycle stage.  ``classify_tmp_lifecycle``
below is new for Unit D.  It reads ``data/tmp/`` and cross-references literal
default-path constants already declared by currently-referenced production
scripts (reconstructed by source inspection, not guessed); it never creates,
deletes, moves or truncates a path.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

# S0187 D20: TMP_ROOT is the CURRENT/ACTIVE tmp authority -- previously a
# hardcoded REPO_ROOT-relative literal, independent of path_governance, so
# this module's own CURRENT quiescence classification was silently observing
# the pre-binding root rather than the workspace-active one. HISTORICAL_TMP_ROOT
# is kept as an explicitly separate, differently-named constant for deliberate
# inspection of pre-binding material -- it is NEVER a fallback for TMP_ROOT.
#
# S0187 D22: LOCAL_ROOT had the exact same defect -- REPO_ROOT-relative,
# never migrated -- surfaced only when repo/data/out was decommissioned this
# tranche and this module's own Canon-evidence reader broke immediately.
from path_governance import (  # noqa: E402
    DEFAULT_LOCAL_OUT_DIR as LOCAL_ROOT,
    DEFAULT_TMP_DIR as TMP_ROOT,
    HISTORICAL_TMP_ROOT,
)
# s0186-impact is historical-only material -- it was never migrated with the
# D-H4 cutover (D9 explicitly excluded tmp/ from the D11 copy) and only ever
# existed under the pre-binding root, so this checkpoint reference correctly
# stays pinned to HISTORICAL_TMP_ROOT rather than following TMP_ROOT.
DEFAULT_CHECKPOINT = HISTORICAL_TMP_ROOT / "s0186-impact" / "checkpoint.json"

import relation_admission_gate as admission_gate  # noqa: E402
import relation_admission_state as admission_state  # noqa: E402
import current_relational_authority as current_authority  # noqa: E402
import audit_relation_inventory as inventory_audit  # noqa: E402

TERM_STATUS_VOCABULARY = frozenset({
    "CURRENTLY_PROVABLE",
    "PARTIALLY_PROVABLE",
    "NOT_PROVABLE",
    "NOT_APPLICABLE",
})

QUIESCENCE_TERMS = (
    "canon",
    "relaciones",
    "apply_pendiente",
    "autorizaciones",
    "receipts_rollback",
    "auditoria",
    "estado_persistente",
    "tmp",
)

_SESSION_DIR_RE = re.compile(r"^s(\d{4})[-_]")

# STAGING owners: literal default-path constants declared by currently
# referenced production scripts (grep-verified against
# src/python_scripts/*.py during Unit D investigation).
_STAGING_OWNERS: dict[str, str] = {
    "html_export": "operator_menu.py:HTML_EXPORT_DIR",
    "reconstruction": "operator_menu.py:RECONSTRUCTION_DIR",
    "sanitation": "canon_sanitation.py:DEFAULT_SANITATION_DIR",
    "session_admission": "admit_session_candidates.py:DEFAULT_TMP_DIR",
    "session_sync": "session_sync.py:DEFAULT_SESSION_SYNC_DIR",
    # Found during S0186 Unit J.2's final TMP reconciliation: this one has
    # a real named default-path constant too, just not yet grep-verified
    # when the dict above was first built.
    "canonical_quality": "operator_menu.py:QUALITY_REPORT_DIR (option_canon_quality; src/rust/doctor canonical-line-gate + deep-node-inspect)",
    # S0187 D20-R: this entry did not exist because material_inventory.py's
    # own TMP_ROOT constant did not exist yet when _STAGING_OWNERS was first
    # built (S0186) -- an obsolete historical gap, not an intentional
    # exclusion. Confirmed unambiguous: material_inventory.py:TMP_ROOT
    # (= DEFAULT_TMP_DIR / "material_inventory") is update_inventory()'s own
    # default `tmp_root` parameter (its work_dir = tmp_root / run_id), the
    # single top-level, menu-invoked producer of this directory -- same
    # evidentiary shape as every other entry in this dict.
    "material_inventory": "material_inventory.py:TMP_ROOT",
}

# Entries with no hardcoded default-path constant in current source, but
# whose filename convention is attributable to a specific script's known
# output shape (Unit D evidence: filename pattern inspection).
_CONTENT_ATTRIBUTABLE_OWNERS: dict[str, str] = {
    "admissions": (
        "admit_session_candidates.py (admit-*/rollback-* filename convention "
        "under a s69_unittest subdirectory; no hardcoded default path). "
        "S0186 Unit J.1 fixed the test-fixture leak that populated "
        "this path -- should no longer recur, but the path shape is "
        "documented here in case it does from a different call site."
    ),
    "session_admission_s69_unittest": (
        "admit_session_candidates.py (admit-*/rollback-* filename convention; "
        "no hardcoded default path). Same J.1 fix as 'admissions' above."
    ),
    "diagnostic_inventory": (
        "DT087 diagnostic-governance content (dt087-*-coverage-* filename "
        "convention; no hardcoded default path)"
    ),
    # Found during S0186 Unit J.2's final TMP reconciliation: a one-off
    # manual invocation of src/go/bridge/cmd/reverse_tiddlers with custom
    # output paths (not the tool's own default convention). Attributed by
    # tmp_lifecycle_governance.find_reverse_verification_bundles(), which
    # detects this class of artifact generically by report SCHEMA (mode +
    # store_policy + html_input_path + canon_input_path + output_html_path
    # fields), not by these specific hardcoded names -- these three literal
    # entries exist only because these particular files were never renamed
    # after that one investigation, not because the detection itself is
    # name-based.
    "verify-reverse-128": (
        "src/go/bridge/cmd/reverse_tiddlers (manual invocation, custom output path; "
        "see tmp_lifecycle_governance.find_reverse_verification_bundles for the "
        "general, schema-based detection of this artifact class)"
    ),
    "tiddly-with-128-relations.html": (
        "src/go/bridge/cmd/reverse_tiddlers output_html_path (manual invocation, "
        "custom output path; see tmp_lifecycle_governance.find_reverse_verification_bundles)"
    ),
    "reverse-128-relations-report.json": (
        "src/go/bridge/cmd/reverse_tiddlers report (manual invocation, custom output path; "
        "see tmp_lifecycle_governance.find_reverse_verification_bundles)"
    ),
}


def _session_label(name: str) -> str | None:
    match = _SESSION_DIR_RE.match(name)
    return f"S{match.group(1)}" if match else None


def classify_tmp_entry(name: str, active_session_id: str) -> dict[str, Any]:
    """Classify one top-level ``data/tmp/`` entry name by lifecycle stage.

    Pure function of the name; performs no filesystem access itself.
    """
    session = _session_label(name)
    if session is not None:
        lifecycle = "ACTIVE_SESSION_TMP" if session == active_session_id else "CLOSED_SESSION_TMP"
        return {
            "lifecycle": lifecycle,
            "owner": f"session {session} (its own IMPACT working area)",
        }
    if name in _STAGING_OWNERS:
        return {"lifecycle": "STAGING", "owner": _STAGING_OWNERS[name]}
    if name in _CONTENT_ATTRIBUTABLE_OWNERS:
        return {
            "lifecycle": "STAGING_CONTENT_ATTRIBUTABLE_NO_DEFAULT_CONSTANT",
            "owner": _CONTENT_ATTRIBUTABLE_OWNERS[name],
        }
    return {
        "lifecycle": "NO_PERSISTENT_OWNER_FOUND_IN_CURRENT_SOURCE",
        "owner": None,
    }


def classify_tmp_lifecycle(
    tmp_root: Path = TMP_ROOT,
    *,
    active_session_id: str = "S0186",
) -> dict[str, Any]:
    """Read-only lifecycle classification of top-level ``data/tmp/`` entries.

    Never creates, deletes, moves or truncates a path -- it only lists
    ``tmp_root`` and classifies names already there.  No entry currently
    under ``data/tmp/`` matches an INBOX (unconsumed-intake) pattern, so that
    bucket is reported with ``observed_count = 0`` rather than fabricated.
    """
    if not tmp_root.is_dir():
        return {
            "schema_version": "quiescence-tmp-lifecycle/v1",
            "error": "tmp_root_missing",
            "entries": [],
            "counts_by_lifecycle": {},
        }
    try:
        tmp_root_display = str(tmp_root.relative_to(REPO_ROOT))
    except ValueError:
        tmp_root_display = str(tmp_root)
    entries: list[dict[str, Any]] = []
    for child in sorted(tmp_root.iterdir(), key=lambda p: p.name):
        info = classify_tmp_entry(child.name, active_session_id)
        entries.append({
            # S0187 D20: was a hardcoded "data/tmp/{name}" literal, misleading
            # once tmp_root moved off REPO_ROOT (it would still claim
            # "data/tmp/..." while actually describing Toshiba content).
            "path": f"{tmp_root_display}/{child.name}",
            "is_dir": child.is_dir(),
            **info,
        })
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry["lifecycle"]] = counts.get(entry["lifecycle"], 0) + 1
    counts.setdefault("INBOX", 0)
    return {
        "schema_version": "quiescence-tmp-lifecycle/v1",
        "tmp_root": tmp_root_display,
        "entry_count": len(entries),
        "entries": entries,
        "counts_by_lifecycle": counts,
        "paths_created": 0,
        "paths_deleted": 0,
    }


def _canon_glob(local_root: Path) -> str:
    return str(local_root / "tiddlers_*.jsonl")


def evaluate_quiescence(
    local_root: Path = LOCAL_ROOT,
    *,
    tmp_root: Path = TMP_ROOT,
    active_session_id: str = "S0186",
    checked_at: str | None = None,
) -> dict[str, Any]:
    """Assemble the H-Q-01 quiescence report for the eight required terms.

    Reads only.  Calls into the modules that already own relational
    generation, reconciliation, admission, apply, authorization, receipts and
    rollback; adds no parallel logic for any of them.  ``checked_at`` should
    be pinned by the caller when the goal is to prove ``estado_persistente``
    stability across repeated calls (unpinned, ``build_state`` stamps its own
    wall-clock time on every call, which is expected volatility, not
    instability of the underlying state).
    """
    terms: dict[str, dict[str, Any]] = {}
    # A replay proves persistence only when both reconstructions receive the
    # same observational timestamp.  Otherwise ``build_state`` correctly
    # emits different ``checked_at`` values and creates a false instability.
    replay_checked_at = checked_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    canon_glob = _canon_glob(local_root)
    try:
        canon_hash = admission_gate.aggregate_canon_hash(canon_glob)
        canon_count = admission_gate.count_canon_records(canon_glob)
        shard_count = len(list(local_root.glob("tiddlers_*.jsonl")))
        terms["canon"] = {
            "status": "CURRENTLY_PROVABLE" if shard_count > 0 else "NOT_PROVABLE",
            "owner": "relation_admission_gate.aggregate_canon_hash / count_canon_records",
            "evidence": {"hash": canon_hash, "records": canon_count, "shards": shard_count},
        }
    except Exception as exc:  # pragma: no cover - defensive; canon glob is always resolvable here
        terms["canon"] = {
            "status": "NOT_PROVABLE",
            "owner": "relation_admission_gate",
            "evidence": {"error": repr(exc)},
        }

    try:
        state = admission_state.build_state(local_root, checked_at=replay_checked_at)
        precondition = admission_state.relational_apply_precondition(state)
        reconciliation = state.get("reconciliation") or {}
        apply_block = state.get("apply") or {}
        rollback = state.get("rollback") or {}
        current_authority_block = state.get("current_authority") or {}
        expected_staleness = state.get("expected_postapply_staleness") or {}

        terms["relaciones"] = {
            "status": (
                "CURRENTLY_PROVABLE"
                if reconciliation.get("manifest_path") and not reconciliation.get("stale_reasons")
                else "PARTIALLY_PROVABLE"
            ),
            "owner": "relation_admission_state.build_state()['reconciliation']",
            "evidence": {
                "verdict": state.get("verdict"),
                "ready_for_review": reconciliation.get("ready_for_review"),
                "dispositions": reconciliation.get("dispositions"),
            },
        }

        apply_reconciled = state.get("verdict") == "RELATIONAL_PRODUCTIVE_APPLY_RECONCILED"
        terms["apply_pendiente"] = {
            "status": "CURRENTLY_PROVABLE",
            "owner": "relation_admission_state.relational_apply_precondition() + build_state()['verdict']",
            "evidence": {
                "verdict": state.get("verdict"),
                "next_action": state.get("next_action"),
                "apply_already_executed": apply_block.get("executed"),
                "apply_reconciled_no_pending_apply": apply_reconciled,
                "precondition_allowed": precondition.get("allowed"),
                "precondition_reasons": precondition.get("reasons"),
            },
        }

        terms["autorizaciones"] = {
            "status": "CURRENTLY_PROVABLE",
            "owner": "relation_admission_state.build_state()['apply'] / ['current_authority']",
            "evidence": {
                "authorization_consumed": apply_block.get("authorization_consumed"),
                "authorization_current": apply_block.get("authorization_current"),
                "current_authority_valid": current_authority_block.get("valid"),
                "current_authority_stale_reasons": current_authority_block.get("stale_reasons"),
                "expected_postapply_staleness_recognized": expected_staleness.get("recognized"),
            },
        }

        try:
            authority = current_authority.resolve_current_relational_authority(local_root)
            authority_terminal: str | None = authority.get("terminal_state")
            authority_error: str | None = None
        except current_authority.CurrentRelationalAuthorityError as exc:
            authority_terminal = None
            authority_error = str(exc)

        terms["receipts_rollback"] = {
            "status": (
                "CURRENTLY_PROVABLE"
                if rollback.get("available") and not rollback.get("stale_reasons")
                else "PARTIALLY_PROVABLE"
            ),
            "owner": (
                "relation_admission_state.build_state()['rollback'] + "
                "current_relational_authority.resolve_current_relational_authority"
            ),
            "evidence": {
                "rollback_available": rollback.get("available"),
                "rollback_current": rollback.get("current"),
                "rollback_ready": rollback.get("ready"),
                "receipt_bound": rollback.get("receipt_bound"),
                "receipt_hash": apply_block.get("receipt_hash"),
                "immutable_bundle_terminal_state": authority_terminal,
                "immutable_bundle_resolver_error": authority_error,
            },
        }

        audit_index = admission_state.build_audit_index(local_root, checked_at=replay_checked_at)
        canon_inventory_audit = inventory_audit.audit_canon(local_root)
        terms["auditoria"] = {
            "status": "CURRENTLY_PROVABLE",
            "owner": "relation_admission_state.build_audit_index + audit_relation_inventory.audit_canon",
            "evidence": {
                "audit_index_artifact_count": len(audit_index.get("artifacts") or []),
                "audit_index_history_path": audit_index.get("history_path"),
                "canon_relation_inventory_total_tiddlers": canon_inventory_audit.get("total_tiddlers"),
                "state_warnings": state.get("warnings"),
            },
        }

        state_replay = admission_state.build_state(local_root, checked_at=replay_checked_at)
        stable = json.dumps(state, sort_keys=True) == json.dumps(state_replay, sort_keys=True)
        terms["estado_persistente"] = {
            "status": "CURRENTLY_PROVABLE" if stable else "PARTIALLY_PROVABLE",
            "owner": "relation_admission_state.build_state (reads exclusively from disk on every call)",
            "evidence": {
                "stable_on_immediate_replay": stable,
                "checked_at_pinned": True,
                "caller_checked_at_pinned": checked_at is not None,
                "replay_checked_at": replay_checked_at,
            },
        }
    except Exception as exc:
        for key in (
            "relaciones",
            "apply_pendiente",
            "autorizaciones",
            "receipts_rollback",
            "auditoria",
            "estado_persistente",
        ):
            terms[key] = {
                "status": "NOT_PROVABLE",
                "owner": "relation_admission_state.build_state",
                "evidence": {"error": repr(exc)},
            }

    tmp_report = classify_tmp_lifecycle(tmp_root, active_session_id=active_session_id)
    terms["tmp"] = {
        "status": "CURRENTLY_PROVABLE" if "error" not in tmp_report else "NOT_PROVABLE",
        "owner": (
            "quiescence_state.classify_tmp_lifecycle (new in Unit D; no prior "
            "module classified TMP/STAGING/INBOX lifecycle) + "
            "relation_admission_state warning 'data_tmp_is_not_an_operational_dependency'"
        ),
        "evidence": tmp_report,
    }

    unresolved = {term: value for term, value in terms.items() if term not in QUIESCENCE_TERMS}
    assert not unresolved, f"unexpected term keys: {sorted(unresolved)}"
    missing = set(QUIESCENCE_TERMS) - set(terms)
    assert not missing, f"missing term keys: {sorted(missing)}"

    blocking = sorted(
        term for term, value in terms.items()
        if value["status"] not in ("CURRENTLY_PROVABLE", "NOT_APPLICABLE")
    )

    return {
        "schema_version": "quiescence-state/v1",
        "hypothesis": "H-Q-01",
        "checked_at": replay_checked_at,
        "term_status_vocabulary": sorted(TERM_STATUS_VOCABULARY),
        "terms": terms,
        "tdc_quiescent": not blocking,
        "blocking_terms": blocking,
    }
