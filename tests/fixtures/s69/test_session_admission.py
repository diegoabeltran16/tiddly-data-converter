from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_DIR = REPO_ROOT / "python_scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import admit_session_candidates as asc

ADMIT_SCRIPT = REPO_ROOT / "python_scripts" / "admit_session_candidates.py"
SESSIONS_DIR = REPO_ROOT / "data" / "out" / "local" / "sessions"
BASE_CONTRACT_SOURCE = (
    REPO_ROOT
    / "data"
    / "out"
    / "local"
    / "sessions"
    / "00_contratos"
    / "m04-s98-propagacion-relacional-chunks-ai-y-rule23.md.json"
)
REAL_CANON_DIR = REPO_ROOT / "data" / "out" / "local"
DATA_TMP = REPO_ROOT / "data" / "tmp"
REPORT_DIR = DATA_TMP / "admissions" / "s69_unittest"
WORK_DIR = DATA_TMP / "session_admission_s69_unittest"
BASE_SESSION_ORIGIN = "m04-s98-propagacion-relacional-chunks-ai-y-rule23"
ALT_EXISTING_SOURCE = (
    "data/out/local/sessions/01_procedencia/m04-s98-propagacion-relacional-chunks-ai-y-rule23.md.json"
)


def run_command(args: list[str], cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.setdefault("GOCACHE", "/tmp/tdc-go-build")
    return subprocess.run(args, cwd=cwd, env=env, check=False, capture_output=True, text=True)


def canon_hash(canon_dir: Path) -> str:
    digest = hashlib.sha256()
    for shard in sorted(canon_dir.glob("tiddlers_*.jsonl")):
        digest.update(shard.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(shard.read_bytes())
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def copy_canon_fixture(target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    for shard in sorted(REAL_CANON_DIR.glob("tiddlers_*.jsonl")):
        shutil.copy2(shard, target_dir / shard.name)
    remove_session_origin(target_dir, BASE_SESSION_ORIGIN)


def remove_session_origin(canon_dir: Path, session_origin: str) -> None:
    for shard in sorted(canon_dir.glob("tiddlers_*.jsonl")):
        kept: list[str] = []
        for raw in shard.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            record = json.loads(raw)
            source_fields = record.get("source_fields") or {}
            if source_fields.get("session_origin") == session_origin:
                continue
            kept.append(raw)
        shard.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")


def base_session_candidate(tmp_dir: Path) -> dict:
    raw = asc._contract_candidate_from_artifact(BASE_CONTRACT_SOURCE, SESSIONS_DIR)
    normalized = normalize_records([raw], tmp_dir)[0]
    normalized["raw_payload_ref"] = f"node:{normalized['id']}"
    return normalized


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def normalize_records(records: list[dict], tmp_dir: Path) -> list[dict]:
    raw_path = tmp_dir / "normalize.raw.jsonl"
    out_path = tmp_dir / "normalize.out.jsonl"
    write_jsonl(raw_path, records)
    result = run_command(
        [
            "go",
            "run",
            "./cmd/canon_preflight",
            "--mode",
            "normalize",
            "--input",
            str(raw_path),
            "--output",
            str(out_path),
        ],
        cwd=REPO_ROOT / "go" / "canon",
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return read_jsonl(out_path)


def replace_status_tags(tags: object, new_status: str) -> object:
    if not isinstance(tags, list):
        return tags
    replaced: list[str] = []
    seen: set[str] = set()
    for item in tags:
        tag = str(item)
        if tag == "status:candidate":
            tag = new_status
        if tag not in seen:
            seen.add(tag)
            replaced.append(tag)
    return replaced


def admitted_projection(record: dict, tmp_dir: Path) -> dict:
    projected = copy.deepcopy(record)
    projected.setdefault("source_fields", {})["canonical_status"] = "local_admitted"
    for field in ("tags", "source_tags", "normalized_tags"):
        projected[field] = replace_status_tags(projected.get(field), "status:local_admitted")
    normalized = normalize_records([projected], tmp_dir)[0]
    normalized["raw_payload_ref"] = f"node:{normalized['id']}"
    return normalized


def append_to_last_shard(canon_dir: Path, record: dict) -> None:
    shards = sorted(canon_dir.glob("tiddlers_*.jsonl"))
    if not shards:
        raise AssertionError(f"no canon shards under {canon_dir}")
    with shards[-1].open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
        handle.write("\n")


def stdout_payload(result: subprocess.CompletedProcess[str]) -> dict:
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise AssertionError(f"no JSON stdout; stderr={result.stderr}")
    return json.loads(lines[-1])


def report_payload(summary: dict) -> dict:
    report_path = REPO_ROOT / summary["report"]
    return json.loads(report_path.read_text(encoding="utf-8"))


class SessionAdmissionFixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        DATA_TMP.mkdir(parents=True, exist_ok=True)
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        WORK_DIR.mkdir(parents=True, exist_ok=True)
        self.real_canon_before = canon_hash(REAL_CANON_DIR)
        self.tmp = tempfile.TemporaryDirectory(prefix="s69_admission_", dir=DATA_TMP)
        self.tmp_dir = Path(self.tmp.name)
        self.base_candidate = base_session_candidate(self.tmp_dir)

    def tearDown(self) -> None:
        self.tmp.cleanup()
        self.assertEqual(self.real_canon_before, canon_hash(REAL_CANON_DIR))

    def write_candidate(self, name: str, record: dict) -> Path:
        path = self.tmp_dir / "candidates" / f"{name}.jsonl"
        write_jsonl(path, [record])
        return path

    def run_admission(self, mode: str, candidate_file: Path, canon_dir: Path, extra: list[str] | None = None) -> subprocess.CompletedProcess[str]:
        args = [
            sys.executable,
            str(ADMIT_SCRIPT),
            mode,
            "--candidate-file",
            str(candidate_file),
            "--sessions-dir",
            str(SESSIONS_DIR),
            "--canon-dir",
            str(canon_dir),
            "--report-dir",
            str(REPORT_DIR),
            "--tmp-dir",
            str(WORK_DIR),
        ]
        if extra:
            args.extend(extra)
        return run_command(args)

    def test_validate_dry_run_apply_and_rollback_on_fixture(self) -> None:
        canon_dir = self.tmp_dir / "canon"
        copy_canon_fixture(canon_dir)
        candidate_file = self.write_candidate("valid-new", self.base_candidate)
        fixture_hash_before = canon_hash(canon_dir)

        validate_result = self.run_admission("validate", candidate_file, canon_dir)
        self.assertEqual(validate_result.returncode, 0, validate_result.stderr)
        validate_summary = stdout_payload(validate_result)
        self.assertEqual(validate_summary["status"], "ok")
        self.assertEqual(validate_summary["eligible_count"], 1)
        self.assertFalse(validate_summary["canon_modified"])

        dry_result = self.run_admission("dry-run", candidate_file, canon_dir, ["--skip-tests"])
        self.assertEqual(dry_result.returncode, 0, dry_result.stderr)
        dry_summary = stdout_payload(dry_result)
        self.assertEqual(dry_summary["status"], "ok")
        self.assertEqual(dry_summary["admitted_count"], 1)
        self.assertEqual(dry_summary["reverse_rejected"], 0)
        self.assertFalse(dry_summary["canon_modified"])
        self.assertEqual(fixture_hash_before, canon_hash(canon_dir))

        apply_result = self.run_admission("apply", candidate_file, canon_dir, ["--skip-tests", "--confirm-apply"])
        self.assertEqual(apply_result.returncode, 0, apply_result.stderr)
        apply_summary = stdout_payload(apply_result)
        self.assertTrue(apply_summary["canon_modified"])
        self.assertTrue(apply_summary["rollback_ready"])
        self.assertNotEqual(fixture_hash_before, canon_hash(canon_dir))

        rollback_result = run_command(
            [
                sys.executable,
                str(ADMIT_SCRIPT),
                "rollback",
                "--admission-report",
                str(REPO_ROOT / apply_summary["report"]),
                "--canon-dir",
                str(canon_dir),
                "--report-dir",
                str(REPORT_DIR),
                "--tmp-dir",
                str(WORK_DIR),
            ]
        )
        self.assertEqual(rollback_result.returncode, 0, rollback_result.stderr)
        rollback_summary = stdout_payload(rollback_result)
        self.assertEqual(rollback_summary["status"], "ok")
        self.assertEqual(rollback_summary["removed_count"], 1)
        self.assertEqual(fixture_hash_before, canon_hash(canon_dir))

    def test_apply_without_confirmation_does_not_run_gates(self) -> None:
        canon_dir = self.tmp_dir / "canon-no-confirm"
        copy_canon_fixture(canon_dir)
        candidate_file = self.write_candidate("valid-no-confirm", self.base_candidate)
        fixture_hash_before = canon_hash(canon_dir)

        result = self.run_admission("apply", candidate_file, canon_dir)
        self.assertEqual(result.returncode, 2)
        summary = stdout_payload(result)
        report = report_payload(summary)
        self.assertFalse(summary["canon_modified"])
        self.assertEqual([], report["commands_run"])
        self.assertEqual("reject_apply_without_confirmation", report["rejected_candidates"][0]["classification"])
        self.assertEqual(fixture_hash_before, canon_hash(canon_dir))

    def test_duplicate_identical_is_skipped_without_append(self) -> None:
        canon_dir = self.tmp_dir / "canon-duplicate"
        copy_canon_fixture(canon_dir)
        append_to_last_shard(canon_dir, admitted_projection(self.base_candidate, self.tmp_dir))
        candidate_file = self.write_candidate("duplicate-identical", self.base_candidate)
        fixture_hash_before = canon_hash(canon_dir)

        result = self.run_admission("dry-run", candidate_file, canon_dir, ["--skip-tests"])
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = stdout_payload(result)
        report = report_payload(summary)
        self.assertEqual(summary["status"], "ok")
        self.assertEqual(summary["eligible_count"], 0)
        self.assertEqual(summary["admitted_count"], 0)
        self.assertEqual(report["classification_counts"]["already_admitted_skip"], 1)
        self.assertEqual(fixture_hash_before, canon_hash(canon_dir))

    def test_conflicts_and_missing_source_are_blocked(self) -> None:
        self.assertFalse((REPO_ROOT / "sessions").exists())

        source_conflict = self.make_variant(
            "#### 🌀 Contrato de sesión 69 = source-path-conflict-fixture-v0"
        )
        session_family_conflict = self.make_variant(
            "#### 🌀 Contrato de sesión 69 = session-family-conflict-fixture-v0",
            source_path=ALT_EXISTING_SOURCE,
        )
        same_id_drift = self.make_content_drift()
        missing_source = copy.deepcopy(self.base_candidate)
        missing_source["source_fields"]["source_path"] = (
            "data/out/local/sessions/00_contratos/m03-s69-missing-source-fixture.md.json"
        )

        cases = [
            ("same-id-different-content", same_id_drift, "conflict_same_id_different_content", "apply"),
            ("same-source-path-different-id", source_conflict, "conflict_same_source_path_different_id", "apply"),
            (
                "same-session-family-already-admitted",
                session_family_conflict,
                "conflict_same_session_family_already_admitted",
                "apply",
            ),
            ("missing-source-path", missing_source, "reject_missing_source_artifact", "validate"),
        ]

        for name, candidate, expected_classification, mode in cases:
            with self.subTest(name=name):
                canon_dir = self.tmp_dir / f"canon-{name}"
                copy_canon_fixture(canon_dir)
                if mode == "apply":
                    append_to_last_shard(canon_dir, admitted_projection(self.base_candidate, self.tmp_dir))
                fixture_hash_before = canon_hash(canon_dir)
                candidate_file = self.write_candidate(name, candidate)
                extra = ["--skip-tests", "--confirm-apply"] if mode == "apply" else None

                result = self.run_admission(mode, candidate_file, canon_dir, extra)
                self.assertEqual(result.returncode, 2)
                summary = stdout_payload(result)
                report = report_payload(summary)
                classifications = {item["classification"] for item in report["rejected_candidates"]}
                self.assertIn(expected_classification, classifications)
                self.assertFalse(summary["canon_modified"])
                self.assertEqual(fixture_hash_before, canon_hash(canon_dir))

    def make_content_drift(self) -> dict:
        drift = copy.deepcopy(self.base_candidate)
        drift["text"] = f"{drift['text']}\n\nS69 conflict content drift."
        normalized = normalize_records([drift], self.tmp_dir)[0]
        normalized["raw_payload_ref"] = f"node:{normalized['id']}"
        return normalized

    def make_variant(self, title: str, source_path: str | None = None) -> dict:
        variant = copy.deepcopy(self.base_candidate)
        variant["title"] = title
        variant["key"] = title
        variant["raw_payload_ref"] = ""
        if source_path is not None:
            variant["source_fields"]["source_path"] = source_path
            variant["source_position"] = source_path
        normalized = normalize_records([variant], self.tmp_dir)[0]
        normalized["raw_payload_ref"] = f"node:{normalized['id']}"
        return normalized


if __name__ == "__main__":
    unittest.main()
