#!/usr/bin/env python3
"""Tests for S0187 Unit C — consolidated material inventory (material_inventory.py).

All scans in this suite run against isolated tmp_path fixtures via explicit
InventoryProfile(root_locator=...) and explicit inventory/manifest/tmp/
transitions paths -- never against the live repository -- so nothing here
can touch Canon or any productive TDC state.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "src" / "python_scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import material_inventory as mi  # noqa: E402
import operator_menu as menu  # noqa: E402


def _profile(root: Path, **overrides) -> mi.InventoryProfile:
    base = mi.default_profile(root)
    return mi.InventoryProfile(
        profile_id=overrides.get("profile_id", base.profile_id),
        root_id=base.root_id,
        root_locator=str(root.resolve()),
        exclusions=overrides.get("exclusions", base.exclusions),
        follow_symlinks=overrides.get("follow_symlinks", base.follow_symlinks),
    )


def _paths(tmp_path: Path) -> dict[str, Path]:
    return {
        "inventory_path": tmp_path / "_state" / "current_inventory.jsonl",
        "manifest_path": tmp_path / "_state" / "current_inventory_manifest.json",
        "tmp_root": tmp_path / "_state" / "tmp",
        "transitions_dir": tmp_path / "_state" / "transitions",
        "lock_path": tmp_path / "_state" / ".lock",
    }


def _update(tmp_path: Path, root: Path, *, profile=None, **kwargs):
    state = _paths(tmp_path)
    state.update(kwargs)
    return mi.update_inventory(profile=profile or _profile(root), **state)


def _status(tmp_path: Path, root: Path, *, profile=None):
    state = _paths(tmp_path)
    return mi.check_status(
        profile=profile or _profile(root),
        inventory_path=state["inventory_path"],
        manifest_path=state["manifest_path"],
    )


def _write(root: Path, rel: str, content: str = "hello") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Determinism / snapshot identity
# ---------------------------------------------------------------------------


def test_deterministic_inventory_ordering(tmp_path):
    root = tmp_path / "repo"
    _write(root, "b/file.txt")
    _write(root, "a/file.txt")
    _write(root, "a.txt")
    records, _stats = mi.scan_material(_profile(root))
    paths = [r["relative_path"] for r in records]
    assert paths == sorted(paths)
    assert paths == ["a.txt", "a/file.txt", "b/file.txt"]


def test_snapshot_id_stable_across_identical_scans(tmp_path):
    root = tmp_path / "repo"
    _write(root, "x.txt", "same content")
    records1, _ = mi.scan_material(_profile(root))
    records2, _ = mi.scan_material(_profile(root))
    h1 = mi.compute_material_state_hash(records1)
    h2 = mi.compute_material_state_hash(records2)
    assert h1 == h2


def test_observed_at_does_not_affect_snapshot_id(tmp_path):
    root = tmp_path / "repo"
    _write(root, "x.txt", "content")
    first = _update(tmp_path, root)
    second = _update(tmp_path, root)
    assert first["manifest"]["observed_at"] != "" and second["manifest"]["observed_at"] != ""
    assert first["snapshot_id"] == second["snapshot_id"]
    assert second["change_summary"]["result"] == "NO_CHANGE"


# ---------------------------------------------------------------------------
# Change detection basics
# ---------------------------------------------------------------------------


def test_added(tmp_path):
    root = tmp_path / "repo"
    _write(root, "a.txt", "1")
    _update(tmp_path, root)
    _write(root, "b.txt", "2")
    result = _update(tmp_path, root)
    assert result["change_summary"]["result"] == "MATERIAL_TRANSITION"
    assert result["change_summary"]["counts"]["added_count"] == 1


def test_removed(tmp_path):
    root = tmp_path / "repo"
    _write(root, "a.txt", "1")
    b = _write(root, "b.txt", "2")
    _update(tmp_path, root)
    b.unlink()
    result = _update(tmp_path, root)
    assert result["change_summary"]["counts"]["removed_count"] == 1


def test_content_changed(tmp_path):
    root = tmp_path / "repo"
    f = _write(root, "a.txt", "1")
    _update(tmp_path, root)
    f.write_text("2", encoding="utf-8")
    result = _update(tmp_path, root, full_verify=True)
    assert result["change_summary"]["counts"]["content_changed_count"] == 1


def test_metadata_changed(tmp_path):
    root = tmp_path / "repo"
    f = _write(root, "a.txt", "1")
    _update(tmp_path, root)
    import os
    import time

    time.sleep(0.01)
    os.utime(f, ns=(int(time.time() * 1e9) + 5_000_000_000, int(time.time() * 1e9) + 5_000_000_000))
    result = _update(tmp_path, root, full_verify=True)
    assert result["change_summary"]["counts"]["metadata_changed_count"] == 1
    assert result["change_summary"]["counts"]["content_changed_count"] == 0


def test_every_same_path_material_hash_field_has_a_causal_event(tmp_path):
    root = tmp_path / "repo"
    _write(root, "a.txt", "1")
    records, _ = mi.scan_material(_profile(root), full_verify=True)
    before = records[0]
    after = dict(before)
    after["git_ignored"] = not before["git_ignored"]

    assert mi.compute_material_state_hash([before]) != mi.compute_material_state_hash([after])
    events, counts = mi.detect_changes([before], [after])
    assert counts["metadata_changed_count"] == 1
    assert counts["unchanged_count"] == 0
    assert events[0]["change_type"] == "METADATA_CHANGED"
    assert events[0]["changed_fields"] == ["git_ignored"]


def test_unchanged_scan_reports_no_change(tmp_path):
    root = tmp_path / "repo"
    _write(root, "a.txt", "1")
    _update(tmp_path, root)
    result = _update(tmp_path, root)
    assert result["change_summary"]["result"] == "NO_CHANGE"


# ---------------------------------------------------------------------------
# Move / copy / duplicate inference
# ---------------------------------------------------------------------------


def test_possible_move_or_rename_unambiguous(tmp_path):
    root = tmp_path / "repo"
    old = _write(root, "old/name.txt", "unique-content-xyz")
    _update(tmp_path, root)
    new_path = root / "new" / "name.txt"
    new_path.parent.mkdir(parents=True, exist_ok=True)
    old.rename(new_path)
    result = _update(tmp_path, root)
    counts = result["change_summary"]["counts"]
    assert counts["possible_move_count"] == 1
    assert counts["added_count"] == 0
    assert counts["removed_count"] == 0


def test_duplicate_hash_does_not_produce_false_move(tmp_path):
    root = tmp_path / "repo"
    old = _write(root, "old/name.txt", "dup-content")
    _write(root, "sibling/name.txt", "dup-content")  # already duplicated at baseline
    _update(tmp_path, root)
    new_path = root / "new" / "name.txt"
    new_path.parent.mkdir(parents=True, exist_ok=True)
    old.rename(new_path)  # removed+added both share a hash that ALSO survives at sibling/name.txt
    result = _update(tmp_path, root)
    counts = result["change_summary"]["counts"]
    assert counts["possible_move_count"] == 0
    assert counts["possible_copy_count"] == 1
    assert counts["duplicate_content_count"] >= 1


def test_possible_copy(tmp_path):
    root = tmp_path / "repo"
    _write(root, "source.txt", "copy-me")
    _update(tmp_path, root)
    _write(root, "clone/source.txt", "copy-me")
    result = _update(tmp_path, root)
    counts = result["change_summary"]["counts"]
    assert counts["possible_copy_count"] == 1
    assert counts["possible_move_count"] == 0


def test_path_and_content_changed_is_not_a_false_move(tmp_path):
    root = tmp_path / "repo"
    old = _write(root, "old/name.txt", "content-A")
    _update(tmp_path, root)
    old.unlink()
    _write(root, "new/name.txt", "content-B-totally-different")
    result = _update(tmp_path, root)
    counts = result["change_summary"]["counts"]
    assert counts["possible_move_count"] == 0
    assert counts["removed_count"] == 1
    assert counts["added_count"] == 1


# ---------------------------------------------------------------------------
# Git boundary / data/refs visibility
# ---------------------------------------------------------------------------


def _init_git(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)


def test_data_refs_visible_even_if_git_ignored(tmp_path):
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    _init_git(root)
    (root / ".gitignore").write_text("data/refs/\n", encoding="utf-8")
    _write(root, "data/refs/paper.pdf.txt", "reference material")
    _write(root, "src/kept.py", "print(1)")
    records, _stats = mi.scan_material(_profile(root))
    by_path = {r["relative_path"]: r for r in records}
    assert "data/refs/paper.pdf.txt" in by_path
    ref_record = by_path["data/refs/paper.pdf.txt"]
    assert ref_record["git_ignored"] is True
    assert ref_record["material_class"] == "EXTERNAL_REFERENCE"
    assert ref_record["authority_relation"] == "NONE"


def test_env_file_classified_as_sensitive_material(tmp_path, monkeypatch):
    """S0187 Unit E human decision (ENV_POLICY_DECISION=CLASSIFY_AND_SKIP_HASH):
    .env content must never be read for hashing at all -- not merely have its
    hash discarded after the fact. A monkeypatched spy on sha256_stream()
    proves the read never happens, rather than asserting only the output shape."""
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    _init_git(root)
    secret_content = "SYNTHETIC_TOKEN=do-not-leak-me"
    _write(root, ".env", secret_content)

    hashed_paths: list[Path] = []
    real_sha256_stream = mi.sha256_stream

    def _spy_sha256_stream(path):
        hashed_paths.append(path)
        return real_sha256_stream(path)

    monkeypatch.setattr(mi, "sha256_stream", _spy_sha256_stream)

    records, _stats = mi.scan_material(_profile(root))
    by_path = {r["relative_path"]: r for r in records}
    env_record = by_path[".env"]

    assert env_record["material_class"] == "SENSITIVE_MATERIAL"
    assert env_record["classification_basis"] == "EXPLICIT_GOVERNED_RULE"
    assert env_record["classification_confidence"] == "HIGH"
    assert env_record["hash_status"] == "SKIPPED_SENSITIVE_POLICY"
    assert env_record["content_hash"] is None
    assert env_record["hash_algorithm"] is None
    assert "SYNTHETIC_TOKEN" not in json.dumps(env_record)

    # The property under test: .env content is never read for hashing at all.
    assert (root / ".env") not in hashed_paths, (
        f"sha256_stream() was called for .env -- content was read for hashing: {hashed_paths}"
    )


def test_gitignore_does_not_gate_scan_scope(tmp_path):
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    _init_git(root)
    (root / ".gitignore").write_text("ignored_dir/\n", encoding="utf-8")
    _write(root, "ignored_dir/file.txt", "still material")
    records, _stats = mi.scan_material(_profile(root))
    paths = {r["relative_path"] for r in records}
    assert "ignored_dir/file.txt" in paths


# ---------------------------------------------------------------------------
# Self-observation boundary
# ---------------------------------------------------------------------------


def test_self_observation_paths_excluded(tmp_path):
    root = tmp_path / "repo"
    _write(root, "data/out/local/inventory/current_inventory.jsonl", "{}")
    _write(root, "data/out/local/audit/material_inventory/transitions/x/manifest.json", "{}")
    _write(root, "data/tmp/material_inventory/run-1/x.jsonl", "{}")
    _write(root, "src/keep.py", "1")
    records, _stats = mi.scan_material(_profile(root))
    paths = {r["relative_path"] for r in records}
    assert paths == {"src/keep.py"}


# ---------------------------------------------------------------------------
# Symlinks / filenames
# ---------------------------------------------------------------------------


def test_symlink_not_followed_but_recorded(tmp_path):
    root = tmp_path / "repo"
    target_dir = root / "target"
    target_dir.mkdir(parents=True)
    _write(root, "target/inside.txt", "content")
    link = root / "link_to_target"
    link.symlink_to(target_dir, target_is_directory=True)
    records, _stats = mi.scan_material(_profile(root))
    paths = {r["relative_path"]: r for r in records}
    assert "link_to_target" in paths
    assert paths["link_to_target"]["object_type"] == "symlink"
    assert "link_to_target/inside.txt" not in paths
    assert "target/inside.txt" in paths


def test_filename_with_spaces_and_unicode(tmp_path):
    root = tmp_path / "repo"
    _write(root, "dir with spaces/tildé résumé.txt", "content")
    records, _stats = mi.scan_material(_profile(root))
    paths = {r["relative_path"] for r in records}
    assert "dir with spaces/tildé résumé.txt" in paths


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------


def test_streaming_hash_matches_direct_hash(tmp_path):
    path = tmp_path / "big.bin"
    payload = (b"0123456789abcdef" * 1024) * 50  # 800 KB, larger than one chunk
    path.write_bytes(payload)
    assert mi.sha256_stream(path) == hashlib.sha256(payload).hexdigest()


def test_unreadable_artifact_surfaces_error_not_silent_drop(tmp_path):
    missing = tmp_path / "vanished.txt"
    record = mi._build_record(missing, "vanished.txt", set(), set(), None, False)
    assert record["observation_error"] is not None
    assert record["hash_status"] == "ERROR"
    assert record["material_class"] in {"SOURCE", "UNKNOWN"}


def test_incomplete_update_fails_before_creating_or_promoting_state(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    stats = mi.ScanStats(artifact_count=1, hash_error_count=1)
    monkeypatch.setattr(mi, "scan_material", lambda *_args, **_kwargs: ([], stats))
    state = _paths(tmp_path)

    try:
        mi.update_inventory(profile=_profile(root), **state)
        assert False, "expected MaterialInventoryError"
    except mi.MaterialInventoryError as exc:
        assert "OBSERVATION_INCOMPLETE" in str(exc)

    assert not state["inventory_path"].exists()
    assert not state["manifest_path"].exists()
    assert not state["tmp_root"].exists()
    assert not state["transitions_dir"].exists()


# ---------------------------------------------------------------------------
# Transition history / reconstructibility
# ---------------------------------------------------------------------------


def test_no_op_scan_creates_no_durable_transition(tmp_path):
    root = tmp_path / "repo"
    _write(root, "a.txt", "1")
    _update(tmp_path, root)
    _update(tmp_path, root)
    transitions_dir = _paths(tmp_path)["transitions_dir"]
    assert not transitions_dir.exists() or list(transitions_dir.iterdir()) == []


def test_material_transition_creates_receipt_without_unchanged_rows(tmp_path):
    root = tmp_path / "repo"
    _write(root, "a.txt", "1")
    _write(root, "stays.txt", "same")
    _update(tmp_path, root)
    _write(root, "b.txt", "2")
    result = _update(tmp_path, root)
    transition_id = result["change_summary"]["transition_id"]
    transitions_dir = _paths(tmp_path)["transitions_dir"]
    tr_dir = transitions_dir / transition_id
    manifest = json.loads((tr_dir / "manifest.json").read_text(encoding="utf-8"))
    events = [json.loads(line) for line in (tr_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert manifest["added_count"] == 1
    assert all(ev["change_type"] != "UNCHANGED" for ev in events)
    assert manifest["events_hash"] == hashlib.sha256((tr_dir / "events.jsonl").read_bytes()).hexdigest()


def test_transition_chain_previous_current_correct(tmp_path):
    root = tmp_path / "repo"
    _write(root, "a.txt", "1")
    r1 = _update(tmp_path, root)
    _write(root, "b.txt", "2")
    r2 = _update(tmp_path, root)
    _write(root, "c.txt", "3")
    r3 = _update(tmp_path, root)
    assert r2["manifest"]["previous_snapshot_id"] == r1["snapshot_id"]
    assert r3["manifest"]["previous_snapshot_id"] == r2["snapshot_id"]


def test_profile_change_blocks_normal_diff(tmp_path):
    root = tmp_path / "repo"
    _write(root, "a.txt", "1")
    _update(tmp_path, root)
    new_profile = _profile(root, profile_id="different-profile-v2")
    result = _update(tmp_path, root, profile=new_profile)
    assert result["change_summary"]["result"] == "INVENTORY_PROFILE_CHANGED_REBASELINE_REQUIRED"
    transitions_dir = _paths(tmp_path)["transitions_dir"]
    assert not transitions_dir.exists() or list(transitions_dir.iterdir()) == []


def test_current_inventory_rebuildable_after_deletion(tmp_path):
    root = tmp_path / "repo"
    _write(root, "a.txt", "1")
    _write(root, "b/c.txt", "2")
    first = _update(tmp_path, root)
    state = _paths(tmp_path)
    state["inventory_path"].unlink()
    state["manifest_path"].unlink()
    second = mi.update_inventory(profile=_profile(root), **state)
    assert second["material_state_hash"] == first["material_state_hash"]
    assert second["snapshot_id"] == first["snapshot_id"]


def test_trajectory_reconstructible_from_receipt(tmp_path):
    root = tmp_path / "repo"
    f = _write(root, "a.txt", "original")
    _update(tmp_path, root)
    f.write_text("modified", encoding="utf-8")
    result = _update(tmp_path, root, full_verify=True)
    transition_id = result["change_summary"]["transition_id"]
    tr_dir = _paths(tmp_path)["transitions_dir"] / transition_id
    events = [json.loads(line) for line in (tr_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    content_changed = [e for e in events if e["change_type"] == "CONTENT_CHANGED"]
    assert len(content_changed) == 1
    assert content_changed[0]["before"]["content_hash"] == hashlib.sha256(b"original").hexdigest()
    assert content_changed[0]["after"]["content_hash"] == hashlib.sha256(b"modified").hexdigest()


# ---------------------------------------------------------------------------
# Status (option 2: check without persisting)
# ---------------------------------------------------------------------------


def test_status_current_and_changes_detected_without_persisting(tmp_path):
    root = tmp_path / "repo"
    f = _write(root, "a.txt", "1")
    _update(tmp_path, root)
    assert _status(tmp_path, root)["status"] == "CURRENT"

    f.write_text("2", encoding="utf-8")
    status = _status(tmp_path, root)
    assert status["status"] == "CHANGES_DETECTED"

    # status must not have persisted -- a subsequent plain status call still
    # sees the same delta (nothing was written to current_inventory).
    status_again = _status(tmp_path, root)
    assert status_again["status"] == "CHANGES_DETECTED"


def test_currentness_describes_last_observation_and_live_check_separately(tmp_path):
    root = tmp_path / "repo"
    _write(root, "a.txt", "1")
    update = _update(tmp_path, root)
    manifest = update["manifest"]
    assert manifest["currentness_scope"] == "LAST_PERSISTED_OBSERVATION_QUALITY"
    assert manifest["last_observed_at"] == manifest["observed_at"]
    assert manifest["verification_mode"] == "INCREMENTAL_STAT_REUSE"

    status = _status(tmp_path, root)
    assert status["status"] == "CURRENT"
    assert status["persisted_snapshot_id"] == manifest["snapshot_id"]
    assert status["last_observed_at"] == manifest["observed_at"]
    assert status["checked_at"] >= status["last_observed_at"]
    assert status["verification_mode"] == "INCREMENTAL_STAT_REUSE"


def test_status_is_read_only_for_current_pair_transitions_and_canon(tmp_path):
    root = tmp_path / "repo"
    canon = _write(root, "data/out/local/tiddlers_1.jsonl", '{"id":"1"}\n')
    _write(root, "a.txt", "1")
    _update(tmp_path, root)
    state = _paths(tmp_path)

    protected = [state["inventory_path"], state["manifest_path"], canon]
    before_hashes = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in protected}
    transitions_before = (
        sorted(path.relative_to(state["transitions_dir"]) for path in state["transitions_dir"].rglob("*"))
        if state["transitions_dir"].exists()
        else []
    )

    assert _status(tmp_path, root)["status"] == "CURRENT"

    after_hashes = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in protected}
    transitions_after = (
        sorted(path.relative_to(state["transitions_dir"]) for path in state["transitions_dir"].rglob("*"))
        if state["transitions_dir"].exists()
        else []
    )
    assert after_hashes == before_hashes
    assert transitions_after == transitions_before


def test_status_no_current_inventory(tmp_path):
    root = tmp_path / "repo"
    _write(root, "a.txt", "1")
    assert _status(tmp_path, root)["status"] == "NO_CURRENT_INVENTORY"


# ---------------------------------------------------------------------------
# Pair consistency (fail-closed)
# ---------------------------------------------------------------------------


def test_current_inventory_pair_inconsistent_when_one_file_missing(tmp_path):
    state = _paths(tmp_path)
    state["inventory_path"].parent.mkdir(parents=True, exist_ok=True)
    state["inventory_path"].write_text("{}\n", encoding="utf-8")
    try:
        mi.load_current_inventory(inventory_path=state["inventory_path"], manifest_path=state["manifest_path"])
        assert False, "expected MaterialInventoryError"
    except mi.MaterialInventoryError as exc:
        assert "CURRENT_INVENTORY_PAIR_INCONSISTENT" in str(exc)


def test_current_inventory_pair_inconsistent_when_hash_tampered(tmp_path):
    root = tmp_path / "repo"
    _write(root, "a.txt", "1")
    _update(tmp_path, root)
    state = _paths(tmp_path)
    manifest = json.loads(state["manifest_path"].read_text(encoding="utf-8"))
    manifest["material_state_hash"] = "0" * 64
    state["manifest_path"].write_text(json.dumps(manifest), encoding="utf-8")
    try:
        mi.load_current_inventory(inventory_path=state["inventory_path"], manifest_path=state["manifest_path"])
        assert False, "expected MaterialInventoryError"
    except mi.MaterialInventoryError:
        pass


# ---------------------------------------------------------------------------
# ASCII projection consumes current inventory, not an independent scan
# ---------------------------------------------------------------------------


def test_ascii_structure_consumes_current_inventory_not_live_scan(tmp_path):
    root = tmp_path / "repo"
    _write(root, "a.txt", "1")
    _update(tmp_path, root)
    state = _paths(tmp_path)
    # mutate the live filesystem AFTER the inventory was captured
    _write(root, "b_added_after_inventory.txt", "2")
    output = tmp_path / "estructura.txt"
    result = mi.render_ascii_structure(
        output_path=output, inventory_path=state["inventory_path"], manifest_path=state["manifest_path"]
    )
    assert result["status"] == "OK"
    text = output.read_text(encoding="utf-8")
    assert "a.txt" in text
    assert "b_added_after_inventory.txt" not in text


def test_ascii_structure_no_current_inventory(tmp_path):
    state = _paths(tmp_path)
    result = mi.render_ascii_structure(
        output_path=tmp_path / "out.txt",
        inventory_path=state["inventory_path"],
        manifest_path=state["manifest_path"],
    )
    assert result["status"] == "NO_CURRENT_INVENTORY"


# ---------------------------------------------------------------------------
# Profile hash / snapshot id composition
# ---------------------------------------------------------------------------


def test_profile_hash_ignores_root_locator(tmp_path):
    root_a = tmp_path / "mount_a" / "repo"
    root_b = tmp_path / "mount_b" / "repo"
    profile_a = _profile(root_a)
    profile_b = _profile(root_b)
    assert mi.compute_profile_hash(profile_a) == mi.compute_profile_hash(profile_b)


# ---------------------------------------------------------------------------
# C-R human status projection: full machine detail -> bounded terminal view
# ---------------------------------------------------------------------------


def _synthetic_status(*, added=100, metadata=50, duplicates=25, unchanged=10_000):
    events = []
    for index in range(added):
        events.append(
            {
                "change_type": mi.CHANGE_ADDED,
                "relative_path": f"src/added-{index:04d}.txt",
                "after": {"relative_path": f"src/added-{index:04d}.txt", "material_class": "SOURCE"},
            }
        )
    for index in range(metadata):
        events.append(
            {
                "change_type": mi.CHANGE_METADATA_CHANGED,
                "relative_path": f"audit/meta-{index:04d}.json",
                "before": {"material_class": "AUDIT_EVIDENCE"},
                "after": {"material_class": "AUDIT_EVIDENCE"},
                "changed_fields": ["mtime_ns"],
            }
        )
    for index in range(duplicates):
        events.append(
            {
                "change_type": mi.CHANGE_DUPLICATED_CONTENT,
                "content_hash": f"hash-{index:04d}",
                "relative_paths": [f"dup/{index}/a", f"dup/{index}/b"],
            }
        )
    return {
        "status": "CHANGES_DETECTED",
        "persisted_snapshot_id": "a" * 64,
        "snapshot_id": "b" * 64,
        "last_observed_at": "2026-09-13T12:00:00Z",
        "checked_at": "2026-09-13T13:00:00Z",
        "verification_mode": "INCREMENTAL_STAT_REUSE",
        "counts": {
            "added_count": added,
            "removed_count": 0,
            "content_changed_count": 0,
            "metadata_changed_count": metadata,
            "unchanged_count": unchanged,
            "possible_move_count": 0,
            "possible_copy_count": 0,
            "duplicate_content_count": duplicates,
            "unknown_count": 0,
        },
        "events": events,
    }


def test_high_volume_status_preserves_full_machine_detail_but_bounds_terminal(capsys):
    status = _synthetic_status()
    original_events = list(status["events"])
    view = menu.print_material_inventory_status(status, detail_limit=20)
    output = capsys.readouterr().out

    assert status["events"] == original_events
    assert len(status["events"]) == 175
    assert view["full_machine_event_count"] == 175
    assert view["delta_event_count"] == 150
    assert len(view["default_detail"]) == 20
    assert view["detail_omitted_count"] == 130
    assert view["metadata_only_count"] == 50
    assert view["unchanged_count"] == 10_000
    assert "1,881" not in output
    assert "UNCHANGED:" not in output
    assert "src/added-0000.txt" in output
    assert "src/added-0099.txt" not in output
    assert len(output.splitlines()) < 55


def test_metadata_and_path_search_remain_accessible_in_bounded_drilldown(monkeypatch, capsys):
    status = _synthetic_status(added=30, metadata=30, duplicates=0)
    answers = iter(["6", "8", "added-0029", "0"])
    monkeypatch.setattr(menu, "prompt", lambda _message="": next(answers))

    menu.review_material_inventory_status(status)
    output = capsys.readouterr().out
    assert "Cambios solo de metadata (30)" in output
    assert "Mostrando 20 de 30 eventos" in output
    assert "audit/meta-0000.json [mtime_ns]" in output
    assert "src/added-0029.txt" in output


def test_current_status_first_view_is_compact_and_never_lists_artifacts(capsys):
    status = {
        "status": "CURRENT",
        "persisted_snapshot_id": "a" * 64,
        "snapshot_id": "a" * 64,
        "last_observed_at": "2026-09-13T12:00:00Z",
        "checked_at": "2026-09-13T13:00:00Z",
        "verification_mode": "FULL_CONTENT_HASHED_DURING_SCAN",
        "persisted_artifact_count": 32_284,
        "live_artifact_count": 32_284,
        "scan_seconds": 2.5,
        "counts": {"unchanged_count": 32_284},
    }
    menu.print_material_inventory_status(status)
    output = capsys.readouterr().out
    assert "Comparación: sin cambios en el momento de la comprobación." in output
    assert "Artefactos: 32284" in output
    assert len(output.splitlines()) < 15
