"""
Characterization tests for the derive_layers.py pipeline — S0109, updated S0116, reconciled S0126/S0127.

These tests freeze the observable behavior of the derivation pipeline:
  canon → enriched → ai → chunks

They operate read-only on existing data/out/local/ outputs and via subprocess
for CLI checks. They do NOT run the full pipeline during tests; they verify
the invariants of the current state.

Counts frozen at: canon=1424, enriched=1424, AI=1424, chunks=1255, shards=15.
Updated from post-S0115 baseline (1090/1090/1090/1012, 11 shards) to post-S0125 state (1375),
then to post-S0125/S0126 admission state (1389), post-S0127 admission state (1396),
then to post-S0129 state (1403 = 1396 + 7 nuevos tiddlers; shard 15 creado; derive_layers re-ejecutado),
then to post-S0132 state (1424 = 1403 + 21 nuevos tiddlers admitidos entre S0130–S0131).

When the canon changes legitimately, update the constants below and run
  sha256sum data/out/local/tiddlers_*.jsonl
to refresh EXPECTED_HASHES.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CANON_DIR = REPO_ROOT / "data" / "out" / "local"
ENRICHED_DIR = CANON_DIR / "enriched"
AI_DIR = CANON_DIR / "ai"

# ── Count invariants ─────────────────────────────────────────────────────────

# Post-S0132 state: 1424 tiddlers (21 nuevos admitidos entre S0130–S0131: artefactos de sesiones).
# Chunks estables en 1255: los nuevos tiddlers no superan el umbral de chunking.
EXPECTED_CANON_COUNT = 1424
EXPECTED_ENRICHED_COUNT = 1424
EXPECTED_AI_COUNT = 1424
EXPECTED_CHUNK_COUNT = 1255


def _count_jsonl_records(directory: Path, glob: str) -> int:
    total = 0
    for path in sorted(directory.glob(glob)):
        with path.open(encoding="utf-8") as f:
            total += sum(1 for line in f if line.strip())
    return total


# ── CLI characterization ─────────────────────────────────────────────────────

class TestDeriveCLI:
    def test_help_exits_zero(self):
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "src" / "python_scripts" / "derive_layers.py"), "--help"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0

    def test_help_contains_input_dir(self):
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "src" / "python_scripts" / "derive_layers.py"), "--help"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert "--input-dir" in result.stdout

    def test_help_contains_enriched_dir(self):
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "src" / "python_scripts" / "derive_layers.py"), "--help"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert "--enriched-dir" in result.stdout

    def test_help_contains_ai_dir(self):
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "src" / "python_scripts" / "derive_layers.py"), "--help"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert "--ai-dir" in result.stdout

    def test_help_contains_strict_flag(self):
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "src" / "python_scripts" / "derive_layers.py"), "--help"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert "--strict" in result.stdout


# ── Count characterization ────────────────────────────────────────────────────

class TestDeriveCountInvariants:
    def test_canon_shards_exist(self):
        shards = sorted(CANON_DIR.glob("tiddlers_*.jsonl"))
        # Post-S0129 state: 15 shards. Previous (post-S0125/S0128): 14 shards.
        assert len(shards) == 15, f"Expected 15 canon shards, got {len(shards)}"

    def test_canon_record_count(self):
        count = _count_jsonl_records(CANON_DIR, "tiddlers_*.jsonl")
        assert count == EXPECTED_CANON_COUNT, (
            f"Canon count mismatch: expected {EXPECTED_CANON_COUNT}, got {count}"
        )

    def test_enriched_record_count(self):
        count = _count_jsonl_records(ENRICHED_DIR, "tiddlers_enriched_*.jsonl")
        assert count == EXPECTED_ENRICHED_COUNT, (
            f"Enriched count mismatch: expected {EXPECTED_ENRICHED_COUNT}, got {count}"
        )

    def test_ai_record_count(self):
        count = _count_jsonl_records(AI_DIR, "tiddlers_ai_*.jsonl")
        assert count == EXPECTED_AI_COUNT, (
            f"AI record count mismatch: expected {EXPECTED_AI_COUNT}, got {count}"
        )

    def test_chunk_record_count(self):
        count = _count_jsonl_records(AI_DIR, "chunks_ai_*.jsonl")
        assert count == EXPECTED_CHUNK_COUNT, (
            f"Chunk count mismatch: expected {EXPECTED_CHUNK_COUNT}, got {count}"
        )

    def test_enriched_count_equals_canon_count(self):
        # S0129: derive_layers re-ejecutado tras nueva admisión; invariante canon==enriched restaurada.
        canon = _count_jsonl_records(CANON_DIR, "tiddlers_*.jsonl")
        enriched = _count_jsonl_records(ENRICHED_DIR, "tiddlers_enriched_*.jsonl")
        assert canon == enriched, f"Canon/enriched invariant broken: {canon} != {enriched}"

    def test_ai_count_equals_canon_count(self):
        # S0129: derive_layers re-ejecutado tras nueva admisión; invariante canon==ai restaurada.
        canon = _count_jsonl_records(CANON_DIR, "tiddlers_*.jsonl")
        ai = _count_jsonl_records(AI_DIR, "tiddlers_ai_*.jsonl")
        assert canon == ai, f"Canon/AI invariant broken: {canon} != {ai}"


# ── Field structure characterization ─────────────────────────────────────────

AI_REQUIRED_FIELDS = {
    "title",
    "id",
    "role_primary",
    "ai_summary",
    "semantic_text",
    "preview_text",
    "retrieval_hints",
    "retrieval_terms",
    "token_estimate",
    "is_chunkable_text",
    "corpus_state",
    "derivation",
}

CHUNK_REQUIRED_FIELDS = {
    "title",
    "chunk_id",
    "chunk_index",
    "chunk_total",
    "source_id",
    "source_title",
    "text",
    "token_estimate",
    "role_primary",
    "corpus_state",
    "within_hard_max",
}

ENRICHED_REQUIRED_FIELDS = {
    "title",
    "id",
    "role_primary",
    "semantic_text",
    "preview_text",
    "taxonomy_path",
    "derivation",
    "schema_version",
}


def _load_first_record(directory: Path, glob: str) -> dict:
    for path in sorted(directory.glob(glob)):
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    return json.loads(line)
    raise FileNotFoundError(f"No records found in {directory}/{glob}")


class TestAIRecordStructure:
    @pytest.fixture(scope="class")
    def sample_ai_record(self):
        return _load_first_record(AI_DIR, "tiddlers_ai_*.jsonl")

    def test_ai_record_has_required_fields(self, sample_ai_record):
        missing = AI_REQUIRED_FIELDS - set(sample_ai_record.keys())
        assert not missing, f"AI record missing fields: {missing}"

    def test_ai_record_title_is_nonempty(self, sample_ai_record):
        assert isinstance(sample_ai_record.get("title"), str)
        assert sample_ai_record["title"].strip()

    def test_ai_record_token_estimate_is_positive(self, sample_ai_record):
        tok = sample_ai_record.get("token_estimate")
        assert isinstance(tok, int) and tok >= 0

    def test_ai_record_corpus_state_is_string(self, sample_ai_record):
        cs = sample_ai_record.get("corpus_state")
        assert isinstance(cs, str) and cs.strip()

    def test_ai_record_is_chunkable_text_is_bool(self, sample_ai_record):
        assert isinstance(sample_ai_record.get("is_chunkable_text"), bool)

    def test_ai_record_derivation_contains_session(self, sample_ai_record):
        deriv = sample_ai_record.get("derivation", {})
        assert isinstance(deriv, dict)
        assert "session" in deriv


class TestChunkStructure:
    @pytest.fixture(scope="class")
    def sample_chunk(self):
        return _load_first_record(AI_DIR, "chunks_ai_*.jsonl")

    def test_chunk_has_required_fields(self, sample_chunk):
        missing = CHUNK_REQUIRED_FIELDS - set(sample_chunk.keys())
        assert not missing, f"Chunk missing fields: {missing}"

    def test_chunk_text_is_nonempty(self, sample_chunk):
        assert isinstance(sample_chunk.get("text"), str)
        assert sample_chunk["text"].strip()

    def test_chunk_token_estimate_is_positive(self, sample_chunk):
        tok = sample_chunk.get("token_estimate")
        assert isinstance(tok, int) and tok > 0

    def test_chunk_within_hard_max_is_bool(self, sample_chunk):
        assert isinstance(sample_chunk.get("within_hard_max"), bool)

    def test_chunk_index_starts_at_zero_or_one(self, sample_chunk):
        idx = sample_chunk.get("chunk_index")
        assert isinstance(idx, int) and idx >= 0


class TestEnrichedRecordStructure:
    @pytest.fixture(scope="class")
    def sample_enriched(self):
        return _load_first_record(ENRICHED_DIR, "tiddlers_enriched_*.jsonl")

    def test_enriched_has_required_fields(self, sample_enriched):
        missing = ENRICHED_REQUIRED_FIELDS - set(sample_enriched.keys())
        assert not missing, f"Enriched record missing fields: {missing}"

    def test_enriched_title_is_nonempty(self, sample_enriched):
        assert isinstance(sample_enriched.get("title"), str)
        assert sample_enriched["title"].strip()

    def test_enriched_schema_version_present(self, sample_enriched):
        assert sample_enriched.get("schema_version")


# ── Canon immutability ────────────────────────────────────────────────────────

class TestCanonImmutability:
    def test_canon_files_are_valid_jsonl(self):
        for path in sorted(CANON_DIR.glob("tiddlers_*.jsonl")):
            with path.open(encoding="utf-8") as f:
                for i, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        json.loads(line)
                    except json.JSONDecodeError as e:
                        pytest.fail(f"Invalid JSON at {path}:{i}: {e}")

    def test_canon_records_all_have_title(self):
        missing_title = 0
        for path in sorted(CANON_DIR.glob("tiddlers_*.jsonl")):
            with path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    if not rec.get("title"):
                        missing_title += 1
        assert missing_title == 0, f"{missing_title} canon records missing title"

    def test_canon_sha256_stable(self):
        """Freeze SHA-256 hashes of all canon shards.

        If this test fails after a legitimate canon update, update the
        EXPECTED_HASHES dict below with the new values.
        """
        # Hashes actualizados al estado post-S0132 (21 nuevos tiddlers admitidos entre S0130–S0131).
        # Para actualizar: sha256sum data/out/local/tiddlers_*.jsonl
        EXPECTED_HASHES = {
            "tiddlers_1.jsonl":  "0a728bede565757838c475599a44af897e3634f2f3023bf17dae1a2a8b318b43",
            "tiddlers_2.jsonl":  "b7019ee1e258ceacaf47dd96d33669d4c708770bae5cdb10b5b6540ca10f2f72",
            "tiddlers_3.jsonl":  "4b9a9da096f2bb2e37676cdbefa0d1e2b14c7fdd9cb0b050c9e14102f84969e0",
            "tiddlers_4.jsonl":  "2e5b8f64d34b6fdca27251a3f599b3269a4d061a62f562fed2cb7ef0eed4658d",
            "tiddlers_5.jsonl":  "526a63a41d7e2ace7dfca05633d423b297015f2837fc228b4ee7d91d1afb56cb",
            "tiddlers_6.jsonl":  "59fa8d41bcb2751c458a0b20217bf2e0c8b350deee118e3b16bc7ecacb3739a2",
            "tiddlers_7.jsonl":  "7b99749b10e7e99595a3aa23cbac7d05eb66262fde44273a87f5913414188c82",
            "tiddlers_8.jsonl":  "d746532735f37e1f7733702e512cebc48c95c97b806d3b4162c1c7087ee9868e",
            "tiddlers_9.jsonl":  "be240dcc6e0d4a2f85ec15877fd7fffc3cc2fd5f6f6630e24b44faa142401273",
            "tiddlers_10.jsonl": "1b557c5b06c121818f72051db985f8c4f8d19ad01fdeed4e7ced08489cd4306a",
            "tiddlers_11.jsonl": "6a1abab8911fba900b002e188c6b2928f657ff56f711b71c97d993b1f6f4031d",
            "tiddlers_12.jsonl": "a1bceb35a84cffaa6381a3219db3ebd773856a99b16f2e3770bf2332e16fc195",
            "tiddlers_13.jsonl": "97823209f7ec437c6b225d164e4ef281288aa2137d504d95f766e3b8a53418b5",
            "tiddlers_14.jsonl": "c7583eab737b01a1d4f451189200e0a95d171bbbe07224c9b2707e1b4381a2f2",
            "tiddlers_15.jsonl": "91e5e08eb13e603ad03a939da913df02849c4611499adbc7ee43518558ec19df",
        }
        mismatches = []
        for name, expected_hash in EXPECTED_HASHES.items():
            path = CANON_DIR / name
            if not path.exists():
                mismatches.append(f"{name}: file not found")
                continue
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != expected_hash:
                mismatches.append(f"{name}: expected {expected_hash[:16]}… got {actual[:16]}…")
        assert not mismatches, "Canon hash mismatch (canon changed):\n" + "\n".join(mismatches)


# ── Path governance ───────────────────────────────────────────────────────────

class TestPathGovernance:
    def test_no_sessions_in_root(self):
        forbidden = REPO_ROOT / "sessions"
        assert not forbidden.exists(), f"Forbidden path exists: {forbidden}"

    def test_no_data_sessions(self):
        forbidden = REPO_ROOT / "data" / "sessions"
        assert not forbidden.exists(), f"Forbidden path exists: {forbidden}"

    def test_no_data_local_at_root_level(self):
        forbidden = REPO_ROOT / "data" / "local"
        assert not forbidden.exists(), f"Forbidden path exists: {forbidden}"

    def test_governed_sessions_path_is_correct(self):
        governed = CANON_DIR / "sessions"
        assert governed.exists(), (
            f"Governed sessions path missing: {governed}"
        )

    def test_qc_reports_exist(self):
        reports_dir = AI_DIR / "reports"
        assert reports_dir.exists()
        reports = list(reports_dir.glob("*.json"))
        assert len(reports) >= 5, f"Expected ≥5 QC reports, got {len(reports)}"


# ── source_type MIME invariant (S0128 post-mortem) ────────────────────────────

class TestCanonSourceTypeMime:
    """All canon records with a non-null source_type must carry a valid MIME type.

    A valid MIME type contains a forward slash (e.g. 'text/markdown',
    'application/json').  Values like 'contrato', 'procedencia', or any other
    artifact-family name written into the wrong field are caught here.

    This test is the permanent regression guard for the S0128 incident where
    7 S0125 session deliverables had source_type set to the artifact-family
    name instead of 'text/markdown', causing reverse_tiddlers to silently
    skip them (rule: out-of-scope-source-type).

    Root cause: _validated_source_type() was absent from session_sync.py and
    admit_session_candidates.py; the raw 'type' field was forwarded to the
    canon without MIME validation.
    """

    def test_all_source_types_are_valid_mime(self):
        bad: list[str] = []
        for path in sorted(CANON_DIR.glob("tiddlers_*.jsonl")):
            with path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    st = rec.get("source_type")
                    if st is not None and st != "" and "/" not in st:
                        bad.append(
                            f"{path.name}: title={rec.get('title','')[:60]!r} "
                            f"source_type={st!r}"
                        )
        assert not bad, (
            f"Canon records with non-MIME source_type (S0128 regression):\n"
            + "\n".join(bad)
        )

    def test_session_deliverables_use_text_markdown(self):
        """Session deliverables (layer:session tag) must use text/markdown or
        application/json — never a bare artifact-family name.
        """
        bad: list[str] = []
        allowed = {"text/markdown", "application/json", "text/plain",
                   "text/vnd.tiddlywiki", "text/csv", None, ""}
        for path in sorted(CANON_DIR.glob("tiddlers_*.jsonl")):
            with path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    tags = rec.get("tags") or []
                    if "layer:session" not in tags:
                        continue
                    st = rec.get("source_type")
                    if st not in allowed:
                        bad.append(
                            f"{path.name}: {rec.get('title','')[:60]!r} → {st!r}"
                        )
        assert not bad, (
            f"Session deliverables with wrong source_type:\n" + "\n".join(bad)
        )
