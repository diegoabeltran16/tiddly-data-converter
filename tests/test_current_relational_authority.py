"""Focused contracts for the single current relational authority API."""

from __future__ import annotations

import hashlib
import json
import sys
import threading
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

import current_relational_authority as authority  # noqa: E402


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _refresh_pointer_manifest_hash(pointer_path: Path, manifest_path: Path) -> None:
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    pointer["bundle_manifest_hash"] = hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    _write_json(pointer_path, pointer)


def _human_bundle(
    tmp_path: Path,
    *,
    terminal: str = "READY_FOR_HUMAN_DELTA_REVIEW",
    include_receipts: bool = False,
) -> tuple[Path, Path, Path]:
    local_root = tmp_path / "local"
    bundle = (
        local_root
        / "audit/relation_admission/generations/rg_fixture/rv_fixture/bundle"
    )
    bundle.mkdir(parents=True)
    artifacts: dict[str, dict[str, str]] = {}
    role_schemas = {
        "pending_queue": "current-relational-human-delta/v2",
        "batch_inventory": "current-relational-human-delta-inventory/v2",
        "current_human_delta": "current-governed-review-human-delta/v1",
    }
    for name in sorted(authority.REQUIRED_HUMAN_DELTA_ARTIFACTS):
        path = bundle / f"{name}.json"
        payload = (
            {"schema_version": role_schemas[name]}
            if name in role_schemas else {}
        )
        _write_json(path, payload)
        artifacts[name] = {
            "path": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        if name in role_schemas:
            artifacts[name]["schema_version"] = role_schemas[name]
    for name in sorted(authority.HUMAN_PENDING_PLACEHOLDER_ARTIFACTS):
        artifacts[name] = {"status": "not_applicable_pending_human_review"}
    if include_receipts:
        path = bundle / "review_receipts.jsonl"
        path.write_bytes(b"")
        artifacts["review_receipts"] = {
            "path": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }

    next_action = authority.TERMINAL_NEXT_ACTION[terminal]
    manifest = {
        "schema_version": authority.SCHEMA_BUNDLE,
        "canon_generation_id": "cg_fixture",
        "relation_generation_id": "rg_fixture",
        "review_state_id": "rv_fixture",
        "readiness_id": None,
        "terminal_state": terminal,
        "next_action": next_action,
        "artifacts": artifacts,
    }
    manifest_path = bundle / "bundle_manifest.json"
    _write_json(manifest_path, manifest)
    pointer_path = local_root / "audit/relation_admission/current_generation.json"
    _write_json(pointer_path, {
        "schema_version": authority.SCHEMA_POINTER,
        "bundle_path": str(bundle),
        "bundle_manifest_path": str(manifest_path),
        "bundle_manifest_hash": hashlib.sha256(
            manifest_path.read_bytes()
        ).hexdigest(),
        "canon_generation_id": "cg_fixture",
        "relation_generation_id": "rg_fixture",
        "review_state_id": "rv_fixture",
        "readiness_id": None,
        "terminal_state": terminal,
        "next_action": next_action,
    })
    return local_root, bundle, pointer_path


def _install_v2_lineage(
    bundle: Path,
    pointer_path: Path,
    *,
    receipts: list[dict[str, object]],
    descriptor: dict[str, object],
) -> None:
    receipts_path = bundle / "review_receipts.jsonl"
    receipts_path.write_text(
        "".join(
            json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n"
            for receipt in receipts
        ),
        encoding="utf-8",
    )
    descriptor = {
        **descriptor,
        "schema_version": "current-review-receipt-lineage/v2",
        "receipt_count": len(receipts),
        "carried_review_receipts_hash": hashlib.sha256(
            receipts_path.read_bytes()
        ).hexdigest(),
        "integrity_verified": True,
    }
    lineage_path = bundle / "review_receipt_lineage.json"
    _write_json(lineage_path, descriptor)
    manifest_path = bundle / "bundle_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["review_lineage_required"] = True
    manifest["artifacts"]["review_receipts"] = {
        "path": receipts_path.name,
        "sha256": hashlib.sha256(receipts_path.read_bytes()).hexdigest(),
        "schema_version": "jsonl/v1",
    }
    manifest["artifacts"]["review_receipt_lineage"] = {
        "path": lineage_path.name,
        "sha256": hashlib.sha256(lineage_path.read_bytes()).hexdigest(),
        "schema_version": "current-review-receipt-lineage/v2",
    }
    _write_json(manifest_path, manifest)
    _refresh_pointer_manifest_hash(pointer_path, manifest_path)


def _v2_lineage_values() -> tuple[
    list[dict[str, object]], dict[str, object]
]:
    receipts: list[dict[str, object]] = [
        {
            "schema_version": "current-single-batch-review-receipt/v2",
            "receipt_id": "hrr_previous",
            "source_relation_generation_id": "rg_previous",
            "source_review_state_id": "rv_previous_root",
            "result_review_state_id": "rv_previous_tip",
        },
        {
            "schema_version": "current-single-batch-review-receipt/v2",
            "receipt_id": "hrr_current",
            "source_relation_generation_id": "rg_fixture",
            "source_review_state_id": "rv_current_root",
            "result_review_state_id": "rv_current_tip",
        },
    ]
    descriptor: dict[str, object] = {
        "receipt_ids": ["hrr_previous", "hrr_current"],
        "segments": [
            {
                "relation_generation_id": "rg_previous",
                "root_review_state_id": "rv_previous_root",
                "tip_review_state_id": "rv_previous_tip",
                "receipt_ids": ["hrr_previous"],
            },
            {
                "relation_generation_id": "rg_fixture",
                "root_review_state_id": "rv_current_root",
                "tip_review_state_id": "rv_current_tip",
                "receipt_ids": ["hrr_current"],
            },
        ],
    }
    return receipts, descriptor


def _install_v1_lineage(
    bundle: Path,
    pointer_path: Path,
    *,
    receipt: dict[str, object],
    descriptor: dict[str, object],
) -> None:
    receipts_path = bundle / "review_receipts.jsonl"
    receipts_path.write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    lineage = {
        **descriptor,
        "schema_version": "current-review-receipt-lineage/v1",
        "receipt_count": 1,
        "carried_review_receipts_hash": hashlib.sha256(
            receipts_path.read_bytes()
        ).hexdigest(),
        "integrity_verified": True,
    }
    lineage_path = bundle / "review_receipt_lineage.json"
    _write_json(lineage_path, lineage)
    manifest_path = bundle / "bundle_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["review_lineage_required"] = True
    manifest["artifacts"]["review_receipts"] = {
        "path": receipts_path.name,
        "sha256": hashlib.sha256(receipts_path.read_bytes()).hexdigest(),
        "schema_version": "jsonl/v1",
    }
    manifest["artifacts"]["review_receipt_lineage"] = {
        "path": lineage_path.name,
        "sha256": hashlib.sha256(lineage_path.read_bytes()).hexdigest(),
        "schema_version": "current-review-receipt-lineage/v1",
    }
    _write_json(manifest_path, manifest)
    _refresh_pointer_manifest_hash(pointer_path, manifest_path)


def test_pointer_cas_creates_and_replaces_exact_bytes_with_persistent_lock(
    tmp_path: Path,
) -> None:
    pointer = tmp_path / "current/current_generation.json"

    created = authority.compare_and_swap_current_pointer(
        pointer, expected=None, replacement=b'{"generation":1}\n',
    )
    replaced = authority.compare_and_swap_current_pointer(
        pointer,
        expected=b'{"generation":1}\n',
        replacement=b'{"generation":2}\n',
    )

    assert created is True
    assert replaced is True
    assert pointer.read_bytes() == b'{"generation":2}\n'
    assert (pointer.parent / ".current_generation.lock").is_file()
    assert not list(pointer.parent.glob(".current_generation.json.*.tmp"))


def test_pointer_cas_mismatch_is_byte_exact_and_leaves_pointer_unchanged(
    tmp_path: Path,
) -> None:
    pointer = tmp_path / "current/current_generation.json"
    pointer.parent.mkdir(parents=True)
    pointer.write_bytes(b'{"generation":1}\n')

    with pytest.raises(authority.CurrentRelationalAuthorityError) as blocked:
        authority.compare_and_swap_current_pointer(
            pointer,
            expected=b'{"generation": 1}\n',
            replacement=b'{"generation":2}\n',
        )

    assert blocked.value.reason_codes == ["current_pointer_changed"]
    assert pointer.read_bytes() == b'{"generation":1}\n'


def test_pointer_cas_rejects_identical_concurrent_publication_without_ownership(
    tmp_path: Path,
) -> None:
    pointer = tmp_path / "current/current_generation.json"
    pointer.parent.mkdir(parents=True)
    peer_bytes = b'{"generation":2}\n'
    pointer.write_bytes(peer_bytes)

    with pytest.raises(authority.CurrentRelationalAuthorityError) as blocked:
        authority.compare_and_swap_current_pointer(
            pointer,
            expected=b'{"generation":1}\n',
            replacement=peer_bytes,
        )

    assert blocked.value.reason_codes == ["current_pointer_changed"]
    assert pointer.read_bytes() == peer_bytes


def test_pointer_cas_supports_rollback_to_prior_bytes_or_absence(
    tmp_path: Path,
) -> None:
    pointer = tmp_path / "current/current_generation.json"
    before, published = b"previous-pointer\n", b"published-pointer\n"

    authority.compare_and_swap_current_pointer(
        pointer, expected=None, replacement=before,
    )
    authority.compare_and_swap_current_pointer(
        pointer, expected=before, replacement=published,
    )
    assert authority.compare_and_swap_current_pointer(
        pointer, expected=published, replacement=before,
    ) is True
    assert pointer.read_bytes() == before

    authority.compare_and_swap_current_pointer(
        pointer, expected=before, replacement=published,
    )
    assert authority.compare_and_swap_current_pointer(
        pointer, expected=published, replacement=None,
    ) is True
    assert not pointer.exists()


def test_pointer_cas_lock_allows_exactly_one_concurrent_winner(
    tmp_path: Path,
) -> None:
    pointer = tmp_path / "current/current_generation.json"
    pointer.parent.mkdir(parents=True)
    pointer.write_bytes(b"source")
    barrier = threading.Barrier(3)
    outcomes: list[tuple[str, bool | list[str]]] = []

    def publish(replacement: bytes) -> None:
        barrier.wait()
        try:
            result = authority.compare_and_swap_current_pointer(
                pointer, expected=b"source", replacement=replacement,
            )
            outcomes.append(("published", result))
        except authority.CurrentRelationalAuthorityError as error:
            outcomes.append(("blocked", error.reason_codes))

    threads = [
        threading.Thread(target=publish, args=(b"first",)),
        threading.Thread(target=publish, args=(b"second",)),
    ]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()

    assert sorted(outcome[0] for outcome in outcomes) == ["blocked", "published"]
    assert [value for status, value in outcomes if status == "blocked"] == [
        ["current_pointer_changed"]
    ]
    assert pointer.read_bytes() in {b"first", b"second"}


def test_public_pointer_lock_excludes_a_concurrent_cas(tmp_path: Path) -> None:
    pointer = tmp_path / "current/current_generation.json"
    pointer.parent.mkdir(parents=True)
    pointer.write_bytes(b"source")
    started = threading.Event()
    completed = threading.Event()

    def publish() -> None:
        started.set()
        authority.compare_and_swap_current_pointer(
            pointer, expected=b"source", replacement=b"replacement",
        )
        completed.set()

    with authority.current_pointer_lock(pointer):
        thread = threading.Thread(target=publish)
        thread.start()
        assert started.wait(timeout=1)
        assert not completed.wait(timeout=0.1)
        assert pointer.read_bytes() == b"source"

    assert completed.wait(timeout=1)
    thread.join()
    assert pointer.read_bytes() == b"replacement"


def test_pointer_cas_fsyncs_unique_temporary_and_parent_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pointer = tmp_path / "current/current_generation.json"
    fsync_calls: list[int] = []
    replaced_from: list[Path] = []
    real_fsync = authority.os.fsync
    real_replace = authority.os.replace

    def recording_fsync(descriptor: int) -> None:
        fsync_calls.append(descriptor)
        real_fsync(descriptor)

    def recording_replace(source: str | Path, destination: str | Path) -> None:
        replaced_from.append(Path(source))
        real_replace(source, destination)

    monkeypatch.setattr(authority.os, "fsync", recording_fsync)
    monkeypatch.setattr(authority.os, "replace", recording_replace)

    authority.compare_and_swap_current_pointer(
        pointer, expected=None, replacement=b"first",
    )
    authority.compare_and_swap_current_pointer(
        pointer, expected=b"first", replacement=b"second",
    )

    assert len(fsync_calls) == 4
    assert len(replaced_from) == 2
    assert replaced_from[0] != replaced_from[1]
    assert all(path.parent == pointer.parent for path in replaced_from)
    assert not any(path.exists() for path in replaced_from)


def test_human_terminal_resolves_only_with_producer_minimum_roles(
    tmp_path: Path,
) -> None:
    local_root, _bundle, _pointer = _human_bundle(tmp_path)

    resolved = authority.resolve_current_relational_authority(local_root)

    assert resolved["terminal_state"] == "READY_FOR_HUMAN_DELTA_REVIEW"
    assert authority.REQUIRED_HUMAN_DELTA_ARTIFACTS <= set(
        resolved["artifacts"]
    )
    assert not authority.HUMAN_PENDING_PLACEHOLDER_ARTIFACTS.intersection(
        resolved["artifacts"]
    )


@pytest.mark.parametrize("declared", [None, "different/bundle_manifest.json"])
def test_schema_v1_pointer_requires_exact_resolved_bundle_manifest_path(
    tmp_path: Path,
    declared: str | None,
) -> None:
    local_root, _bundle, pointer_path = _human_bundle(tmp_path)
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    if declared is None:
        pointer.pop("bundle_manifest_path")
    else:
        pointer["bundle_manifest_path"] = declared
    _write_json(pointer_path, pointer)

    with pytest.raises(authority.CurrentRelationalAuthorityError) as blocked:
        authority.resolve_current_relational_authority(local_root)

    assert blocked.value.reason_codes == [
        "current_bundle_manifest_path_mismatch"
    ]


def test_human_terminal_missing_active_or_placeholder_role_is_incomplete(
    tmp_path: Path,
) -> None:
    for suffix, missing in (
        ("active", "current_human_delta"),
        ("placeholder", "authorization_request"),
    ):
        local_root, bundle, pointer_path = _human_bundle(tmp_path / suffix)
        manifest_path = bundle / "bundle_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["artifacts"].pop(missing)
        _write_json(manifest_path, manifest)
        _refresh_pointer_manifest_hash(pointer_path, manifest_path)

        with pytest.raises(authority.CurrentRelationalAuthorityError) as blocked:
            authority.resolve_current_relational_authority(local_root)

        assert "current_bundle_incomplete" in blocked.value.reason_codes


def test_human_terminal_rejects_non_pending_placeholder_state(
    tmp_path: Path,
) -> None:
    local_root, bundle, pointer_path = _human_bundle(tmp_path)
    manifest_path = bundle / "bundle_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"]["authorization_request"] = {
        "status": "created",
    }
    _write_json(manifest_path, manifest)
    _refresh_pointer_manifest_hash(pointer_path, manifest_path)

    with pytest.raises(authority.CurrentRelationalAuthorityError) as blocked:
        authority.resolve_current_relational_authority(local_root)

    assert "current_bundle_artifact_state_invalid" in blocked.value.reason_codes


def test_review_complete_terminal_requires_receipt_role(
    tmp_path: Path,
) -> None:
    local_root, _bundle, _pointer = _human_bundle(
        tmp_path,
        terminal="REVIEW_COMPLETE_PENDING_READINESS_RECOMPOSITION",
    )
    with pytest.raises(authority.CurrentRelationalAuthorityError) as blocked:
        authority.resolve_current_relational_authority(local_root)
    assert "current_bundle_incomplete" in blocked.value.reason_codes

    recovered_root, _bundle, _pointer = _human_bundle(
        tmp_path / "with-receipts",
        terminal="REVIEW_COMPLETE_PENDING_READINESS_RECOMPOSITION",
        include_receipts=True,
    )
    resolved = authority.resolve_current_relational_authority(recovered_root)
    assert resolved["terminal_state"] == (
        "REVIEW_COMPLETE_PENDING_READINESS_RECOMPOSITION"
    )


@pytest.mark.parametrize(
    ("role", "schema"),
    [
        ("pending_queue", "unknown-human-delta/v999"),
        ("batch_inventory", "unknown-human-delta-inventory/v999"),
        ("current_human_delta", "unknown-governed-delta/v999"),
    ],
)
def test_current_authority_rejects_unknown_derived_artifact_schema(
    tmp_path: Path, role: str, schema: str,
) -> None:
    local_root, bundle, pointer_path = _human_bundle(tmp_path)
    manifest_path = bundle / "bundle_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    item = manifest["artifacts"][role]
    artifact_path = bundle / item["path"]
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    payload["schema_version"] = schema
    _write_json(artifact_path, payload)
    item["schema_version"] = schema
    item["sha256"] = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    _write_json(manifest_path, manifest)
    _refresh_pointer_manifest_hash(pointer_path, manifest_path)

    with pytest.raises(authority.CurrentRelationalAuthorityError) as blocked:
        authority.resolve_current_relational_authority(local_root)

    assert "current_bundle_artifact_schema_invalid" in blocked.value.reason_codes


def test_v2_receipt_segments_cover_the_exact_cross_generation_ledger(
    tmp_path: Path,
) -> None:
    local_root, bundle, pointer_path = _human_bundle(tmp_path)
    receipts, descriptor = _v2_lineage_values()
    _install_v2_lineage(
        bundle, pointer_path, receipts=receipts, descriptor=descriptor,
    )

    resolved = authority.resolve_current_relational_authority(local_root)

    assert resolved["artifacts"]["review_receipts"] == (
        bundle / "review_receipts.jsonl"
    )
    assert resolved["artifacts"]["review_receipt_lineage"] == (
        bundle / "review_receipt_lineage.json"
    )


@pytest.mark.parametrize(
    "corruption",
    [None, "receipt_ids", "relation", "root", "tip"],
)
def test_v1_receipt_lineage_requires_the_exact_declared_chain(
    tmp_path: Path, corruption: str | None,
) -> None:
    local_root, bundle, pointer_path = _human_bundle(tmp_path)
    receipt: dict[str, object] = {
        "schema_version": "current-single-batch-review-receipt/v1",
        "receipt_id": "hrr_fixture",
        "source_relation_generation_id": "rg_fixture",
        "source_review_state_id": "rv_root",
        "result_review_state_id": "rv_tip",
    }
    descriptor: dict[str, object] = {
        "source_relation_generation_id": "rg_fixture",
        "root_review_state_id": "rv_root",
        "tip_review_state_id": "rv_tip",
        "receipt_ids": ["hrr_fixture"],
    }
    if corruption == "receipt_ids":
        descriptor["receipt_ids"] = ["hrr_other"]
    elif corruption == "relation":
        descriptor["source_relation_generation_id"] = "rg_other"
    elif corruption == "root":
        descriptor["root_review_state_id"] = "rv_other"
    elif corruption == "tip":
        descriptor["tip_review_state_id"] = "rv_other"
    _install_v1_lineage(
        bundle, pointer_path, receipt=receipt, descriptor=descriptor,
    )

    if corruption is None:
        assert authority.resolve_current_relational_authority(local_root)[
            "terminal_state"
        ] == "READY_FOR_HUMAN_DELTA_REVIEW"
    else:
        with pytest.raises(authority.CurrentRelationalAuthorityError) as blocked:
            authority.resolve_current_relational_authority(local_root)
        assert "review_receipt_lineage_invalid" in blocked.value.reason_codes


@pytest.mark.parametrize(
    "corruption",
    [
        "descriptor_receipt_omitted",
        "descriptor_receipt_duplicated",
        "segments_empty",
        "segment_empty",
        "segment_relation_duplicated",
        "segment_receipt_duplicated",
        "segment_receipt_omitted",
        "segment_relation_binding_wrong",
        "segment_root_wrong",
        "segment_tip_wrong",
        "ledger_receipt_id_duplicated",
        "ledger_receipt_id_empty",
    ],
)
def test_v2_receipt_segment_corruption_is_fail_closed(
    tmp_path: Path,
    corruption: str,
) -> None:
    local_root, bundle, pointer_path = _human_bundle(tmp_path)
    receipts, descriptor = _v2_lineage_values()
    segments = descriptor["segments"]
    assert isinstance(segments, list)

    if corruption == "descriptor_receipt_omitted":
        descriptor["receipt_ids"] = ["hrr_previous"]
    elif corruption == "descriptor_receipt_duplicated":
        descriptor["receipt_ids"] = [
            "hrr_previous", "hrr_current", "hrr_current",
        ]
    elif corruption == "segments_empty":
        descriptor["segments"] = []
    elif corruption == "segment_empty":
        segments[0]["receipt_ids"] = []
    elif corruption == "segment_relation_duplicated":
        segments[1]["relation_generation_id"] = "rg_previous"
    elif corruption == "segment_receipt_duplicated":
        segments[0]["receipt_ids"] = ["hrr_previous", "hrr_previous"]
    elif corruption == "segment_receipt_omitted":
        descriptor["segments"] = [segments[0]]
    elif corruption == "segment_relation_binding_wrong":
        segments[0]["receipt_ids"] = ["hrr_current"]
        segments[1]["receipt_ids"] = ["hrr_previous"]
    elif corruption == "segment_root_wrong":
        segments[0]["root_review_state_id"] = "rv_other"
    elif corruption == "segment_tip_wrong":
        segments[0]["tip_review_state_id"] = "rv_other"
    elif corruption == "ledger_receipt_id_duplicated":
        receipts[1]["receipt_id"] = "hrr_previous"
        descriptor["receipt_ids"] = ["hrr_previous", "hrr_previous"]
        segments[1]["receipt_ids"] = ["hrr_previous"]
    else:
        receipts[1]["receipt_id"] = ""
        descriptor["receipt_ids"] = ["hrr_previous", ""]
        segments[1]["receipt_ids"] = [""]

    _install_v2_lineage(
        bundle, pointer_path, receipts=receipts, descriptor=descriptor,
    )

    with pytest.raises(authority.CurrentRelationalAuthorityError) as blocked:
        authority.resolve_current_relational_authority(local_root)

    assert "review_receipt_lineage_invalid" in blocked.value.reason_codes
