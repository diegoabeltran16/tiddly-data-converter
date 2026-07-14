#!/usr/bin/env python3
"""Executable dry-run policy for S0171 metadata promotion.

The module maps curated source-tag evidence to proposed metadata only.  It has
no apply path and never mutates canon shards or productive derivatives.
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from tag_sanitation_policy import normalize_text, stable_json


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
DEFAULT_POLICY_PATH = (
    REPO_ROOT
    / "data"
    / "out"
    / "local"
    / "pipeline"
    / "metadata_promotion"
    / "s0171"
    / "metadata_promotion_policy.json"
)

POLICY_VERSION = "metadata-promotion/v1"
FORMAL_TEMPLATE_MODEL = "T=R∪A∪C∪N∪D∪Q"
FORMAL_RELATION_VOCAB = [
    "part_of",
    "defines",
    "requires",
    "uses",
    "replaces",
    "alternative_to",
    "do_not_combine_with",
]

ALLOWED_FIELDS = [
    "tech_stack",
    "topics",
    "language",
    "language_variants",
    "artifact_family",
    "status",
    "session_id",
    "milestones",
    "layer",
    "module",
    "source_kind",
    "workflow_stage",
    "template_set",
    "template_node",
    "structural_role",
    "governance_axis",
    "formal_relation_vocab",
]

MULTI_VALUE_FIELDS = {
    "tech_stack",
    "topics",
    "language_variants",
    "milestones",
    "governance_axis",
    "formal_relation_vocab",
}

TEMPLATE_SET_VALUES = [
    "root",
    "startup",
    "core_mother",
    "normative_transversal",
    "thematic_deployment",
    "situated_material",
]

# The operator supplied these exact mappings in S0171.  S0169 classified the
# values as unknown_review; the exception is intentionally exact and records
# that upstream classification on every candidate.  It is not a generic
# unknown-to-metadata promotion rule.
CURATED_EXACT_TAG_MAPPINGS = {
    "⚙️ Python": {"target_field": "tech_stack", "proposed_value": "python"},
    "⚙️ JSON": {"target_field": "tech_stack", "proposed_value": "json"},
    "⚙️ Markdown": {"target_field": "tech_stack", "proposed_value": "markdown"},
    "⚙️ Shell": {"target_field": "tech_stack", "proposed_value": "shell"},
    "⚙️ Go": {"target_field": "tech_stack", "proposed_value": "go"},
    "⚙️ Rust": {"target_field": "tech_stack", "proposed_value": "rust"},
}

ARTIFACT_ALIASES = {
    "contrato_de_sesion": "session_contract",
    "balance_de_sesion": "session_balance",
    "diagnostico_de_sesion": "session_diagnosis",
    "propuesta_de_sesion": "session_proposal",
    "procedencia_de_sesion": "session_provenance",
    "hipotesis_de_sesion": "session_hypothesis",
    "detalles_de_sesion": "session_details",
    "diagnostico_tematico": "thematic_diagnosis",
    "diagnostico_de_micro_ciclo": "micro_cycle_diagnosis",
    "diagnostico_de_meso_ciclo": "meso_cycle_diagnosis",
    "diagnostico_de_proyecto": "project_diagnosis",
    "session_contract": "session_contract",
    "diagnosis": "diagnosis",
    "proposal": "proposal",
    "balance": "balance",
    "procedure": "procedure",
}

LANGUAGE_ALIASES = {
    "es": "es",
    "espanol": "es",
    "spanish": "es",
    "en": "en",
    "english": "en",
}

CONTROLLED_VALUES = {
    "language": ["es", "en"],
    "layer": ["canon", "derived", "pipeline", "audit", "session"],
    "status": [
        "draft",
        "approved",
        "rejected",
        "active",
        "deprecated",
        "delivered",
        "local_admitted",
    ],
    "template_set": TEMPLATE_SET_VALUES,
}

DEFAULT_POLICY: dict[str, Any] = {
    "policy_version": POLICY_VERSION,
    "session": "S0171",
    "dry_run": True,
    "canon_modified": False,
    "productive_derivatives_modified": False,
    "source_policy": "tag-sanitation/v1",
    "formal_template_model": FORMAL_TEMPLATE_MODEL,
    "formal_relation_vocab": FORMAL_RELATION_VOCAB,
    "allowed_fields": ALLOWED_FIELDS,
    "multi_value_fields": sorted(MULTI_VALUE_FIELDS),
    "template_set_values": TEMPLATE_SET_VALUES,
    "prefix_mappings": {
        "topic:": "topics",
        "tema:": "topics",
        "lang:": "language",
        "language:": "language",
        "idioma:": "language",
        "artifact:": "artifact_family",
        "family:": "artifact_family",
        "status:": "status",
        "session:": "session_id",
        "milestone:": "milestones",
        "layer:": "layer",
        "module:": "module",
        "source:": "source_kind",
    },
    "value_normalization": {
        "python": "python",
        "py": "python",
        "js": "javascript",
        "md": "markdown",
        "español": "es",
        "spanish": "es",
        "english": "en",
    },
    "artifact_aliases": ARTIFACT_ALIASES,
    "language_aliases": LANGUAGE_ALIASES,
    "controlled_values": CONTROLLED_VALUES,
    "generic_topic_values": ["tema", "general", "misc", "unknown"],
    "blocked_sources": ["p0_blocked", "unknown_review"],
    "curated_exact_tag_mappings": CURATED_EXACT_TAG_MAPPINGS,
    "curated_override_rule": {
        "scope": "exact_match_only",
        "upstream_classification": "unknown_review",
        "effective_classification": "p1_metadata_only",
        "basis": "operator_supplied_mapping_in_S0171",
        "generic_unknown_promotion_allowed": False,
    },
    "human_review_required_for": [
        "ambiguous_topic",
        "multiple_conflicting_languages",
        "unknown_prefix",
        "generic_value",
        "path_like_value",
        "code_like_value",
        "template_node_topic_collision",
        "relation_like_tag_without_admission",
        "invalid_controlled_value",
        "noncanonical_session_id",
    ],
    "anti_cycle": {
        "tdc_projected_tags_as_primary_source": False,
        "projected_tags_namespace": "tdc:",
    },
    "relation_safety": {
        "may_emit_canonical_relations": False,
        "may_emit_relation_candidates": False,
        "relation_vocab_is_metadata_only": True,
    },
}


def load_policy(path: Path | str = DEFAULT_POLICY_PATH) -> dict[str, Any]:
    policy_path = Path(path)
    if not policy_path.exists():
        return json.loads(json.dumps(DEFAULT_POLICY, ensure_ascii=False))
    payload = json.loads(policy_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"metadata promotion policy root must be an object: {policy_path}")
    merged = json.loads(json.dumps(DEFAULT_POLICY, ensure_ascii=False))
    merged.update(payload)
    return merged


def write_default_policy(path: Path | str = DEFAULT_POLICY_PATH) -> dict[str, Any]:
    policy = json.loads(json.dumps(DEFAULT_POLICY, ensure_ascii=False))
    policy_path = Path(path)
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    policy_path.write_text(stable_json(policy, indent=2) + "\n", encoding="utf-8")
    return policy


def normalize_token(value: Any) -> str:
    text = normalize_text(value).casefold()
    text = "".join(
        char for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    )
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_")


def looks_path_or_code_like(value: str) -> bool:
    lowered = normalize_text(value).casefold()
    return bool(
        "/" in lowered
        or "\\" in lowered
        or re.search(r"\.(py|sh|go|rs|json|jsonl|md|toml|yaml|yml)$", lowered)
    )


def normalize_session_id(value: str) -> str | None:
    clean = normalize_text(value)
    match = re.fullmatch(r"(?:(?:m\d{2})-)?s0*(\d{1,4})", clean, flags=re.IGNORECASE)
    if not match:
        return None
    return f"S{int(match.group(1)):04d}"


def _prefix_mapping(tag: str, policy: dict[str, Any]) -> tuple[str, str] | None:
    lowered = tag.casefold()
    mappings = policy.get("prefix_mappings") or {}
    for prefix in sorted(mappings, key=len, reverse=True):
        if lowered.startswith(str(prefix).casefold()):
            return str(mappings[prefix]), normalize_text(tag[len(prefix):])
    return None


def _blocked_decision(
    *, target_field: str | None, value: str, block_reason: str, reason: str
) -> dict[str, Any]:
    return {
        "target_field": target_field,
        "proposed_value": normalize_token(value) if value else None,
        "normalization_applied": bool(value),
        "confidence": "low",
        "promotion_status": "blocked",
        "authority_level": "proposed",
        "requires_human_review": True,
        "block_reason": block_reason,
        "reason": reason,
    }


def classify_promotion(
    tag: str,
    *,
    upstream_rag_class: str,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return a proposed metadata decision, a blocked decision, or ``None``.

    ``None`` means the source is outside the promotion surface.  P0, generic
    unknown and projected ``tdc:*`` values deliberately take that path.
    """

    policy = policy or DEFAULT_POLICY
    clean = normalize_text(tag)
    exact = (policy.get("curated_exact_tag_mappings") or {}).get(clean)
    if exact:
        return {
            "target_field": exact["target_field"],
            "proposed_value": exact["proposed_value"],
            "normalization_applied": clean != exact["proposed_value"],
            "confidence": "high",
            "promotion_status": "candidate",
            "authority_level": "proposed",
            "requires_human_review": False,
            "source_tag_classification": "p1_metadata_only",
            "promotion_basis": "policy_curated_exact_mapping",
            "classification_override": {
                "upstream": upstream_rag_class,
                "effective": "p1_metadata_only",
                "basis": "operator_supplied_mapping_in_S0171",
            },
            "reason": f"Exact S0171 mapping promotes {clean} to {exact['target_field']}",
        }

    if upstream_rag_class != "p1_metadata_only":
        return None
    mapped = _prefix_mapping(clean, policy)
    if mapped is None:
        return _blocked_decision(
            target_field=None,
            value=clean,
            block_reason="unknown_prefix",
            reason="P1 source has no metadata-promotion/v1 field mapping",
        )
    target_field, raw_value = mapped
    if not raw_value:
        return _blocked_decision(
            target_field=target_field,
            value=raw_value,
            block_reason="generic_value",
            reason="Metadata prefix has an empty value",
        )
    if looks_path_or_code_like(raw_value):
        return _blocked_decision(
            target_field=target_field,
            value=raw_value,
            block_reason="path_like_value",
            reason="Paths and file-like values cannot be promoted as metadata",
        )

    proposed: str | None
    if target_field == "session_id":
        proposed = normalize_session_id(raw_value)
        if proposed is None:
            return _blocked_decision(
                target_field=target_field,
                value=raw_value,
                block_reason="noncanonical_session_id",
                reason="session:* value is not SNNNN or mNN-sNNNN",
            )
    elif target_field == "language":
        proposed = (policy.get("language_aliases") or {}).get(normalize_token(raw_value))
        if proposed is None:
            return _blocked_decision(
                target_field=target_field,
                value=raw_value,
                block_reason="invalid_controlled_value",
                reason="Language is outside the controlled vocabulary",
            )
    elif target_field == "artifact_family":
        proposed = (policy.get("artifact_aliases") or {}).get(normalize_token(raw_value))
        if proposed is None:
            return _blocked_decision(
                target_field=target_field,
                value=raw_value,
                block_reason="invalid_controlled_value",
                reason="Artifact family is outside the controlled vocabulary",
            )
    else:
        proposed = normalize_token(raw_value)

    if target_field == "topics" and proposed in set(policy.get("generic_topic_values") or []):
        return _blocked_decision(
            target_field=target_field,
            value=raw_value,
            block_reason="generic_value",
            reason="Generic topic values require human review",
        )
    controlled = (policy.get("controlled_values") or {}).get(target_field)
    if controlled and proposed not in set(controlled):
        return _blocked_decision(
            target_field=target_field,
            value=raw_value,
            block_reason="invalid_controlled_value",
            reason=f"{target_field} value is outside the controlled vocabulary",
        )
    if target_field == "module" and not re.fullmatch(r"m\d{2}", proposed or ""):
        return _blocked_decision(
            target_field=target_field,
            value=raw_value,
            block_reason="invalid_controlled_value",
            reason="module value must use mNN",
        )

    return {
        "target_field": target_field,
        "proposed_value": proposed,
        "normalization_applied": raw_value != proposed,
        "confidence": "high",
        "promotion_status": "candidate",
        "authority_level": "proposed",
        "requires_human_review": False,
        "source_tag_classification": "p1_metadata_only",
        "promotion_basis": "p1_prefix_mapping",
        "reason": f"P1 prefix maps to {target_field} under metadata-promotion/v1",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or inspect metadata-promotion/v1.")
    parser.add_argument("--policy", default=str(DEFAULT_POLICY_PATH))
    parser.add_argument("--write-default", action="store_true")
    parser.add_argument("--classify", action="append", default=[])
    parser.add_argument("--upstream-rag-class", default="p1_metadata_only")
    args = parser.parse_args()

    policy = write_default_policy(args.policy) if args.write_default else load_policy(args.policy)
    if args.classify:
        rows = [
            classify_promotion(tag, upstream_rag_class=args.upstream_rag_class, policy=policy)
            for tag in args.classify
        ]
        print(stable_json(rows, indent=2))
    else:
        print(stable_json(policy, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
