#!/usr/bin/env python3
"""governed_relation_admission_policy.py — S0186 Unit H8

Governed relational admission policy: HUMAN GOVERNS THE RULE, MACHINE PROVES
EACH MATCH, MACHINE DERIVES THE CONSEQUENCE, HUMAN REVIEWS ONLY WHAT THE RULE
CANNOT PROVE.

This module never writes canon and never runs admission/Apply. Most of it
is evaluation-only: it reads the live CURRENT technical-relation-candidates
bundle and partitions its pending (undecided) candidates into disjoint,
deterministic, versioned, hashed policy classes plus a residual
human-exception set. Two functions do write, each to exactly one thing and
nothing else: ``write_policy_authorization`` (a human authorization record)
and ``materialize_authorized_policy`` (policy_derived rows appended to
human_review_decisions.jsonl, via current_relation_human_review's existing
atomic-write primitives -- never a second, competing decisions authority).
Both are phrase-confirmed or re-verified fail-closed immediately before
writing.

Relationship to existing contracts (do not duplicate, do not contradict):

  relation_admission_policy.py (S0131) governs the OLDER
  ``relations-candidate/v1`` narrative-relation population, where
  ``evidence.kind`` may be ``ai_inference``/``title_mention``/
  ``structural_tag`` -- genuinely weak, inferential evidence. Its
  ``EVIDENCE_POLICY[...]["always_human_review"]`` flags for
  depende_de/valida/produce_artefacto are correct FOR THAT POPULATION and are
  left untouched. That evaluator (``evaluate_admissibility``) is not wired
  into the live CURRENT technical pipeline (verified: only
  ``EVIDENCE_POLICY``/``GLOBAL_MIN_CONFIDENCE`` are imported by
  relation_admission_gate.py, for a confidence-floor lookup only -- the
  ``always_human_review`` state machine itself is dead code on this path).

  This module instead governs the ``technical-relation-candidates/v1``
  population produced by generate_technical_relation_candidates.py, where a
  ``technical_evidence_kind`` of ``python_ast_import`` means the relation was
  mechanically proven by parsing Python's own ``ast`` module -- a
  categorically different evidence class that S0131 predates and does not
  contemplate. No existing contract is overridden; this is an additive,
  narrower contract for evidence S0131's model has no vocabulary for.

  current_relation_human_review.py's S0181 ``decision_mode="batch"`` already
  lets a human confirm one homogeneous *group* in one gesture, keyed by
  ``review_policy_id`` (an ad hoc classification tag, e.g.
  ``S0181_DIRECT_AST_IMPORT_V1``). That still requires a fresh human
  confirmation every time the batch's specific candidate_ids change (a new
  generation, a grown repo). ``governed_relation_policy/v1`` is the missing
  layer above it: a policy is defined and versioned independently of any
  specific candidate_id set, a human authorizes it ONCE per CURRENT batch
  scope (bound by hash, invalidated by any material drift), and only then
  does the machine derive per-candidate decisions -- each one tagged
  ``decision_mode="policy_derived"``, never silently relabeled as an
  individual or batch human review that did not happen.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

import current_relation_human_review as human_review  # noqa: E402

DEFAULT_LOCAL_ROOT = REPO_ROOT / "data" / "out" / "local"
DEFAULT_CURRENT_DIR = DEFAULT_LOCAL_ROOT / "pipeline" / "relation_candidates" / "current"

SCHEMA_GOVERNED_POLICY = "governed-relation-admission-policy/v1"
SCHEMA_POLICY_PREVIEW = "governed-relation-admission-policy-preview/v1"
SCHEMA_AUTHORIZATION_SCOPE = "governed-relation-admission-authorization-scope/v1"

AUTHORIZATION_SCOPE_CURRENT_BATCH = "CURRENT_BATCH"

# review_reason values that must never be auto-derived by any policy,
# regardless of technical_relation_kind or evidence strength.
NEVER_AUTO_REVIEW_REASONS = frozenset({"reconciliation_ambiguous", "rebaseline_uncovered"})


def _json_canonical(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash(payload: Any) -> str:
    return hashlib.sha256(_json_canonical(payload)).hexdigest()


def _basename(repo_path: str) -> str:
    return repo_path.rsplit("/", 1)[-1]


@dataclass(frozen=True)
class RelationPolicy:
    """A deterministic, versioned, machine-evaluable admission rule.

    ``evaluate`` receives one candidate dict (technical-relation-candidates/v1
    shape) and must return (eligible, exception_reason_code_or_None). It must
    be a pure function of the candidate -- no I/O, no randomness, no
    dependence on anything outside the candidate object itself, so the same
    CURRENT input always yields the same result.
    """

    policy_id: str
    policy_version: str
    technical_relation_kind: str
    allowed_predicate: str
    rationale: str
    evidence_requirements: dict[str, Any]
    resolution_requirements: dict[str, Any]
    currentness_requirements: dict[str, Any]
    exclusion_conditions: tuple[str, ...]
    decision_effect: str
    decision_reason_code: str | None
    authorization_requirements: dict[str, Any]
    evaluate: Callable[[dict[str, Any]], tuple[bool, str | None]] = field(repr=False, compare=False)

    @property
    def structural_definition(self) -> dict[str, Any]:
        """Everything that participates in the policy hash -- not ``rationale``.

        ``rationale`` is prose for humans; changing its wording must not
        change the policy's identity or invalidate a live authorization.
        """
        return {
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "technical_relation_kind": self.technical_relation_kind,
            "allowed_predicate": self.allowed_predicate,
            "evidence_requirements": self.evidence_requirements,
            "resolution_requirements": self.resolution_requirements,
            "currentness_requirements": self.currentness_requirements,
            "exclusion_conditions": sorted(self.exclusion_conditions),
            "decision_effect": self.decision_effect,
            "decision_reason_code": self.decision_reason_code,
            "authorization_requirements": self.authorization_requirements,
        }

    @property
    def policy_hash(self) -> str:
        return _hash(self.structural_definition)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_GOVERNED_POLICY,
            **self.structural_definition,
            "policy_hash": self.policy_hash,
            "rationale": self.rationale,
        }


def _base_resolution_requirements() -> dict[str, Any]:
    return {
        "source_resolved_uniquely": True,
        "target_resolved_uniquely": True,
        "source_canonical_id_present": True,
        "target_canonical_id_present": True,
        "source_ne_target": True,
    }


def _base_currentness_requirements() -> dict[str, Any]:
    return {
        "candidate_reconciliation_class_in": ["new", "modified"],
        "review_reason_not_in": sorted(NEVER_AUTO_REVIEW_REASONS),
    }


def _endpoints_resolved_and_distinct(candidate: dict[str, Any]) -> bool:
    source = candidate.get("source") or {}
    target = candidate.get("target") or {}
    source_id = str(source.get("canonical_id") or "")
    target_id = str(target.get("canonical_id") or "")
    if not source_id or not target_id:
        return False
    return source_id != target_id


def _evaluate_python_ast_import(candidate: dict[str, Any]) -> tuple[bool, str | None]:
    if candidate.get("technical_relation_kind") != "python_ast_import":
        return False, "wrong_technical_relation_kind"
    if candidate.get("relation_type") != "depende_de":
        return False, "predicate_mismatch"
    evidence = candidate.get("evidence") or {}
    if evidence.get("technical_evidence_kind") != "ast_import" or evidence.get("parser") != "python_ast":
        return False, "parser_evidence_mismatch"
    if not evidence.get("raw_observation"):
        return False, "evidence_line_not_verifiable"
    if not _endpoints_resolved_and_distinct(candidate):
        return False, "endpoint_not_uniquely_resolved_or_self_reference"
    return True, None


def _evaluate_test_imports_subject(candidate: dict[str, Any]) -> tuple[bool, str | None]:
    if candidate.get("technical_relation_kind") != "test_imports_subject":
        return False, "wrong_technical_relation_kind"
    if candidate.get("relation_type") != "valida":
        return False, "predicate_mismatch"
    evidence = candidate.get("evidence") or {}
    if evidence.get("technical_evidence_kind") != "ast_import" or evidence.get("parser") != "python_ast":
        return False, "parser_evidence_mismatch"
    if not evidence.get("raw_observation"):
        return False, "evidence_line_not_verifiable"
    if not _endpoints_resolved_and_distinct(candidate):
        return False, "endpoint_not_uniquely_resolved_or_self_reference"
    source_path = str((candidate.get("source") or {}).get("repo_path") or "")
    target_path = str((candidate.get("target") or {}).get("repo_path") or "")
    source_base = _basename(source_path)
    target_base = _basename(target_path)
    if not source_base.startswith("test_") or not source_base.endswith(".py"):
        return False, "subject_basename_correspondence_not_demonstrated"
    expected_target = source_base[len("test_"):]
    if expected_target != target_base:
        return False, "subject_basename_correspondence_not_demonstrated"
    return True, None


_TMP_LIKE_JOIN_MARKERS = ("tmp_path", "tempfile", "tmpdir", "scratch", "out_dir", "workdir", "work_dir")


def _looks_like_ephemeral_path_join(raw_observation: str) -> bool:
    lowered = raw_observation.lower()
    return any(marker in lowered for marker in _TMP_LIKE_JOIN_MARKERS)


def _evaluate_script_references_path(candidate: dict[str, Any]) -> tuple[bool, str | None]:
    if candidate.get("technical_relation_kind") != "script_references_path":
        return False, "wrong_technical_relation_kind"
    if candidate.get("relation_type") != "references":
        return False, "predicate_mismatch"
    evidence = candidate.get("evidence") or {}
    if evidence.get("technical_evidence_kind") != "path_literal":
        return False, "parser_evidence_mismatch"
    raw_observation = str(evidence.get("raw_observation") or "")
    if not raw_observation:
        return False, "evidence_line_not_verifiable"
    if not _endpoints_resolved_and_distinct(candidate):
        return False, "endpoint_not_uniquely_resolved_or_self_reference"
    source_path = str((candidate.get("source") or {}).get("repo_path") or "")
    if source_path.startswith("tests/"):
        return False, "test_sourced_literal_fixture_noise_risk"
    if _looks_like_ephemeral_path_join(raw_observation):
        return False, "ephemeral_path_join_misresolution_risk"
    return True, None


def _reject_unsupported_kind(reason: str) -> Callable[[dict[str, Any]], tuple[bool, str | None]]:
    def _evaluate(_candidate: dict[str, Any]) -> tuple[bool, str | None]:
        return False, reason

    return _evaluate


def build_policy_registry() -> tuple[RelationPolicy, ...]:
    """Return the CURRENT set of governed policies.

    ``script_reads_path`` and ``script_writes_artifact`` are deliberately
    UNSUPPORTED, not merely restricted: generate_technical_relation_candidates
    .py's path_literal_observations() extracts a single AST string Constant
    in isolation. When source code builds a path by joining an unrelated
    prefix with that literal (``tmp_path / "README.md"``,
    ``REPO_ROOT / "data" / "README.md"``), the isolated literal can match a
    real file that is NOT the one actually read/written -- demonstrated live
    in the CURRENT batch (a read of ``data/README.md`` misresolved to the
    canon record for the repo-root ``README.md``; a write to a pytest
    ``tmp_path`` fixture file misresolved to the same). This is a structural
    evidence weakness of the observation itself, not a matter of source
    scope or sample size (there are only 5 such candidates CURRENT-wide) --
    no policy is defined for these kinds. They always fall to human review.
    """
    return (
        RelationPolicy(
            policy_id="PYTHON_AST_IMPORT_DEPENDENCY_V1",
            policy_version="1.0.0",
            technical_relation_kind="python_ast_import",
            allowed_predicate="depende_de",
            rationale=(
                "A Python `import`/`from ... import` statement was parsed by "
                "Python's own `ast` module (technical_evidence_kind="
                "python_ast_import, parser=python_ast), and both endpoints "
                "resolve uniquely to distinct canonical repo artifacts. This "
                "is a mechanically verifiable fact, not an inference."
            ),
            evidence_requirements={
                "technical_evidence_kind": "ast_import",
                "parser": "python_ast",
                "raw_observation_present": True,
            },
            resolution_requirements=_base_resolution_requirements(),
            currentness_requirements=_base_currentness_requirements(),
            exclusion_conditions=(
                "reconciliation_ambiguous", "unresolved_endpoint", "self_reference",
                "parser_evidence_mismatch",
            ),
            decision_effect="approved_for_admission",
            decision_reason_code="DIRECT_CODE_DEPENDENCY_CONFIRMED",
            authorization_requirements={"scope": AUTHORIZATION_SCOPE_CURRENT_BATCH, "human_confirmation": "required"},
            evaluate=_evaluate_python_ast_import,
        ),
        RelationPolicy(
            policy_id="TEST_IMPORTS_SUBJECT_STRICT_BASENAME_V1",
            policy_version="1.0.0",
            technical_relation_kind="test_imports_subject",
            allowed_predicate="valida",
            rationale=(
                "The generator labels ANY import from a tests/ file of a "
                "src/python_scripts/ module as test_imports_subject/valida, "
                "regardless of whether the imported module is genuinely the "
                "subject under test or an incidental helper/fixture import "
                "(demonstrated live: 133/168 pending candidates are exactly "
                "this -- e.g. test_relation_correspondence_matrix.py "
                "importing build_relation_correspondence_matrix.py, or a "
                "test importing a shared fixture-support module). This "
                "policy admits only the strict case where the test file's "
                "own name already asserts its subject: test_<X>.py importing "
                "exactly <X>.py -- the one case defensible without further "
                "evidence. All other test_imports_subject candidates are a "
                "genuine relation but not proven to be *validation of the "
                "subject*, and are left to human review."
            ),
            evidence_requirements={
                "technical_evidence_kind": "ast_import",
                "parser": "python_ast",
                "raw_observation_present": True,
            },
            resolution_requirements=_base_resolution_requirements(),
            currentness_requirements=_base_currentness_requirements(),
            exclusion_conditions=(
                "reconciliation_ambiguous", "unresolved_endpoint", "self_reference",
                "subject_basename_correspondence_not_demonstrated",
            ),
            decision_effect="approved_for_admission",
            decision_reason_code="TEST_VALIDATES_TARGET_CONFIRMED",
            authorization_requirements={"scope": AUTHORIZATION_SCOPE_CURRENT_BATCH, "human_confirmation": "required"},
            evaluate=_evaluate_test_imports_subject,
        ),
        RelationPolicy(
            policy_id="SCRIPT_PATH_REFERENCE_PRODUCTION_SOURCE_V1",
            policy_version="1.0.0",
            technical_relation_kind="script_references_path",
            allowed_predicate="references",
            rationale=(
                "A string literal in PRODUCTION source code (source repo_path "
                "not under tests/) exactly matches a real repo file's path. "
                "Production code does not fabricate throwaway path strings "
                "for scaffolding the way test code does; sampled prod-sourced "
                "candidates were all genuine functional references (a "
                "subprocess invocation, a scope-list member, a Path join "
                "rooted at REPO_ROOT). Test-sourced literals are excluded "
                "categorically (see TEST_SOURCED exception below): a "
                "demonstrated false positive exists CURRENT-wide (a test "
                "building a throwaway tmp_path file literally named "
                "README.md, misresolved to the real repo README.md), and "
                "test fixtures routinely embed real-looking path strings as "
                "test data rather than genuine references. The `references` "
                "predicate does not exceed what a literal path mention can "
                "prove either way; this policy only bounds WHICH literals it "
                "trusts to be non-coincidental."
            ),
            evidence_requirements={
                "technical_evidence_kind": "path_literal",
                "raw_observation_present": True,
            },
            resolution_requirements=_base_resolution_requirements(),
            currentness_requirements=_base_currentness_requirements(),
            exclusion_conditions=(
                "reconciliation_ambiguous", "unresolved_endpoint", "self_reference",
                "test_sourced_literal_fixture_noise_risk", "ephemeral_path_join_misresolution_risk",
            ),
            decision_effect="approved_for_admission",
            decision_reason_code="EXPLICIT_REFERENCE_CONFIRMED",
            authorization_requirements={"scope": AUTHORIZATION_SCOPE_CURRENT_BATCH, "human_confirmation": "required"},
            evaluate=_evaluate_script_references_path,
        ),
        RelationPolicy(
            policy_id="SCRIPT_PATH_READ_UNSUPPORTED_V1",
            policy_version="1.0.0",
            technical_relation_kind="script_reads_path",
            allowed_predicate="references",
            rationale=(
                "UNSUPPORTED by design (see build_policy_registry docstring): "
                "path_literal_observations() extracts an isolated string "
                "literal, so a multi-segment path join (e.g. `REPO_ROOT / "
                "\"data\" / \"README.md\"`) can misresolve to a different, "
                "unrelated real file that shares only the final path "
                "segment. Demonstrated live for 3 of 4 CURRENT candidates: "
                "a read of data/README.md was reported as reading the "
                "repo-root README.md. No policy is safe to define here."
            ),
            evidence_requirements={},
            resolution_requirements={},
            currentness_requirements={},
            exclusion_conditions=("always_unsupported",),
            decision_effect="human_review_required",
            decision_reason_code=None,
            authorization_requirements={"scope": None, "human_confirmation": "not_applicable"},
            evaluate=_reject_unsupported_kind("multi_segment_path_join_misresolution_risk_demonstrated"),
        ),
        RelationPolicy(
            policy_id="SCRIPT_ARTIFACT_WRITE_UNSUPPORTED_V1",
            policy_version="1.0.0",
            technical_relation_kind="script_writes_artifact",
            allowed_predicate="produce_artefacto",
            rationale=(
                "UNSUPPORTED for the same structural reason as "
                "SCRIPT_PATH_READ_UNSUPPORTED_V1. Demonstrated live for the "
                "single CURRENT candidate: a write to a pytest tmp_path "
                "fixture file misresolved to the repo-root README.md."
            ),
            evidence_requirements={},
            resolution_requirements={},
            currentness_requirements={},
            exclusion_conditions=("always_unsupported",),
            decision_effect="human_review_required",
            decision_reason_code=None,
            authorization_requirements={"scope": None, "human_confirmation": "not_applicable"},
            evaluate=_reject_unsupported_kind("multi_segment_path_join_misresolution_risk_demonstrated"),
        ),
    )


ELIGIBILITY_CLASSES = frozenset({
    "POLICY_ELIGIBLE", "PARTIALLY_POLICY_ELIGIBLE", "HUMAN_REVIEW_REQUIRED", "UNSUPPORTED",
})


def load_current_pending(local_root: Path = DEFAULT_LOCAL_ROOT) -> dict[str, Any]:
    """Read-only: the live CURRENT pending (undecided, ready-for-review) set."""
    current_dir = local_root / "pipeline" / "relation_candidates" / "current"
    ready = human_review.load_jsonl(current_dir / human_review.QUEUE_FILE)
    decisions_path = human_review.decision_authority_path(current_dir)
    decided_ids = {str(row.get("candidate_id") or "") for row in human_review.load_jsonl(decisions_path)}
    by_id = {str(row.get("candidate_id") or ""): row for row in ready}
    pending_ids = sorted(cid for cid in by_id if cid not in decided_ids)

    review_reason_by_id: dict[str, str] = {}
    generation_pointer = json.loads((local_root / "audit" / "relation_admission" / "current_generation.json").read_text())
    bundle_path = Path(generation_pointer["bundle_path"])
    delta_manifest = json.loads((bundle_path / "current_human_delta_manifest.json").read_text())
    for item in delta_manifest.get("review_candidates") or []:
        review_reason_by_id[str(item.get("candidate_id") or "")] = str(item.get("review_reason") or "")

    return {
        "current_dir": current_dir,
        "pending_ids": pending_ids,
        "by_id": by_id,
        "review_reason_by_id": review_reason_by_id,
        "bindings": human_review.current_bindings(current_dir, local_root),
    }


def partition_pending_candidates(
    policies: tuple[RelationPolicy, ...],
    pending_ids: list[str],
    by_id: dict[str, Any],
    review_reason_by_id: dict[str, str],
) -> dict[str, Any]:
    """Deterministically partition the pending set. Disjoint, exhaustive.

    A candidate whose review_reason is in NEVER_AUTO_REVIEW_REASONS is routed
    to human_exception_required before any policy is even consulted --
    ambiguity is never overridden by a policy match on technical_relation_kind
    alone.
    """
    by_policy: dict[str, list[str]] = {policy.policy_id: [] for policy in policies}
    exceptions: list[dict[str, Any]] = []
    seen: set[str] = set()

    for candidate_id in pending_ids:
        if candidate_id in seen:
            continue
        seen.add(candidate_id)
        candidate = by_id.get(candidate_id)
        if candidate is None:
            exceptions.append({"candidate_id": candidate_id, "reason_code": "candidate_missing_from_queue"})
            continue
        review_reason = review_reason_by_id.get(candidate_id)
        if review_reason in NEVER_AUTO_REVIEW_REASONS:
            exceptions.append({
                "candidate_id": candidate_id,
                "reason_code": "reconciliation_ambiguous_never_auto"
                if review_reason == "reconciliation_ambiguous" else "rebaseline_uncovered_never_auto",
            })
            continue
        kind = candidate.get("technical_relation_kind")
        matching = [policy for policy in policies if policy.technical_relation_kind == kind]
        if not matching:
            exceptions.append({"candidate_id": candidate_id, "reason_code": "no_policy_defined_for_kind"})
            continue
        resolved = False
        last_reason = "unclassified"
        for policy in matching:
            eligible, reason_code = policy.evaluate(candidate)
            if eligible:
                by_policy[policy.policy_id].append(candidate_id)
                resolved = True
                break
            last_reason = reason_code or "policy_conditions_not_met"
        if not resolved:
            exceptions.append({"candidate_id": candidate_id, "reason_code": last_reason})

    total_partitioned = sum(len(ids) for ids in by_policy.values()) + len(exceptions)
    if total_partitioned != len(seen):
        raise AssertionError(
            f"partition is not exhaustive/disjoint: partitioned={total_partitioned} pending={len(seen)}"
        )
    return {"by_policy": by_policy, "exceptions": exceptions, "total_pending": len(seen)}


def eligible_candidate_set_hash(candidate_ids: list[str]) -> str:
    return _hash(sorted(candidate_ids))


def build_policy_authorization_scope(
    policy: RelationPolicy, eligible_candidate_ids: list[str], bindings: dict[str, str],
) -> dict[str, Any]:
    """The exact binding a human authorization for this policy would freeze.

    Any material drift in canon_hash, candidate_batch_hash,
    reconciliation_hash, the policy's own hash, or the eligible set itself
    invalidates a prior authorization -- it must be recomputed, never reused
    silently.
    """
    return {
        "schema_version": SCHEMA_AUTHORIZATION_SCOPE,
        "authorization_scope": AUTHORIZATION_SCOPE_CURRENT_BATCH,
        "canon_hash": bindings["canon_hash"],
        "candidate_batch_hash": bindings["candidate_manifest_hash"],
        "reconciliation_hash": bindings["reconciliation_manifest_hash"],
        "policy_id": policy.policy_id,
        "policy_version": policy.policy_version,
        "policy_hash": policy.policy_hash,
        "eligible_candidate_set_hash": eligible_candidate_set_hash(eligible_candidate_ids),
        "eligible_candidate_count": len(eligible_candidate_ids),
    }


SCHEMA_AUTHORIZATION_RECORD = "governed-relation-admission-authorization-record/v1"

DEFAULT_AUTHORIZATIONS_DIR = (
    DEFAULT_LOCAL_ROOT / "audit" / "relation_admission" / "current" / "policy_authorizations"
)


def authorization_confirmation_phrase(policy_id: str) -> str:
    return f"AUTHORIZE POLICY {policy_id} FOR CURRENT BATCH"


def authorization_id(scope: dict[str, Any]) -> str:
    return "auth_" + _hash(scope)[:24]


class PolicyAuthorizationRefused(ValueError):
    """Fail-closed: the human confirmation text did not match exactly."""


def write_policy_authorization(
    policy: RelationPolicy, eligible_candidate_ids: list[str], bindings: dict[str, str], *,
    actor: str, confirmation: str,
    authorizations_dir: Path = DEFAULT_AUTHORIZATIONS_DIR,
    authorized_at: str | None = None,
) -> dict[str, Any]:
    """Persist a human authorization for exactly this policy + CURRENT scope.

    This is the ONLY function in this module that writes to disk. It refuses
    (fail-closed, no partial write) unless ``confirmation`` matches
    ``authorization_confirmation_phrase(policy.policy_id)`` exactly -- a
    phrase-binding confirmation, not a bare y/N, consistent with every other
    governed confirmation in this codebase (BATCH_CONFIRMATION,
    SUPERSESSION_CONFIRMATION, APPLY_CONFIRMATION). It never evaluates
    candidates, never approves anything, and never touches Canon or
    human_review_decisions.jsonl -- it only records that a human authorized
    this policy for this exact, hash-bound batch scope. A later step
    (deliberately not implemented in S0186 Unit H8) must still re-verify this
    authorization's bindings against the then-current state before deriving
    or persisting any decision from it.
    """
    expected = authorization_confirmation_phrase(policy.policy_id)
    if confirmation != expected:
        raise PolicyAuthorizationRefused(
            f"confirmation text did not match exactly. expected={expected!r}"
        )
    if not str(actor or "").strip():
        raise PolicyAuthorizationRefused("actor (human identity) is required")
    scope = build_policy_authorization_scope(policy, eligible_candidate_ids, bindings)
    record = {
        "schema_version": SCHEMA_AUTHORIZATION_RECORD,
        "authorization_id": authorization_id(scope),
        "authorized_by": actor.strip(),
        "authorized_at": authorized_at or datetime.now(timezone.utc).isoformat(),
        "confirmation_phrase": confirmation,
        "consumed": False,
        **scope,
    }
    authorizations_dir.mkdir(parents=True, exist_ok=True)
    out_path = authorizations_dir / f"{record['authorization_id']}.json"
    out_path.write_text(json.dumps(record, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return record


def verify_policy_authorization_current(
    authorization: dict[str, Any], policy: RelationPolicy,
    eligible_candidate_ids: list[str], bindings: dict[str, str],
) -> list[str]:
    """Fail-closed re-verification: what would make a stored authorization stale.

    Returns an empty list only if every binding still matches exactly. Any
    drift -- Canon grew, the candidate batch or reconciliation regenerated,
    the policy itself changed, or the eligible set moved even by one
    candidate_id -- is returned as a reason and must block reuse.
    """
    fresh = build_policy_authorization_scope(policy, eligible_candidate_ids, bindings)
    reasons = []
    for field_name in (
        "canon_hash", "candidate_batch_hash", "reconciliation_hash",
        "policy_id", "policy_version", "policy_hash",
        "eligible_candidate_set_hash", "eligible_candidate_count",
    ):
        if authorization.get(field_name) != fresh.get(field_name):
            reasons.append(f"stale:{field_name}")
    if authorization.get("consumed"):
        reasons.append("already_consumed")
    return reasons


def load_policy_authorizations(
    policy_id: str | None = None, authorizations_dir: Path = DEFAULT_AUTHORIZATIONS_DIR,
) -> list[dict[str, Any]]:
    """Read-only: every stored authorization record, newest first.

    Reading an authorization never re-verifies it -- callers that need to
    know whether one is still usable must call
    ``verify_policy_authorization_current`` against live CURRENT state.
    """
    if not authorizations_dir.is_dir():
        return []
    records = []
    for path in sorted(authorizations_dir.glob("auth_*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if policy_id is not None and record.get("policy_id") != policy_id:
            continue
        records.append(record)
    records.sort(key=lambda r: str(r.get("authorized_at") or ""), reverse=True)
    return records


def materialized_candidate_ids_for_policy(
    policy_id: str, current_dir: Path,
) -> set[str]:
    """Read-only: candidate_ids already decided via this policy (any decision_mode='policy_derived' row whose review_policy_id matches).

    This is derived from the decisions file itself, not from an
    authorization's ``consumed`` flag -- the flag records that ONE
    authorization was used, but the durable fact of "was this candidate
    already decided by this policy" must survive even if the authorization
    file were lost, and must stay correct across multiple authorizations of
    the same policy over time (e.g. a later CURRENT batch growing and being
    re-authorized).
    """
    decisions_path = human_review.decision_authority_path(current_dir)
    materialized = set()
    for row in human_review.load_jsonl(decisions_path):
        if row.get("decision_mode") == "policy_derived" and row.get("review_policy_id") == policy_id:
            materialized.add(str(row.get("candidate_id") or ""))
    return materialized


def materialized_decision_provenance_for_policy(
    policy_id: str, current_dir: Path,
) -> dict[str, int]:
    """Read-only: split materialized_candidate_ids_for_policy() by how each
    decision reached the CURRENT generation.

    S0186 Unit H (policy_derived generational preservation fix): a
    materialized decision inherited from an earlier generation via
    prepare_current_relational_generation._preserve_equivalent_decisions()
    carries a ``generational_preservation`` marker (added there, never by
    materialize_authorized_policy()); one written directly in THIS
    generation does not. Both are equally "materialized" and equally
    effective for admission -- this distinction is for operator visibility
    only (see build_policy_status()), never for eligibility or gating.
    """
    decisions_path = human_review.decision_authority_path(current_dir)
    freshly_materialized = 0
    generationally_preserved = 0
    for row in human_review.load_jsonl(decisions_path):
        if row.get("decision_mode") != "policy_derived" or row.get("review_policy_id") != policy_id:
            continue
        if row.get("generational_preservation"):
            generationally_preserved += 1
        else:
            freshly_materialized += 1
    return {
        "freshly_materialized": freshly_materialized,
        "generationally_preserved": generationally_preserved,
    }


class PolicyMaterializationBlocked(ValueError):
    """Fail-closed: the authorization is not currently valid for materialization."""

    def __init__(self, reasons: list[str]):
        self.reasons = reasons
        super().__init__(", ".join(reasons) or "authorization not valid")


def materialize_authorized_policy(
    local_root: Path, *, policy_id: str, authorization: dict[str, Any], actor: str,
    reviewed_at: str | None = None,
) -> dict[str, Any]:
    """Turn one still-valid authorization into persisted policy_derived decisions.

    Re-verifies EVERY binding against freshly recomputed CURRENT state right
    before writing (not just at authorization time) and refuses, writing
    nothing, on any drift -- including the authorization having already been
    consumed. This is the ONLY function in this module that writes to
    ``human_review_decisions.jsonl``, and it delegates the actual atomic
    write to current_relation_human_review's existing primitives (the
    established owner of that file) rather than duplicating them.

    authorization != decision != admission != Apply: this function persists
    decisions only. It never touches Canon, never runs the admission gate,
    never applies anything.
    """
    policies = {policy.policy_id: policy for policy in build_policy_registry()}
    policy = policies.get(policy_id)
    if policy is None:
        raise PolicyMaterializationBlocked([f"unknown_policy:{policy_id}"])
    if policy.decision_effect != "approved_for_admission":
        raise PolicyMaterializationBlocked([f"policy_has_no_approving_decision_effect:{policy_id}"])

    state = load_current_pending(local_root)
    partition = partition_pending_candidates(
        build_policy_registry(), state["pending_ids"], state["by_id"], state["review_reason_by_id"],
    )
    eligible_ids = partition["by_policy"][policy_id]

    staleness = verify_policy_authorization_current(authorization, policy, eligible_ids, state["bindings"])
    if staleness:
        raise PolicyMaterializationBlocked(staleness)
    if not eligible_ids:
        raise PolicyMaterializationBlocked(["eligible_set_empty"])

    current_dir = state["current_dir"]
    decisions_path = human_review.decision_authority_path(current_dir)
    decisions = human_review.load_existing_decisions(decisions_path, set(state["by_id"]), state["bindings"])
    already_decided = sorted(set(eligible_ids) & set(decisions))
    if already_decided:
        # The eligible-set-hash check above should already have caught this
        # (a decided candidate is no longer "pending"), but refuse loudly
        # rather than silently overwrite if it somehow did not.
        raise PolicyMaterializationBlocked([f"candidate_already_decided:{','.join(already_decided[:5])}"])

    new_records: list[dict[str, Any]] = []
    for candidate_id in eligible_ids:
        record = materialize_policy_decision(
            policy, state["by_id"][candidate_id], actor=actor, bindings=state["bindings"],
            human_authorization_id=authorization["authorization_id"], reviewed_at=reviewed_at,
        )
        decisions[candidate_id] = record
        new_records.append(record)

    # Re-check immediately before the write for a last-moment concurrent
    # change, exactly as persist_batch_preview() does for batch decisions.
    if human_review.current_bindings(current_dir, local_root) != state["bindings"]:
        raise PolicyMaterializationBlocked(["current_bindings_changed_during_materialization"])

    human_review.atomic_write_jsonl(decisions_path, decisions)
    try:
        for record in new_records:
            human_review.append_audit(current_dir / human_review.AUDIT_FILE, record, previous=None)
    except OSError as error:
        raise RuntimeError(
            "authoritative policy-derived decisions persisted, but auxiliary audit append failed"
        ) from error

    authorization = {**authorization, "consumed": True}
    authorizations_dir = local_root / "audit" / "relation_admission" / "current" / "policy_authorizations"
    out_path = authorizations_dir / f"{authorization['authorization_id']}.json"
    if out_path.is_file():
        out_path.write_text(
            json.dumps(authorization, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8",
        )

    return {
        "schema_version": "governed-relation-admission-materialization-receipt/v1",
        "policy_id": policy_id,
        "authorization_id": authorization["authorization_id"],
        "materialized_count": len(new_records),
        "candidate_ids": eligible_ids,
        "actor": actor,
        "canon_modified": False,
        "apply_executed": False,
    }


def build_policy_status(local_root: Path = DEFAULT_LOCAL_ROOT) -> dict[str, Any]:
    """Read-only: eligible / authorized / materialized / status per policy.

    S0186 Unit H8 (second diagnostic pass): a *consumed* authorization is a
    successful, historical fact -- the human authorized it, it was used
    exactly once as designed, and its bindings still describe that past
    eligible set correctly. That is not the same thing as *stale* (bindings
    that no longer match current reality and can never be reused). Both used
    to be folded into a single ``stale_authorizations`` count via
    ``verify_policy_authorization_current``'s "already_consumed" reason,
    which made a successful materialization look like a failure in the
    operator view. Authorizations are now partitioned into three disjoint
    groups: active (fresh, reusable, not yet consumed), consumed (used
    successfully -- historical, not stale), and genuinely stale (bindings
    drifted, never consumed, unusable as-is).
    """
    state = load_current_pending(local_root)
    policies = build_policy_registry()
    partition = partition_pending_candidates(
        policies, state["pending_ids"], state["by_id"], state["review_reason_by_id"],
    )
    statuses = []
    for policy in policies:
        eligible_ids = partition["by_policy"][policy.policy_id]
        materialized_ids = materialized_candidate_ids_for_policy(policy.policy_id, state["current_dir"])
        provenance = materialized_decision_provenance_for_policy(policy.policy_id, state["current_dir"])
        authorizations = load_policy_authorizations(
            policy.policy_id, local_root / "audit" / "relation_admission" / "current" / "policy_authorizations",
        )
        active_authorizations: list[dict[str, Any]] = []
        consumed_authorizations: list[dict[str, Any]] = []
        stale_authorizations: list[dict[str, Any]] = []
        for authorization in authorizations:
            # A consumed authorization is a historical fact, decided the
            # moment materialize_authorized_policy() flipped its consumed
            # flag. It must NOT be re-judged against a freshly recomputed
            # eligible set: successful consumption is EXPECTED to shrink
            # that set (the materialized candidates are no longer pending),
            # so comparing it to current state would always -- wrongly --
            # look like drift. Only a still-unconsumed authorization's
            # bindings are meaningfully compared to current state at all.
            if bool(authorization.get("consumed")):
                consumed_authorizations.append(authorization)
                continue
            reasons = verify_policy_authorization_current(authorization, policy, eligible_ids, state["bindings"])
            if not reasons:
                active_authorizations.append(authorization)
            else:
                stale_authorizations.append(authorization)
        fresh_authorization = active_authorizations[0] if active_authorizations else None
        if policy.decision_effect != "approved_for_admission":
            status = "UNSUPPORTED"
        elif materialized_ids and provenance["freshly_materialized"] == 0:
            status = "MATERIALIZED_PRESERVED"
        elif materialized_ids:
            status = "MATERIALIZED"
        elif fresh_authorization is not None:
            status = "AUTHORIZED_PENDING_MATERIALIZATION"
        elif stale_authorizations:
            status = "STALE_AUTHORIZATION"
        elif eligible_ids:
            status = "ELIGIBLE_NOT_AUTHORIZED"
        else:
            status = "NO_ELIGIBLE_CANDIDATES"
        statuses.append({
            "policy_id": policy.policy_id,
            "eligible": len(eligible_ids),
            "authorized": fresh_authorization["eligible_candidate_count"] if fresh_authorization else 0,
            "materialized": len(materialized_ids),
            "materialized_freshly_this_generation": provenance["freshly_materialized"],
            "materialized_generationally_preserved": provenance["generationally_preserved"],
            # True once any decision has been materialized: materialization
            # writes into the exact file
            # (current_relation_human_review.decision_authority_path())
            # relation_admission_gate.py's human-decision criteria consume,
            # so "materialized" and "effective for the human-decision gate
            # criterion" are the same moment, not two separate phases.
            # Whether a materialized candidate additionally reaches
            # admission_ready_dry_run depends on OTHER, unrelated gate
            # criteria (e.g. repo lifecycle metadata) that policy governance
            # does not and must not try to satisfy.
            "effective_for_admission": len(materialized_ids) > 0,
            "status": status,
            "authorization_id": fresh_authorization["authorization_id"] if fresh_authorization else None,
            "active_authorizations": len(active_authorizations),
            "consumed_authorizations": len(consumed_authorizations),
            "stale_authorizations": len(stale_authorizations),
        })
    return {"schema_version": "governed-relation-admission-policy-status/v3", "policies": statuses}


def _sample(candidate_ids: list[str], by_id: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    samples = []
    for candidate_id in candidate_ids[:limit]:
        candidate = by_id.get(candidate_id) or {}
        samples.append({
            "candidate_id": candidate_id,
            "source": (candidate.get("source") or {}).get("repo_path"),
            "target": (candidate.get("target") or {}).get("repo_path"),
            "predicate": candidate.get("relation_type"),
            "evidence": (candidate.get("evidence") or {}).get("raw_observation"),
        })
    return samples


def build_current_policy_preview(local_root: Path = DEFAULT_LOCAL_ROOT) -> dict[str, Any]:
    """Read-only preview: policies x CURRENT pending. Writes nothing."""
    state = load_current_pending(local_root)
    policies = build_policy_registry()
    partition = partition_pending_candidates(
        policies, state["pending_ids"], state["by_id"], state["review_reason_by_id"],
    )

    policy_summaries = []
    for policy in policies:
        eligible_ids = partition["by_policy"][policy.policy_id]
        summary: dict[str, Any] = {
            "policy_id": policy.policy_id,
            "policy_version": policy.policy_version,
            "policy_hash": policy.policy_hash,
            "technical_relation_kind": policy.technical_relation_kind,
            "allowed_predicate": policy.allowed_predicate,
            "decision_effect": policy.decision_effect,
            "eligible_count": len(eligible_ids),
            "sample": _sample(eligible_ids, state["by_id"]),
        }
        if eligible_ids:
            summary["authorization_scope"] = build_policy_authorization_scope(
                policy, eligible_ids, state["bindings"],
            )
        policy_summaries.append(summary)

    from collections import Counter
    exception_reason_counts = Counter(item["reason_code"] for item in partition["exceptions"])

    return {
        "schema_version": SCHEMA_POLICY_PREVIEW,
        "bindings": state["bindings"],
        "current_pending_total": partition["total_pending"],
        "policies": policy_summaries,
        "policy_eligible_total": sum(len(ids) for ids in partition["by_policy"].values()),
        "human_exception_total": len(partition["exceptions"]),
        "exception_reason_counts": dict(sorted(exception_reason_counts.items())),
        "exception_sample": partition["exceptions"][:20],
        "human_only_candidate_ids": sorted(item["candidate_id"] for item in partition["exceptions"]),
    }


def materialize_policy_decision(
    policy: RelationPolicy, candidate: dict[str, Any], *, actor: str,
    bindings: dict[str, str], human_authorization_id: str,
    reviewed_at: str | None = None,
) -> dict[str, Any]:
    """Build (but do not persist) one policy-derived decision record.

    Callers MUST have already verified: the policy authorization for this
    exact CURRENT batch scope exists and is unexpired
    (authorization.policy_hash == policy.policy_hash,
    authorization.eligible_candidate_set_hash matches the freshly
    recomputed eligible set, and authorization.candidate_batch_hash /
    canon_hash / reconciliation_hash all match ``bindings``), and that
    ``candidate["candidate_id"]`` is a member of that authorized eligible
    set. This function does not re-verify any of that -- it only shapes the
    record with correct, non-falsified provenance. H8 does not call this
    against the live pending set; it exists so the provenance contract is
    testable end to end before any human authorization occurs.
    """
    if policy.decision_effect != "approved_for_admission":
        raise ValueError(f"policy {policy.policy_id} has no approving decision_effect")
    eligible, reason_code = policy.evaluate(candidate)
    if not eligible:
        raise ValueError(f"candidate does not satisfy policy {policy.policy_id}: {reason_code}")
    return human_review.build_decision_record(
        candidate,
        decision=policy.decision_effect,
        reason_code=policy.decision_reason_code or "",
        actor=actor,
        bindings=bindings,
        decision_mode="policy_derived",
        review_policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        policy_hash=policy.policy_hash,
        human_authorization_id=human_authorization_id,
        authorization_scope=AUTHORIZATION_SCOPE_CURRENT_BATCH,
        reviewed_at=reviewed_at,
    )


EXCEPTION_REASON_CATEGORY: dict[str, str] = {
    "reconciliation_ambiguous_never_auto": "RECONCILIATION_AMBIGUOUS",
    "rebaseline_uncovered_never_auto": "RECONCILIATION_AMBIGUOUS",
    "multi_segment_path_join_misresolution_risk_demonstrated": "UNSUPPORTED_POLICY",
}


def exception_category(reason_code: str) -> str:
    """Never lump every exception under one 'ambiguous' label (S0186 H8 fix).

    Only a review_reason of reconciliation_ambiguous/rebaseline_uncovered is
    genuine reconciliation ambiguity. A policy that exists but whose
    conditions this specific candidate does not satisfy is
    MANUAL_REVIEW_REQUIRED, not ambiguity -- conflating the two misrepresents
    which candidates are contentious versus merely unproven.
    """
    return EXCEPTION_REASON_CATEGORY.get(reason_code, "MANUAL_REVIEW_REQUIRED")


def render_compact_summary(preview: dict[str, Any], status: dict[str, Any] | None = None) -> str:
    status_by_policy = {p["policy_id"]: p for p in (status or {}).get("policies", [])}
    lines = [
        "RELACIONES CURRENT — GOBERNANZA POR POLÍTICAS",
        "",
        f"Pendientes únicas: {preview['current_pending_total']}",
        "",
    ]
    if status_by_policy:
        lines.append(f"{'POLÍTICA / FAMILIA':<44} {'ELEGIBLES':>9} {'AUTORIZ.':>9} {'MATERIAL.':>10} {'ESTADO':<32}")
        lines.append("-" * 108)
        materialized_policies = []
        for policy in preview["policies"]:
            item = status_by_policy.get(policy["policy_id"], {})
            lines.append(
                f"{policy['policy_id']:<44} {item.get('eligible', policy['eligible_count']):>9} "
                f"{item.get('authorized', 0):>9} {item.get('materialized', 0):>10} {item.get('status', ''):<32}"
            )
            if item.get("materialized"):
                materialized_policies.append((policy["policy_id"], item))
        for policy_id, item in materialized_policies:
            lines.append(
                f"  {policy_id}: efectivo para admisión=Sí; "
                f"admission_ready_dry_run depende además de otros criterios de la compuerta "
                f"(ver detalle); autorización consumida (histórica, no obsoleta): "
                f"{item.get('consumed_authorizations', 0)}"
            )
            lines.append(
                f"    materializadas en esta generación: {item.get('materialized_freshly_this_generation', 0)}; "
                f"preservadas por linaje generacional: {item.get('materialized_generationally_preserved', 0)}"
            )
    else:
        lines.append(f"{'POLÍTICA / FAMILIA':<48} {'ELEGIBLES':>10}")
        lines.append("-" * 60)
        for policy in preview["policies"]:
            lines.append(f"{policy['policy_id']:<48} {policy['eligible_count']:>10}")

    from collections import Counter
    category_counts: Counter[str] = Counter()
    for reason, count in preview["exception_reason_counts"].items():
        category_counts[exception_category(reason)] += count

    lines.append("")
    lines.append("EXCEPCIONES POR CATEGORÍA (nunca se autoaprueban):")
    for category in ("RECONCILIATION_AMBIGUOUS", "UNSUPPORTED_POLICY", "MANUAL_REVIEW_REQUIRED"):
        if category_counts.get(category):
            lines.append(f"  {category:<32} {category_counts[category]:>10}")
    lines += [
        "",
        f"Cubiertas por políticas: {preview['policy_eligible_total']}",
        f"Revisión humana restante (todas las categorías): {preview['human_exception_total']}",
        f"Sin clasificar: {preview['current_pending_total'] - preview['policy_eligible_total'] - preview['human_exception_total']}",
    ]
    return "\n".join(lines)


def render_policy_detail(preview: dict[str, Any], policy_id: str, status: dict[str, Any] | None = None) -> str:
    policy = next((p for p in preview["policies"] if p["policy_id"] == policy_id), None)
    if policy is None:
        return f"Política desconocida: {policy_id}"
    lines = [
        f"policy_id: {policy['policy_id']}",
        f"policy_version: {policy['policy_version']}",
        f"policy_hash: {policy['policy_hash']}",
        f"technical_relation_kind: {policy['technical_relation_kind']}",
        f"allowed_predicate: {policy['allowed_predicate']}",
        f"decision_effect: {policy['decision_effect']}",
        f"candidatos elegibles: {policy['eligible_count']}",
    ]
    item = next((p for p in (status or {}).get("policies", []) if p["policy_id"] == policy_id), None)
    if item is not None:
        lines.append(f"estado: {item['status']}")
        lines.append(f"autorizados: {item['authorized']} | materializados: {item['materialized']}")
        lines.append(f"efectivo para admisión (criterio de decisión humana): {item.get('effective_for_admission')}")
        if item.get("effective_for_admission"):
            lines.append(
                "  (admission_ready_dry_run puede seguir siendo menor: depende de otros criterios "
                "de la compuerta -- p.ej. metadata de lifecycle -- ajenos a la gobernanza por políticas)"
            )
        if item.get("authorization_id"):
            lines.append(f"authorization_id vigente (activa, reutilizable): {item['authorization_id']}")
        lines.append(
            f"autorizaciones -- activas: {item.get('active_authorizations', 0)} | "
            f"consumidas (históricas, no obsoletas): {item.get('consumed_authorizations', 0)} | "
            f"obsoletas (no reutilizables): {item.get('stale_authorizations', 0)}"
        )
    if "authorization_scope" in policy:
        lines.append("")
        lines.append("authorization_scope (lo que una autorización fijaría):")
        lines.append(json.dumps(policy["authorization_scope"], indent=2, ensure_ascii=False))
        lines.append("")
        lines.append(f"Frase de confirmación exacta requerida: {authorization_confirmation_phrase(policy_id)!r}")
    lines.append("")
    lines.append(f"Muestra (hasta {len(policy['sample'])}):")
    for item in policy["sample"]:
        lines.append(f"  - {item['source']} -> {item['target']} | {item['predicate']} | {item['evidence']}")
    return "\n".join(lines)


def render_exceptions_detail(preview: dict[str, Any]) -> str:
    from collections import Counter, defaultdict
    by_category: dict[str, Counter[str]] = defaultdict(Counter)
    for reason, count in preview["exception_reason_counts"].items():
        by_category[exception_category(reason)][reason] = count

    lines = [f"Excepciones humanas totales: {preview['human_exception_total']}", ""]
    for category in ("RECONCILIATION_AMBIGUOUS", "UNSUPPORTED_POLICY", "MANUAL_REVIEW_REQUIRED"):
        reasons = by_category.get(category)
        if not reasons:
            continue
        lines.append(f"{category} ({sum(reasons.values())}):")
        for reason, count in reasons.items():
            lines.append(f"  - {reason}: {count}")
        lines.append("")
    lines.append(f"Muestra (hasta {len(preview['exception_sample'])} candidate_id, no el detalle completo):")
    for item in preview["exception_sample"]:
        lines.append(f"  - {item['candidate_id']}: {item['reason_code']} [{exception_category(item['reason_code'])}]")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Governed relational admission policy (S0186 Unit H8)")
    parser.add_argument("--local-root", type=Path, default=DEFAULT_LOCAL_ROOT)
    parser.add_argument("--compact", action="store_true", help="print the human-facing compact summary instead of JSON")
    parser.add_argument("--policy", help="show full detail (scope, sample, confirmation phrase) for one policy_id")
    parser.add_argument("--exceptions", action="store_true", help="show the human-exception reason breakdown and a sample")
    parser.add_argument(
        "--authorize", metavar="POLICY_ID",
        help="write a human authorization for POLICY_ID over its current eligible set (requires --actor and --confirmation)",
    )
    parser.add_argument("--actor", help="human identity authorizing (--authorize) or materializing (--materialize)")
    parser.add_argument("--confirmation", help="exact confirmation phrase (required with --authorize)")
    parser.add_argument(
        "--status", action="store_true",
        help="show eligible/authorized/materialized/status per policy instead of eligible counts alone",
    )
    parser.add_argument(
        "--materialize", metavar="POLICY_ID",
        help="materialize decisions from POLICY_ID's current, still-valid authorization (requires --actor)",
    )
    args = parser.parse_args(argv)

    if args.materialize:
        authorizations = load_policy_authorizations(
            args.materialize, args.local_root / "audit" / "relation_admission" / "current" / "policy_authorizations",
        )
        fresh = None
        policies = {p.policy_id: p for p in build_policy_registry()}
        policy = policies.get(args.materialize)
        if policy is not None:
            state = load_current_pending(args.local_root)
            partition = partition_pending_candidates(
                build_policy_registry(), state["pending_ids"], state["by_id"], state["review_reason_by_id"],
            )
            eligible_ids = partition["by_policy"][args.materialize]
            for authorization in authorizations:
                if not verify_policy_authorization_current(authorization, policy, eligible_ids, state["bindings"]):
                    fresh = authorization
                    break
        if fresh is None:
            print(f"No existe una autorización vigente y no consumida para {args.materialize}.")
            print("Use la opción de autorizar primero, o verifique si ya fue materializada / quedó obsoleta.")
            return 1
        try:
            receipt = materialize_authorized_policy(
                args.local_root, policy_id=args.materialize, authorization=fresh, actor=args.actor or "",
            )
        except PolicyMaterializationBlocked as error:
            print(f"MATERIALIZACIÓN BLOQUEADA: {error}")
            return 1
        print(
            f"Decisiones materializadas: {receipt['materialized_count']} "
            f"(policy={receipt['policy_id']}, authorization={receipt['authorization_id']})"
        )
        return 0

    preview = build_current_policy_preview(args.local_root)

    if args.authorize:
        policies = {p.policy_id: p for p in build_policy_registry()}
        policy = policies.get(args.authorize)
        if policy is None:
            print(f"Política desconocida: {args.authorize}")
            return 1
        state = load_current_pending(args.local_root)
        partition = partition_pending_candidates(
            build_policy_registry(), state["pending_ids"], state["by_id"], state["review_reason_by_id"],
        )
        eligible_ids = partition["by_policy"][args.authorize]
        try:
            record = write_policy_authorization(
                policy, eligible_ids, state["bindings"],
                actor=args.actor or "", confirmation=args.confirmation or "",
                authorizations_dir=args.local_root / "audit" / "relation_admission" / "current" / "policy_authorizations",
            )
        except PolicyAuthorizationRefused as error:
            print(f"AUTORIZACIÓN RECHAZADA: {error}")
            print(f"Frase exacta requerida: {authorization_confirmation_phrase(args.authorize)!r}")
            return 1
        print(f"Autorización escrita: {record['authorization_id']} ({record['eligible_candidate_count']} candidatos)")
        return 0

    status = build_policy_status(args.local_root) if (args.status or args.compact or args.policy) else None

    if args.policy:
        print(render_policy_detail(preview, args.policy, status))
    elif args.exceptions:
        print(render_exceptions_detail(preview))
    elif args.status:
        print(json.dumps(status, indent=2, ensure_ascii=False))
    elif args.compact:
        print(render_compact_summary(preview, status))
    else:
        print(json.dumps(preview, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
