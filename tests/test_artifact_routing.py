from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

from artifact_routing import compare_canonical, route_artifact, validate_routed_artifact


def _session_payload() -> dict:
    return {
        "title": "#### 🌀 Contrato de sesión 0186 = routing-test",
        "type": "text/markdown",
        "created": "20260901000000000",
        "modified": "20260901000000000",
        "session_id": "m04-s0186",
        "module": "m04",
        "session": "S0186",
        "status": "delivered",
        "canonical_slug": "m04-s0186-contrato-routing-test",
        "tags": ["sesion", "contrato", "m04", "s0186"],
        "text": "contenido",
    }


def test_routes_session_before_session_schema(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    path = sessions / "00_contratos" / "m04-s0186-routing-test.md.json"
    path.parent.mkdir(parents=True)
    payload = _session_payload()
    path.write_text(json.dumps(payload), encoding="utf-8")

    route = route_artifact(path, payload, sessions)
    assert route.family == "session_deliverable"
    assert validate_routed_artifact(route, path, payload, sessions)["valid"] is True


def test_routes_dt087_as_thematic_and_does_not_apply_session_schema() -> None:
    sessions = REPO_ROOT / "data" / "out" / "local" / "sessions"
    path = sessions / "06_diagnoses" / "tema" / "diagnostico-tematico-0087-cobertura-canonica-diagnosticos-brecha-sincronizacion-tdc.md.json"
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    payload = json.loads(path.read_text(encoding="utf-8"))

    route = route_artifact(path, payload, sessions)
    assert route.family == "thematic_diagnostic"
    assert validate_routed_artifact(route, path, payload, sessions)["valid"] is True
    assert compare_canonical(route, payload, []) ["decision"] == "UNRESOLVED"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_other_or_unsupported_is_explicitly_unresolved(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    route = route_artifact(tmp_path / "mystery.json", {"title": "mystery"}, sessions)
    assert route.family == "other_or_unsupported"
    assert compare_canonical(route, {"title": "mystery"}, []) ["decision"] == "UNRESOLVED"


def test_declared_policy_and_technical_report_are_not_collapsed_into_session(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    policy = route_artifact(
        tmp_path / "policy.json",
        {"title": "Policy", "source_fields": {"artifact_family": "policy"}},
        sessions,
    )
    report = route_artifact(tmp_path / "report.json", {"title": "Report", "technical_report": True}, sessions)
    assert policy.family == "policy"
    assert report.family == "technical_report"


def test_compare_evidence_covers_same_missing_replacement_and_conflict(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    payload = {"id": "agent-1", "title": "#### 🤖🌀 Agente de Contexto de Sesión", "version_id": "v1"}
    route = route_artifact(tmp_path / "agent.json", payload, sessions)
    assert route.family == "agent_definition"
    assert compare_canonical(route, payload, [payload.copy()]) ["decision"] == "SAME"
    assert compare_canonical(route, payload, []) ["decision"] == "MISSING"
    assert compare_canonical(route, {**payload, "version_id": "v2"}, [payload.copy()]) ["decision"] == "REPLACEMENT"
    assert compare_canonical(route, payload, [{"id": "other", "title": payload["title"], "version_id": "v1"}]) ["decision"] == "CONFLICT"


def test_missing_identity_is_fail_closed(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    payload = {"title": "#### 🤖🌀 Agente de Calidad y Reconstrucción", "version_id": "v1"}
    route = route_artifact(tmp_path / "agent.json", payload, sessions)
    assert compare_canonical(route, payload, []) ["decision"] == "UNRESOLVED"
