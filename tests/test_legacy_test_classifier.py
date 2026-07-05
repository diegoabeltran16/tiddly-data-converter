"""S0150 tests for legacy pytest failure classification."""

from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

import legacy_test_classifier as classifier  # noqa: E402


def test_classifier_identifies_obsolete_baseline_freezes(tmp_path: Path) -> None:
    log = tmp_path / "pytest.log"
    log.write_text(
        "\n".join(
            [
                "FAILED tests/test_classification_characterization.py::TestRoleDistributionFreeze::test_total_ai_record_count - AssertionError: assert 1597 == 1424",
                "FAILED tests/test_derive_layers_characterization.py::TestDeriveCountInvariants::test_canon_record_count - AssertionError: Canon count mismatch",
                "2 failed, 1514 passed, 1 skipped in 1.00s",
            ]
        ),
        encoding="utf-8",
    )

    payload = classifier.classify_pytest_log(pytest_log=log, out_dir=tmp_path / "out", session="S0150")

    assert payload["summary"]["failed"] == 2
    assert len(payload["failures"]) == 2
    assert all("baseline_freeze_obsolete" in failure["classification"] for failure in payload["failures"])
    assert (tmp_path / "out" / "s0150_legacy_test_classification.json").exists()
    assert (tmp_path / "out" / "s0150_legacy_test_classification.md").exists()


def test_classifier_does_not_allow_removing_protected_tests_without_review(tmp_path: Path) -> None:
    log = tmp_path / "pytest.log"
    log.write_text(
        "\n".join(
            [
                "FAILED tests/test_derive_layers_characterization.py::TestCanonImmutability::test_canon_sha256_stable - AssertionError: Canon hash mismatch",
                "FAILED tests/test_relation_human_review_gate.py::test_human_review - AssertionError: human review failed",
                "2 failed, 10 passed in 1.00s",
            ]
        ),
        encoding="utf-8",
    )

    payload = classifier.classify_pytest_log(pytest_log=log, out_dir=tmp_path / "out", session="S0150")

    assert payload["critical_test_removal_permitted"] is False
    assert all(failure["removal_allowed"] is False for failure in payload["failures"])
    assert all("requires_human_review" in failure["classification"] for failure in payload["failures"])


def test_classifier_outputs_valid_json(tmp_path: Path) -> None:
    log = tmp_path / "pytest.log"
    log.write_text("1 passed in 0.01s\n", encoding="utf-8")

    classifier.classify_pytest_log(pytest_log=log, out_dir=tmp_path / "out", session="S0150")
    payload = json.loads((tmp_path / "out" / "s0150_legacy_test_classification.json").read_text(encoding="utf-8"))

    assert payload["session"] == "S0150"
    assert payload["failures"] == []
    assert payload["tests_removed"] == 0
