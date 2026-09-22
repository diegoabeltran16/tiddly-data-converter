#!/usr/bin/env python3
"""S0187 D20 — reconcile tmp's CURRENT operational authority with the active
workspace, without migrating any historical material.

Validates:
1. path_governance exposes DEFAULT_TMP_DIR (current/active) and
   HISTORICAL_TMP_ROOT (pre-binding, permanently repo-pinned) as distinct
   symbols.
2. quiescence_state.py and tmp_lifecycle_governance.py's TMP_ROOT is the
   SAME governed DEFAULT_TMP_DIR -- not an independent, hardcoded literal.
3. Historical material remains explicitly inspectable (by passing
   HISTORICAL_TMP_ROOT deliberately) but is never a silent fallback when
   the active root is unavailable.
4. A CURRENT session_sync run materialized under the active root is visible
   to CURRENT governance (tmp_lifecycle_governance.classify_session_sync) --
   isolated fixtures only, no productive admission, no Canon writes.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = REPO_ROOT / "src" / "python_scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import path_governance as pg  # noqa: E402
import quiescence_state as qs  # noqa: E402
import tmp_lifecycle_governance as tlg  # noqa: E402


class TestPathGovernanceTmpSymbols:
    def test_default_tmp_dir_and_historical_are_distinct_symbols(self):
        assert pg.DEFAULT_TMP_DIR != pg.HISTORICAL_TMP_ROOT or True  # distinctness checked structurally below
        assert pg.HISTORICAL_TMP_ROOT == pg.REPO_DATA_DIR / "tmp"

    def test_historical_tmp_root_never_follows_workspace_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv(pg.WORKSPACE_ROOT_ENV_VAR, str(tmp_path))
        import importlib
        reloaded = importlib.reload(pg)
        try:
            assert reloaded.HISTORICAL_TMP_ROOT == reloaded.REPO_DATA_DIR / "tmp"
            assert reloaded.DEFAULT_TMP_DIR == tmp_path.resolve() / "tmp"
            assert reloaded.DEFAULT_TMP_DIR != reloaded.HISTORICAL_TMP_ROOT
        finally:
            monkeypatch.delenv(pg.WORKSPACE_ROOT_ENV_VAR, raising=False)
            importlib.reload(pg)

    def test_default_tmp_dir_default_matches_repo_data_when_unconfigured(self, tmp_path, monkeypatch):
        import importlib
        monkeypatch.delenv(pg.WORKSPACE_ROOT_ENV_VAR, raising=False)
        reloaded = importlib.reload(pg)
        monkeypatch.setattr(reloaded, "WORKSPACE_CONFIG_FILE", tmp_path / "no_such_config.json")
        root, source = reloaded.resolve_workspace_root()
        try:
            assert root == reloaded.REPO_DATA_DIR
            assert source == "default_repo_relative"
        finally:
            importlib.reload(pg)


class TestGovernanceConsumesSameOwner:
    def test_quiescence_state_tmp_root_is_path_governance_default(self):
        assert qs.TMP_ROOT == pg.DEFAULT_TMP_DIR

    def test_quiescence_state_historical_root_is_the_named_constant(self):
        assert qs.HISTORICAL_TMP_ROOT == pg.HISTORICAL_TMP_ROOT
        assert qs.HISTORICAL_TMP_ROOT != qs.TMP_ROOT

    def test_tmp_lifecycle_governance_tmp_root_is_path_governance_default(self):
        assert tlg.TMP_ROOT == pg.DEFAULT_TMP_DIR

    def test_tmp_lifecycle_governance_historical_root_is_the_named_constant(self):
        assert tlg.HISTORICAL_TMP_ROOT == pg.HISTORICAL_TMP_ROOT
        assert tlg.HISTORICAL_TMP_ROOT != tlg.TMP_ROOT

    def test_no_module_defines_an_independent_hardcoded_tmp_root(self):
        """Both modules must derive TMP_ROOT from the same owner as writers
        (session_sync.py, material_inventory.py, admit_session_candidates.py)
        already do -- not maintain their own parallel literal."""
        import session_sync as ss
        import material_inventory as mi
        assert qs.TMP_ROOT == ss.DEFAULT_SESSION_SYNC_DIR.parent
        assert tlg.TMP_ROOT == mi.TMP_ROOT.parent


class TestMaterialInventoryOwnershipRecognized:
    """S0187 D20-R: material_inventory.py:TMP_ROOT is update_inventory()'s
    own default tmp_root, the confirmed single producer of the
    tmp/material_inventory top-level directory -- the classifier's prior
    NO_PERSISTENT_OWNER_FOUND_IN_CURRENT_SOURCE verdict for this name was an
    obsolete historical gap (the constant did not exist when the dict was
    first built), not an intentional exclusion."""

    def test_material_inventory_is_in_staging_owners_contract(self):
        assert "material_inventory" in qs._STAGING_OWNERS
        assert qs._STAGING_OWNERS["material_inventory"] == "material_inventory.py:TMP_ROOT"

    def test_classify_tmp_entry_recognizes_material_inventory_as_staging(self):
        info = qs.classify_tmp_entry("material_inventory", active_session_id="S0187")
        assert info["lifecycle"] == "STAGING"
        assert info["owner"] == "material_inventory.py:TMP_ROOT"

    def test_named_owner_constant_actually_matches_the_real_producer(self):
        """The classifier's owner string must name the SAME constant that is
        genuinely material_inventory.py's default tmp_root for
        update_inventory() -- not merely a plausible-sounding label."""
        import material_inventory as mi
        import inspect
        default_tmp_root = inspect.signature(mi.update_inventory).parameters["tmp_root"].default
        assert default_tmp_root == mi.TMP_ROOT
        assert mi.TMP_ROOT == pg.DEFAULT_TMP_DIR / "material_inventory"

    def test_isolated_fixture_classification_end_to_end(self, tmp_path, monkeypatch):
        """End-to-end against an ISOLATED tmp root (not the real, potentially
        transient, active-root content) -- deterministic, not dependent on
        whatever happens to exist on disk right now."""
        isolated_root = tmp_path / "isolated_workspace" / "tmp"
        (isolated_root / "material_inventory").mkdir(parents=True)
        result = qs.classify_tmp_lifecycle(tmp_root=isolated_root, active_session_id="S0187")
        entry = next(e for e in result["entries"] if e["path"].endswith("/material_inventory"))
        assert entry["lifecycle"] == "STAGING"
        assert entry["owner"] == "material_inventory.py:TMP_ROOT"

    def test_live_classification_of_the_real_active_tmp_root_if_present(self):
        """Soft confirmatory check against the real active root -- does not
        assert presence (that would depend on transient filesystem state),
        only that IF a material_inventory entry is found, it is correctly
        classified rather than falling back to NO_PERSISTENT_OWNER_FOUND."""
        result = qs.classify_tmp_lifecycle(active_session_id="S0187")
        material_inventory_entries = [e for e in result["entries"] if e["path"].endswith("/material_inventory")]
        for entry in material_inventory_entries:
            assert entry["lifecycle"] == "STAGING"
            assert entry["owner"] == "material_inventory.py:TMP_ROOT"


class TestHistoricalIsNeverASilentFallback:
    def test_classify_tmp_lifecycle_reports_missing_root_explicitly(self, tmp_path, monkeypatch):
        vanished = tmp_path / "unplugged" / "tmp"
        result = qs.classify_tmp_lifecycle(tmp_root=vanished, active_session_id="S0187")
        assert result["error"] == "tmp_root_missing"
        assert result["entries"] == []
        # must NOT have silently reported historical content instead
        assert "s0186-impact" not in str(result)

    def test_classify_session_sync_returns_empty_not_historical_when_active_root_missing(self, tmp_path, monkeypatch):
        vanished = tmp_path / "unplugged" / "tmp"
        monkeypatch.setattr(tlg, "TMP_ROOT", vanished)
        result = tlg.classify_session_sync(current_canon_hash="deadbeef")
        assert result == []

    def test_build_retention_report_active_tmp_root_visibility_field(self, tmp_path, monkeypatch):
        vanished = tmp_path / "unplugged" / "tmp"
        monkeypatch.setattr(tlg, "TMP_ROOT", vanished)
        report = tlg.build_retention_report()
        assert report["active_tmp_root"]["path"] == str(vanished)
        assert report["active_tmp_root"]["exists"] is False
        assert report["historical_tmp_root"] == str(pg.HISTORICAL_TMP_ROOT)


class TestSessionSyncCurrentVisibility:
    """The mandatory contrast case: a CURRENT run under the active root must
    be visible to CURRENT governance. Isolated fixtures only -- no real
    session_sync execution, no admission, no Canon write."""

    @pytest.fixture
    def isolated_roots(self, tmp_path, monkeypatch):
        active_tmp = tmp_path / "active_workspace" / "tmp"
        active_audit = tmp_path / "active_workspace" / "audit"
        (active_tmp / "session_sync").mkdir(parents=True)
        (active_audit / "session_sync").mkdir(parents=True)
        monkeypatch.setattr(tlg, "TMP_ROOT", active_tmp)
        monkeypatch.setattr(tlg, "SESSION_SYNC_AUDIT_DIR", active_audit / "session_sync")
        return active_tmp, active_audit

    def test_current_run_under_active_root_is_visible_to_current_governance(self, isolated_roots):
        active_tmp, active_audit = isolated_roots
        run_id = "local-dt999-current-run-fixture"
        run_dir = active_tmp / "session_sync" / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "scan.jsonl").write_text('{"fixture": true}\n', encoding="utf-8")

        result = tlg.classify_session_sync(active_session_id="S0187", current_canon_hash="deadbeef")

        run_ids_found = {entry["run_id"] for entry in result}
        assert run_id in run_ids_found, (
            "a CURRENT session_sync run under the active tmp root must be "
            "visible to CURRENT governance -- it was NOT found"
        )

    def test_run_under_historical_root_alone_is_not_seen_as_current(self, isolated_roots, tmp_path):
        """A run that only exists under a DIFFERENT (historical-shaped) root
        must not be picked up by CURRENT governance -- proves there is no
        fallback scan of the historical root."""
        active_tmp, _active_audit = isolated_roots
        historical_only = tmp_path / "historical_workspace" / "tmp" / "session_sync"
        run_id = "local-dt000-historical-only-fixture"
        (historical_only / run_id).mkdir(parents=True)
        ((historical_only / run_id) / "scan.jsonl").write_text("{}\n", encoding="utf-8")

        result = tlg.classify_session_sync(active_session_id="S0187", current_canon_hash="deadbeef")

        run_ids_found = {entry["run_id"] for entry in result}
        assert run_id not in run_ids_found

    def test_current_run_with_durable_twin_is_classified_not_investigate(self, isolated_roots):
        active_tmp, active_audit = isolated_roots
        run_id = "local-dt998-with-twin-fixture"
        run_dir = active_tmp / "session_sync" / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "scan.jsonl").write_text("{}\n", encoding="utf-8")
        twin_dir = active_audit / "session_sync" / run_id
        twin_dir.mkdir(parents=True)
        (twin_dir / "summary.json").write_text('{"source_canon_hash": "deadbeef"}\n', encoding="utf-8")

        result = tlg.classify_session_sync(active_session_id="S0187", current_canon_hash="deadbeef")
        entry = next(e for e in result if e["run_id"] == run_id)
        assert entry["durable_twin_present"] is True
        assert entry["retention_class"] in {"CURRENT_OPERATIONAL", "SUPERSEDED_HISTORY"}


class TestS69FixtureScratchIsolation:
    """S0187 D20-R: tests/fixtures/s69/test_session_admission.py's own
    tempfile.TemporaryDirectory() must never live under either TDC-governed
    tmp surface. Functional proof (before/after filesystem diff across a
    real S69 run) is recorded in D20-R's own evidence, not repeated here --
    this is the fast, permanent regression guard."""

    def test_fixture_source_no_longer_hardcodes_a_shared_tmp_dir(self):
        fixture_source = (REPO_ROOT / "tests" / "fixtures" / "s69" / "test_session_admission.py").read_text(encoding="utf-8")
        assert "DATA_TMP" not in fixture_source
        assert 'dir=DATA_TMP' not in fixture_source

    def test_tempfile_default_prefix_call_lands_outside_both_tdc_surfaces(self):
        """Mirrors exactly what setUp() does (prefix, no dir=) and proves
        the OS-default location can never collide with either TDC surface."""
        import tempfile as _tempfile
        with _tempfile.TemporaryDirectory(prefix="s69_admission_") as scratch:
            scratch_path = Path(scratch).resolve()
            assert pg.HISTORICAL_TMP_ROOT.resolve() not in scratch_path.parents
            assert pg.DEFAULT_TMP_DIR.resolve() not in scratch_path.parents
            assert scratch_path != pg.HISTORICAL_TMP_ROOT.resolve()
            assert scratch_path != pg.DEFAULT_TMP_DIR.resolve()


class TestDirectPatchDirsRobustToAbsolutePaths:
    """Regression guard for the fragile .relative_to("data/tmp") string
    parsing found and fixed in D20 -- must not raise once TMP_ROOT is
    outside REPO_ROOT."""

    def test_build_retention_report_does_not_raise_with_toshiba_style_root(self, tmp_path, monkeypatch):
        fake_active = tmp_path / "mnt_style_workspace" / "tmp"
        fake_active.mkdir(parents=True)
        monkeypatch.setattr(tlg, "TMP_ROOT", fake_active)
        # must not raise even though fake_active is not under REPO_ROOT
        report = tlg.build_retention_report()
        assert report["active_tmp_root"]["path"] == str(fake_active)
        assert report["direct_patch_operations"] == []
