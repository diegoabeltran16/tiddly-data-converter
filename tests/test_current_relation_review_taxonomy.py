from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

import current_relation_review_taxonomy as taxonomy  # noqa: E402


def _reconciliation(candidate_id: str, classification: str) -> dict:
    return {
        "candidate_id": candidate_id,
        "counterpart_candidate_id": "rc_old_" + candidate_id.removeprefix("rc_current_"),
        "classification": classification,
        "decision_reusable": classification == "equivalent",
    }


def _rebaseline(candidate_id: str) -> dict:
    return {
        "cause": [
            "predecessor_manifest_bound_to_mutable_inventory",
            "certified_predecessor_inventory_unrecoverable",
        ],
        "current_candidate_coverage": [{
            "candidate_id": candidate_id,
            "coverage_status": "pending_human_rebaseline_review",
            "review_required": True,
            "preserved_effective_decision_id": None,
            "reason_code": "current_candidate_not_covered_by_certified_decision",
        }],
    }


def test_existing_reconciliation_class_is_propagated_to_review_reason() -> None:
    candidate_id = "rc_current_" + "1" * 24
    result = taxonomy.build_review_taxonomy(
        [candidate_id], [_reconciliation(candidate_id, "ambiguous")],
    )
    assert result["conservation_valid"] is True
    assert result["items"] == [{
        "candidate_id": candidate_id,
        "reconciliation_class": "ambiguous",
        "review_reason": "reconciliation_ambiguous",
        "evidence": {
            "reconciliation_observation": "ambiguous",
            "reconciliation_decision_reusable": False,
            "reconciliation_counterpart_candidate_id": "rc_old_" + "1" * 24,
        },
    }]


def test_governed_uncovered_candidate_uses_rebaseline_reason_without_class_claim() -> None:
    candidate_id = "rc_current_" + "2" * 24
    result = taxonomy.build_review_taxonomy(
        [candidate_id], [_reconciliation(candidate_id, "equivalent")],
        _rebaseline(candidate_id),
    )
    assert result["conservation_valid"] is True
    assert result["items"][0]["reconciliation_class"] is None
    assert result["items"][0]["review_reason"] == "rebaseline_uncovered"
    assert result["items"][0]["evidence"]["reconciliation_observation"] == "equivalent"


def test_missing_reason_blocks_taxonomy_conservation() -> None:
    candidate_id = "rc_current_" + "3" * 24
    result = taxonomy.build_review_taxonomy([candidate_id], [], None)
    assert result["conservation_valid"] is False
    assert result["missing_review_reason_candidate_ids"] == [candidate_id]


def test_unsupported_reconciliation_class_blocks_taxonomy_conservation() -> None:
    candidate_id = "rc_current_" + "4" * 24
    result = taxonomy.build_review_taxonomy(
        [candidate_id], [_reconciliation(candidate_id, "invented")],
    )
    assert result["conservation_valid"] is False
    assert result["unsupported_review_reason_candidate_ids"] == [candidate_id]


def test_published_taxonomy_rejects_inconsistent_reason_and_duplicate() -> None:
    candidate_id = "rc_current_" + "5" * 24
    result = taxonomy.validate_published_review_taxonomy(
        [candidate_id], [{
            "candidate_id": candidate_id,
            "reconciliation_class": "ambiguous",
            "review_reason": "reconciliation_new",
        }, {
            "candidate_id": candidate_id,
            "reconciliation_class": "ambiguous",
            "review_reason": "reconciliation_ambiguous",
        }],
    )
    assert result["valid"] is False
    assert result["duplicate_candidate_ids"] == [candidate_id]
    assert result["inconsistent_candidate_ids"] == [candidate_id]
