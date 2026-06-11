"""Tests for S0139 historical relation type governance."""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "python_scripts"))

from build_historical_relation_type_decision_matrix import (  # noqa: E402
    MANDATORY_HISTORICAL_TYPES,
    alias_cycles,
    build_alias_rows,
    build_decisions,
    build_governance_bundle,
    build_migration_preview,
    scan_canon_relations,
    self_alias_violations,
    write_outputs,
)


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record(tid: str, title: str | None = None, relations: list[dict] | None = None) -> dict:
    return {
        "id": tid,
        "key": title or f"Tiddler {tid}",
        "title": title or f"Tiddler {tid}",
        "role_primary": "config",
        "relations": relations or [],
        "text": "Sample text.",
        "source_fields": {},
    }


def _write_fixture_canon(tmp_path: Path) -> Path:
    records = [
        _record(
            "src",
            "Source",
            [
                {"type": "usa", "target_id": "target-usa"},
                {"type": "requiere", "target_id": "target-requiere"},
                {"type": "parte_de", "target_id": "target-parte"},
                {"type": "define", "target_id": "target-define"},
                {"type": "child_of", "target_id": "target-child"},
                {"type": "references", "target_id": "target-references"},
                {"type": "mystery_rel", "target_id": "target-usa"},
            ],
        ),
        _record("target-usa", "Target usa"),
        _record("target-requiere", "Target requiere"),
        _record("target-parte", "Target parte"),
        _record("target-define", "Target define"),
        _record("target-child", "Target child"),
        _record("target-references", "Target references"),
    ]
    shard = tmp_path / "tiddlers_1.jsonl"
    shard.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
    return shard


def _bundle_from_tmp(tmp_path: Path) -> dict:
    _write_fixture_canon(tmp_path)
    return build_governance_bundle(str(tmp_path / "tiddlers_*.jsonl"), session="s0139")


def test_inventory_reads_canonical_relations_without_modifying_files(tmp_path: Path) -> None:
    shard = _write_fixture_canon(tmp_path)
    before = _hash(shard)

    inventory, _entries = scan_canon_relations(str(tmp_path / "tiddlers_*.jsonl"))

    assert _hash(shard) == before
    assert inventory["total_relations_seen"] == 7
    assert inventory["relation_type_counts"]["usa"] == 1
    assert inventory["target_resolution_summary"]["resolved"] == 7


def test_each_mandatory_historical_type_receives_a_decision(tmp_path: Path) -> None:
    bundle = _bundle_from_tmp(tmp_path)
    decisions = bundle["decisions"]["decisions_by_type"]

    for rel_type in MANDATORY_HISTORICAL_TYPES:
        assert rel_type in decisions
        assert decisions[rel_type]["decision_status"] in {
            "canonical_keep",
            "legacy_readonly",
            "legacy_alias_candidate",
            "canonical_equivalent",
            "deprecated_blocked",
            "structural_only",
            "requires_human_decision",
            "unknown_legacy",
        }


def test_child_of_is_not_classified_as_modern_semantic_relation(tmp_path: Path) -> None:
    bundle = _bundle_from_tmp(tmp_path)
    child = bundle["decisions"]["decisions_by_type"]["child_of"]

    assert child["decision_status"] == "structural_only"
    assert child["proposed_canonical_type"] == ""
    assert child["new_candidate_policy"] == "blocked_as_semantic_candidate"


def test_usa_cannot_be_migrated_automatically_without_alias_or_legacy_status(tmp_path: Path) -> None:
    bundle = _bundle_from_tmp(tmp_path)
    usa = bundle["decisions"]["decisions_by_type"]["usa"]

    assert usa["decision_status"] in {"legacy_alias_candidate", "legacy_readonly"}
    assert usa["alias_applied"] is False
    assert usa["migration_allowed_in_s0139"] is False
    assert usa["applied_to_canon"] is False


def test_requiere_declares_direction_preservation(tmp_path: Path) -> None:
    bundle = _bundle_from_tmp(tmp_path)
    requiere = bundle["decisions"]["decisions_by_type"]["requiere"]

    assert requiere["proposed_canonical_type"] == "depende_de"
    assert requiere["direction_preserved"] in {"true", "false", "requires_review"}
    assert requiere["requires_human_review"] is True


def test_alias_map_contains_no_cycles(tmp_path: Path) -> None:
    bundle = _bundle_from_tmp(tmp_path)
    rows = build_alias_rows(bundle["decisions"])

    assert alias_cycles(rows) == []


def test_alias_map_has_no_self_alias_except_canonical_keep(tmp_path: Path) -> None:
    bundle = _bundle_from_tmp(tmp_path)
    rows = build_alias_rows(bundle["decisions"])

    assert self_alias_violations(rows) == []


def test_unknown_type_remains_unknown_or_requires_human_decision(tmp_path: Path) -> None:
    bundle = _bundle_from_tmp(tmp_path)
    mystery = bundle["decisions"]["decisions_by_type"]["mystery_rel"]

    assert mystery["decision_status"] in {"unknown_legacy", "requires_human_decision"}
    assert mystery["requires_human_review"] is True


def test_migration_preview_declares_no_canon_application(tmp_path: Path) -> None:
    inventory, _entries = scan_canon_relations(str(_write_fixture_canon(tmp_path).parent / "tiddlers_*.jsonl"))
    decisions = build_decisions(inventory)
    preview = build_migration_preview(inventory, decisions)

    assert preview["dry_run"] is True
    assert preview["applied_to_canon"] is False
    assert preview["canon_modified"] is False
    assert preview["migration_allowed_in_s0139"] is False


def test_writing_reports_does_not_change_tiddlers_jsonl(tmp_path: Path) -> None:
    shard = _write_fixture_canon(tmp_path)
    before = _hash(shard)
    bundle = build_governance_bundle(str(tmp_path / "tiddlers_*.jsonl"), session="s0139")

    written = write_outputs(
        tmp_path / "out",
        "s0139",
        bundle["inventory"],
        bundle["decisions"],
        bundle["alias_rows"],
        bundle["migration_preview"],
    )

    assert _hash(shard) == before
    assert "inventory" in written
    with (tmp_path / "out" / "s0139_alias_map_proposal.csv").open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert rows
