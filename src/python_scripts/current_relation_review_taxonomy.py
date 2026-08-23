"""Single contract for current relational human-review taxonomy.

Cross-generation reconciliation and the reason for a new human review are
separate dimensions.  In particular, a governed rebaseline may require a new
review without making a cross-generation claim.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Iterable


SCHEMA_REVIEW_TAXONOMY = "current-relational-review-taxonomy/v1"
RECONCILIATION_CLASS_TO_REVIEW_REASON = {
    "new": "reconciliation_new",
    "modified": "reconciliation_modified",
    "ambiguous": "reconciliation_ambiguous",
}
REBASELINE_UNCOVERED = "rebaseline_uncovered"
ALLOWED_REVIEW_REASONS = (
    *RECONCILIATION_CLASS_TO_REVIEW_REASON.values(),
    REBASELINE_UNCOVERED,
)
REBASELINE_REQUIRED_CAUSES = frozenset({
    "predecessor_manifest_bound_to_mutable_inventory",
    "certified_predecessor_inventory_unrecoverable",
})


def _unique_index(rows: Iterable[dict[str, Any]], key: str) -> tuple[dict[str, dict[str, Any]], set[str]]:
    result: dict[str, dict[str, Any]] = {}
    duplicates: set[str] = set()
    for row in rows:
        identity = str(row.get(key) or "")
        if not identity or identity in result:
            duplicates.add(identity or "<missing>")
            continue
        result[identity] = row
    return result, duplicates


def build_review_taxonomy(
    pending_candidate_ids: Iterable[str],
    current_to_predecessor: Iterable[dict[str, Any]],
    governed_rebaseline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify why every current pending candidate requires human review.

    An ``equivalent`` observation from an uncertifiable predecessor is retained
    as provenance only.  It does not become an operational reconciliation
    class; the review reason is instead ``rebaseline_uncovered`` when every
    governed rebaseline precondition is verified.
    """
    pending = [str(candidate_id) for candidate_id in pending_candidate_ids]
    duplicate_ids = {candidate_id for candidate_id in pending if pending.count(candidate_id) > 1}
    matrix, matrix_duplicates = _unique_index(current_to_predecessor, "candidate_id")
    duplicate_ids.update(matrix_duplicates & set(pending))
    request = governed_rebaseline or {}
    coverage, coverage_duplicates = _unique_index(
        request.get("current_candidate_coverage") or [], "candidate_id"
    )
    duplicate_ids.update(coverage_duplicates & set(pending))
    causes = set(request.get("cause") or [])
    certified_discontinuity = REBASELINE_REQUIRED_CAUSES.issubset(causes)
    items: list[dict[str, Any]] = []
    missing: list[str] = []
    unsupported: list[str] = []
    for candidate_id in sorted(set(pending)):
        reconciliation = matrix.get(candidate_id) or {}
        observed_class = reconciliation.get("classification")
        reconciliation_class: str | None = None
        review_reason: str | None = None
        evidence: dict[str, Any] = {
            "reconciliation_observation": observed_class,
            "reconciliation_decision_reusable": reconciliation.get("decision_reusable"),
            "reconciliation_counterpart_candidate_id": reconciliation.get("counterpart_candidate_id"),
        }
        if observed_class in RECONCILIATION_CLASS_TO_REVIEW_REASON:
            reconciliation_class = str(observed_class)
            review_reason = RECONCILIATION_CLASS_TO_REVIEW_REASON[reconciliation_class]
        else:
            candidate_coverage = coverage.get(candidate_id) or {}
            rebaseline_uncovered = bool(
                governed_rebaseline
                and certified_discontinuity
                and candidate_coverage.get("coverage_status") == "pending_human_rebaseline_review"
                and candidate_coverage.get("review_required") is True
                and not candidate_coverage.get("preserved_effective_decision_id")
                and candidate_coverage.get("reason_code")
                == "current_candidate_not_covered_by_certified_decision"
            )
            evidence.update({
                "governed_rebaseline": bool(governed_rebaseline),
                "certified_predecessor_continuity": "unavailable" if certified_discontinuity else "not_verified",
                "coverage_status": candidate_coverage.get("coverage_status"),
                "preserved_effective_decision_id": candidate_coverage.get("preserved_effective_decision_id"),
                "coverage_reason_code": candidate_coverage.get("reason_code"),
            })
            if rebaseline_uncovered:
                review_reason = REBASELINE_UNCOVERED
            elif observed_class not in (None, "", "equivalent"):
                unsupported.append(candidate_id)
            else:
                missing.append(candidate_id)
        items.append({
            "candidate_id": candidate_id,
            "reconciliation_class": reconciliation_class,
            "review_reason": review_reason,
            "evidence": evidence,
        })
    counts = Counter(str(item["review_reason"]) for item in items if item["review_reason"])
    conservation_valid = bool(
        len(pending) == len(set(pending)) == len(items)
        and sum(counts.values()) == len(items)
        and not duplicate_ids
        and not missing
        and not unsupported
    )
    return {
        "schema_version": SCHEMA_REVIEW_TAXONOMY,
        "items": items,
        "review_reason_counts": {
            reason: counts.get(reason, 0) for reason in ALLOWED_REVIEW_REASONS
        },
        "missing_review_reason_candidate_ids": sorted(missing),
        "unsupported_review_reason_candidate_ids": sorted(unsupported),
        "duplicate_candidate_ids": sorted(duplicate_ids),
        "total_pending": len(set(pending)),
        "conservation_valid": conservation_valid,
    }


def validate_published_review_taxonomy(
    pending_candidate_ids: Iterable[str], review_candidates: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Validate a published taxonomy without reconstructing its provenance."""
    pending = [str(candidate_id) for candidate_id in pending_candidate_ids]
    rows = list(review_candidates)
    indexed, duplicate_ids = _unique_index(rows, "candidate_id")
    missing_ids = sorted(set(pending) - set(indexed))
    outside_ids = sorted(set(indexed) - set(pending))
    missing_reason: list[str] = []
    unsupported: list[str] = []
    inconsistent: list[str] = []
    for candidate_id in sorted(set(pending) & set(indexed)):
        row = indexed[candidate_id]
        reconciliation_class = row.get("reconciliation_class")
        reason = row.get("review_reason")
        if not reason:
            missing_reason.append(candidate_id)
            continue
        if reason not in ALLOWED_REVIEW_REASONS:
            unsupported.append(candidate_id)
            continue
        expected = RECONCILIATION_CLASS_TO_REVIEW_REASON.get(str(reconciliation_class))
        if reason == REBASELINE_UNCOVERED:
            if reconciliation_class is not None:
                inconsistent.append(candidate_id)
        elif expected != reason:
            inconsistent.append(candidate_id)
    counts = Counter(
        str(row.get("review_reason")) for row in indexed.values()
        if row.get("review_reason") in ALLOWED_REVIEW_REASONS
    )
    valid = not any((duplicate_ids, missing_ids, outside_ids, missing_reason, unsupported, inconsistent))
    valid = valid and len(set(pending)) == len(pending) == sum(counts.values())
    return {
        "valid": valid,
        "total_pending": len(set(pending)),
        "review_reason_counts": {reason: counts.get(reason, 0) for reason in ALLOWED_REVIEW_REASONS},
        "missing_candidate_ids": missing_ids,
        "outside_candidate_ids": outside_ids,
        "missing_review_reason_candidate_ids": sorted(missing_reason),
        "unsupported_review_reason_candidate_ids": sorted(unsupported),
        "inconsistent_candidate_ids": sorted(inconsistent),
        "duplicate_candidate_ids": sorted(duplicate_ids),
    }
