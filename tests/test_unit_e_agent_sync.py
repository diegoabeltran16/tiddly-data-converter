"""S0186 Unit E -- agent sync and operational binding.

The E gate requires reproducible runtime profiles for both canonical
agents (Agente de Contexto de Sesión, Agente de Calidad y Reconstrucción),
binding to session intent and Canon snapshot, explicit surfacing of
unresolved ``requiere`` dependencies, and an intact legacy fallback that is
never silently merged with canonical evidence.

``agent_sync.py`` (new in Unit E) owns none of the Canon-reading
primitives it composes: it reuses ``audit_tags_inventory.read_canon_records``
and ``relation_admission_gate.aggregate_canon_hash`` / ``count_canon_records``,
and cross-checks its two agent titles against ``artifact_routing.route_artifact``
(Unit A) instead of duplicating that routing decision. This file tests only
what is new for E.
"""

from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "src" / "python_scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import agent_sync  # noqa: E402
from relation_admission_gate import aggregate_canon_hash, count_canon_records  # noqa: E402


SESSION_KWARGS = dict(
    session_id="m04-s0186",
    branch="s0186-routing-sincronizacion-convergencia-memoria-durable-tdc",
    head="69e49bc4e8d78efb6388f815cdbd0da466a73b91",
)


# ── routing cross-check: E must not duplicate Unit A's decision silently ────

def test_both_canonical_titles_still_route_as_agent_definition() -> None:
    result = agent_sync.verify_titles_route_as_agent_definition()
    assert result == {"context_agent": "agent_definition", "quality_agent": "agent_definition"}


# ── canonical resolution against the live Canon ─────────────────────────────

def test_context_agent_resolves_with_id_version_and_requiere_dependencies() -> None:
    manifest = agent_sync.evaluate_agent_sync(**SESSION_KWARGS)
    canonical = manifest["agents"]["context_agent"]["canonical"]
    assert canonical["status"] == "RESOLVED"
    assert canonical["id"] == "acb035b3-2eb7-5367-b773-9c5326c72921"
    assert canonical["version_id"] == "sha256:26df2c942a79ad708da7995f5215b0588fea450ac3d03aaec0a25610d6d6eb3f"
    assert canonical["relations"]["requiere_total"] == 4
    assert canonical["relations"]["requiere_resolved"] == 4
    assert canonical["relations"]["requiere_unresolved"] == []


def test_quality_agent_resolves_with_id_version_and_requiere_dependencies() -> None:
    manifest = agent_sync.evaluate_agent_sync(**SESSION_KWARGS)
    canonical = manifest["agents"]["quality_agent"]["canonical"]
    assert canonical["status"] == "RESOLVED"
    assert canonical["id"] == "04c32c24-a6be-5855-be9a-8f26fa0c26ee"
    assert canonical["version_id"] == "sha256:24a2b40409d4f5be94f4f95e2c013888e15beeb2b674ba7c77e32edb94520536"
    assert canonical["relations"]["requiere_total"] == 3
    assert canonical["relations"]["requiere_resolved"] == 3
    assert canonical["relations"]["requiere_unresolved"] == []


def test_no_unresolved_dependency_is_surfaced_for_the_live_canon() -> None:
    manifest = agent_sync.evaluate_agent_sync(**SESSION_KWARGS)
    assert manifest["unresolved_dependencies"] == []
    assert manifest["overall_status"] == "AGENT_SYNC_BOUND_NO_UNRESOLVED_DEPENDENCIES"


# ── missing canonical definition must be reported, never fabricated ────────

def test_missing_canonical_agent_is_explicitly_flagged_not_fabricated() -> None:
    profile = agent_sync.build_agent_runtime_profile(
        "phantom_agent", "#### does not exist", records=[], canon_index={}, repo_root=REPO_ROOT
    )
    assert profile["canonical"]["status"] == "NOT_FOUND_IN_CANON"
    assert "id" not in profile["canonical"]
    assert "version_id" not in profile["canonical"]


def test_unresolved_requiere_target_is_surfaced_not_silently_dropped() -> None:
    fake_record = {
        "id": "fake-id",
        "title": "#### fake agent",
        "version_id": "sha256:fake",
        "canonical_slug": "fake-agent",
        "relations": [
            {"type": "requiere", "target_id": "does-not-exist", "evidence": "content_embedded"},
        ],
        "content": {"plain": json.dumps({"rol_principal": "procedimiento"})},
    }
    profile = agent_sync.build_agent_runtime_profile(
        "phantom_agent", "#### fake agent", records=[fake_record], canon_index={}, repo_root=REPO_ROOT
    )
    canonical = profile["canonical"]
    assert canonical["status"] == "RESOLVED"
    assert canonical["relations"]["requiere_resolved"] == 0
    assert len(canonical["relations"]["requiere_unresolved"]) == 1
    assert canonical["relations"]["requiere_unresolved"][0]["target_id"] == "does-not-exist"


def test_conflict_multiple_canon_matches_is_reported_not_arbitrarily_picked() -> None:
    dup = [
        {"id": "a", "title": "#### dup", "version_id": "v1"},
        {"id": "b", "title": "#### dup", "version_id": "v2"},
    ]
    profile = agent_sync.build_agent_runtime_profile(
        "dup_agent", "#### dup", records=dup, canon_index={}, repo_root=REPO_ROOT
    )
    assert profile["canonical"]["status"] == "CONFLICT_MULTIPLE_CANON_MATCHES"
    assert len(profile["canonical"]["matches"]) == 2


# ── legacy fallback preserved and never merged into canonical section ──────

def test_legacy_fallback_sources_are_read_fresh_and_hashed() -> None:
    manifest = agent_sync.evaluate_agent_sync(**SESSION_KWARGS)
    for profile in manifest["agents"].values():
        legacy = profile["legacy_fallback"]
        assert legacy["status"] == "PRESERVED_AS_FALLBACK"
        assert len(legacy["sources"]) == len(agent_sync.LEGACY_FALLBACK_PATHS)
        for source in legacy["sources"]:
            assert source["sha256"].startswith("sha256:")
            assert source["bytes"] > 0


def test_canonical_and_legacy_sections_are_never_merged() -> None:
    manifest = agent_sync.evaluate_agent_sync(**SESSION_KWARGS)
    for profile in manifest["agents"].values():
        assert "canonical" in profile and "legacy_fallback" in profile
        # Canonical identity fields must never appear under legacy_fallback.
        assert "id" not in profile["legacy_fallback"]
        assert "version_id" not in profile["legacy_fallback"]
        # Legacy source listing must never appear under canonical.
        assert "sources" not in profile["canonical"]


# ── binding to session intent and Canon snapshot ────────────────────────────

def test_manifest_binds_session_intent_and_live_canon_snapshot() -> None:
    manifest = agent_sync.evaluate_agent_sync(**SESSION_KWARGS)
    assert manifest["session_intent"] == SESSION_KWARGS
    assert manifest["snapshot"]["records"] == count_canon_records(agent_sync.DEFAULT_CANON_GLOB)
    assert manifest["snapshot"]["manifest_sha256"] == "sha256:" + aggregate_canon_hash(agent_sync.DEFAULT_CANON_GLOB)
    assert manifest["snapshot"]["shards"] == len(glob.glob(agent_sync.DEFAULT_CANON_GLOB))


# ── convergence: repeated evaluation on unchanged Canon is stable ──────────

def test_evaluate_agent_sync_is_deterministic_across_two_isolated_calls() -> None:
    first = agent_sync.evaluate_agent_sync(**SESSION_KWARGS)
    second = agent_sync.evaluate_agent_sync(**SESSION_KWARGS)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


# ── no canon mutation: read-only guarantee ──────────────────────────────────

def test_evaluate_agent_sync_does_not_modify_canon_shards() -> None:
    shard_paths = sorted(glob.glob(agent_sync.DEFAULT_CANON_GLOB))
    before = {p: Path(p).read_bytes() for p in shard_paths}
    agent_sync.evaluate_agent_sync(**SESSION_KWARGS)
    after = {p: Path(p).read_bytes() for p in shard_paths}
    assert before == after


# ── independent gate: not a self-certification by the quality-agent profile ─

def test_compute_binding_gate_passes_on_the_live_manifest() -> None:
    manifest = agent_sync.evaluate_agent_sync(**SESSION_KWARGS)
    gate = agent_sync.compute_binding_gate(manifest)
    assert gate["gate_pass"] is True
    assert gate["canonical_found_both"] is True
    assert gate["requiere_dependencies_resolved"] is True
    assert gate["legacy_fallback_preserved"] is True
    assert gate["canonical_legacy_not_mixed"] is True


def test_compute_binding_gate_fails_closed_when_canonical_missing() -> None:
    manifest = agent_sync.evaluate_agent_sync(**SESSION_KWARGS)
    manifest["agents"]["quality_agent"]["canonical"] = {"status": "NOT_FOUND_IN_CANON"}
    gate = agent_sync.compute_binding_gate(manifest)
    assert gate["canonical_found_both"] is False
    assert gate["gate_pass"] is False


def test_gate_is_not_a_field_the_quality_agent_profile_asserts_about_itself() -> None:
    manifest = agent_sync.evaluate_agent_sync(**SESSION_KWARGS)
    quality_profile = manifest["agents"]["quality_agent"]
    assert "gate_pass" not in quality_profile
    assert "gate_pass" not in quality_profile["canonical"]


# ── protected operations: static regression guard ───────────────────────────

def test_module_declares_no_protected_operations_invoked() -> None:
    manifest = agent_sync.evaluate_agent_sync(**SESSION_KWARGS)
    assert manifest["protected_operations_invoked"] == []


def test_module_has_no_admit_apply_reverse_or_rollback_entrypoint() -> None:
    forbidden = {"admit", "apply", "reverse", "rollback", "write_canon"}
    names = {name for name in dir(agent_sync) if not name.startswith("_")}
    assert forbidden.isdisjoint(names)
