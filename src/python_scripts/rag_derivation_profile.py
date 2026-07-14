#!/usr/bin/env python3
"""Versioned S0172 profile for the authoritative derivative orchestrator.

This module owns only the declarative RAG-derivation profile.  It is not a
producer: ``derive_layers.py`` remains the sole productive orchestrator.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from metadata_promotion_policy import POLICY_VERSION as METADATA_POLICY_VERSION
from rag_derivative_writers import require_nonproductive_evidence_target
from tag_sanitation_policy import POLICY_VERSION as TAG_POLICY_VERSION


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
PROFILE_SCHEMA_VERSION = "rag-derivation-profile/v1"
DEFAULT_PROFILE_PATH = (
    REPO_ROOT
    / "data"
    / "out"
    / "local"
    / "pipeline"
    / "rag_derivation"
    / "s0172"
    / "rag_derivation_profile.json"
)
DEFAULT_TAG_POLICY_PATH = (
    REPO_ROOT / "data" / "out" / "local" / "pipeline" / "tag_sanitation" / "s0169" / "tag_sanitation_policy.json"
)
DEFAULT_METADATA_POLICY_PATH = (
    REPO_ROOT / "data" / "out" / "local" / "pipeline" / "metadata_promotion" / "s0171" / "metadata_promotion_policy.json"
)
DEFAULT_SEMANTIC_TYPE_POLICY_PATH = (
    REPO_ROOT
    / "data"
    / "out"
    / "local"
    / "pipeline"
    / "relation_type_governance"
    / "s0139"
    / "s0139_historical_relation_type_decisions.json"
)


def stable_json(value: Any, *, indent: int | None = None) -> str:
    if indent is None:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=indent)


def sha256_file(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def repo_relative(path: Path | str) -> str:
    candidate = Path(path).resolve()
    try:
        return candidate.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(candidate)


def build_profile(
    *,
    tag_policy_path: Path | str = DEFAULT_TAG_POLICY_PATH,
    metadata_policy_path: Path | str = DEFAULT_METADATA_POLICY_PATH,
    semantic_type_policy_path: Path | str = DEFAULT_SEMANTIC_TYPE_POLICY_PATH,
    productive_orchestrator_hash: str | None = None,
) -> dict[str, Any]:
    """Return the single declarative profile consumed by ``derive_layers``."""

    profile = {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "profile_id": PROFILE_SCHEMA_VERSION,
        "productive_orchestrator": "src/python_scripts/derive_layers.py",
        "semantic_builder": "src/python_scripts/semantic_text_builder.py",
        "semantic_type_policy_path": repo_relative(semantic_type_policy_path),
        "semantic_dynamic_relation_preview_inputs": False,
        "tag_policy_version": TAG_POLICY_VERSION,
        "tag_policy_path": repo_relative(tag_policy_path),
        "metadata_policy_version": METADATA_POLICY_VERSION,
        "metadata_policy_path": repo_relative(metadata_policy_path),
        "rag_gate": "src/python_scripts/validate_rag_tag_gate.py",
        "artifact_families": ["enriched", "ai", "chunks_ai", "microsoft_copilot"],
        "raw_source_tags_allowed_in_semantic_text": False,
        "raw_p1_allowed": False,
        "unknown_allowed": False,
        "template_nodes_as_topics_allowed": False,
        "formal_relation_edges_allowed": False,
        "productive_write_default": False,
        "authority": {
            "orchestrator": "active_authoritative",
            "profile": "active_supporting",
            "preview_only": True,
        },
    }
    if productive_orchestrator_hash is not None:
        profile["productive_orchestrator_hash"] = productive_orchestrator_hash
    return profile


def write_profile(path: Path | str = DEFAULT_PROFILE_PATH, **kwargs: Any) -> Path:
    profile = build_profile(**kwargs)
    target = require_nonproductive_evidence_target(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(stable_json(profile, indent=2) + "\n", encoding="utf-8")
    return target


def load_profile(path: Path | str) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"rag derivation profile is required: {target}")
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"rag derivation profile root must be an object: {target}")
    validate_profile(payload, profile_path=target)
    return payload


def validate_profile(profile: dict[str, Any], *, profile_path: Path | None = None) -> None:
    required_values = {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "productive_orchestrator": "src/python_scripts/derive_layers.py",
        "semantic_builder": "src/python_scripts/semantic_text_builder.py",
        "semantic_dynamic_relation_preview_inputs": False,
        "tag_policy_version": TAG_POLICY_VERSION,
        "metadata_policy_version": METADATA_POLICY_VERSION,
        "rag_gate": "src/python_scripts/validate_rag_tag_gate.py",
        "productive_write_default": False,
    }
    errors: list[str] = []
    for key, expected in required_values.items():
        if profile.get(key) != expected:
            errors.append(f"{key} must be {expected!r}")
    expected_families = ["enriched", "ai", "chunks_ai", "microsoft_copilot"]
    if profile.get("artifact_families") != expected_families:
        errors.append("artifact_families must declare the four governed derivative families")
    for key in (
        "raw_source_tags_allowed_in_semantic_text",
        "raw_p1_allowed",
        "unknown_allowed",
        "template_nodes_as_topics_allowed",
        "formal_relation_edges_allowed",
    ):
        if profile.get(key) is not False:
            errors.append(f"{key} must be false")
    for key in ("tag_policy_path", "metadata_policy_path", "semantic_type_policy_path"):
        if not isinstance(profile.get(key), str) or not profile[key].strip():
            errors.append(f"{key} must be a non-empty path")
    if "productive_orchestrator_hash" in profile and (
        not isinstance(profile["productive_orchestrator_hash"], str)
        or len(profile["productive_orchestrator_hash"]) != 64
    ):
        errors.append("productive_orchestrator_hash must be a sha256 hex string when present")
    if errors:
        location = f" in {profile_path}" if profile_path else ""
        raise ValueError("invalid rag derivation profile" + location + ": " + "; ".join(errors))


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or validate rag-derivation-profile/v1.")
    parser.add_argument("--profile", default=str(DEFAULT_PROFILE_PATH))
    parser.add_argument("--tag-policy", default=str(DEFAULT_TAG_POLICY_PATH))
    parser.add_argument("--metadata-policy", default=str(DEFAULT_METADATA_POLICY_PATH))
    parser.add_argument("--semantic-type-policy", default=str(DEFAULT_SEMANTIC_TYPE_POLICY_PATH))
    parser.add_argument("--productive-orchestrator-hash", default=None)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if args.write:
        target = write_profile(
            args.profile,
            tag_policy_path=args.tag_policy,
            metadata_policy_path=args.metadata_policy,
            semantic_type_policy_path=args.semantic_type_policy,
            productive_orchestrator_hash=args.productive_orchestrator_hash,
        )
        print(stable_json({"profile": str(target), "sha256": sha256_file(target)}, indent=2))
    else:
        print(stable_json(load_profile(args.profile), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
