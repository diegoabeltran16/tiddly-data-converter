from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "src" / "python_scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import admit_session_candidates as asc  # noqa: E402


def _entry(record_id: str, source_path: str, text: str, line: int = 1) -> asc.CandidateEntry:
    record = {
        "id": record_id,
        "key": record_id,
        "title": record_id,
        "canonical_slug": record_id,
        "text": text,
        "source_fields": {
            "source_path": source_path,
            "session_origin": "m04-s0183-artifact",
            "artifact_family": "contrato_de_sesion",
        },
    }
    return asc.CandidateEntry(
        line_no=line,
        record=record,
        serialized=asc._canonical_json(record),
        source_path=source_path,
        session_origin="m04-s0183-artifact",
        artifact_family="contrato_de_sesion",
    )


def _index(record: dict, source_path: str) -> asc.CanonIndex:
    canonical = asc.CanonRecord(
        record=record,
        serialized=asc._canonical_json(record),
        shard="tiddlers_1.jsonl",
        line_no=1,
    )
    return asc.CanonIndex(
        by_id={str(record["id"]): canonical},
        by_key={},
        by_slug={},
        by_source_path={source_path: canonical},
        by_session_family={},
        by_hash={},
        by_title={},
    )


def test_same_id_changed_content_is_replacement_even_if_path_changed() -> None:
    candidate = _entry("stable-id", "new/path.md.json", "new")
    current = {**candidate.record, "text": "old", "source_fields": {**candidate.record["source_fields"], "source_path": "old/path.md.json"}}
    eligible, _, rejected, _, stats = asc._classify_against_index(
        [candidate], _index(current, "old/path.md.json"), allow_replacements=True
    )
    assert rejected == []
    assert eligible[0].replacement is not None
    assert stats["replacement_by_same_id"] == 1


def test_same_source_path_different_id_is_drift_even_when_replacements_allowed() -> None:
    candidate = _entry("new-id", "same/path.md.json", "new")
    current = {**candidate.record, "id": "old-id", "key": "old-id", "title": "old-id", "canonical_slug": "old-id"}
    eligible, _, rejected, _, stats = asc._classify_against_index(
        [candidate], _index(current, "same/path.md.json"), allow_replacements=True
    )
    assert eligible == []
    assert rejected[0]["classification"] == "source_path_identity_drift"
    assert stats["source_path_identity_drift"] == 1


def test_duplicate_id_with_different_payload_is_blocking_conflict() -> None:
    first = _entry("duplicate-id", "first/path.md.json", "first", line=1)
    second = _entry("duplicate-id", "second/path.md.json", "second", line=2)
    eligible, _, rejected, _, stats = asc._classify_against_index([first, second], None)
    assert eligible == [first]
    assert rejected[0]["classification"] == "conflict_same_id_different_content"
    assert stats["conflict_same_id_different_content"] == 1
