"""S0186 Unit D — quiescence (H-Q-01) and TMP lifecycle coverage.

H-Q-01 requires eight terms (Canon, relaciones, apply pendiente,
autorizaciones, receipts/rollback, auditoría, estado persistente, TMP) to be
reconstructible by owner before ``TDC_QUIESCENT`` can be asserted, each
classified ``CURRENTLY_PROVABLE`` / ``PARTIALLY_PROVABLE`` / ``NOT_PROVABLE`` /
``NOT_APPLICABLE``.  The contract's D gate additionally requires TMP
classification without deletion and a stable computation.

``quiescence_state.py`` (new in Unit D) implements no relational/admission
logic of its own for seven of the eight terms -- it only reads the outputs of
``relation_admission_state``, ``current_relational_authority``,
``relation_admission_gate`` and ``audit_relation_inventory``, all of which
already have their own test suites.  This file therefore does not re-test
those owners; it covers only what is new for D:

1. the TMP lifecycle classifier (no existing owner classified TMP/STAGING/
   INBOX before this unit), proven read-only on an isolated fixture tree;
2. that the full eight-term assembly is stable across repeated calls
   ("cálculo estable") both on an isolated minimal fixture and against the
   live local root;
3. that no mutating entrypoint (authorize/apply/admit/rollback-execution) is
   reachable from this module, as a static regression guard.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "src" / "python_scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import quiescence_state as qs  # noqa: E402


# ── classify_tmp_entry: pure function, table-driven ──────────────────────────

def test_classify_tmp_entry_covers_every_lifecycle_bucket() -> None:
    assert qs.classify_tmp_entry("s0186-impact", "S0186")["lifecycle"] == "ACTIVE_SESSION_TMP"
    assert qs.classify_tmp_entry("s0185-impact", "S0186")["lifecycle"] == "CLOSED_SESSION_TMP"
    assert qs.classify_tmp_entry("session_sync", "S0186")["lifecycle"] == "STAGING"
    assert qs.classify_tmp_entry("diagnostic_inventory", "S0186")["lifecycle"] == (
        "STAGING_CONTENT_ATTRIBUTABLE_NO_DEFAULT_CONSTANT"
    )
    orphan = qs.classify_tmp_entry("some-unreferenced-scratch-dir", "S0186")
    assert orphan["lifecycle"] == "NO_PERSISTENT_OWNER_FOUND_IN_CURRENT_SOURCE"
    assert orphan["owner"] is None


# ── classify_tmp_lifecycle: read-only on an isolated fixture ────────────────

def _build_tmp_fixture(root: Path) -> None:
    (root / "s0186-impact").mkdir(parents=True)
    (root / "s0186-impact" / "checkpoint.json").write_text("{}", encoding="utf-8")
    (root / "s0180-impact").mkdir(parents=True)
    (root / "session_sync").mkdir(parents=True)
    (root / "orphan-scratch").mkdir(parents=True)
    (root / "orphan-scratch" / "note.txt").write_text("x", encoding="utf-8")


def test_classify_tmp_lifecycle_creates_and_deletes_nothing(tmp_path: Path) -> None:
    fixture_root = tmp_path / "data" / "tmp"
    _build_tmp_fixture(fixture_root)

    before = sorted(str(p.relative_to(fixture_root)) for p in fixture_root.rglob("*"))
    report = qs.classify_tmp_lifecycle(fixture_root, active_session_id="S0186")
    after = sorted(str(p.relative_to(fixture_root)) for p in fixture_root.rglob("*"))

    assert before == after
    assert report["paths_created"] == 0
    assert report["paths_deleted"] == 0
    assert report["entry_count"] == 4

    by_path = {entry["path"].rsplit("/", 1)[-1]: entry for entry in report["entries"]}
    assert by_path["s0186-impact"]["lifecycle"] == "ACTIVE_SESSION_TMP"
    assert by_path["s0180-impact"]["lifecycle"] == "CLOSED_SESSION_TMP"
    assert by_path["session_sync"]["lifecycle"] == "STAGING"
    assert by_path["orphan-scratch"]["lifecycle"] == "NO_PERSISTENT_OWNER_FOUND_IN_CURRENT_SOURCE"
    assert report["counts_by_lifecycle"]["INBOX"] == 0


def test_classify_tmp_lifecycle_is_deterministic(tmp_path: Path) -> None:
    fixture_root = tmp_path / "data" / "tmp"
    _build_tmp_fixture(fixture_root)
    report_a = qs.classify_tmp_lifecycle(fixture_root, active_session_id="S0186")
    report_b = qs.classify_tmp_lifecycle(fixture_root, active_session_id="S0186")
    assert json.dumps(report_a, sort_keys=True) == json.dumps(report_b, sort_keys=True)


def test_classify_tmp_lifecycle_reports_missing_root_without_creating_it(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    report = qs.classify_tmp_lifecycle(missing, active_session_id="S0186")
    assert report.get("error") == "tmp_root_missing"
    assert not missing.exists()


# ── evaluate_quiescence: isolated minimal fixture (no relational state at all) ──

def test_evaluate_quiescence_on_isolated_fixture_reports_every_term(tmp_path: Path) -> None:
    local_root = tmp_path / "data" / "out" / "local"
    local_root.mkdir(parents=True)
    (local_root / "tiddlers_1.jsonl").write_text(
        json.dumps({"id": "a", "title": "a", "relations": []}) + "\n", encoding="utf-8",
    )
    tmp_root = tmp_path / "data" / "tmp"
    tmp_root.mkdir(parents=True)

    report = qs.evaluate_quiescence(
        local_root, tmp_root=tmp_root, active_session_id="S0186", checked_at="2026-09-01T00:00:00Z",
    )

    assert set(report["terms"]) == set(qs.QUIESCENCE_TERMS)
    for term, value in report["terms"].items():
        assert value["status"] in qs.TERM_STATUS_VOCABULARY, term
        assert value["owner"], term
    # Canon is reconstructible even for a single-shard fixture.
    assert report["terms"]["canon"]["status"] == "CURRENTLY_PROVABLE"
    assert report["terms"]["canon"]["evidence"]["records"] == 1


# ── evaluate_quiescence: stability against the live local root ──────────────

def test_evaluate_quiescence_is_stable_on_two_live_reads() -> None:
    """'Cálculo estable': two independent, fresh calls against the real
    repository state, with checked_at pinned, must be byte-identical."""
    fixed = "2026-09-01T00:00:00Z"
    report_a = qs.evaluate_quiescence(checked_at=fixed)
    report_b = qs.evaluate_quiescence(checked_at=fixed)
    assert json.dumps(report_a, sort_keys=True) == json.dumps(report_b, sort_keys=True)
    assert report_a["terms"]["estado_persistente"]["evidence"]["stable_on_immediate_replay"] is True


def test_evaluate_quiescence_pins_an_unprovided_replay_timestamp() -> None:
    """An operator invocation has no timestamp argument, but its immediate
    replay must not become unstable merely because ``checked_at`` is emitted."""
    report = qs.evaluate_quiescence()

    persistence = report["terms"]["estado_persistente"]
    assert persistence["status"] == "CURRENTLY_PROVABLE"
    assert persistence["evidence"]["checked_at_pinned"] is True
    assert persistence["evidence"]["caller_checked_at_pinned"] is False


def test_evaluate_quiescence_live_state_matches_canon_ground_truth() -> None:
    """Cross-check the reported Canon evidence against ground truth computed
    independently from the same material Canon this test run observes.

    S0187 Impacto Unidad B (R-B-06): shard count is discovered state, not a
    fixed historical invariant — a governed reshard (existing shard_canon
    capability) can legitimately change it, and a governed sanitation apply
    can legitimately change record count. This test verifies coherence
    between observation and reality, not a frozen snapshot."""
    report = qs.evaluate_quiescence(checked_at="2026-09-01T00:00:00Z")
    canon_evidence = report["terms"]["canon"]["evidence"]
    discovered_live_shard_count = len(list(qs.LOCAL_ROOT.glob("tiddlers_*.jsonl")))
    assert canon_evidence["shards"] == discovered_live_shard_count
    # NOTE: the records==3730 assertion this line used to sit beside was
    # already failing pre-existingly (live canon has grown since Unit D) and
    # is out of scope for R-B-06, which authorizes only the shard-count
    # assertion above; left untouched below to avoid silently absorbing an
    # unrelated pre-existing failure into this recalibration.
    assert canon_evidence["records"] == 3730


# ── static guard: no mutating entrypoint reachable from this module ─────────

_FORBIDDEN_IMPORTS_OR_CALLS = (
    "import admit_session_candidates",
    "admission_state.authorize",
    "admission_state.apply(",
    "current_authority.authorize",
    "current_authority.apply(",
    ".rollback(",
    ".reverse(",
)


def test_module_source_never_references_mutating_entrypoints() -> None:
    """Guards against a future edit silently wiring in a mutating call.

    Docstring citations of a script's *filename* (e.g. explaining that an
    orphaned TMP entry's naming convention is attributable to
    ``admit_session_candidates.py``) are fine; an actual ``import`` of it, or
    a call to any owner's authorize/apply/rollback/reverse entrypoint, is
    not -- Unit D is read-only by contract.
    """
    source = (SCRIPTS / "quiescence_state.py").read_text(encoding="utf-8")
    for forbidden in _FORBIDDEN_IMPORTS_OR_CALLS:
        assert forbidden not in source, forbidden
    # Only the read-only owners this unit is authorized to consume.
    for allowed_import in (
        "import relation_admission_gate",
        "import relation_admission_state",
        "import current_relational_authority",
        "import audit_relation_inventory",
    ):
        assert allowed_import in source
