#!/usr/bin/env python3
"""S0186 Unit E — agent sync and operational binding, read-only.

The session contract's E gate requires reproducible runtime profiles for
*both* canonical agents, binding to session intent and Canon snapshot,
explicit surfacing of unresolved dependencies, and an intact legacy
fallback that is never silently merged with canonical evidence.

Two agents are declared as canonical ``agent_definition`` records in the
live Canon (``data/out/local/tiddlers_29.jsonl``), each carrying a
``relations`` graph (``parte_de`` / ``requiere`` / ``usa``) whose
``target_id`` values point at other Canon records:

- ``#### 🤖🌀 Agente de Contexto de Sesión``
- ``#### 🤖🌀 Agente de Calidad y Reconstrucción``

``artifact_routing.route_artifact`` already recognizes both titles and
dispatches them to the ``agent_definition`` family (Unit A).  No owner
module previously resolved their canonical identity, ``requiere``
dependency graph or bound them to a runtime session/snapshot -- that is
the gap this module closes.

This module owns none of the Canon-reading primitives it uses: it calls
``audit_tags_inventory.read_canon_records`` for shard iteration and
``relation_admission_gate.aggregate_canon_hash`` / ``count_canon_records``
for the snapshot binding, exactly as other S0186 units do.  It never
writes to Canon, never admits, never applies and never modifies the two
canonical agent records it reads.
"""

from __future__ import annotations

import glob
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
LOCAL_ROOT = REPO_ROOT / "data" / "out" / "local"

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from audit_tags_inventory import DEFAULT_CANON_GLOB, read_canon_records  # noqa: E402
from relation_admission_gate import aggregate_canon_hash, count_canon_records  # noqa: E402
from artifact_routing import route_artifact  # noqa: E402


AGENT_TITLES: dict[str, str] = {
    "context_agent": "#### 🤖🌀 Agente de Contexto de Sesión",
    "quality_agent": "#### 🤖🌀 Agente de Calidad y Reconstrucción",
}

LEGACY_FALLBACK_PATHS = (
    "AGENTS.md",
    ".agents/skills/tdc-session/SKILL.md",
    ".agents/skills/tdc-session/references/03_impacto_implementacion.md",
)


def _sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def verify_titles_route_as_agent_definition() -> dict[str, str]:
    """Cross-check against Unit A's routing decision, not a duplicated literal.

    Returns the family ``artifact_routing.route_artifact`` assigns to each
    declared title today, so drift between this module's expectations and
    the Unit A routing boundary is visible instead of silently assumed.
    """
    sessions_dir = LOCAL_ROOT / "sessions"
    result: dict[str, str] = {}
    for agent_key, title in AGENT_TITLES.items():
        route = route_artifact(Path("agent-sync-probe.json"), {"title": title}, sessions_dir)
        result[agent_key] = route.family
    return result


def index_canon_by_id(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for record in records:
        record_id = record.get("id")
        if isinstance(record_id, str) and record_id:
            index[record_id] = record
    return index


def _project_canon_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": record.get("id"),
        "title": record.get("title"),
        "version_id": record.get("version_id"),
        "canonical_slug": record.get("canonical_slug"),
    }


def resolve_relation_targets(record: dict[str, Any], canon_index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Resolve every canon-level ``relations`` entry against the live Canon.

    ``record["relations"]`` (canon-native, ``target_id``-keyed) is treated as
    the authoritative dependency graph -- it is what the Canon actually
    persisted, as opposed to the pre-resolution title-keyed declaration
    embedded in the record's own JSON payload.
    """
    by_type: dict[str, list[dict[str, Any]]] = {"parte_de": [], "requiere": [], "usa": []}
    unresolved: list[dict[str, Any]] = []

    for relation in record.get("relations") or []:
        rel_type = relation.get("type")
        target_id = relation.get("target_id")
        target_record = canon_index.get(target_id) if isinstance(target_id, str) else None
        resolved_entry = {
            "type": rel_type,
            "target_id": target_id,
            "evidence": relation.get("evidence"),
            "resolved": target_record is not None,
            "target_title": target_record.get("title") if target_record else None,
            "target_version_id": target_record.get("version_id") if target_record else None,
        }
        by_type.setdefault(rel_type, []).append(resolved_entry)
        if target_record is None:
            unresolved.append(resolved_entry)

    return {
        "by_type": by_type,
        "requiere_total": len(by_type.get("requiere", [])),
        "requiere_resolved": sum(1 for r in by_type.get("requiere", []) if r["resolved"]),
        "requiere_unresolved": [r for r in by_type.get("requiere", []) if not r["resolved"]],
        "usa_total": len(by_type.get("usa", [])),
        "usa_resolved": sum(1 for r in by_type.get("usa", []) if r["resolved"]),
        "usa_unresolved": [r for r in by_type.get("usa", []) if not r["resolved"]],
        "parte_de_total": len(by_type.get("parte_de", [])),
        "parte_de_resolved": sum(1 for r in by_type.get("parte_de", []) if r["resolved"]),
        "all_unresolved": unresolved,
    }


def extract_declared_payload(record: dict[str, Any]) -> dict[str, Any] | None:
    """Parse the record's own declarative JSON payload (``content.plain``).

    Returns ``None`` (never raises) when the payload is missing or not
    parseable, so a malformed canonical record is reported as an explicit
    limitation rather than crashing the whole runtime profile.
    """
    plain = (record.get("content") or {}).get("plain")
    if not isinstance(plain, str):
        return None
    try:
        payload = json.loads(plain)
    except (json.JSONDecodeError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def build_agent_runtime_profile(
    agent_key: str,
    title: str,
    records: list[dict[str, Any]],
    canon_index: dict[str, dict[str, Any]],
    repo_root: Path,
) -> dict[str, Any]:
    matches = [r for r in records if r.get("title") == title]

    if not matches:
        canonical: dict[str, Any] = {
            "status": "NOT_FOUND_IN_CANON",
            "declared_title": title,
        }
    elif len(matches) > 1:
        canonical = {
            "status": "CONFLICT_MULTIPLE_CANON_MATCHES",
            "declared_title": title,
            "matches": [_project_canon_record(r) for r in matches],
        }
    else:
        record = matches[0]
        payload = extract_declared_payload(record)
        relation_resolution = resolve_relation_targets(record, canon_index)
        canonical = {
            "status": "RESOLVED",
            **_project_canon_record(record),
            "document_id": record.get("document_id"),
            "order_in_document": record.get("order_in_document"),
            "rol_principal": (payload or {}).get("rol_principal"),
            "roles_secundarios": (payload or {}).get("roles_secundarios"),
            "declared_payload_parseable": payload is not None,
            "relations": relation_resolution,
        }

    legacy_sources = []
    for rel_path in LEGACY_FALLBACK_PATHS:
        path = repo_root / rel_path
        text = path.read_text(encoding="utf-8")
        legacy_sources.append(
            {
                "path": rel_path,
                "sha256": _sha256_text(text),
                "chars": len(text),
                "bytes": len(text.encode("utf-8")),
            }
        )

    return {
        "agent_key": agent_key,
        "declared_title": title,
        "canonical": canonical,
        "legacy_fallback": {
            "status": "PRESERVED_AS_FALLBACK",
            "note": (
                "Legacy governance sources (AGENTS.md, SKILL.md, active reference "
                "instruction) do not name two distinct agent identities; they "
                "describe the session operator's phase discipline as a whole. "
                "They remain the fallback path if canonical resolution fails, "
                "but are never merged into the canonical section above."
            ),
            "sources": legacy_sources,
        },
        "mixing_guard": "canonical and legacy_fallback are disjoint keys; neither substitutes the other",
    }


def snapshot_binding(canon_glob: str) -> dict[str, Any]:
    return {
        "shards": len(glob.glob(canon_glob)),
        "records": count_canon_records(canon_glob),
        "manifest_sha256": "sha256:" + aggregate_canon_hash(canon_glob),
    }


def evaluate_agent_sync(
    session_id: str,
    branch: str,
    head: str,
    canon_glob: str = DEFAULT_CANON_GLOB,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    records = read_canon_records(canon_glob)
    canon_index = index_canon_by_id(records)

    profiles = {
        agent_key: build_agent_runtime_profile(agent_key, title, records, canon_index, repo_root)
        for agent_key, title in AGENT_TITLES.items()
    }

    routing_cross_check = verify_titles_route_as_agent_definition()

    unresolved_dependencies: list[dict[str, Any]] = []
    both_resolved = True
    for agent_key, profile in profiles.items():
        canonical = profile["canonical"]
        if canonical["status"] != "RESOLVED":
            both_resolved = False
            continue
        for entry in canonical["relations"]["requiere_unresolved"]:
            unresolved_dependencies.append({"agent_key": agent_key, **entry})

    if both_resolved and not unresolved_dependencies:
        overall_status = "AGENT_SYNC_BOUND_NO_UNRESOLVED_DEPENDENCIES"
    elif not both_resolved:
        overall_status = "AGENT_SYNC_PARTIAL_CANONICAL_NOT_FOUND"
    else:
        overall_status = "AGENT_SYNC_PARTIAL_UNRESOLVED_REQUIERE_DEPENDENCY"

    return {
        "schema": "s0186-unit-e-agent-sync/v1",
        "session_intent": {"session_id": session_id, "branch": branch, "head": head},
        "snapshot": snapshot_binding(canon_glob),
        "routing_cross_check": routing_cross_check,
        "agents": profiles,
        "unresolved_dependencies": unresolved_dependencies,
        "overall_status": overall_status,
        "protected_operations_invoked": [],
    }


def compute_binding_gate(manifest: dict[str, Any]) -> dict[str, Any]:
    """Independent, data-only gate evaluation over an already-built manifest.

    Deliberately not a method of the quality-agent profile itself: the
    Quality Agent's own canonical definition explicitly forbids an
    implementation self-certifying its own result, so this gate is computed
    by the caller (here, the test suite) from persisted evidence, never
    emitted as a field the profile asserts about itself.
    """
    context_ok = manifest["agents"]["context_agent"]["canonical"]["status"] == "RESOLVED"
    quality_ok = manifest["agents"]["quality_agent"]["canonical"]["status"] == "RESOLVED"
    routing_ok = all(family == "agent_definition" for family in manifest["routing_cross_check"].values())
    no_unresolved = not manifest["unresolved_dependencies"]
    legacy_preserved = all(
        profile["legacy_fallback"]["status"] == "PRESERVED_AS_FALLBACK" and profile["legacy_fallback"]["sources"]
        for profile in manifest["agents"].values()
    )
    no_mixing = all(
        set(profile.keys()) >= {"canonical", "legacy_fallback", "mixing_guard"}
        for profile in manifest["agents"].values()
    )
    return {
        "canonical_found_both": context_ok and quality_ok,
        "routing_consistent_with_unit_a": routing_ok,
        "requiere_dependencies_resolved": no_unresolved,
        "legacy_fallback_preserved": legacy_preserved,
        "canonical_legacy_not_mixed": no_mixing,
        "gate_pass": context_ok and quality_ok and routing_ok and no_unresolved and legacy_preserved and no_mixing,
    }


def main() -> None:
    manifest = evaluate_agent_sync(
        session_id="m04-s0186",
        branch="s0186-routing-sincronizacion-convergencia-memoria-durable-tdc",
        head="69e49bc4e8d78efb6388f815cdbd0da466a73b91",
    )
    out_path = REPO_ROOT / "data" / "tmp" / "s0186-impact" / "unit-e-agent-sync-report.json"
    out_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(compute_binding_gate(manifest), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
