#!/usr/bin/env python3
"""Machine-readable corpus governance helpers for local authority and lineage."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from path_governance import (
    DEFAULT_AI_DIR,
    DEFAULT_AUDIT_DIR,
    DEFAULT_CANON_DIR,
    DEFAULT_ENRICHED_DIR,
    DEFAULT_EXPORT_DIR,
    DEFAULT_LOCAL_OUT_DIR,
    DEFAULT_MICROSOFT_COPILOT_DIR,
    DEFAULT_PROPOSALS_FILE,
    DEFAULT_REMOTE_OUT_DIR,
    DEFAULT_REVERSE_HTML_DIR,
    as_display_path,
    sorted_canon_shards,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
CANON_POLICY_BUNDLE_REL = "data/sessions/00_contratos/policy/canon_policy_bundle.json"
DERIVED_LAYERS_REGISTRY_REL = "data/sessions/00_contratos/projections/derived_layers_registry.json"
CANON_POLICY_BUNDLE_PATH = REPO_ROOT / CANON_POLICY_BUNDLE_REL
DERIVED_LAYERS_REGISTRY_PATH = REPO_ROOT / DERIVED_LAYERS_REGISTRY_REL

PATHISH_SUFFIX_RE = re.compile(r"\.[A-Za-z0-9._-]+$")


def safe_str(value) -> str:
    return "" if value is None else str(value)


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_canon_policy_bundle(path: Path | None = None) -> dict:
    return _load_json(path or CANON_POLICY_BUNDLE_PATH)


def load_layer_registry(path: Path | None = None) -> dict:
    return _load_json(path or DERIVED_LAYERS_REGISTRY_PATH)


def role_primary_contract(bundle: dict | None = None) -> dict:
    bundle = bundle or load_canon_policy_bundle()
    contract = bundle.get("role_primary_contract")
    if not isinstance(contract, dict):
        raise ValueError("canon_policy_bundle.json missing role_primary_contract")
    return contract


def role_primary_canonical_roles(bundle: dict | None = None) -> set[str]:
    contract = role_primary_contract(bundle)
    roles = contract.get("canonical_roles")
    if not isinstance(roles, list) or not roles:
        raise ValueError("role_primary_contract.canonical_roles must be a non-empty array")
    return {safe_str(role).strip() for role in roles if safe_str(role).strip()}


def _normalized_role_value(value) -> str:
    return safe_str(value).strip().lower()


def classify_role_primary_value(value, bundle: dict | None = None) -> dict:
    """Classify a role_primary value against the S79 contract without mutating it."""
    contract = role_primary_contract(bundle)
    role = _normalized_role_value(value)
    canonical_roles = role_primary_canonical_roles(bundle)
    aliases = contract.get("aliases_allowed") or {}
    legacy = contract.get("legacy_accepted_transitional") or {}
    ambiguous = contract.get("ambiguous_roles") or {}

    if role in canonical_roles:
        return {
            "input_role": role,
            "canonical_role": role,
            "verdict": "role_ok",
            "migration_class": "canonical",
        }

    if role in aliases:
        return {
            "input_role": role,
            "canonical_role": aliases.get(role),
            "verdict": "role_alias_mapped",
            "migration_class": "alias_allowed",
        }

    if role in legacy:
        canonical_role = (legacy.get(role) or {}).get("canonical_role")
        if canonical_role:
            return {
                "input_role": role,
                "canonical_role": canonical_role,
                "verdict": "role_legacy_detected",
                "migration_class": "legacy_accepted_transitional",
            }
        return {
            "input_role": role,
            "canonical_role": None,
            "candidate_roles": ambiguous.get(role) or [],
            "verdict": "role_ambiguous",
            "migration_class": "legacy_ambiguous",
        }

    if role in ambiguous:
        return {
            "input_role": role,
            "canonical_role": None,
            "candidate_roles": ambiguous.get(role) or [],
            "verdict": "role_ambiguous",
            "migration_class": "ambiguous",
        }

    return {
        "input_role": role,
        "canonical_role": None,
        "verdict": contract.get("invalid_policy", {}).get("default_verdict", "role_invalid"),
        "migration_class": "invalid",
    }


def looks_like_repo_path(title: str) -> bool:
    title = safe_str(title)
    if not title:
        return False
    return (
        "/" in title
        or title in {".gitignore", "README.md", "estructura.txt", "scripts.txt", "contratos.txt"}
        or bool(PATHISH_SUFFIX_RE.search(title))
    )


def _rule_matches(match: dict, title_lower: str, tags_lower: list[str]) -> bool:
    if not match:
        return True

    if match.get("repo_path_like") is True and not looks_like_repo_path(title_lower):
        return False
    if match.get("repo_path_like") is False and looks_like_repo_path(title_lower):
        return False

    tags_any = match.get("tags_any") or []
    if tags_any and not any(tag in tags_lower for tag in tags_any):
        return False

    tags_absent = match.get("tags_absent") or []
    if tags_absent and any(tag in tags_lower for tag in tags_absent):
        return False

    tags_prefix_any = match.get("tags_prefix_any") or []
    if tags_prefix_any and not any(
        any(tag.startswith(prefix) for prefix in tags_prefix_any) for tag in tags_lower
    ):
        return False

    title_contains_any = match.get("title_contains_any") or []
    if title_contains_any and not any(fragment in title_lower for fragment in title_contains_any):
        return False

    title_prefixes = match.get("title_prefixes") or []
    if title_prefixes and not any(title_lower.startswith(prefix) for prefix in title_prefixes):
        return False

    title_prefixes_not = match.get("title_prefixes_not") or []
    if title_prefixes_not and any(title_lower.startswith(prefix) for prefix in title_prefixes_not):
        return False

    title_suffixes = match.get("title_suffixes") or []
    if title_suffixes and not any(title_lower.endswith(suffix) for suffix in title_suffixes):
        return False

    return True


def resolve_corpus_policy(rec: dict, bundle: dict | None = None) -> dict:
    bundle = bundle or load_canon_policy_bundle()
    title_lower = safe_str(rec.get("title")).lower()
    tags_lower = [safe_str(tag).lower() for tag in (rec.get("tags") or [])]
    rules = sorted(bundle["corpus_state_resolution_rules"], key=lambda item: item["priority"])

    for rule in rules:
        if not _rule_matches(rule.get("match") or {}, title_lower, tags_lower):
            continue
        state_name = rule["result"]["corpus_state"]
        state_catalog = bundle["corpus_state_catalog"]
        state = state_catalog[state_name]
        return {
            "corpus_state": state_name,
            "chunk_eligibility": rule["result"].get("chunk_eligibility", state["chunk_eligibility"]),
            "chunk_exclusion_reason": rule["result"].get(
                "chunk_exclusion_reason",
                state["chunk_exclusion_reason"],
            ),
            "corpus_state_rule_id": rule["rule_id"],
            "outside_live_corpus": state["outside_live_corpus"],
            "evidence_mode": state["evidence_mode"],
        }

    raise ValueError("no corpus_state resolution rule matched the record")


def _iter_jsonl(path: Path) -> list[dict]:
    records: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def _load_canon_records(canon_dir: Path) -> list[dict]:
    records: list[dict] = []
    for shard_path in sorted_canon_shards(canon_dir):
        records.extend(_iter_jsonl(shard_path))
    return records


def _load_ai_records(ai_dir: Path) -> list[dict]:
    records: list[dict] = []
    for shard_path in sorted(ai_dir.glob("tiddlers_ai_*.jsonl")):
        records.extend(_iter_jsonl(shard_path))
    return records


def validate_policy_bundle(bundle: dict) -> list[str]:
    errors: list[str] = []

    if bundle.get("schema_version") != "v0":
        errors.append("canon policy bundle schema_version must be v0")

    contract = bundle.get("role_primary_contract")
    if not isinstance(contract, dict):
        errors.append("role_primary_contract must be a non-empty object")
    else:
        roles = contract.get("canonical_roles")
        if not isinstance(roles, list) or not roles:
            errors.append("role_primary_contract.canonical_roles must be a non-empty array")
            canonical_roles: set[str] = set()
        else:
            canonical_roles = {safe_str(role).strip() for role in roles if safe_str(role).strip()}
            if len(canonical_roles) != len(roles):
                errors.append("role_primary_contract.canonical_roles contains duplicates or empty values")
            if "unclassified" not in canonical_roles:
                errors.append("role_primary_contract.canonical_roles must include unclassified")

        for section_name in ("source_role_mappings", "tag_role_mappings", "aliases_allowed"):
            mappings = contract.get(section_name)
            if not isinstance(mappings, dict):
                errors.append(f"role_primary_contract.{section_name} must be an object")
                continue
            for alias, canonical_role in mappings.items():
                if safe_str(canonical_role) not in canonical_roles:
                    errors.append(
                        f"role_primary_contract.{section_name}.{alias} maps to undefined role {canonical_role}"
                    )

        legacy = contract.get("legacy_accepted_transitional")
        if not isinstance(legacy, dict):
            errors.append("role_primary_contract.legacy_accepted_transitional must be an object")
        else:
            for legacy_role, payload in legacy.items():
                if not isinstance(payload, dict):
                    errors.append(f"legacy role {legacy_role} must be an object")
                    continue
                canonical_role = payload.get("canonical_role")
                if canonical_role is not None and safe_str(canonical_role) not in canonical_roles:
                    errors.append(
                        f"legacy role {legacy_role} maps to undefined canonical_role {canonical_role}"
                    )

    states = bundle.get("corpus_state_catalog")
    if not isinstance(states, dict) or not states:
        errors.append("corpus_state_catalog must be a non-empty object")
        return errors

    for state_name, state in states.items():
        for field in ("description", "evidence_mode", "outside_live_corpus", "chunk_eligibility"):
            if field not in state:
                errors.append(f"corpus_state_catalog.{state_name} missing field {field}")

    rules = bundle.get("corpus_state_resolution_rules")
    if not isinstance(rules, list) or not rules:
        errors.append("corpus_state_resolution_rules must be a non-empty array")
    else:
        seen_rule_ids: set[str] = set()
        for rule in rules:
            rule_id = safe_str(rule.get("rule_id"))
            if not rule_id:
                errors.append("corpus_state_resolution_rules contains a rule without rule_id")
                continue
            if rule_id in seen_rule_ids:
                errors.append(f"duplicate corpus_state rule_id: {rule_id}")
            seen_rule_ids.add(rule_id)
            state_name = safe_str((rule.get("result") or {}).get("corpus_state"))
            if state_name not in states:
                errors.append(f"corpus_state rule {rule_id} points to undefined state {state_name}")
        if not any(rule.get("rule_id") == "general_fallback" for rule in rules):
            errors.append("corpus_state_resolution_rules must define general_fallback")

    transitions = bundle.get("corpus_state_transitions")
    if not isinstance(transitions, list) or not transitions:
        errors.append("corpus_state_transitions must be a non-empty array")
    else:
        for transition in transitions:
            if transition.get("from") not in states:
                errors.append(f"transition from undefined state: {transition.get('from')}")
            if transition.get("to") not in states:
                errors.append(f"transition to undefined state: {transition.get('to')}")

    return errors


def validate_layer_registry(registry: dict) -> list[str]:
    errors: list[str] = []
    layer_classes = registry.get("layer_classes")
    layers = registry.get("layers")
    edges = registry.get("lineage_edges")

    if registry.get("schema_version") != "v0":
        errors.append("derived layer registry schema_version must be v0")

    if not isinstance(layer_classes, dict) or not layer_classes:
        errors.append("layer_classes must be a non-empty object")
        return errors
    if not isinstance(layers, list) or not layers:
        errors.append("layers must be a non-empty array")
        return errors
    if not isinstance(edges, list) or not edges:
        errors.append("lineage_edges must be a non-empty array")
        return errors

    layer_ids: set[str] = set()
    by_id: dict[str, dict] = {}
    for layer in layers:
        layer_id = safe_str(layer.get("layer_id"))
        if not layer_id:
            errors.append("layer entry missing layer_id")
            continue
        if layer_id in layer_ids:
            errors.append(f"duplicate layer_id: {layer_id}")
        layer_ids.add(layer_id)
        by_id[layer_id] = layer

        layer_class = safe_str(layer.get("layer_class"))
        if layer_class not in layer_classes:
            errors.append(f"layer {layer_id} uses undefined layer_class {layer_class}")

        for parent in layer.get("lineage_parents") or []:
            if parent not in layer_ids and parent not in [l.get("layer_id") for l in layers]:
                errors.append(f"layer {layer_id} references unknown lineage_parent {parent}")
        for source in layer.get("validation_inputs") or []:
            if source not in [l.get("layer_id") for l in layers]:
                errors.append(f"layer {layer_id} references unknown validation_input {source}")

    source_of_truth = safe_str(registry.get("source_of_truth_layer"))
    if source_of_truth not in by_id:
        errors.append(f"source_of_truth_layer points to undefined layer {source_of_truth}")

    authoritative_layers = [
        layer["layer_id"]
        for layer in layers
        if layer.get("authority") == "local_source_of_truth"
    ]
    if authoritative_layers != [source_of_truth]:
        errors.append(
            "exactly one layer must have authority local_source_of_truth and it must match source_of_truth_layer"
        )

    for edge in edges:
        if edge.get("from") not in by_id:
            errors.append(f"lineage edge from unknown layer {edge.get('from')}")
        if edge.get("to") not in by_id:
            errors.append(f"lineage edge to unknown layer {edge.get('to')}")

    required_layer_ids = {
        "canon",
        "proposals",
        "enriched",
        "ai",
        "audit",
        "reverse_html",
        "export",
        "microsoft_copilot",
        "remote",
    }
    missing_layers = sorted(required_layer_ids - set(by_id))
    if missing_layers:
        errors.append(f"registry missing required layer ids: {', '.join(missing_layers)}")

    return errors


def validate_repository_alignment(
    canon_dir: Path | None = None,
    ai_dir: Path | None = None,
    bundle: dict | None = None,
    registry: dict | None = None,
) -> dict:
    bundle = bundle or load_canon_policy_bundle()
    registry = registry or load_layer_registry()
    canon_dir = canon_dir or DEFAULT_CANON_DIR
    ai_dir = ai_dir or DEFAULT_AI_DIR

    errors = validate_policy_bundle(bundle)
    errors.extend(validate_layer_registry(registry))
    warnings: list[str] = []

    expected_bundle_paths = {
        "local_output_root": as_display_path(DEFAULT_LOCAL_OUT_DIR),
        "remote_output_root": as_display_path(DEFAULT_REMOTE_OUT_DIR),
        "session_proposal_artifact_pattern": as_display_path(DEFAULT_PROPOSALS_FILE),
        "reverse_html_root": as_display_path(DEFAULT_REVERSE_HTML_DIR),
    }
    bundle_alignment: dict[str, dict] = {}
    for field, expected in expected_bundle_paths.items():
        actual = bundle.get(field)
        aligned = actual == expected
        bundle_alignment[field] = {"expected": expected, "actual": actual, "aligned": aligned}
        if not aligned:
            errors.append(f"bundle path mismatch for {field}: expected {expected}, found {actual}")

    expected_layer_paths = {
        "canon": as_display_path(DEFAULT_CANON_DIR),
        "proposals": as_display_path(DEFAULT_PROPOSALS_FILE),
        "enriched": as_display_path(DEFAULT_ENRICHED_DIR),
        "ai": as_display_path(DEFAULT_AI_DIR),
        "audit": as_display_path(DEFAULT_AUDIT_DIR),
        "reverse_html": as_display_path(DEFAULT_REVERSE_HTML_DIR),
        "export": as_display_path(DEFAULT_EXPORT_DIR),
        "microsoft_copilot": as_display_path(DEFAULT_MICROSOFT_COPILOT_DIR),
        "remote": as_display_path(DEFAULT_REMOTE_OUT_DIR),
    }
    layer_map = {layer["layer_id"]: layer for layer in registry["layers"]}
    layer_path_alignment: dict[str, dict] = {}
    layer_presence: list[dict] = []
    for layer_id, expected_path in expected_layer_paths.items():
        actual_path = layer_map[layer_id]["path"]
        aligned = actual_path == expected_path
        exists = (REPO_ROOT / actual_path).exists()
        presence = layer_map[layer_id]["presence"]
        layer_path_alignment[layer_id] = {
            "expected": expected_path,
            "actual": actual_path,
            "aligned": aligned,
        }
        layer_presence.append(
            {
                "layer_id": layer_id,
                "path": actual_path,
                "presence": presence,
                "exists": exists,
            }
        )
        if not aligned:
            errors.append(f"layer path mismatch for {layer_id}: expected {expected_path}, found {actual_path}")
        if presence == "required" and not exists:
            errors.append(f"required governed layer path does not exist: {actual_path}")
        if presence != "required" and not exists:
            warnings.append(f"optional governed layer path not present right now: {actual_path}")

    canon_records = _load_canon_records(canon_dir)
    observed_state_dist: Counter[str] = Counter()
    observed_rule_dist: Counter[str] = Counter()
    explicit_tag_dist: Counter[str] = Counter()
    expected_by_id: dict[str, dict] = {}
    for rec in canon_records:
        policy = resolve_corpus_policy(rec, bundle)
        record_id = safe_str(rec.get("id"))
        if record_id:
            expected_by_id[record_id] = policy
        observed_state_dist[policy["corpus_state"]] += 1
        observed_rule_dist[policy["corpus_state_rule_id"]] += 1
        for tag in [safe_str(tag).lower() for tag in (rec.get("tags") or [])]:
            if (
                tag in {"state:live-path", "state:historical-snapshot", "status:archival-only"}
                or tag.startswith("superseded-by:")
            ):
                explicit_tag_dist[tag] += 1

    if not explicit_tag_dist:
        warnings.append(
            "current canon exposes no explicit state:* or status:* tags; corpus_state still resolves mostly from governed heuristics"
        )

    ai_alignment = {
        "checked": False,
        "ai_record_count": 0,
        "mismatched_corpus_state": 0,
        "mismatched_rule_id": 0,
        "samples": [],
    }
    ai_files = sorted(ai_dir.glob("tiddlers_ai_*.jsonl"))
    if ai_files:
        ai_alignment["checked"] = True
        ai_records = _load_ai_records(ai_dir)
        ai_alignment["ai_record_count"] = len(ai_records)
        if len(ai_records) != len(canon_records):
            errors.append(
                f"ai layer record count {len(ai_records)} does not match canon record count {len(canon_records)}"
            )
        for rec in ai_records:
            node_id = safe_str(rec.get("node_id") or rec.get("id"))
            expected = expected_by_id.get(node_id)
            if not expected:
                ai_alignment["samples"].append(
                    {
                        "node_id": node_id,
                        "reason": "missing_canon_match",
                    }
                )
                continue
            actual_state = rec.get("corpus_state")
            actual_rule_id = rec.get("corpus_state_rule_id")
            if actual_state != expected["corpus_state"]:
                ai_alignment["mismatched_corpus_state"] += 1
                if len(ai_alignment["samples"]) < 10:
                    ai_alignment["samples"].append(
                        {
                            "node_id": node_id,
                            "field": "corpus_state",
                            "expected": expected["corpus_state"],
                            "actual": actual_state,
                        }
                    )
            if actual_rule_id != expected["corpus_state_rule_id"]:
                ai_alignment["mismatched_rule_id"] += 1
                if len(ai_alignment["samples"]) < 10:
                    ai_alignment["samples"].append(
                        {
                            "node_id": node_id,
                            "field": "corpus_state_rule_id",
                            "expected": expected["corpus_state_rule_id"],
                            "actual": actual_rule_id,
                        }
                    )
        if ai_alignment["mismatched_corpus_state"]:
            errors.append(
                f"ai layer corpus_state mismatches detected: {ai_alignment['mismatched_corpus_state']}"
            )
        if ai_alignment["mismatched_rule_id"]:
            errors.append(
                f"ai layer corpus_state_rule_id mismatches detected: {ai_alignment['mismatched_rule_id']}"
            )

    report = {
        "status": "ok" if not errors else "fail",
        "policy_bundle_ref": CANON_POLICY_BUNDLE_REL,
        "layer_registry_ref": DERIVED_LAYERS_REGISTRY_REL,
        "canon_dir": as_display_path(canon_dir),
        "ai_dir": as_display_path(ai_dir),
        "errors": errors,
        "warnings": warnings,
        "bundle_alignment": bundle_alignment,
        "layer_path_alignment": layer_path_alignment,
        "layer_presence": layer_presence,
        "canon_observation": {
            "record_count": len(canon_records),
            "observed_corpus_state_distribution": dict(observed_state_dist.most_common()),
            "observed_corpus_state_rule_distribution": dict(observed_rule_dist.most_common()),
            "explicit_state_tag_distribution": dict(explicit_tag_dist.most_common()),
        },
        "ai_alignment": ai_alignment,
    }
    return report
