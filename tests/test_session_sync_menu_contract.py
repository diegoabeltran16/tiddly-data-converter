from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "src" / "python_scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import operator_menu as menu  # noqa: E402


def _inventory() -> dict:
    return {
        "generated_candidate_file": None,
        "missing_by_id": [],
        "replaceable_same_id_different_content": [],
        "blocked_same_id_different_content": [],
        "invalid": [],
        "unsupported": [],
        "existing_by_id": [],
        "same_id_different_content": [],
        "source_canon_hash": "sha256:canon",
        "candidate_sha256": None,
        "selection": {
            "scope": "missing",
            "filter": {"type": "session_id", "value": "m04-s0183"},
        },
        "total_files_scanned": 0,
        "total_session_records": 0,
        "inventory_path": "inventory.json",
        "persistent_summary_path": "summary.json",
    }


def test_missing_scope_never_enables_replacements() -> None:
    assert menu.sync_admission_extra_args(_inventory()) == []
    replacement = _inventory()
    replacement["selection"]["scope"] = "replacement"
    assert menu.sync_admission_extra_args(replacement) == ["--allow-replacements"]


def test_menu_requires_scope_and_session_filter_before_scan(monkeypatch) -> None:
    answers = iter(["1", "1", "m04-s0183", "0"])
    observed: dict[str, object] = {}

    def fake_scan(**kwargs):
        observed.update(kwargs)
        return _inventory()

    monkeypatch.setattr(menu, "prompt", lambda _message: next(answers))
    monkeypatch.setattr(menu, "scan_session_sync", fake_scan)
    menu.option_session_sync(menu.MenuState())

    assert observed["scope"] == "missing"
    assert observed["filter_type"] == "session_id"
    assert observed["filter_value"] == "m04-s0183"
