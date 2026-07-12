#!/usr/bin/env python3
"""Executable tag sanitation policy for RAG-facing derived layers.

The policy is intentionally conservative: P0 tags are blocked from RAG first,
not removed from canon. This module has no apply path and never writes canon
shards.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import unicodedata
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
DEFAULT_POLICY_PATH = (
    REPO_ROOT
    / "data"
    / "out"
    / "local"
    / "pipeline"
    / "tag_sanitation"
    / "s0169"
    / "tag_sanitation_policy.json"
)

POLICY_VERSION = "tag-sanitation/v1"

DEFAULT_P0_BLOCK_PATTERNS = [
    r"^---\s*",
    r"^#+\s",
    r"^src/",
    r"^data/",
    r"^tests/",
    r"^\.github/",
    r"(^|/)__pycache__(/|$)",
    r"(^|/)\.pytest_cache(/|$)",
    r"(^|/)target(/|$)",
    r"(^|/)node_modules(/|$)",
    r".*\.(py|sh|go|rs|json|jsonl)$",
]

DEFAULT_P1_METADATA_PREFIXES = [
    "session:",
    "milestone:",
    "status:",
    "artifact:",
    "layer:",
    "topic:",
    "module:",
    "language:",
    "authority:",
    "state:",
    "source:",
    "role:",
    "taxonomy:",
    "family:",
]

DEFAULT_P2_HUMAN_NAVIGATION_PATTERNS = [
    r"^#+\s+.*[\U0001F300-\U0001FAFF]",
]

DEFAULT_POLICY = {
    "policy_version": POLICY_VERSION,
    "session": "S0169",
    "dry_run": True,
    "canon_modified": False,
    "p0_block_patterns": DEFAULT_P0_BLOCK_PATTERNS,
    "p1_metadata_prefixes": DEFAULT_P1_METADATA_PREFIXES,
    "p2_human_navigation_patterns": DEFAULT_P2_HUMAN_NAVIGATION_PATTERNS,
    "p3_projectable_namespaces": ["tdc:"],
    "rag_blocklist": [],
    "rag_allowlist": [],
    "never_use_as_relation_source": ["tdc:*"],
    "never_use_as_primary_metadata_source": ["tdc:*"],
    "default_action": {
        "p0_blocked": "block_from_rag",
        "p1_promote": "promote_to_metadata",
        "p2_human_nav": "keep",
        "p3_projectable": "candidate_for_projection",
        "unknown": "review",
    },
}

CLASSIFICATIONS = {
    "p0_blocked",
    "p1_promote",
    "p2_human_nav",
    "p3_projectable",
    "unknown",
}

RAG_CLASS_BY_CLASSIFICATION = {
    "p0_blocked": "p0_blocked",
    "p1_promote": "p1_metadata_only",
    "p2_human_nav": "p2_human_navigation",
    "p3_projectable": "p3_projectable",
    "unknown": "unknown_review",
}


def stable_json(value: Any, *, indent: int | None = None) -> str:
    if indent is None:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=indent)


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"[ \t]+", " ", text).strip()


def parse_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [tag for tag in (normalize_text(item) for item in value) if tag]
    text = normalize_text(value)
    if not text:
        return []
    tags: list[str] = []
    for match in re.finditer(r"\[\[([^\]]+)\]\]|(\S+)", text):
        tag = normalize_text(match.group(1) or match.group(2))
        if tag:
            tags.append(tag)
    return tags


def load_policy(path: Path | str = DEFAULT_POLICY_PATH) -> dict[str, Any]:
    policy_path = Path(path)
    if not policy_path.exists():
        return dict(DEFAULT_POLICY)
    payload = json.loads(policy_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"policy root must be an object: {policy_path}")
    merged = dict(DEFAULT_POLICY)
    merged.update(payload)
    return merged


def write_default_policy(path: Path | str = DEFAULT_POLICY_PATH) -> dict[str, Any]:
    policy = dict(DEFAULT_POLICY)
    policy_path = Path(path)
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    policy_path.write_text(stable_json(policy, indent=2) + "\n", encoding="utf-8")
    return policy


def has_emoji(text: str) -> bool:
    for char in text:
        codepoint = ord(char)
        if 0x1F000 <= codepoint <= 0x1FAFF:
            return True
        if unicodedata.category(char) == "So" and codepoint > 0x2600:
            return True
    return False


def looks_like_markdown_header(tag: str) -> bool:
    return bool(re.match(r"^#+\s", tag))


def looks_like_code_marker(tag: str) -> bool:
    return bool(re.match(r"^---\s*", tag))


def looks_like_path(tag: str) -> bool:
    lowered = tag.lower()
    if lowered.startswith(("src/", "data/", "tests/", ".github/")):
        return True
    if any(part in lowered for part in ("__pycache__", ".pytest_cache", "node_modules/")):
        return True
    if lowered == "target" or lowered.startswith("target/") or "/target/" in lowered:
        return True
    if "/" in tag and re.search(r"\.(py|sh|go|rs|json|jsonl)$", lowered):
        return True
    return bool(re.search(r"\.(py|sh|go|rs|json|jsonl)$", lowered))


def looks_like_metadata_prefix(tag: str, policy: dict[str, Any] | None = None) -> bool:
    policy = policy or DEFAULT_POLICY
    lowered = tag.casefold()
    return any(lowered.startswith(prefix.casefold()) for prefix in policy.get("p1_metadata_prefixes", []))


def _matches_any_regex(tag: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, tag) for pattern in patterns)


def _matches_any_glob(tag: str, patterns: list[str]) -> bool:
    lowered = tag.casefold()
    return any(fnmatch.fnmatchcase(lowered, pattern.casefold()) for pattern in patterns)


def classify_tag(tag: str, policy: dict[str, Any] | None = None) -> dict[str, Any]:
    policy = policy or DEFAULT_POLICY
    clean = normalize_text(tag)
    human_nav = _matches_any_regex(clean, list(policy.get("p2_human_navigation_patterns", [])))
    p3_namespace = any(
        clean.casefold().startswith(ns.casefold())
        for ns in policy.get("p3_projectable_namespaces", [])
    )
    metadata_prefix = looks_like_metadata_prefix(clean, policy)
    code_marker = looks_like_code_marker(clean)
    markdown_header = looks_like_markdown_header(clean)
    path_like = looks_like_path(clean)
    blocklisted = clean in set(policy.get("rag_blocklist", [])) or _matches_any_glob(
        clean, list(policy.get("rag_blocklist", []))
    )
    p0_pattern = _matches_any_regex(clean, list(policy.get("p0_block_patterns", [])))

    if human_nav:
        classification = "p2_human_nav"
        rag_policy = "human_only"
        recommended_action = "keep"
    elif blocklisted or code_marker or path_like or (p0_pattern and not metadata_prefix):
        classification = "p0_blocked"
        rag_policy = "block"
        recommended_action = "block_from_rag"
    elif p3_namespace:
        classification = "p3_projectable"
        rag_policy = "metadata_only"
        recommended_action = "candidate_for_projection"
    elif metadata_prefix:
        classification = "p1_promote"
        rag_policy = "metadata_only"
        recommended_action = "promote_to_metadata"
    else:
        classification = "unknown"
        rag_policy = "allow"
        recommended_action = "review"

    return {
        "tag": clean,
        "has_emoji": has_emoji(clean),
        "looks_like_path": path_like,
        "looks_like_markdown_header": markdown_header,
        "looks_like_code_marker": code_marker,
        "looks_like_metadata_prefix": metadata_prefix,
        "classification": classification,
        "rag_policy": rag_policy,
        "recommended_action": recommended_action,
    }


def rag_allowed_tags(tags: list[str], policy: dict[str, Any] | None = None) -> list[str]:
    return filter_tags_for_rag(tags, policy)["allowed_semantic_tags"]


def classify_tag_for_rag(tag: str, policy: dict[str, Any] | None = None) -> dict[str, Any]:
    policy = policy or DEFAULT_POLICY
    decision = classify_tag(tag, policy)
    rag_class = RAG_CLASS_BY_CLASSIFICATION[decision["classification"]]
    clean = decision["tag"]
    allowlist = set(policy.get("rag_allowlist", []))

    semantic_text_allowed = False
    retrieval_hints_allowed = False
    embedding_metadata_allowed = False
    output_bucket = "unknown_tags"
    blocked_from_rag = True

    if clean in allowlist:
        semantic_text_allowed = True
        retrieval_hints_allowed = True
        embedding_metadata_allowed = True
        blocked_from_rag = False
        output_bucket = "allowed_semantic_tags"
    elif rag_class == "p1_metadata_only":
        retrieval_hints_allowed = True
        embedding_metadata_allowed = True
        output_bucket = "metadata_only_tags"
    elif rag_class == "p2_human_navigation":
        output_bucket = "human_navigation_tags"
    elif rag_class == "p3_projectable":
        retrieval_hints_allowed = True
        embedding_metadata_allowed = True
        output_bucket = "projectable_tags"
    elif rag_class == "p0_blocked":
        output_bucket = "blocked_tags"

    if rag_class in {"p1_metadata_only", "p2_human_navigation", "p3_projectable"}:
        blocked_from_rag = False

    return {
        **decision,
        "rag_class": rag_class,
        "semantic_text_allowed": semantic_text_allowed,
        "retrieval_hints_allowed": retrieval_hints_allowed,
        "embedding_metadata_allowed": embedding_metadata_allowed,
        "blocked_from_rag": blocked_from_rag,
        "output_bucket": output_bucket,
    }


def _append_unique(target: list[str], tag: str, seen: set[str]) -> None:
    key = tag.casefold()
    if key not in seen:
        seen.add(key)
        target.append(tag)


def filter_tags_for_rag(tags: list[str], policy: dict[str, Any] | None = None) -> dict[str, Any]:
    policy = policy or DEFAULT_POLICY
    result: dict[str, Any] = {
        "policy_version": policy.get("policy_version", POLICY_VERSION),
        "allowed_semantic_tags": [],
        "retrieval_hint_tags": [],
        "metadata_only_tags": [],
        "human_navigation_tags": [],
        "projectable_tags": [],
        "blocked_tags": [],
        "unknown_tags": [],
        "classified_tags": [],
        "counts": {
            "total_input_tags": 0,
            "allowed_semantic_tags": 0,
            "retrieval_hint_tags": 0,
            "metadata_only_tags": 0,
            "human_navigation_tags": 0,
            "projectable_tags": 0,
            "blocked_tags": 0,
            "unknown_tags": 0,
        },
    }
    seen_by_bucket: dict[str, set[str]] = {
        key: set()
        for key in (
            "allowed_semantic_tags",
            "retrieval_hint_tags",
            "metadata_only_tags",
            "human_navigation_tags",
            "projectable_tags",
            "blocked_tags",
            "unknown_tags",
        )
    }

    for raw_tag in tags:
        clean = normalize_text(raw_tag)
        if not clean:
            continue
        result["counts"]["total_input_tags"] += 1
        decision = classify_tag_for_rag(clean, policy)
        result["classified_tags"].append(decision)
        bucket = decision["output_bucket"]
        _append_unique(result[bucket], clean, seen_by_bucket[bucket])
        if decision["semantic_text_allowed"]:
            _append_unique(result["allowed_semantic_tags"], clean, seen_by_bucket["allowed_semantic_tags"])
        if decision["retrieval_hints_allowed"]:
            _append_unique(result["retrieval_hint_tags"], clean, seen_by_bucket["retrieval_hint_tags"])

    for key in seen_by_bucket:
        result[key] = sorted(result[key], key=lambda item: item.casefold())
        result["counts"][key] = len(result[key])
    return result


def p0_tags_from_inventory(inventory: dict[str, Any]) -> set[str]:
    tags = inventory.get("tags", inventory)
    if not isinstance(tags, list):
        return set()
    return {
        str(item.get("tag"))
        for item in tags
        if isinstance(item, dict) and item.get("classification") == "p0_blocked" and item.get("tag")
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or inspect the executable S0169 tag sanitation policy.")
    parser.add_argument("--policy", default=str(DEFAULT_POLICY_PATH), help="Policy JSON path.")
    parser.add_argument("--write-default", action="store_true", help="Write the default policy JSON.")
    parser.add_argument("--classify", action="append", default=[], help="Classify one tag value.")
    args = parser.parse_args()

    if args.write_default:
        policy = write_default_policy(args.policy)
    else:
        policy = load_policy(args.policy)

    if args.classify:
        rows = [classify_tag(tag, policy) for tag in args.classify]
        print(stable_json(rows, indent=2))
    else:
        print(stable_json(policy, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
