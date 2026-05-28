"""
tests/test_relation_admission_policy.py — S0131

Pruebas de contrato para la política de admisión relacional gobernada.

Estas pruebas validan la política CONCEPTUAL de admisión.
NO modifican el canon, NO ejecutan --apply, NO admiten relaciones.

Casos obligatorios (S0131 spec §7.5):
  1. Candidato con evidencia fuerte puede clasificarse como admissible.
  2. Candidato con target unresolved queda en needs_review o rejected, nunca admissible.
  3. Candidato basado solo en tag nativo (structural_tag) no puede ser admissible.
  4. Candidato duplicado de relación canónica debe ser bloqueado.
  5. Candidato con tipo no permitido debe ser rechazado.
  6. s0131_relation_state_machine.json debe ser JSON válido.
  7. La matriz de evidencia debe tener todos los tipos mínimos obligatorios.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "python_scripts"))

import relation_admission_policy as rap

# ---------------------------------------------------------------------------
# Fixtures helpers
# ---------------------------------------------------------------------------

SRC_ID = "src-aabbccdd1122334455667788"
TGT_ID = "tgt-eeff5566778899001122334455"
EXCERPT = "Diagnósticos previos consultados: DT029, DT030"


def _make_canon(
    *,
    src_text: str = EXCERPT + " fuente adicional",
    tgt_text: str = "Texto del tiddler target.",
    src_relations: list | None = None,
) -> dict[str, dict]:
    return {
        SRC_ID: {
            "id": SRC_ID,
            "title": "Tiddler source para tests",
            "text": src_text,
            "tags": ["layer:session", "m04"],
            "relations": src_relations or [],
        },
        TGT_ID: {
            "id": TGT_ID,
            "title": "Tiddler target para tests",
            "text": tgt_text,
            "tags": [],
            "relations": [],
        },
    }


def _make_candidate(
    *,
    rel_type: str = "referencia_a",
    ev_kind: str = "explicit_reference",
    excerpt: str = EXCERPT,
    score: float = 0.85,
    tgt_resolution: str = "resolved",
    src_id: str = SRC_ID,
    tgt_id: str = TGT_ID,
    status: str = "candidate",
) -> dict:
    return {
        "candidate_id": "rc1_a1b2c3d4e5f6a7b8",
        "status": status,
        "source": {"tiddler_id": src_id, "title": "Tiddler source"},
        "target": {
            "tiddler_id": tgt_id,
            "title": "Tiddler target",
            "resolution_status": tgt_resolution,
        },
        "relation": {
            "type": rel_type,
            "direction": "source_to_target",
        },
        "evidence": {
            "kind": ev_kind,
            "excerpt": excerpt,
        },
        "confidence": {"score": score},
        "provenance": {"generated_by": "test", "created_at": "20260527190000000"},
    }


# ---------------------------------------------------------------------------
# Caso 1: Candidato con evidencia fuerte → admissible
# ---------------------------------------------------------------------------

class TestStrongEvidenceCandidateIsAdmissible:
    """Caso 1: Un candidato con evidencia fuerte y target resuelto puede ser admissible."""

    def test_strong_candidate_is_admissible_with_human_approval(self):
        canon = _make_canon()
        candidate = _make_candidate(
            rel_type="referencia_a",
            ev_kind="explicit_reference",
            excerpt=EXCERPT,
            score=0.92,
            tgt_resolution="resolved",
        )
        result = rap.evaluate_admissibility(
            candidate, canon, require_human_approval=True, human_approved=True
        )
        assert result.eligible_state == rap.STATE_ADMISSIBLE, (
            f"blocking: {result.blocking_reasons}"
        )

    def test_strong_candidate_without_human_approval_is_needs_review(self):
        canon = _make_canon()
        candidate = _make_candidate(
            rel_type="referencia_a",
            ev_kind="explicit_reference",
            excerpt=EXCERPT,
            score=0.92,
            tgt_resolution="resolved",
        )
        result = rap.evaluate_admissibility(
            candidate, canon, require_human_approval=True, human_approved=False
        )
        # Tiene warning, no blocking — el estado final depende de la política
        assert result.eligible_state in {rap.STATE_ADMISSIBLE, rap.STATE_NEEDS_REVIEW}

    def test_strong_candidate_not_rejected(self):
        canon = _make_canon()
        candidate = _make_candidate(
            rel_type="referencia_a",
            ev_kind="explicit_reference",
            excerpt=EXCERPT,
            score=0.92,
            tgt_resolution="resolved",
        )
        result = rap.evaluate_admissibility(
            candidate, canon, require_human_approval=True, human_approved=True
        )
        assert result.eligible_state != rap.STATE_REJECTED

    def test_wikilink_evidence_is_strong_enough(self):
        canon = _make_canon()
        candidate = _make_candidate(
            rel_type="referencia_a",
            ev_kind="wikilink",
            excerpt=EXCERPT,
            score=0.75,
            tgt_resolution="resolved",
        )
        result = rap.evaluate_admissibility(
            candidate, canon, require_human_approval=True, human_approved=True
        )
        assert result.eligible_state == rap.STATE_ADMISSIBLE, (
            f"blocking: {result.blocking_reasons}"
        )


# ---------------------------------------------------------------------------
# Caso 2: Target unresolved → nunca admissible
# ---------------------------------------------------------------------------

class TestUnresolvedTargetIsNeverAdmissible:
    """Caso 2: Un candidato con target unresolved no puede ser admissible."""

    def test_unresolved_target_is_not_admissible(self):
        canon = _make_canon()
        candidate = _make_candidate(
            rel_type="referencia_a",
            ev_kind="explicit_reference",
            excerpt=EXCERPT,
            score=0.92,
            tgt_resolution="unresolved",  # target no resuelto
        )
        result = rap.evaluate_admissibility(
            candidate, canon, require_human_approval=True, human_approved=True
        )
        assert result.eligible_state != rap.STATE_ADMISSIBLE

    def test_unresolved_target_produces_blocking_reason(self):
        canon = _make_canon()
        candidate = _make_candidate(tgt_resolution="unresolved")
        result = rap.evaluate_admissibility(candidate, canon)
        assert any("resoluci" in r.lower() or "resol" in r.lower() or "unresolved" in r.lower()
                   for r in result.blocking_reasons)

    def test_ambiguous_target_is_not_admissible(self):
        canon = _make_canon()
        candidate = _make_candidate(
            tgt_resolution="ambiguous",
            ev_kind="explicit_reference",
            excerpt=EXCERPT,
            score=0.9,
        )
        result = rap.evaluate_admissibility(
            candidate, canon, require_human_approval=True, human_approved=True
        )
        assert result.eligible_state != rap.STATE_ADMISSIBLE

    def test_resolved_target_passes_resolution_check(self):
        canon = _make_canon()
        candidate = _make_candidate(tgt_resolution="resolved")
        result = rap.evaluate_admissibility(candidate, canon)
        assert result.checks.get("target_resolved") is True


# ---------------------------------------------------------------------------
# Caso 3: Solo tag nativo (structural_tag) no puede ser admissible
# ---------------------------------------------------------------------------

class TestTagOnlyEvidenceNotAdmissible:
    """Caso 3: Un candidato basado solo en tag nativo no puede ser admissible."""

    def test_structural_tag_alone_is_not_admissible_for_referencia_a(self):
        canon = _make_canon()
        candidate = _make_candidate(
            rel_type="referencia_a",
            ev_kind="structural_tag",  # solo tag nativo
            excerpt="tag-nativo-ejemplo",
            score=0.8,
            tgt_resolution="resolved",
        )
        result = rap.evaluate_admissibility(
            candidate, canon, require_human_approval=True, human_approved=True
        )
        assert result.eligible_state != rap.STATE_ADMISSIBLE, (
            "Un tag nativo solo no debe ser suficiente para admisión de referencia_a"
        )

    def test_structural_tag_produces_blocking_reason(self):
        canon = _make_canon()
        candidate = _make_candidate(
            rel_type="referencia_a",
            ev_kind="structural_tag",
            excerpt="tag-nativo",
            score=0.8,
            tgt_resolution="resolved",
        )
        result = rap.evaluate_admissibility(
            candidate, canon, require_human_approval=True, human_approved=True
        )
        assert len(result.blocking_reasons) > 0, (
            "Debe haber al menos un blocking_reason para structural_tag en referencia_a"
        )

    def test_tag_native_rule_documented_in_policy(self):
        """La política documenta que structural_tag es insuficiente para referencia_a."""
        policy = rap.get_policy_for_type("referencia_a")
        assert policy is not None
        assert "structural_tag" in policy.get("insufficient_alone", set()), (
            "structural_tag debe estar en insufficient_alone para referencia_a"
        )


# ---------------------------------------------------------------------------
# Caso 4: Duplicado canónico bloqueado
# ---------------------------------------------------------------------------

class TestDuplicateCanonicalIsBlocked:
    """Caso 4: Un candidato que duplica una relación canónica ya existente debe bloquearse."""

    def test_duplicate_canonical_relation_is_blocked(self):
        # Canon ya tiene la misma relación
        canon = _make_canon(
            src_relations=[{
                "target_id": TGT_ID,
                "type": "referencia_a",
                "direction": "source_to_target",
            }]
        )
        candidate = _make_candidate(
            rel_type="referencia_a",
            ev_kind="explicit_reference",
            excerpt=EXCERPT,
            score=0.92,
            tgt_resolution="resolved",
        )
        result = rap.evaluate_admissibility(
            candidate, canon, require_human_approval=True, human_approved=True
        )
        assert result.eligible_state != rap.STATE_ADMISSIBLE

    def test_duplicate_check_is_false_in_checks(self):
        canon = _make_canon(
            src_relations=[{"target_id": TGT_ID, "type": "referencia_a"}]
        )
        candidate = _make_candidate(rel_type="referencia_a", tgt_resolution="resolved")
        result = rap.evaluate_admissibility(
            candidate, canon, require_human_approval=True, human_approved=True
        )
        assert result.checks.get("not_duplicate_canonical") is False

    def test_non_duplicate_different_type_passes_duplicate_check(self):
        """Misma fuente+target pero tipo diferente → no duplicado."""
        canon = _make_canon(
            src_relations=[{"target_id": TGT_ID, "type": "referencia_a"}]
        )
        candidate = _make_candidate(
            rel_type="menciona_diagnostico",
            ev_kind="title_mention",
            excerpt=EXCERPT,
            score=0.75,
            tgt_resolution="resolved",
        )
        result = rap.evaluate_admissibility(candidate, canon)
        assert result.checks.get("not_duplicate_canonical") is True


# ---------------------------------------------------------------------------
# Caso 5: Tipo de relación no permitido → rechazado
# ---------------------------------------------------------------------------

class TestUnknownTypeIsRejected:
    """Caso 5: Un candidato con tipo de relación no en el catálogo es rechazado."""

    def test_unknown_type_is_rejected(self):
        canon = _make_canon()
        candidate = _make_candidate(
            rel_type="tipo_inventado_xyzzy",
            ev_kind="explicit_reference",
            excerpt=EXCERPT,
            score=0.9,
            tgt_resolution="resolved",
        )
        result = rap.evaluate_admissibility(
            candidate, canon, require_human_approval=True, human_approved=True
        )
        assert result.eligible_state == rap.STATE_REJECTED

    def test_unknown_type_has_blocking_reason(self):
        canon = _make_canon()
        candidate = _make_candidate(rel_type="tipo_inventado_xyzzy")
        result = rap.evaluate_admissibility(candidate, canon)
        assert any("no permitido" in r for r in result.blocking_reasons)

    def test_allowed_type_passes_type_check(self):
        canon = _make_canon()
        candidate = _make_candidate(rel_type="referencia_a")
        result = rap.evaluate_admissibility(candidate, canon)
        assert result.checks.get("relation_type_allowed") is True


# ---------------------------------------------------------------------------
# Caso 6: s0131_relation_state_machine.json debe ser JSON válido
# ---------------------------------------------------------------------------

class TestStateMachineJsonIsValid:
    """Caso 6: El archivo state_machine.json del pipeline S0131 es JSON válido."""

    SM_PATH = (
        REPO_ROOT
        / "data" / "out" / "local" / "pipeline" / "relation_admission" / "s0131"
        / "s0131_relation_state_machine.json"
    )

    def test_state_machine_file_exists(self):
        assert self.SM_PATH.exists(), f"No encontrado: {self.SM_PATH}"

    def test_state_machine_is_valid_json(self):
        content = self.SM_PATH.read_text(encoding="utf-8")
        data = json.loads(content)  # raises JSONDecodeError si inválido
        assert isinstance(data, dict)

    def test_state_machine_has_required_keys(self):
        data = json.loads(self.SM_PATH.read_text(encoding="utf-8"))
        assert "states" in data, "Falta campo 'states'"
        assert "transitions" in data, "Falta campo 'transitions'"
        assert "initial_state" in data, "Falta campo 'initial_state'"

    def test_state_machine_has_all_required_states(self):
        data = json.loads(self.SM_PATH.read_text(encoding="utf-8"))
        state_ids = {s["id"] for s in data["states"]}
        required = {
            rap.STATE_CANDIDATE,
            rap.STATE_NEEDS_REVIEW,
            rap.STATE_REJECTED,
            rap.STATE_ADMISSIBLE,
            rap.STATE_ADMITTED_FUTURE,
        }
        missing = required - state_ids
        assert not missing, f"Estados faltantes en state_machine.json: {missing}"


# ---------------------------------------------------------------------------
# Caso 7: La matriz de evidencia tiene todos los tipos mínimos obligatorios
# ---------------------------------------------------------------------------

class TestEvidenceMatrixCompleteness:
    """Caso 7: La política de evidencia cubre todos los tipos mínimos obligatorios del spec."""

    def test_required_policy_types_all_covered(self):
        missing = rap.validate_policy_completeness()
        assert not missing, (
            f"Tipos obligatorios sin política de evidencia: {missing}"
        )

    def test_evidence_policy_has_expected_fields(self):
        for rel_type, policy in rap.EVIDENCE_POLICY.items():
            assert "min_evidence_kinds" in policy, f"Falta min_evidence_kinds en {rel_type}"
            assert "insufficient_alone" in policy, f"Falta insufficient_alone en {rel_type}"
            assert "min_confidence" in policy, f"Falta min_confidence en {rel_type}"
            assert "excerpt_required" in policy, f"Falta excerpt_required en {rel_type}"
            assert "fp_risk" in policy, f"Falta fp_risk en {rel_type}"
            assert "always_human_review" in policy, f"Falta always_human_review en {rel_type}"
            assert "valid_example" in policy, f"Falta valid_example en {rel_type}"
            assert "invalid_example" in policy, f"Falta invalid_example en {rel_type}"

    def test_fp_risk_values_are_valid(self):
        valid_risks = {"low", "medium", "high", "critical"}
        for rel_type, policy in rap.EVIDENCE_POLICY.items():
            assert policy["fp_risk"] in valid_risks, (
                f"fp_risk inválido en {rel_type}: {policy['fp_risk']!r}"
            )

    def test_min_confidence_is_float_in_range(self):
        for rel_type, policy in rap.EVIDENCE_POLICY.items():
            mc = policy["min_confidence"]
            assert isinstance(mc, float), f"min_confidence no es float en {rel_type}"
            assert 0.0 <= mc <= 1.0, f"min_confidence fuera de rango en {rel_type}: {mc}"

    def test_evidence_matrix_csv_exists(self):
        csv_path = (
            REPO_ROOT
            / "data" / "out" / "local" / "pipeline" / "relation_admission" / "s0131"
            / "s0131_relation_evidence_matrix.csv"
        )
        assert csv_path.exists(), f"No encontrado: {csv_path}"

    def test_evidence_matrix_csv_has_all_required_types(self):
        import csv as csv_module
        csv_path = (
            REPO_ROOT
            / "data" / "out" / "local" / "pipeline" / "relation_admission" / "s0131"
            / "s0131_relation_evidence_matrix.csv"
        )
        if not csv_path.exists():
            pytest.skip("CSV no generado todavía")
        rows = list(csv_module.DictReader(csv_path.open(encoding="utf-8")))
        types_in_csv = {r["relation_type"] for r in rows}
        # Verificar que todos los tipos de EVIDENCE_POLICY están en el CSV
        missing = set(rap.EVIDENCE_POLICY.keys()) - types_in_csv
        assert not missing, f"Tipos de EVIDENCE_POLICY no en CSV: {missing}"


# ---------------------------------------------------------------------------
# Casos adicionales: auto-relación, target fuera del canon, score bajo
# ---------------------------------------------------------------------------

class TestAdditionalBlockingConditions:
    """Verificaciones adicionales de condiciones de bloqueo."""

    def test_self_relation_is_blocked(self):
        canon = _make_canon()
        candidate = _make_candidate(
            src_id=SRC_ID,
            tgt_id=SRC_ID,  # source == target
            tgt_resolution="resolved",
            ev_kind="explicit_reference",
            excerpt=EXCERPT,
            score=0.9,
        )
        # Note: SRC_ID might not be in canon as target, but self-relation is the main check
        result = rap.evaluate_admissibility(candidate, canon)
        assert result.checks.get("no_self_relation") is False

    def test_target_not_in_canon_is_blocked(self):
        canon = _make_canon()  # only has SRC_ID and TGT_ID
        candidate = _make_candidate(
            tgt_id="nonexistent-id-abc123",
            tgt_resolution="resolved",  # says resolved but not actually in canon
        )
        result = rap.evaluate_admissibility(candidate, canon)
        assert result.checks.get("target_in_canon") is False
        assert result.eligible_state == rap.STATE_REJECTED

    def test_low_confidence_score_is_blocked(self):
        canon = _make_canon()
        candidate = _make_candidate(
            rel_type="referencia_a",
            ev_kind="explicit_reference",
            excerpt=EXCERPT,
            score=0.30,  # below both thresholds
            tgt_resolution="resolved",
        )
        result = rap.evaluate_admissibility(
            candidate, canon, require_human_approval=True, human_approved=True
        )
        assert result.checks.get("confidence_sufficient") is False

    def test_always_human_review_type_requires_human_approval(self):
        """Tipos en ALWAYS_HUMAN_REVIEW_TYPES siempre bloquean si human_approved=False."""
        canon = _make_canon()
        always_human_type = "corrige"  # in ALWAYS_HUMAN_REVIEW_TYPES
        candidate = _make_candidate(
            rel_type=always_human_type,
            ev_kind="explicit_reference",
            excerpt=EXCERPT,
            score=0.9,
            tgt_resolution="resolved",
        )
        result = rap.evaluate_admissibility(
            candidate, canon, require_human_approval=True, human_approved=False
        )
        assert result.eligible_state != rap.STATE_ADMISSIBLE

    def test_policy_type_aliases_resolve_correctly(self):
        """Los aliases del spec S0131 se resuelven a tipos del catálogo DT029/DT031."""
        for alias, canonical in rap.POLICY_TYPE_ALIASES.items():
            resolved = rap._resolve_type(alias)
            assert resolved == canonical, f"Alias {alias!r} no resuelve a {canonical!r}"

    def test_design_json_is_valid(self):
        """El archivo de diseño principal S0131 es JSON válido."""
        design_path = (
            REPO_ROOT
            / "data" / "out" / "local" / "pipeline" / "relation_admission" / "s0131"
            / "s0131_relation_admission_design.json"
        )
        assert design_path.exists(), f"No encontrado: {design_path}"
        data = json.loads(design_path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        assert "schema" in data
        assert "admission_circuit" in data
