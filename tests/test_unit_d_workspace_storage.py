#!/usr/bin/env python3
"""S0187 Unit D — workspace/storage path owner, config boundary, and gated
migration preview/apply.

Validates:
1. Default (no override) resolution is byte-identical to the pre-D4 behavior.
2. Runtime env override (TDC_WORKSPACE_ROOT) takes precedence and is never
   persisted.
3. Persisted config override (.tdc/workspace_storage.json) is honored and
   contains no secret-looking fields.
4. data/in stays pinned to the repo checkout regardless of workspace-root
   override (Gate D-H2 / explicit out-of-scope material); data/refs instead
   follows WORKSPACE_ROOT since S0187 D22 (REFS != CANON, REFS != CORE
   RUNTIME STATE, but REFS is workspace-owned, not repo-owned).
5. validate_location() fails closed on a read-only mount.
6. preview_migration() never touches the filesystem beyond reading, and
   correctly excludes in/tmp/out-remote (repo-pinned or transient) while
   including refs alongside out/local in the migration payload.
7. apply_migration() never performs a write and always refuses/blocks.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = REPO_ROOT / "src" / "python_scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import path_governance as pg  # noqa: E402
import workspace_storage_ops as wso  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_report_paths(monkeypatch, tmp_path):
    """workspace_storage_ops writes latest-* evidence reports to fixed,
    real, module-level paths under the repo's data/out/local/audit/
    regardless of what source/target a test passes in. Left unpatched,
    every test in this module would pollute real Unit D evidence with
    fake tmp_path content (discovered live: an earlier version of this
    file did exactly that -- see D11 pre-flight evidence). Redirect all
    report globals into this test's own tmp_path instead."""
    reports_dir = tmp_path / "_isolated_reports"
    monkeypatch.setattr(wso, "REPORTS_DIR", reports_dir)
    monkeypatch.setattr(wso, "CHECKPOINT_REPORT", reports_dir / "latest_checkpoint.json")
    monkeypatch.setattr(wso, "PREVIEW_REPORT", reports_dir / "latest_preview.json")
    monkeypatch.setattr(wso, "MIGRATION_REPORT", reports_dir / "latest_migration_report.json")
    monkeypatch.setattr(wso, "PRE_COPY_MANIFEST_REPORT", reports_dir / "latest_pre_copy_manifest.json")
    monkeypatch.setattr(wso, "COPY_RECEIPT_REPORT", reports_dir / "latest_copy_receipt.json")
    monkeypatch.setattr(wso, "VERIFY_REPORT", reports_dir / "latest_verify_result.json")


@pytest.fixture
def reloaded_path_governance(monkeypatch):
    """Reload path_governance under a controlled environment, then restore it."""
    def _reload():
        return importlib.reload(pg)

    yield _reload
    monkeypatch.delenv(pg.WORKSPACE_ROOT_ENV_VAR, raising=False)
    importlib.reload(pg)


class TestDefaultBackwardCompatibility:
    """Tests the DEFAULT (no override) resolution path in isolation from
    whatever real .tdc/workspace_storage.json this checkout may currently
    have -- this repo now has a real persisted cutover config (S0187 Unit D
    D-H4) pointing at Toshiba, so these tests must not read the module-level
    `pg` globals directly; they reload path_governance with the config file
    path monkeypatched to a nonexistent location to test the documented
    default behavior deterministically, regardless of this machine's actual
    current configuration."""

    @pytest.fixture
    def isolated_default_pg(self, monkeypatch, tmp_path):
        monkeypatch.delenv(pg.WORKSPACE_ROOT_ENV_VAR, raising=False)
        reloaded = importlib.reload(pg)
        monkeypatch.setattr(reloaded, "WORKSPACE_CONFIG_FILE", tmp_path / "no_such_config.json")
        root, source = reloaded.resolve_workspace_root()
        yield reloaded, root, source
        importlib.reload(pg)

    def test_default_workspace_root_is_repo_data(self, isolated_default_pg):
        _reloaded, root, source = isolated_default_pg
        assert root == REPO_ROOT / "data"
        assert source == "default_repo_relative"

    def test_default_canon_dir_unchanged(self, isolated_default_pg):
        reloaded, root, _source = isolated_default_pg
        assert root / "out" / "local" == REPO_ROOT / "data" / "out" / "local"

    def test_default_input_html_unchanged(self):
        # data/in is always repo-pinned regardless of any config -- safe to
        # read from the real module without isolation.
        assert pg.DEFAULT_INPUT_HTML == REPO_ROOT / "data" / "in" / "tiddly-data-converter (Saved).html"

    def test_default_sessions_dir_unchanged(self, isolated_default_pg):
        reloaded, root, _source = isolated_default_pg
        assert root / "out" / "local" / "sessions" == REPO_ROOT / "data" / "out" / "local" / "sessions"


class TestRuntimeOverride:
    def test_env_override_takes_precedence(self, tmp_path, monkeypatch, reloaded_path_governance):
        monkeypatch.setenv(pg.WORKSPACE_ROOT_ENV_VAR, str(tmp_path))
        reloaded = reloaded_path_governance()
        assert reloaded.WORKSPACE_ROOT == tmp_path.resolve()
        assert reloaded.WORKSPACE_ROOT_SOURCE == "runtime_override_env"
        assert reloaded.DEFAULT_CANON_DIR == tmp_path.resolve() / "out" / "local"

    def test_env_override_is_never_persisted(self, tmp_path, monkeypatch, reloaded_path_governance):
        monkeypatch.setenv(pg.WORKSPACE_ROOT_ENV_VAR, str(tmp_path))
        reloaded_path_governance()
        assert not pg.WORKSPACE_CONFIG_FILE.exists() or "runtime_override_env" not in (
            json.loads(pg.WORKSPACE_CONFIG_FILE.read_text()) if pg.WORKSPACE_CONFIG_FILE.exists() else {}
        )

    def test_in_stays_pinned_but_refs_follows_override(self, tmp_path, monkeypatch, reloaded_path_governance):
        monkeypatch.setenv(pg.WORKSPACE_ROOT_ENV_VAR, str(tmp_path))
        reloaded = reloaded_path_governance()
        assert reloaded.DEFAULT_INPUT_HTML == REPO_ROOT / "data" / "in" / "tiddly-data-converter (Saved).html"
        # S0187 D22: refs was reclassified as workspace-owned reference
        # material, not repo-side input -- it now follows WORKSPACE_ROOT
        # exactly like out/ and tmp/, so an override moves it too.
        assert reloaded.DEFAULT_REFS_DIR == tmp_path.resolve() / "refs"


class TestPersistedConfig:
    def test_save_and_load_roundtrip(self, tmp_path, monkeypatch, reloaded_path_governance):
        fake_config = tmp_path / "workspace_storage.json"
        monkeypatch.setattr(pg, "WORKSPACE_CONFIG_FILE", fake_config)
        target = tmp_path / "elsewhere"
        pg.save_workspace_storage_config(target)
        loaded = pg.load_workspace_storage_config()
        assert loaded["workspace_root"] == str(target.resolve())

    def test_persisted_config_has_no_secret_fields(self, tmp_path, monkeypatch):
        fake_config = tmp_path / "workspace_storage.json"
        monkeypatch.setattr(pg, "WORKSPACE_CONFIG_FILE", fake_config)
        pg.save_workspace_storage_config(tmp_path / "elsewhere")
        payload = json.loads(fake_config.read_text())
        forbidden = {"password", "token", "secret", "credential", "refresh_token", "client_id", "key"}
        for field_name in payload:
            assert not any(term in field_name.lower() for term in forbidden), (
                f"config field {field_name!r} looks secret-shaped"
            )

    def test_persisted_config_overrides_default_but_not_env(self, tmp_path, monkeypatch, reloaded_path_governance):
        fake_config = tmp_path / "workspace_storage.json"
        target = tmp_path / "configured_root"
        monkeypatch.setattr(pg, "WORKSPACE_CONFIG_FILE", fake_config)
        pg.save_workspace_storage_config(target)
        reloaded = reloaded_path_governance()
        # reload re-binds WORKSPACE_CONFIG_FILE to the real module-level default,
        # so patch it again post-reload and re-resolve directly.
        monkeypatch.setattr(reloaded, "WORKSPACE_CONFIG_FILE", fake_config)
        root, source = reloaded.resolve_workspace_root()
        assert root == target.resolve()
        assert source == "persisted_config"


class TestValidateLocation:
    def test_writable_tmp_dir_is_ok(self, tmp_path):
        result = wso.validate_location(tmp_path)
        assert result["ok"] is True
        assert result["read_only_mount"] is False

    def test_fails_closed_on_readonly_mount(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            wso,
            "describe_mount",
            lambda path: {"device": "/dev/fake", "mountpoint": str(tmp_path), "fstype": "ext4", "options": ["ro", "relatime"]},
        )
        result = wso.validate_location(tmp_path)
        assert result["ok"] is False
        assert result["read_only_mount"] is True
        assert any("solo lectura" in w for w in result["warnings"])

    def test_nonexistent_parent_still_probed(self, tmp_path):
        candidate = tmp_path / "does" / "not" / "exist"
        result = wso.validate_location(candidate)
        assert result["exists"] is False
        assert isinstance(result["free_bytes"], int)


class TestPreviewMigration:
    def test_preview_migrates_out_local_and_refs_excludes_in_tmp_remote(self):
        preview = wso.preview_migration("/tmp/nonexistent-target-for-preview-test")
        migrate_labels = " ".join(preview["will_migrate"].keys())
        assert list(preview["will_migrate"].keys())[0].startswith("out/local")
        # S0187 D22: refs now follows WORKSPACE_ROOT, so a future migration
        # of the workspace carries it along with out/local.
        assert "refs/" in migrate_labels
        not_migrate_labels = " ".join(preview["will_not_migrate"].keys())
        assert "out/remote" in not_migrate_labels
        assert "in/" in not_migrate_labels
        assert "refs/" not in not_migrate_labels
        assert "tmp/" in not_migrate_labels
        assert "secrets" in not_migrate_labels

    def test_preview_never_mutates_source(self, tmp_path):
        before = wso.checkpoint_source()["canon"]["concat_sha256"]
        wso.preview_migration(tmp_path / "some-target")
        after = wso.checkpoint_source()["canon"]["concat_sha256"]
        assert before == after

    def test_preview_reports_copy_verify_cutover_order(self):
        preview = wso.preview_migration("/tmp/nonexistent-target-for-preview-test")
        assert preview["migration_order"] == "COPY -> VERIFY -> CUTOVER (never MOVE -> HOPE)"


class TestApplyMigrationAlwaysGated:
    def test_refuses_on_readonly_target(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            wso,
            "describe_mount",
            lambda path: {"device": "/dev/fake", "mountpoint": str(tmp_path), "fstype": "ext4", "options": ["ro"]},
        )
        report = wso.apply_migration(tmp_path)
        assert report["status"] == "REFUSED"

    def test_blocks_even_when_target_is_writable(self, tmp_path):
        report = wso.apply_migration(tmp_path)
        assert report["status"] == "BLOCKED_PENDING_HUMAN_GATE"

    def test_never_creates_files_under_target(self, tmp_path):
        target = tmp_path / "would-be-workspace"
        wso.apply_migration(target)
        assert not target.exists()


class TestConfiguredStorageUnavailableFailsClosed:
    """EXPLICIT CONFIGURATION FAILURE != PERMISSION TO FALL BACK. A persisted
    config pointing at a now-unreachable root must raise, never silently
    resolve to an empty/zero-shard Canon and never silently retry against
    REPO_DATA_DIR -- that would be split-brain storage. Fully isolated:
    never touches this machine's real .tdc/workspace_storage.json."""

    @pytest.fixture
    def unavailable_root_pg(self, monkeypatch, tmp_path):
        monkeypatch.delenv(pg.WORKSPACE_ROOT_ENV_VAR, raising=False)
        reloaded = importlib.reload(pg)
        fake_config = tmp_path / "workspace_storage.json"
        monkeypatch.setattr(reloaded, "WORKSPACE_CONFIG_FILE", fake_config)
        vanished_root = tmp_path / "unplugged_drive" / "tdc-workspace"
        reloaded.save_workspace_storage_config(vanished_root)
        # vanished_root is deliberately never created -- simulates an
        # unmounted/unavailable external drive.
        yield reloaded, vanished_root
        importlib.reload(pg)

    def test_resolve_workspace_root_still_returns_the_configured_path(self, unavailable_root_pg):
        """Resolution itself is not an existence check -- it must return
        exactly what was configured, not silently substitute the default."""
        reloaded, vanished_root = unavailable_root_pg
        root, source = reloaded.resolve_workspace_root()
        assert root == vanished_root.resolve()
        assert source == "persisted_config"
        assert not root.exists()

    def test_require_reachable_workspace_root_raises_explicitly(self, unavailable_root_pg):
        reloaded, vanished_root = unavailable_root_pg
        with pytest.raises(reloaded.WorkspaceRootUnavailableError):
            reloaded.require_reachable_workspace_root(vanished_root)

    def test_checkpoint_source_fails_closed_not_silently_empty(self, tmp_path, monkeypatch):
        """wso.checkpoint_source() calls path_governance.require_reachable_workspace_root()
        with no argument, which reads path_governance's OWN module-level
        WORKSPACE_ROOT global -- patch that same module object (the one wso
        actually imported its function from), not a reloaded copy."""
        vanished_root = tmp_path / "unplugged_drive" / "tdc-workspace"
        monkeypatch.setattr(pg, "WORKSPACE_ROOT", vanished_root)
        with pytest.raises(pg.WorkspaceRootUnavailableError) as exc_info:
            wso.checkpoint_source()
        assert str(vanished_root) in str(exc_info.value)
        assert str(pg.REPO_DATA_DIR) not in str(exc_info.value)

    def test_failure_does_not_fall_back_to_repo_data(self, unavailable_root_pg):
        """The exception message/identity must point at the configured
        (unavailable) root, never quietly resolve to REPO_DATA_DIR."""
        reloaded, vanished_root = unavailable_root_pg
        with pytest.raises(reloaded.WorkspaceRootUnavailableError) as exc_info:
            reloaded.require_reachable_workspace_root(vanished_root)
        assert str(vanished_root) in str(exc_info.value)
        assert str(reloaded.REPO_DATA_DIR) not in str(exc_info.value)


class TestFreezeCopyVerifyCycle:
    """D11/D12 governed copy mechanism -- exercised only against tmp_path
    fixtures, never against the real Toshiba device or the real repo source."""

    @pytest.fixture
    def fake_source(self, tmp_path):
        source = tmp_path / "fake_out_local"
        (source / "sub").mkdir(parents=True)
        (source / "a.jsonl").write_text("alpha\n")
        (source / "sub" / "b.jsonl").write_text("beta\n")
        return source

    def test_freeze_manifest_captures_all_files_with_hash(self, fake_source):
        manifest = wso.freeze_pre_copy_manifest(fake_source)
        assert manifest["file_count"] == 2
        rels = {e["relative_path"] for e in manifest["entries"]}
        assert rels == {"a.jsonl", str(Path("sub") / "b.jsonl")}
        for entry in manifest["entries"]:
            assert len(entry["sha256"]) == 64

    def test_freeze_manifest_excludes_secret_like_filenames(self, fake_source):
        (fake_source / ".env").write_text("SECRET=1\n")
        (fake_source / "id_rsa.pem").write_text("fake\n")
        manifest = wso.freeze_pre_copy_manifest(fake_source)
        rels = {e["relative_path"] for e in manifest["entries"]}
        assert ".env" not in rels
        assert "id_rsa.pem" not in rels
        assert set(manifest["rejected_secret_like_filenames"]) == {".env", "id_rsa.pem"}

    def test_execute_copy_requires_exact_token(self, fake_source, tmp_path):
        manifest = wso.freeze_pre_copy_manifest(fake_source)
        target = tmp_path / "target_ws"
        with pytest.raises(PermissionError):
            wso.execute_authorized_copy(manifest, target, human_authorization="nope")
        assert not target.exists()

    def test_execute_copy_materializes_under_out_local(self, fake_source, tmp_path):
        manifest = wso.freeze_pre_copy_manifest(fake_source)
        target = tmp_path / "target_ws"
        receipt = wso.execute_authorized_copy(manifest, target, human_authorization=wso.COPY_AUTHORIZATION_TOKEN)
        assert receipt["status"] == "COMPLETED"
        assert (target / "out" / "local" / "a.jsonl").read_text() == "alpha\n"
        assert (target / "out" / "local" / "sub" / "b.jsonl").read_text() == "beta\n"
        assert receipt["source_deleted"] is False
        assert receipt["cutover_performed"] is False

    def test_execute_copy_never_deletes_or_modifies_source(self, fake_source, tmp_path):
        before = (fake_source / "a.jsonl").read_text()
        manifest = wso.freeze_pre_copy_manifest(fake_source)
        wso.execute_authorized_copy(manifest, tmp_path / "target_ws", human_authorization=wso.COPY_AUTHORIZATION_TOKEN)
        assert (fake_source / "a.jsonl").exists()
        assert (fake_source / "a.jsonl").read_text() == before

    def test_verify_passes_on_clean_copy(self, fake_source, tmp_path):
        manifest = wso.freeze_pre_copy_manifest(fake_source)
        target = tmp_path / "target_ws"
        wso.execute_authorized_copy(manifest, target, human_authorization=wso.COPY_AUTHORIZATION_TOKEN)
        result = wso.verify_target_against_manifest(manifest, target)
        assert result["equivalence_verified"] is True
        assert result["missing_files"] == []
        assert result["mismatches"] == []
        assert result["unexpected_extra_files"] == []

    def test_verify_detects_missing_file(self, fake_source, tmp_path):
        manifest = wso.freeze_pre_copy_manifest(fake_source)
        target = tmp_path / "target_ws"
        wso.execute_authorized_copy(manifest, target, human_authorization=wso.COPY_AUTHORIZATION_TOKEN)
        (target / "out" / "local" / "a.jsonl").unlink()
        result = wso.verify_target_against_manifest(manifest, target)
        assert result["equivalence_verified"] is False
        assert "a.jsonl" in result["missing_files"]

    def test_verify_detects_content_drift(self, fake_source, tmp_path):
        manifest = wso.freeze_pre_copy_manifest(fake_source)
        target = tmp_path / "target_ws"
        wso.execute_authorized_copy(manifest, target, human_authorization=wso.COPY_AUTHORIZATION_TOKEN)
        (target / "out" / "local" / "a.jsonl").write_text("alphB\n")  # same byte length as "alpha\n" -> forces hash check, not size check
        result = wso.verify_target_against_manifest(manifest, target)
        assert result["equivalence_verified"] is False
        assert result["mismatches"][0]["relative_path"] == "a.jsonl"
        assert result["mismatches"][0]["reason"] == "hash_mismatch"

    def test_verify_detects_unexpected_extra_file(self, fake_source, tmp_path):
        manifest = wso.freeze_pre_copy_manifest(fake_source)
        target = tmp_path / "target_ws"
        wso.execute_authorized_copy(manifest, target, human_authorization=wso.COPY_AUTHORIZATION_TOKEN)
        (target / "out" / "local" / "extra.jsonl").write_text("surprise\n")
        result = wso.verify_target_against_manifest(manifest, target)
        assert result["equivalence_verified"] is False
        assert "extra.jsonl" in result["unexpected_extra_files"]

    def test_copy_fails_closed_on_missing_source_file(self, fake_source, tmp_path):
        manifest = wso.freeze_pre_copy_manifest(fake_source)
        (fake_source / "a.jsonl").unlink()  # simulate source vanishing mid-flight
        target = tmp_path / "target_ws"
        receipt = wso.execute_authorized_copy(manifest, target, human_authorization=wso.COPY_AUTHORIZATION_TOKEN)
        assert receipt["status"] in {"PARTIAL", "FAILED"}
        assert receipt["failed_file_count"] >= 1


class TestCheckpointSource:
    def test_checkpoint_matches_live_canon_shard_count(self):
        checkpoint = wso.checkpoint_source()
        shards = pg.sorted_canon_shards(pg.DEFAULT_CANON_DIR)
        assert checkpoint["canon"]["shard_count"] == len(shards)

    def test_checkpoint_is_read_only(self):
        before = {p: p.stat().st_mtime for p in pg.sorted_canon_shards(pg.DEFAULT_CANON_DIR)}
        wso.checkpoint_source()
        after = {p: p.stat().st_mtime for p in pg.sorted_canon_shards(pg.DEFAULT_CANON_DIR)}
        assert before == after
