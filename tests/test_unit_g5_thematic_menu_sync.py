"""S0186 Unit G5 — thematic_diagnostic menu-sync reconciliation regression.

Covers the family-normalization fix in session_sync.build_thematic_diagnostic_candidate
(order_in_document, source_fields.session_origin) and the DT065/DT070 tags repair,
against the real admission-gate contract in admit_session_candidates.py /
canon_proposal.py. Read-only against Canon: no admission, no apply.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

import admit_session_candidates as admit  # noqa: E402
import canon_proposal  # noqa: E402
import session_sync  # noqa: E402
from artifact_routing import route_artifact  # noqa: E402

SESSIONS_DIR = REPO_ROOT / "data" / "out" / "local" / "sessions"
TEMA_DIR = SESSIONS_DIR / "06_diagnoses" / "tema"

DT065 = TEMA_DIR / "diagnostico-tematico-065-alineacion-funcional-autoridad-codigo-arqueologia-pipelines-tdc.md.json"
DT070 = TEMA_DIR / "diagnostico-tematico-070-canon-activos-binarios-clasificacion-integridad-reversibilidad.md.json"
DT087 = TEMA_DIR / "diagnostico-tematico-0087-cobertura-canonica-diagnosticos-brecha-sincronizacion-tdc.md.json"


def _thematic_payload(canonical_slug: str, tags: list[str] | None = None) -> dict:
    payload = {
        "title": f"#### 🌀 Diagnóstico temático de prueba = {canonical_slug}",
        "type": "text/markdown",
        "created": "20260901000000000",
        "modified": "20260901000000000",
        "canonical_slug": canonical_slug,
        "text": "## contenido de prueba",
    }
    if tags is not None:
        payload["tags"] = tags
    return payload


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _admission_field_errors(record: dict) -> list[str]:
    """Reuse the exact presence-only gate from admit_session_candidates.py."""
    missing_fields = [field for field in admit.REQUIRED_CANON_FIELDS if field not in record]
    if missing_fields:
        return [f"missing required fields: {', '.join(missing_fields)}"]
    source_fields = record.get("source_fields")
    if not isinstance(source_fields, dict):
        return ["source_fields must be a non-empty object"]
    missing_source_fields = [
        field for field in admit.REQUIRED_SOURCE_FIELDS if not admit._safe_str(source_fields.get(field))
    ]
    if missing_source_fields:
        return [f"missing source_fields: {', '.join(missing_source_fields)}"]
    return []


# ── order_in_document / session_origin (adapter fix) ────────────────────────

def test_thematic_candidate_has_positive_order_in_document(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    slug = "diagnostico-tematico-999-prueba-order"
    path = sessions / "06_diagnoses" / "tema" / f"{slug}.md.json"
    _write(path, _thematic_payload(slug, tags=["diagnostico-tematico", "DT999"]))

    candidate = session_sync.build_thematic_diagnostic_candidate(path, sessions)

    assert isinstance(candidate.record["order_in_document"], int)
    assert candidate.record["order_in_document"] >= 1


def test_thematic_candidate_session_origin_is_own_canonical_slug_not_fabricated(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    slug = "diagnostico-tematico-999-prueba-origin"
    path = sessions / "06_diagnoses" / "tema" / f"{slug}.md.json"
    _write(path, _thematic_payload(slug, tags=["diagnostico-tematico", "DT999"]))

    candidate = session_sync.build_thematic_diagnostic_candidate(path, sessions)

    session_origin = candidate.record["source_fields"]["session_origin"]
    assert session_origin == slug
    # Must not look like a session id (mXX-sNNNN) -- this is the diagnostic's
    # own identity, not an invented session membership claim.
    assert not session_origin.startswith("m0")
    assert "-s0" not in session_origin[:6]


def test_thematic_candidate_now_clears_the_admission_presence_gate(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    slug = "diagnostico-tematico-999-prueba-gate"
    path = sessions / "06_diagnoses" / "tema" / f"{slug}.md.json"
    _write(path, _thematic_payload(slug, tags=["diagnostico-tematico", "DT999"]))

    candidate = session_sync.build_thematic_diagnostic_candidate(path, sessions)

    assert _admission_field_errors(candidate.record) == []


# ── DT065 / DT070 (legacy no-tags case) ──────────────────────────────────────

def test_dt065_and_dt070_repaired_tags_clear_admission_gate() -> None:
    for path in (DT065, DT070):
        candidate = session_sync.build_thematic_diagnostic_candidate(path, SESSIONS_DIR)
        assert candidate.record["tags"], f"{path.name}: tags still empty"
        assert candidate.record["source_tags"] == candidate.record["tags"]
        assert candidate.record["normalized_tags"] == candidate.record["tags"]
        assert _admission_field_errors(candidate.record) == []


def test_dt065_dt070_tags_match_mechanical_sibling_convention() -> None:
    """The repair must reuse the exact two-tag baseline convention 30+ other
    thematic diagnostics already use (family tag + DT-number tag), not
    invented topic keywords."""
    payload_065 = json.loads(DT065.read_text(encoding="utf-8"))
    payload_070 = json.loads(DT070.read_text(encoding="utf-8"))
    assert payload_065["tags"] == ["diagnostico-tematico", "DT065"]
    assert payload_070["tags"] == ["diagnostico-tematico", "DT070"]


def test_legacy_no_tags_thematic_diagnostic_still_fails_closed_before_repair(tmp_path: Path) -> None:
    """Characterizes the original DT065/DT070 defect on a synthetic fixture:
    a thematic diagnostic with no tags field at all builds a candidate with
    tags=[] (present but empty) -- the admission presence-only gate does not
    catch this (the key exists), but canon_proposal.validate_lines's
    value-level check (tags must be a non-empty array) correctly still
    fails it closed. This is the real, value-level gate that DT065/DT070
    originally failed once their (previously) empty tags reached this stage."""
    sessions = tmp_path / "sessions"
    slug = "diagnostico-tematico-999-legacy-no-tags"
    path = sessions / "06_diagnoses" / "tema" / f"{slug}.md.json"
    _write(path, _thematic_payload(slug, tags=None))  # no tags key at all

    candidate = session_sync.build_thematic_diagnostic_candidate(path, sessions)
    assert candidate.record["tags"] == []  # present, but empty
    assert _admission_field_errors(candidate.record) == []  # presence-only gate does not catch this

    errors = canon_proposal.validate_lines([candidate.record], canon_dir=None, allow_existing=True)
    assert any("tags must be a non-empty array" in e for e in errors)


# ── session_deliverable regression (must be unaffected) ─────────────────────

def test_session_deliverable_order_in_document_and_session_origin_unaffected(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    path = sessions / "00_contratos" / "m04-s0999-contrato-prueba-g5.md.json"
    _write(
        path,
        {
            "title": "#### 🌀 Contrato de sesión 0999 = prueba-g5",
            "type": "text/markdown",
            "created": "20260901000000000",
            "modified": "20260901000000000",
            "session_id": "m04-s0999",
            "module": "m04",
            "session": "S0999",
            "status": "delivered",
            "canonical_slug": "m04-s0999-contrato-prueba-g5",
            "tags": ["sesion", "contrato", "m04", "s0999"],
            "text": "contenido",
        },
    )

    candidate = session_sync.build_candidate_from_artifact(path, sessions)

    # Session semantics unchanged by the thematic-only G5 fix: session_origin
    # is still extract_session_id(path) (the artifact's own filename-stem
    # identity, per session_artifact_governance.extract_session_id), and
    # order_in_document still the family's fixed position among the seven
    # ordinary deliverables -- neither is touched by the thematic-only fix.
    assert candidate.record["source_fields"]["session_origin"] == "m04-s0999-contrato-prueba-g5"
    assert candidate.record["order_in_document"] == 1  # 00_contratos is position 1
    assert _admission_field_errors(candidate.record) == []


def test_real_dt087_still_routes_and_builds_unaffected_by_g5() -> None:
    route = route_artifact(DT087, json.loads(DT087.read_text(encoding="utf-8")), SESSIONS_DIR)
    assert route.family == "thematic_diagnostic"
    candidate = session_sync.build_thematic_diagnostic_candidate(DT087, SESSIONS_DIR)
    assert candidate.record["order_in_document"] == 1
    assert candidate.record["source_fields"]["session_origin"] == candidate.record["canonical_slug"]
    assert _admission_field_errors(candidate.record) == []


# ── end-to-end: real admit_session_candidates.validate over the live corpus ─

def test_full_thematic_corpus_passes_admission_validate(tmp_path: Path) -> None:
    """End-to-end (not just field-presence): builds every live thematic
    diagnostic candidate, writes them to a real JSONL, and runs them through
    the actual admit_session_candidates validation path canon_proposal.py
    included) -- must be zero rejects."""
    candidates = []
    for path in sorted(TEMA_DIR.glob("*.md.json")):
        try:
            candidate = session_sync.build_thematic_diagnostic_candidate(path, SESSIONS_DIR)
        except ValueError:
            continue  # not a candidate-eligible thematic diagnostic; not this test's concern
        candidates.append(candidate.record)

    assert len(candidates) >= 30  # sanity: corpus is populated

    candidate_file = tmp_path / "thematic-candidates.jsonl"
    with candidate_file.open("w", encoding="utf-8") as handle:
        for record in candidates:
            handle.write(json.dumps(record, ensure_ascii=False))
            handle.write("\n")

    validation = admit._build_candidate_validation(candidate_file, SESSIONS_DIR)
    assert validation.rejected == [], validation.rejected
    assert len(validation.entries) == len(candidates)
