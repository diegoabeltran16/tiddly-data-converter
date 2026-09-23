"""
Characterization tests for the derive_layers.py pipeline — S0109, updated S0116, reconciled S0126/S0127.

These tests freeze the observable behavior of the derivation pipeline:
  canon → enriched → ai → chunks

They operate read-only on existing data/out/local/ outputs and via subprocess
for CLI checks. They do NOT run the full pipeline during tests; they verify
the invariants of the current state.

Counts frozen at: canon=3711 (shards=38); enriched=1424, AI=1424, chunks=1255 remain
frozen at their post-S0132 values (see S0186 Unit G2 note below).
Updated from post-S0115 baseline (1090/1090/1090/1012, 11 shards) to post-S0125 state (1375),
then to post-S0125/S0126 admission state (1389), post-S0127 admission state (1396),
then to post-S0129 state (1403 = 1396 + 7 nuevos tiddlers; shard 15 creado; derive_layers re-ejecutado),
then to post-S0132 state (1424 = 1403 + 21 nuevos tiddlers admitidos entre S0130–S0131).

S0186 Unit G2 golden-fixture reconciliation (canon-only): the canon has grown
governedly (dozens of audit/admissions/backups/admit-* snapshots, S0183/S0184/
S0185 sessions) from the post-S0132 baseline to 3711 records / 38 shards,
reproduced live and byte-matched against data/out/local/tiddlers_*.jsonl and
the currently-active relation-generation pointer's canon binding. Re-baselined:
EXPECTED_CANON_COUNT, test_canon_shards_exist, EXPECTED_HASHES.
NOT re-baselined (left as an explicit, open blocker — see
test_enriched_count_equals_canon_count / test_ai_count_equals_canon_count):
EXPECTED_ENRICHED_COUNT, EXPECTED_AI_COUNT, EXPECTED_CHUNK_COUNT. derive_layers.py
has not been re-run since canon passed the last derivation (enriched/AI still
report 2205, chunks 1920) -- this is a real, currently-existing pipeline-stage
lag, not a golden-number problem, and updating the constants alone would not
make the cross-invariant tests self-consistent. Requires an actual
derive_layers.py re-run against the current canon before re-baselining.

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
SCRIPTS_DIR = REPO_ROOT / "src" / "python_scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
from path_governance import DEFAULT_AI_DIR, DEFAULT_CANON_DIR, DEFAULT_ENRICHED_DIR

# S0187 D23-A: these were hardcoded REPO_ROOT-relative literals -- migrated
# so this suite reads from the governed roots instead of the old
# materialization. All count/hash expectations below are deliberately
# untouched: several of these tests are already known-failing on content
# drift (pre-existing, D20-R baseline, see the module docstring above), out
# of D23-A's scope. The goal is only that they fail for that same,
# already-known reason -- not for looking at the wrong materialization.
CANON_DIR = DEFAULT_CANON_DIR
ENRICHED_DIR = DEFAULT_ENRICHED_DIR
AI_DIR = DEFAULT_AI_DIR

from path_governance import CANON_SHARD_FILENAME_RE  # noqa: E402

# ── Count invariants ─────────────────────────────────────────────────────────

# S0186 Unit G2: canon re-baselined to current live state (see module docstring).
EXPECTED_CANON_COUNT = 3711
# Post-S0132 state, NOT re-baselined (UNRESOLVED_DRIFT, see module docstring):
# derive_layers.py has not been re-run against the current canon.
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
        """S0187 Impacto Unidad B (R-B-06): shard COUNT is discovered state,
        not a fixed invariant — a governed reshard (existing shard_canon
        capability) can legitimately change it. What this test actually
        protects is that shards exist, are named per the governed
        tiddlers_<n>.jsonl contract, and are readable; not a specific count."""
        shards = sorted(CANON_DIR.glob("tiddlers_*.jsonl"))
        assert len(shards) > 0, "Expected at least one canon shard, found none"
        for shard in shards:
            assert CANON_SHARD_FILENAME_RE.match(shard.name), (
                f"Shard {shard.name} does not match the governed tiddlers_<n>.jsonl pattern"
            )
            with shard.open(encoding="utf-8") as fh:
                fh.readline()  # must be readable

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
        # S0186 Unit G2: EXPECTED failure, classified UNRESOLVED_DRIFT (see module
        # docstring) — derive_layers.py has not been re-run since canon grew past
        # the last derivation. This is an un-executed pipeline step, not a stale
        # golden number; do not patch this assertion to hide the gap.
        canon = _count_jsonl_records(CANON_DIR, "tiddlers_*.jsonl")
        enriched = _count_jsonl_records(ENRICHED_DIR, "tiddlers_enriched_*.jsonl")
        assert canon == enriched, f"Canon/enriched invariant broken: {canon} != {enriched}"

    def test_ai_count_equals_canon_count(self):
        # S0186 Unit G2: EXPECTED failure, classified UNRESOLVED_DRIFT (see module
        # docstring and test_enriched_count_equals_canon_count above).
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
        # S0186 Unit G2: re-baselined to current live state (see module docstring).
        # Para actualizar: sha256sum data/out/local/tiddlers_*.jsonl
        EXPECTED_HASHES = {
            "tiddlers_1.jsonl":  "4a3c6d5a394e5ed22ea26e102dc08a128937d291c6de1554e823228377eabe92",
            "tiddlers_2.jsonl":  "95281fe9f5f0325e9721bba4df3e025f1fe41e736dcd6109ceec5b2ce9b7c53c",
            "tiddlers_3.jsonl":  "ab6b7853059c61456ef2b4c7661823bf0d1a7c3dd78dbe6befa0352a4cff615d",
            "tiddlers_4.jsonl":  "878d12cffd3ac17fc7029fd1f9ae306b9b730c0d54c8f0e219f351b20fbddd39",
            "tiddlers_5.jsonl":  "95e9e86de6c0ac0870ae8aee9d7732db42219373cb3087f0dd7150efaf1d99f4",
            "tiddlers_6.jsonl":  "7385ca8ece110524f146c333e61897235d8c02ac1d75d70b62b51a227b7f32f9",
            "tiddlers_7.jsonl":  "9600f2fe6070da13c357710a7800c33e97b345b5e785b83f87198ff6dc442944",
            "tiddlers_8.jsonl":  "b87735cb03a153e7ced532b38ca0ad1999ef1e8a1d9fc4f0cb771bcf441acb0b",
            "tiddlers_9.jsonl":  "c4d3b061f801dd10fc704affbd9cbfd8ca97cbbe9329dddef92d445b73d015a9",
            "tiddlers_10.jsonl": "5331fb6bec09608126819c438c3bb42f6d6522c1016623f5bf208241dcc7c68d",
            "tiddlers_11.jsonl": "cd15a99298296364621fe63c7ca96dc5965e47e59de639a07125ca02928d772b",
            "tiddlers_12.jsonl": "3affb7c71a9bd6135e42b90458807ef5765aadf9774bc5cbb4516654a4ebda28",
            "tiddlers_13.jsonl": "bd0bc69bdf2edf9393f743e447bb9f8063bbe290ac983668c8b55d73ce329b0d",
            "tiddlers_14.jsonl": "426197913e14c4c4d41952f0318ec227e559b3ee626e3df8d7223ca8aaab21ae",
            "tiddlers_15.jsonl": "761b80568d5fdf23c6b7ae4bc929782f11baa5352edb98826ffda2d3b89b5e1b",
            "tiddlers_16.jsonl": "4ba02856e2a637c4c31029fd674a7498e2a732fbf4297be77364b98f023b2ffb",
            "tiddlers_17.jsonl": "09dfb603ea14ecf61c6478ff906cb27f396f83ff98114791515e87fd95442c4c",
            "tiddlers_18.jsonl": "be3cd3f965ebb74262613708447cca7a81e684da143a88b1eb244df909c64c4c",
            "tiddlers_19.jsonl": "3685c2d26c50f62ee21c891c97158da5c9f5729fad8278ac2c131cb2660dcf62",
            "tiddlers_20.jsonl": "60def462c65558745f86408274e940060f2d5f98f714ffc342b2563dd2d64f6f",
            "tiddlers_21.jsonl": "542763cb8edf6e67b6ec9477da2e8be57ca0f77b30f5c7e4ff4c4032793186da",
            "tiddlers_22.jsonl": "1336ab0378c1bccd687049b09b579a6f734e5f3046f10ff4ea659eafe139e81d",
            "tiddlers_23.jsonl": "ac543755e73a9722732de3ad30d59f940815c8dcf3d40bd0fb0b6e71238beffe",
            "tiddlers_24.jsonl": "2c852a67e9fea0a6158171617f08726ebcf5d1bbd4ff3905a558584130a24fc9",
            "tiddlers_25.jsonl": "a7ccdc344d6f616f8a4252324b944d1f37c431241c849f05ccd2c73957db1d58",
            "tiddlers_26.jsonl": "09ff0470c0c7cb1e948e13c230d863c698a4bd56ef8b75762960778b66dbe7a8",
            "tiddlers_27.jsonl": "8ce10e122be99506c8313a390bf42a2b691bedbf0b06bc6eac8644008b044b07",
            "tiddlers_28.jsonl": "7cc65e1a0b8f1dc1d47228192a647a581dbb0e6ce14ea7d54a380fd1c5ac0700",
            "tiddlers_29.jsonl": "8409998e75394c888d19ae0184a1061e164da11c1796e63a445fe3b1986fec73",
            "tiddlers_30.jsonl": "735f5e2e9d43e1dd7f7879f0308d32764498905b92a511e97a43a8294f78e7f3",
            "tiddlers_31.jsonl": "69e47d176f281307ac2627d0f72c6522fc41cbab4a800a1332428834a7e892f9",
            "tiddlers_32.jsonl": "b9077d658da33a234c507ad862389443edadb88b2ca47d8dfba41d2623f9e7e0",
            "tiddlers_33.jsonl": "13df480df4bd5d249c4dc9602f4d62b1a2bc8802f64bd198125bb60b44cca784",
            "tiddlers_34.jsonl": "6f7cf816a1d188677ad34b0475e413606b45f5ded042426f48c835c5ab968ae0",
            "tiddlers_35.jsonl": "16ae84b0d67e1b2737dfc5cdca61f81483ba3d44ae0df8d920f364c9fdbb8787",
            "tiddlers_36.jsonl": "52330f8c1b5586de3fc5499cb7a3f8f13ebe40aed2d69d4a7ee4773e0f9efc22",
            "tiddlers_37.jsonl": "3170674ec3ea83cd83ed36acdbbccd904212f338bf7b75a70296d11d490dd149",
            "tiddlers_38.jsonl": "48c1a61281b5efe8975944c788160a5ee302905b8017fbd8893a6d19b8ec5337",
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
