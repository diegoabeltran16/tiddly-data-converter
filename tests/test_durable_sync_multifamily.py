"""Focused S0186-B coverage for family-first durable sync."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "src" / "python_scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import session_sync as ss  # noqa: E402
from admit_session_candidates import CanonIndex, CanonRecord, _canonical_json  # noqa: E402


def _empty_index() -> CanonIndex:
    return CanonIndex(by_id={}, by_key={}, by_slug={}, by_source_path={}, by_session_family={}, by_hash={}, by_title={})


def _normalizer(records, _work_dir):
    return [{**record, "id": f"current-{index}"} for index, record in enumerate(records)], object()


def _write_session(root: Path) -> None:
    path = root / "00_contratos" / "m04-s0186-fixture.md.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "title": "#### 🌀 Contrato de sesión 0186 = fixture",
                "type": "text/markdown",
                "created": "20260901000000000",
                "modified": "20260901000000000",
                "session_id": "m04-s0186",
                "module": "m04",
                "session": "S0186",
                "status": "delivered",
                "canonical_slug": "m04-s0186-contrato-fixture",
                "tags": ["sesion", "contrato", "m04", "s0186"],
                "text": "# Fixture\n\nContenido.",
            }
        ),
        encoding="utf-8",
    )


def _write_thematic(root: Path, slug: str = "diagnostico-tematico-0087-fixture") -> Path:
    path = root / "06_diagnoses" / "tema" / "diagnostico-tematico-0087-fixture.md.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "title": "#### 🌀 Diagnóstico temático 0087 = fixture",
                "type": "text/markdown",
                "created": "20260901000000000",
                "modified": "20260901000000000",
                "canonical_slug": slug,
                "tags": ["diagnostico-tematico", "DT087"],
                "text": "# DT087\n\nFixture durable.",
            }
        ),
        encoding="utf-8",
    )
    return path


def _scan(root: Path, out: Path, index: CanonIndex | None = None) -> dict:
    with (
        patch.object(ss, "_run_normalize", side_effect=_normalizer),
        patch.object(ss, "_load_canon_index", return_value=index or _empty_index()),
        patch.object(ss, "_canon_hash", return_value="sha256:fixture-canon"),
    ):
        return ss.scan_session_sync(root, REPO_ROOT / "data/out/local", out, run_id="unit-b")


def test_routes_before_schema_and_prepares_two_family_candidates(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    _write_session(sessions)
    _write_thematic(sessions)

    inventory = _scan(sessions, tmp_path / "out")

    routes = {item["family"]: item for item in inventory["family_decisions"]}
    assert routes["session_deliverable"]["schema_valid"] is True
    assert routes["thematic_diagnostic"]["schema_valid"] is True
    assert routes["thematic_diagnostic"]["canonical_compare"] == "MISSING"
    assert routes["thematic_diagnostic"]["candidate_status"] == "prepared_non_authoritative"
    assert inventory["candidate_count"] == 2


def test_same_is_noop_and_replacement_preserves_existing_reference(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    _write_thematic(sessions)
    first = _scan(sessions, tmp_path / "first")
    candidate = json.loads(Path(first["generated_candidate_file"]).read_text(encoding="utf-8").splitlines()[0])
    same = CanonRecord(record=candidate, serialized=_canonical_json(candidate), shard="tiddlers_001.jsonl", line_no=7)
    index = _empty_index()
    index.by_id[candidate["id"]] = same
    inventory = _scan(sessions, tmp_path / "same", index)
    decision = inventory["family_decisions"][0]
    assert decision["canonical_compare"] == "SAME"
    assert decision["candidate_status"] == "no_op"

    changed = {**candidate, "text": "changed"}
    index.by_id[candidate["id"]] = CanonRecord(record=changed, serialized=_canonical_json(changed), shard="tiddlers_001.jsonl", line_no=9)
    inventory = _scan(sessions, tmp_path / "replacement", index)
    assert inventory["family_decisions"][0]["canonical_compare"] == "REPLACEMENT"
    assert inventory["replacement_by_same_id"][0]["shard"] == "tiddlers_001.jsonl"


def test_conflict_and_unsupported_are_fail_closed_without_session_schema(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    _write_thematic(sessions)
    first = _scan(sessions, tmp_path / "first")
    candidate = json.loads(Path(first["generated_candidate_file"]).read_text(encoding="utf-8").splitlines()[0])
    conflicting = {**candidate, "id": "other-id"}
    index = _empty_index()
    index.by_title[candidate["title"]] = [
        CanonRecord(record=conflicting, serialized=_canonical_json(conflicting), shard="tiddlers_001.jsonl", line_no=3)
    ]
    inventory = _scan(sessions, tmp_path / "conflict", index)
    assert inventory["family_decisions"][0]["canonical_compare"] == "CONFLICT"

    unsupported = sessions / "notes" / "unknown.md.json"
    unsupported.parent.mkdir(parents=True)
    unsupported.write_text(json.dumps({"title": "Unknown", "text": "x"}), encoding="utf-8")
    inventory = _scan(sessions, tmp_path / "unsupported")
    unsupported_route = next(item for item in inventory["family_decisions"] if item["family"] == "other_or_unsupported")
    assert unsupported_route["canonical_compare"] == "UNRESOLVED"
    assert unsupported_route["candidate_status"] == "blocked"
