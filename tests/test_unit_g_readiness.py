"""S0186 Unit G3/G4 — historical thematic_diagnostic readiness (including the
G4 DT065/DT070 remediation) and S0186 deliverable structural readiness
regression.

Read-only: no admission, no Canon write, no candidate preparation persisted.
Reuses existing family owners (artifact_routing, session_sync) only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

from artifact_routing import compare_canonical, route_artifact, validate_routed_artifact  # noqa: E402
from session_sync import build_thematic_diagnostic_candidate  # noqa: E402

SESSIONS_DIR = REPO_ROOT / "data" / "out" / "local" / "sessions"
TEMA_DIR = SESSIONS_DIR / "06_diagnoses" / "tema"

DT065 = TEMA_DIR / "diagnostico-tematico-065-alineacion-funcional-autoridad-codigo-arqueologia-pipelines-tdc.md.json"
DT070 = TEMA_DIR / "diagnostico-tematico-070-canon-activos-binarios-clasificacion-integridad-reversibilidad.md.json"

# The one governance-withheld reason artifact_routing.compare_canonical ever
# returns for thematic_diagnostic. Names the authority that belongs to the
# normal, future, governed Canon-update procedure -- not a technical defect.
NORMAL_CANON_UPDATE_AUTHORITY_REASON = "canonical_scope_not_authorized_for_thematic_diagnostic"

DELIVERABLES = [
    "00_contratos/m04-s0186-contrato-routing-sincronizacion-convergencia-memoria-durable-tdc.md.json",
    "01_procedencia/m04-s0186-procedencia-routing-sincronizacion-convergencia-memoria-durable-tdc.md.json",
    "02_detalles_de_sesion/m04-s0186-routing-sincronizacion-convergencia-memoria-durable-tdc.md.json",
    "03_hipotesis/m04-s0186-hipotesis-routing-sincronizacion-convergencia-memoria-durable-tdc.md.json",
    "04_balance_de_sesion/m04-s0186-balance-routing-sincronizacion-convergencia-memoria-durable-tdc.md.json",
    "05_propuesta_de_sesion/m04-s0186-propuesta-routing-sincronizacion-convergencia-memoria-durable-tdc.md.json",
    "06_diagnoses/sesion/diagnostico-sesion-s0186-routing-sincronizacion-convergencia-memoria-durable-tdc.md.json",
]


def _readiness_for(path: Path) -> tuple[str, dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    route = route_artifact(path, payload, SESSIONS_DIR)
    validation = validate_routed_artifact(route, path, payload, SESSIONS_DIR)
    if not validation["valid"]:
        return "BLOCKED_BY_ARTIFACT_DEFECT", validation
    try:
        build_thematic_diagnostic_candidate(path, SESSIONS_DIR)
    except ValueError:
        return "BLOCKED_BY_ARTIFACT_DEFECT", validation
    compare = compare_canonical(route, payload, [])
    if compare["decision"] == "UNRESOLVED" and compare["reason"] == NORMAL_CANON_UPDATE_AUTHORITY_REASON:
        return "TECHNICALLY_READY_AWAITING_NORMAL_AUTHORITY", validation
    if compare["decision"] == "UNRESOLVED":
        return "BLOCKED_BY_AUTHORITY", validation
    return compare["decision"], validation


# ── G4: DT065 / DT070 remediation ────────────────────────────────────────────
#
# Before G4, both files carried no canonical_slug field at all (not malformed,
# not ambiguous -- genuinely absent), so session_sync.build_thematic_diagnostic_candidate
# raised ValueError. G4 confirmed the identity is deterministically derivable:
# 32/33 other well-formed thematic diagnostics have canonical_slug == their own
# filename stem, with zero exceptions in that convention (DT064 is the sole,
# untouched, differently-shaped legacy record). G4 added exactly that field
# (canonical_slug = filename stem) to DT065 and DT070 -- title, text, type,
# and created were left byte-identical; only modified was bumped to record the
# structural correction.

def test_dt065_repaired_own_schema_valid_and_identity_resolvable() -> None:
    readiness, validation = _readiness_for(DT065)
    assert validation["valid"] is True
    assert readiness == "TECHNICALLY_READY_AWAITING_NORMAL_AUTHORITY"


def test_dt070_repaired_own_schema_valid_and_identity_resolvable() -> None:
    readiness, validation = _readiness_for(DT070)
    assert validation["valid"] is True
    assert readiness == "TECHNICALLY_READY_AWAITING_NORMAL_AUTHORITY"


def test_dt065_dt070_canonical_slug_matches_filename_convention() -> None:
    """Confirms the repair used the same deterministic convention as every
    other well-formed sibling, not an invented value."""
    for path in (DT065, DT070):
        payload = json.loads(path.read_text(encoding="utf-8"))
        expected_slug = path.name[: -len(".md.json")]
        assert payload["canonical_slug"] == expected_slug


def test_dt065_dt070_title_and_text_untouched_by_repair() -> None:
    """The repair must be minimal: no substantive content rewrite."""
    expected_titles = {
        DT065: "#### 🌀 Diagnóstico temático 0065 = alineación funcional, autoridad de código y arqueología de pipelines TDC",
        DT070: "#### 🌀 Diagnóstico temático 0070 = canon de activos binarios, clasificación, integridad y reversibilidad",
    }
    for path, expected_title in expected_titles.items():
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["title"] == expected_title
        assert payload["text"].startswith("## Diagnóstico temático")


def test_dt065_dt070_identity_deterministic_across_repeated_reads() -> None:
    """Same persisted artifact -> same derived identity, read fresh from disk
    each time (no reliance on in-memory state)."""
    for path in (DT065, DT070):
        first_readiness, _ = _readiness_for(path)
        second_readiness, _ = _readiness_for(path)
        assert first_readiness == second_readiness == "TECHNICALLY_READY_AWAITING_NORMAL_AUTHORITY"


def test_g4_repair_produces_zero_remaining_artifact_defects_in_corpus() -> None:
    """Full corpus rerun from disk: no previously-valid diagnostic regressed,
    and no artifact_defect remains anywhere in the family. Asserts the
    invariant, not a fixed corpus size -- the tema/ corpus grows over time
    (e.g. new diagnostics added by other concurrent sessions), so a hardcoded
    total would be a false regression, not a real one."""
    readiness_counts: dict[str, int] = {}
    total = 0
    for path in sorted(TEMA_DIR.glob("*.md.json")):
        readiness, _ = _readiness_for(path)
        readiness_counts[readiness] = readiness_counts.get(readiness, 0) + 1
        total += 1
    assert readiness_counts.get("BLOCKED_BY_ARTIFACT_DEFECT", 0) == 0
    assert readiness_counts.get("TECHNICALLY_READY_AWAITING_NORMAL_AUTHORITY", 0) == total
    assert total >= 33  # at least the population known as of G4
    assert sum(readiness_counts.values()) == total


def test_dt066_and_dt087_still_well_formed_authority_gated_unaffected_by_g4() -> None:
    dt066 = TEMA_DIR / "diagnostico-tematico-066-evaluacion-calidad-rag-ia-premium-derivados-gobernados-tdc.md.json"
    dt087 = TEMA_DIR / "diagnostico-tematico-0087-cobertura-canonica-diagnosticos-brecha-sincronizacion-tdc.md.json"
    for path in (dt066, dt087):
        assert path.exists(), path
        readiness, validation = _readiness_for(path)
        assert validation["valid"] is True
        assert readiness == "TECHNICALLY_READY_AWAITING_NORMAL_AUTHORITY"


def test_no_thematic_diagnostic_is_silently_ready_for_canon_update() -> None:
    """Canonical scope is deliberately withheld from this whole family (a
    governance boundary, not evaluated by G); no artifact should ever
    classify a full canon-admission decision (SAME/MISSING/REPLACEMENT) under
    the current governance boundary -- only technical readiness pending the
    normal authority."""
    for path in sorted(TEMA_DIR.glob("*.md.json")):
        readiness, _ = _readiness_for(path)
        assert readiness in {
            "TECHNICALLY_READY_AWAITING_NORMAL_AUTHORITY",
            "BLOCKED_BY_AUTHORITY",
            "BLOCKED_BY_ARTIFACT_DEFECT",
        }


def test_s0186_seven_deliverables_have_no_structural_post_blocker() -> None:
    for rel in DELIVERABLES:
        path = SESSIONS_DIR / rel
        assert path.exists(), rel
        payload = json.loads(path.read_text(encoding="utf-8"))  # must parse
        route = route_artifact(path, payload, SESSIONS_DIR)
        validation = validate_routed_artifact(route, path, payload, SESSIONS_DIR)
        assert validation["valid"] is True, (rel, validation["errors"])
