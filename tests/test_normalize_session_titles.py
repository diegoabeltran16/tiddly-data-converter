#!/usr/bin/env python3
"""Tests for normalize_session_titles.py — S0124."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "python_scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from normalize_session_titles import (  # noqa: E402
    NormalizationEntry,
    NormalizationPlan,
    apply_normalization_plan,
    audit_canon,
    audit_sessions_dir,
    build_normalization_plan,
    format_audit_report,
    load_last_plan,
    save_plan,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _write_shard(canon_dir: Path, name: str, records: list[dict]) -> None:
    canon_dir.mkdir(parents=True, exist_ok=True)
    shard = canon_dir / name
    shard.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )


def _write_staging_artifact(sessions_dir: Path, subfolder: str, filename: str, title: str) -> Path:
    folder = sessions_dir / subfolder
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / filename
    path.write_text(
        json.dumps([{"title": title, "text": "contenido de prueba"}], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def _make_canon_record(rec_id: str, title: str) -> dict:
    return {"id": rec_id, "title": title, "text": "contenido", "type": "text/markdown"}


# ── Audit staging ─────────────────────────────────────────────────────────────

class TestAuditSessionsDir:
    def test_canonical_title_has_canonical_status(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / "sessions"
        _write_staging_artifact(
            sessions_dir, "00_contratos",
            "m04-s0117-test.md.json",
            "#### 🌀 Contrato de sesión 0117 = pruebas P0 para remote_pull_canon y session_sync scan",
        )
        entries = audit_sessions_dir(sessions_dir)
        assert len(entries) == 1
        assert entries[0].status == "canonical"

    def test_s_prefix_title_has_normalizable_status(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / "sessions"
        _write_staging_artifact(
            sessions_dir, "00_contratos",
            "m04-s0117-test.md.json",
            "#### 🌀 Contrato de sesión S0117 = pruebas P0 para remote_pull_canon y session_sync scan",
        )
        entries = audit_sessions_dir(sessions_dir)
        assert len(entries) == 1
        e = entries[0]
        assert e.status == "normalizable"
        assert e.proposed_title is not None
        assert "0117" in e.proposed_title
        assert "S0117" not in e.proposed_title

    def test_unpadded_number_normalizable(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / "sessions"
        _write_staging_artifact(
            sessions_dir, "00_contratos",
            "m03-s65-test.md.json",
            "#### 🌀 Contrato de sesión 65 = microsoft-copilot-execution-surface-and-readme-hardening-v0",
        )
        entries = audit_sessions_dir(sessions_dir)
        assert entries[0].status == "normalizable"
        assert entries[0].proposed_title is not None
        assert "0065" in entries[0].proposed_title

    def test_multiple_artifacts_audited(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / "sessions"
        _write_staging_artifact(
            sessions_dir, "00_contratos", "a.md.json",
            "#### 🌀 Contrato de sesión 0117 = slug A"
        )
        _write_staging_artifact(
            sessions_dir, "01_procedencia", "b.md.json",
            "#### 🌀🧾 Procedencia de sesión S0117 = slug A"
        )
        entries = audit_sessions_dir(sessions_dir)
        statuses = {e.artifact_family: e.status for e in entries}
        assert statuses.get("contrato_de_sesion") == "canonical"
        assert statuses.get("procedencia_de_sesion") == "normalizable"


# ── Audit canon ───────────────────────────────────────────────────────────────

class TestAuditCanon:
    def test_non_canonical_title_detected_in_canon(self, tmp_path: Path) -> None:
        canon_dir = tmp_path / "canon"
        _write_shard(canon_dir, "tiddlers_1.jsonl", [
            _make_canon_record("id-001", "#### 🌀 Contrato de sesión S0111 = dry-run gobernado"),
            _make_canon_record("id-002", "#### 🌀 Balance de sesión 0066 = family-flow"),  # canonical
        ])
        entries = audit_canon(canon_dir)
        assert len(entries) == 2
        by_id = {e.record_id: e for e in entries}
        assert by_id["id-001"].status == "normalizable"
        assert by_id["id-002"].status == "canonical"

    def test_non_session_records_skipped(self, tmp_path: Path) -> None:
        canon_dir = tmp_path / "canon"
        _write_shard(canon_dir, "tiddlers_1.jsonl", [
            {"id": "code-001", "title": "MyScript.py", "text": "code"},
            {"id": "ref-001", "title": "Some reference", "text": "text"},
        ])
        entries = audit_canon(canon_dir)
        assert len(entries) == 0

    def test_shard_and_line_number_recorded(self, tmp_path: Path) -> None:
        canon_dir = tmp_path / "canon"
        _write_shard(canon_dir, "tiddlers_1.jsonl", [
            _make_canon_record("id-001", "#### 🌀 Contrato de sesión S0111 = slug"),
        ])
        entries = audit_canon(canon_dir)
        assert len(entries) == 1
        assert entries[0].artifact_path == "tiddlers_1.jsonl"
        assert entries[0].line_number == 1


# ── Build plan ────────────────────────────────────────────────────────────────

class TestBuildNormalizationPlan:
    def test_plan_has_correct_counts(self, tmp_path: Path) -> None:
        canon_dir = tmp_path / "canon"
        _write_shard(canon_dir, "tiddlers_1.jsonl", [
            _make_canon_record("id-001", "#### 🌀 Contrato de sesión S0111 = slug A"),
            _make_canon_record("id-002", "#### 🌀 Balance de sesión 0066 = slug B"),
        ])
        entries = audit_canon(canon_dir)
        plan = build_normalization_plan(entries, canon_dir)
        assert plan.normalizable_count == 1
        assert plan.total_checked == 2
        assert plan.dry_run is True
        assert plan.applied is False

    def test_collision_blocks_entries(self, tmp_path: Path) -> None:
        """Two canon records with different IDs that normalise to the same title are blocked."""
        canon_dir = tmp_path / "canon"
        # Both have S0111 but different record IDs — normalise to same title → collision
        _write_shard(canon_dir, "tiddlers_1.jsonl", [
            _make_canon_record("id-A", "#### 🌀 Contrato de sesión S0111 = dry-run gobernado"),
            _make_canon_record("id-B", "#### 🌀 Contrato de sesión S0111 = dry-run gobernado"),
        ])
        entries = audit_canon(canon_dir)
        plan = build_normalization_plan(entries, canon_dir)
        blocked = [e for e in plan.entries if e.status == "blocked"]
        assert len(blocked) == 2  # both blocked due to collision

    def test_same_id_same_proposed_no_false_collision(self, tmp_path: Path) -> None:
        """Same record in two shards with same ID is not a collision."""
        canon_dir = tmp_path / "canon"
        _write_shard(canon_dir, "tiddlers_1.jsonl", [
            _make_canon_record("id-dup", "#### 🌀 Contrato de sesión S0111 = dry-run gobernado"),
        ])
        _write_shard(canon_dir, "tiddlers_2.jsonl", [
            _make_canon_record("id-dup", "#### 🌀 Contrato de sesión S0111 = dry-run gobernado"),
        ])
        entries = audit_canon(canon_dir)
        plan = build_normalization_plan(entries, canon_dir)
        blocked = [e for e in plan.entries if e.status == "blocked"]
        # Same ID → not a true collision → not blocked
        assert len(blocked) == 0


# ── Apply plan: dry-run ───────────────────────────────────────────────────────

class TestDryRun:
    def test_dry_run_does_not_modify_canon(self, tmp_path: Path) -> None:
        """Canon-only plan returns no-op (canon entries are never applied)."""
        canon_dir = tmp_path / "canon"
        sessions_dir = tmp_path / "sessions"
        _write_shard(canon_dir, "tiddlers_1.jsonl", [
            _make_canon_record("id-001", "#### 🌀 Contrato de sesión S0111 = dry-run gobernado"),
        ])
        original = (canon_dir / "tiddlers_1.jsonl").read_bytes()
        entries = audit_canon(canon_dir)
        plan = build_normalization_plan(entries, canon_dir)
        # Canon-only plan → no staging entries → success=False, canon untouched
        success, msg, updated = apply_normalization_plan(plan, canon_dir, sessions_dir, confirm=False)
        assert not success
        assert "canon" in msg or "no hay" in msg
        assert (canon_dir / "tiddlers_1.jsonl").read_bytes() == original

    def test_dry_run_does_not_modify_staging(self, tmp_path: Path) -> None:
        """Staging dry-run returns True but does not write files."""
        canon_dir = tmp_path / "canon"
        sessions_dir = tmp_path / "sessions"
        path = _write_staging_artifact(
            sessions_dir, "00_contratos", "test.md.json",
            "#### 🌀 Contrato de sesión S0111 = slug"
        )
        original = path.read_bytes()
        entries = audit_sessions_dir(sessions_dir)
        plan = build_normalization_plan(entries, canon_dir)
        success, msg, updated = apply_normalization_plan(plan, canon_dir, sessions_dir, confirm=False)
        assert success
        assert "dry-run" in msg
        assert path.read_bytes() == original

    def test_dry_run_does_not_modify_staging(self, tmp_path: Path) -> None:
        canon_dir = tmp_path / "canon"
        sessions_dir = tmp_path / "sessions"
        path = _write_staging_artifact(
            sessions_dir, "00_contratos", "test.md.json",
            "#### 🌀 Contrato de sesión S0111 = slug"
        )
        original = path.read_bytes()
        entries = audit_sessions_dir(sessions_dir)
        plan = build_normalization_plan(entries, canon_dir)
        apply_normalization_plan(plan, canon_dir, sessions_dir, confirm=False)
        assert path.read_bytes() == original


# ── Apply plan: real apply ────────────────────────────────────────────────────

class TestApplyPlan:
    def test_apply_normalizes_staging_title(self, tmp_path: Path) -> None:
        """apply_normalization_plan normalises staging entries (canon skipped)."""
        canon_dir = tmp_path / "canon"
        sessions_dir = tmp_path / "sessions"
        backup_dir = tmp_path / "backup"
        # Canon shard present for backup; its entries will NOT be applied
        _write_shard(canon_dir, "tiddlers_1.jsonl", [
            _make_canon_record("id-001", "#### 🌀 Contrato de sesión S0111 = dry-run gobernado"),
        ])
        path = _write_staging_artifact(
            sessions_dir, "00_contratos", "m04-s0111-test.md.json",
            "#### 🌀 Contrato de sesión S0111 = dry-run gobernado",
        )
        entries = audit_sessions_dir(sessions_dir)
        plan = build_normalization_plan(entries, canon_dir)
        success, msg, updated = apply_normalization_plan(
            plan, canon_dir, sessions_dir, backup_dir=backup_dir, confirm=True
        )
        assert success
        assert updated.applied is True
        # Staging title was updated
        raw = json.loads(path.read_text(encoding="utf-8"))
        updated_title = raw[0]["title"] if isinstance(raw, list) else raw["title"]
        assert updated_title == "#### 🌀 Contrato de sesión 0111 = dry-run gobernado"
        # Canon shard title was NOT changed
        with (canon_dir / "tiddlers_1.jsonl").open(encoding="utf-8") as f:
            canon_rec = json.loads(f.readline())
        assert canon_rec["title"] == "#### 🌀 Contrato de sesión S0111 = dry-run gobernado"

    def test_apply_only_modifies_title(self, tmp_path: Path) -> None:
        """All other fields must remain unchanged after apply (staging)."""
        canon_dir = tmp_path / "canon"
        sessions_dir = tmp_path / "sessions"
        backup_dir = tmp_path / "backup"
        original_rec = {
            "id": "id-sentinel",
            "title": "#### 🌀 Contrato de sesión S0111 = slug",
            "text": "SENTINEL_TEXT",
            "tags": ["tag-a", "tag-b"],
            "relations": [{"id": "rel-1"}],
            "created": "20260101000000000",
        }
        path = sessions_dir / "00_contratos" / "m04-s0111-sentinel.md.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps([original_rec], ensure_ascii=False, indent=2), encoding="utf-8")
        entries = audit_sessions_dir(sessions_dir)
        plan = build_normalization_plan(entries, canon_dir)
        apply_normalization_plan(plan, canon_dir, sessions_dir, backup_dir=backup_dir, confirm=True)
        raw = json.loads(path.read_text(encoding="utf-8"))
        updated_rec = raw[0] if isinstance(raw, list) else raw
        assert updated_rec["id"] == "id-sentinel"
        assert updated_rec["text"] == "SENTINEL_TEXT"
        assert updated_rec["tags"] == ["tag-a", "tag-b"]
        assert updated_rec["relations"] == [{"id": "rel-1"}]
        assert updated_rec["created"] == "20260101000000000"
        # Title should have changed
        assert "S0111" not in updated_rec["title"]

    def test_apply_creates_backup(self, tmp_path: Path) -> None:
        """A backup of canon shards is created even when only staging is modified."""
        canon_dir = tmp_path / "canon"
        sessions_dir = tmp_path / "sessions"
        backup_dir = tmp_path / "backup"
        _write_shard(canon_dir, "tiddlers_1.jsonl", [
            _make_canon_record("id-001", "#### 🌀 Contrato de sesión S0111 = slug"),
        ])
        _write_staging_artifact(
            sessions_dir, "00_contratos", "m04-s0111-test.md.json",
            "#### 🌀 Contrato de sesión S0111 = slug",
        )
        entries = audit_sessions_dir(sessions_dir)
        plan = build_normalization_plan(entries, canon_dir)
        apply_normalization_plan(plan, canon_dir, sessions_dir, backup_dir=backup_dir, confirm=True)
        assert backup_dir.exists()
        assert (backup_dir / "tiddlers_1.jsonl").exists()

    def test_canon_entries_skipped_in_apply(self, tmp_path: Path) -> None:
        """Canon entries are never applied — only staging entries are."""
        canon_dir = tmp_path / "canon"
        sessions_dir = tmp_path / "sessions"
        _write_shard(canon_dir, "tiddlers_1.jsonl", [
            _make_canon_record("id-001", "#### 🌀 Contrato de sesión S0111 = slug"),
        ])
        original_bytes = (canon_dir / "tiddlers_1.jsonl").read_bytes()
        entries = audit_canon(canon_dir)
        plan = build_normalization_plan(entries, canon_dir)
        success, msg, updated = apply_normalization_plan(plan, canon_dir, sessions_dir, confirm=True)
        # success=False because there are no staging entries
        assert not success
        assert "canon" in msg or "no hay" in msg
        # Canon shard is UNTOUCHED
        assert (canon_dir / "tiddlers_1.jsonl").read_bytes() == original_bytes

    def test_apply_staging_title(self, tmp_path: Path) -> None:
        canon_dir = tmp_path / "canon"
        sessions_dir = tmp_path / "sessions"
        backup_dir = tmp_path / "backup"
        path = _write_staging_artifact(
            sessions_dir, "00_contratos", "m04-s0111-test.md.json",
            "#### 🌀 Contrato de sesión S0111 = dry-run gobernado"
        )
        entries = audit_sessions_dir(sessions_dir)
        plan = build_normalization_plan(entries, canon_dir)
        success, _, updated = apply_normalization_plan(
            plan, canon_dir, sessions_dir, backup_dir=backup_dir, confirm=True
        )
        assert success
        raw = json.loads(path.read_text(encoding="utf-8"))
        updated_title = raw[0]["title"] if isinstance(raw, list) else raw["title"]
        assert updated_title == "#### 🌀 Contrato de sesión 0111 = dry-run gobernado"


# ── Save/load plan ────────────────────────────────────────────────────────────

class TestSaveLoadPlan:
    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        canon_dir = tmp_path / "canon"
        out_dir = tmp_path / "audit"
        _write_shard(canon_dir, "tiddlers_1.jsonl", [
            _make_canon_record("id-001", "#### 🌀 Contrato de sesión S0111 = slug"),
        ])
        entries = audit_canon(canon_dir)
        plan = build_normalization_plan(entries, canon_dir)
        save_plan(plan, out_dir)
        loaded = load_last_plan(out_dir)
        assert loaded is not None
        assert loaded.run_id == plan.run_id
        assert loaded.normalizable_count == plan.normalizable_count

    def test_load_returns_none_when_no_file(self, tmp_path: Path) -> None:
        assert load_last_plan(tmp_path / "nonexistent") is None


# ── Format report ─────────────────────────────────────────────────────────────

class TestFormatAuditReport:
    def test_empty_returns_no_entries_message(self) -> None:
        result = format_audit_report([])
        assert "Sin entradas" in result

    def test_report_shows_normalizable_count(self, tmp_path: Path) -> None:
        entries = [
            NormalizationEntry(
                source="staging",
                artifact_path="00_contratos/test.md.json",
                line_number=0,
                artifact_family="contrato_de_sesion",
                record_id="",
                current_title="#### 🌀 Contrato de sesión S0111 = slug",
                proposed_title="#### 🌀 Contrato de sesión 0111 = slug",
                issue="s_prefix_in_number",
                status="normalizable",
            )
        ]
        report = format_audit_report(entries)
        assert "normalizable:  1" in report
        assert "0111" in report
