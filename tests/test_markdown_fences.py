from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

import markdown_fence_validation as fences  # noqa: E402


def _scan(tmp_path: Path, content: str) -> dict:
    path = tmp_path / "sample.md"
    path.write_text(content, encoding="utf-8")
    return fences.scan_file(path, tmp_path)


def test_commonmark_fence_classifications(tmp_path: Path) -> None:
    exact = _scan(tmp_path, "```text\ncontent\n```\n")
    assert [item["classification"] for item in exact["occurrences"]] == [
        "opening_fence", "valid_exact_pair",
    ]

    longer = _scan(tmp_path, "```text\ncontent\n````\n")
    assert longer["defects"] == []
    assert longer["occurrences"][-1]["classification"] == "valid_longer_closer"


def test_outer_fence_preserves_literal_inner_fences(tmp_path: Path) -> None:
    result = _scan(tmp_path, "````markdown\n```text\nexample\n```\n````\n")
    assert result["defects"] == []
    assert result["occurrences"][-1]["classification"] == "intentional_outer_fence"


def test_short_mismatched_and_unclosed_fences_are_reported(tmp_path: Path) -> None:
    short = _scan(tmp_path, "````text\ncontent\n```\n")
    assert {item["classification"] for item in short["defects"]} == {
        "short_closer", "unclosed_fence",
    }

    mismatched = _scan(tmp_path, "```text\ncontent\n~~~\n")
    assert {item["classification"] for item in mismatched["defects"]} == {
        "mismatched_character", "unclosed_fence",
    }


def test_inventory_is_deterministic_and_empty_file_is_valid(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("No fences.\n", encoding="utf-8")
    first = fences.build_inventory(tmp_path, ("README.md",))
    second = fences.build_inventory(tmp_path, ("README.md",))
    assert first["summary"] == second["summary"]
    assert first["summary"]["fences_total"] == 0
    assert first["summary"]["defects_confirmed"] == 0


def test_report_manifest_records_manual_changes(tmp_path: Path) -> None:
    inventory = fences.build_inventory(tmp_path, ())
    fences.write_reports(inventory, tmp_path / "out", [{
        "path": "doc.md", "opening_line": 1, "defect": "unclosed_fence",
    }])
    report = (tmp_path / "out" / "changed-fences.json").read_text(encoding="utf-8")
    assert '"path": "doc.md"' in report


def test_primary_document_scope_has_no_confirmed_fence_defects() -> None:
    inventory = fences.build_inventory(REPO_ROOT)
    assert inventory["summary"]["files"] >= 1
    assert inventory["summary"]["defects_confirmed"] == 0
