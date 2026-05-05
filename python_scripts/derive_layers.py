#!/usr/bin/env python3
"""
derive_layers.py — Stable entrypoint for local derivation (S52+).

Reads canon shards from the governed local canon root and produces:
  - data/out/local/enriched/tiddlers_enriched_{N}.jsonl
  - data/out/local/ai/tiddlers_ai_{N}.jsonl
  - data/out/local/ai/chunks_ai_{N}.jsonl
  - data/out/local/enriched/manifest.json
  - data/out/local/ai/manifest.json
  - data/out/local/microsoft_copilot/manifest.json
  - data/out/local/microsoft_copilot/navigation_index.json
  - data/out/local/microsoft_copilot/entities.json
  - data/out/local/microsoft_copilot/topics.json
  - data/out/local/microsoft_copilot/source_arbitration_report.json
  - data/out/local/microsoft_copilot/nodes.csv
  - data/out/local/microsoft_copilot/edges.csv
  - data/out/local/microsoft_copilot/artifacts.csv
  - data/out/local/microsoft_copilot/coverage.csv
  - data/out/local/microsoft_copilot/overview.txt
  - data/out/local/microsoft_copilot/reading_guide.txt
  - data/out/local/microsoft_copilot/bundles/*.txt
  - data/out/local/microsoft_copilot/spec/**/*.md
  - data/out/local/microsoft_copilot/spec/**/*.json
  - data/out/local/microsoft_copilot/copilot_agent/corpus.txt
  - data/out/local/microsoft_copilot/copilot_agent/entities.json
  - data/out/local/microsoft_copilot/copilot_agent/relations.csv
  - data/out/local/ai/reports/classification_report.json
  - data/out/local/ai/reports/chunk_qc_report.json
  - data/out/local/ai/reports/retrieval_qc_report.json
  - data/out/local/ai/reports/relations_qc_report.json
  - data/out/local/ai/reports/derivation_report.json

Hardening principles (S55):
  - 100% shard-aware: no monolithic input, no hardcoded shard count
  - Controlled vocabulary for role_primary loaded from the S79 policy contract
  - Token-aware structural chunker with hard max guardrail
  - Corpus eligibility policy loaded from machine-readable governance rules
  - Retrieval hints: normalized dedup, split into terms + aliases
  - Relations validated against known node IDs
  - Three distinct text fields: preview_text, semantic_text, ai_summary
  - Deterministic: no fabrication, no metadata invention
  - Chunk-level traceability back to canon shard, line and structural context
"""

import argparse
import csv
import json
import math
import re
import statistics
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from corpus_governance import (
    CANON_POLICY_BUNDLE_REL,
    DERIVED_LAYERS_REGISTRY_REL,
    classify_role_primary_value,
    load_canon_policy_bundle,
    load_layer_registry,
    role_primary_canonical_roles,
    resolve_corpus_policy,
)
from path_governance import (
    DEFAULT_AI_DIR,
    DEFAULT_AI_REPORTS_DIR,
    DEFAULT_AUDIT_DIR,
    DEFAULT_CANON_DIR,
    DEFAULT_ENRICHED_DIR,
    DEFAULT_EXPORT_DIR,
    DEFAULT_MICROSOFT_COPILOT_DIR,
    as_display_path,
    resolve_repo_path,
    sorted_canon_shards,
)

# ── Derivation session identifier ────────────────────────────────────────────
SESSION = "S55"
SCHEMA_VERSION = "v2"
MICROSOFT_COPILOT_GENERATED_FROM_SESSION = "m03-s61-microsoft-copilot-json-csv-txt-projection-mvp-v0"
MICROSOFT_COPILOT_FORMAT_VERSION = "json_csv_txt_mvp_v0"
MICROSOFT_COPILOT_OVERVIEW_MAX_ITEMS = 12
COPILOT_AGENT_GENERATED_FROM_SESSION = "m03-s64-copilot-agent-semantic-compression-and-reversible-canon-hardening-v0"
COPILOT_AGENT_INTEGRATION_BASELINE_SESSION = "m03-s63-copilot-agent-generator-integration-and-canonicalization-v0"
COPILOT_AGENT_SEMANTIC_REFERENCE_SESSION = "m03-s62-copilot-agent-three-master-files-pack-v0"
COPILOT_AGENT_FORMAT_VERSION = "semantic_reversible_pack_v1"
COPILOT_AGENT_ENTITY_LIMIT = 50
COPILOT_AGENT_CORPUS_MAX_CHARS = 32000
COPILOT_AGENT_FAMILY_ORDER = [
    "integration_flow",
    "semantic_compression",
    "copilot_projection",
    "minimal_canon",
    "strict_reversibility",
]
COPILOT_AGENT_FAMILY_TARGETS = {
    "integration_flow": 8,
    "semantic_compression": 10,
    "copilot_projection": 12,
    "minimal_canon": 8,
    "strict_reversibility": 7,
}
COPILOT_AGENT_TYPE_CAPS = {
    "session": 7,
    "contract": 8,
    "hypothesis": 6,
    "provenance": 6,
}
COPILOT_AGENT_RECENT_MARKERS = {
    "m03-s59",
    "m03-s60",
    "m03-s61",
    "m03-s62",
    "m03-s63",
    "m03-s64",
}
COPILOT_AGENT_REVERSE_MARKERS = {"m03-s50", "m03-s57"}
COPILOT_AGENT_STRICT_ANCHOR_TITLES = {
    "contratos/policy/canon_policy_bundle.json",
    "go/canon/embedded_json_text.go",
    "go/canon/identity.go",
}
COPILOT_AGENT_FAMILY_PURPOSES = {
    "integration_flow": "Pipeline real, capas oficiales y entrypoints que sostienen la integración del flujo.",
    "semantic_compression": "Reglas madre y nodos orientadores que hacen posible una compresión semántica legible.",
    "copilot_projection": "Lineaje S59-S64 que gobierna la proyección Microsoft Copilot y el subpaquete copilot_agent.",
    "minimal_canon": "Cierre documental mínimo que debe permanecer absorbido en canon y seguir siendo trazable.",
    "strict_reversibility": "Reglas, artefactos y componentes que condicionan normalización determinística y reverse estricto.",
}
MICROSOFT_COPILOT_MICROSOFT_SUPPORT_REF = {
    "title": "Formatos de archivo admitidos por Microsoft 365 Copilot",
    "url": "https://support.microsoft.com/es-es/topic/formatos-de-archivo-admitidos-por-microsoft-365-copilot-1afb9a70-2232-4753-85c2-602c422af3a8",
    "observed_support": {
        "json": "configuration and markup",
        "txt": "document creation and plain text",
        "csv": "data analysis and spreadsheets",
    },
    "consulted_at": "2026-04-22",
}
CANON_POLICY_BUNDLE = load_canon_policy_bundle()
LAYER_REGISTRY = load_layer_registry()

# ── Default configuration ─────────────────────────────────────────────────────
DEFAULT_ENRICHED_SHARD_SIZE = 100
DEFAULT_AI_SHARD_SIZE = 100
DEFAULT_CHUNK_SHARD_SIZE = 200
DEFAULT_CHUNK_TARGET_TOKENS = 1800
DEFAULT_CHUNK_MAX_TOKENS = 4000   # hard max — no chunk may exceed this
DEFAULT_MICROCHUNK_MIN_TOKENS = 80
DEFAULT_TIDDLER_SHARD_SIZE = 100
DEFAULT_CHUNK_SHARD_SIZE_ARG = 200

# ── Controlled vocabulary for role_primary ────────────────────────────────────
VALID_ROLES = role_primary_canonical_roles(CANON_POLICY_BUNDLE)

# Stop words for retrieval hint extraction
STOP_WORDS = {
    "para", "como", "este", "esta", "todo", "cada", "donde", "cuando",
    "tiddly", "data", "converter", "desde", "hasta", "sobre", "entre",
    "pero", "sino", "porque", "aunque", "mientras", "durante", "tras",
    "ante", "bajo", "cabe", "con", "contra", "desde", "hace",
    "hacia", "mediante", "para", "por", "segun", "según", "sin",
    "sobre", "tras", "versus", "the", "and", "for", "from", "with",
    "that", "this", "are", "was", "were", "has", "have", "been",
    "not", "all", "can", "will", "its", "into", "than", "then",
    "they", "them", "what", "when", "also",
}

PATHISH_SUFFIX_RE = re.compile(r"\.[A-Za-z0-9._-]+$")
NON_SPACE_RE = re.compile(r"\S")
WORDLIKE_RE = re.compile(r"\w+", flags=re.UNICODE)
PUNCTLIKE_RE = re.compile(r"[^\w\s]", flags=re.UNICODE)
MARKDOWN_HEADER_RE = re.compile(r"^#{1,6}\s+")
CODE_BOUNDARY_RE = re.compile(
    r"^(?:"
    r"def\s+|async\s+def\s+|class\s+|func\s+|type\s+\w+|"
    r"const\s*\(|var\s*\(|package\s+\w+|impl\b|pub\s+fn\s+|fn\s+|"
    r"[A-Za-z_][A-Za-z0-9_]*\s*\(\)\s*\{|"
    r"//\s*[─=-]{2,}|#\s*[─=-]{2,}"
    r")"
)
HEADING_LINE_RE = re.compile(r"^(#{1,6}\s+.+|//\s*[^\s].+|#\s+[^\s].+)$")

# ── Helpers ────────────────────────────────────────────────────────────────────

def estimate_tokens(text: str) -> int:
    """Robust local proxy for token count across prose, markdown and code."""
    if not text:
        return 0
    stripped = text.strip()
    if not stripped:
        return 0

    non_space_chars = len(NON_SPACE_RE.findall(stripped))
    word_units = len(WORDLIKE_RE.findall(stripped))
    punct_units = len(PUNCTLIKE_RE.findall(stripped))

    # Blend a word-like estimate with a conservative char-based floor so that
    # prose, markup and code do not undercount too aggressively.
    word_based = word_units + math.ceil(punct_units * 0.35)
    char_based = math.ceil(non_space_chars / 4.2)
    return max(1, max(word_based, char_based))


def safe_str(val) -> str:
    return "" if val is None else str(val)


def normalize_for_dedup(s: str) -> str:
    """Normalize string for deduplication: lowercase + remove accents."""
    s = s.lower().strip()
    # Remove accents
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def strip_emoji(s: str) -> str:
    """Remove emoji characters from a string."""
    emoji_pattern = re.compile(
        "[\U0001F300-\U0001FFFF"
        "\U00002600-\U000027BF"
        "\U0000FE00-\U0000FE0F"
        "\u200d"
        "\u20E3"
        "]+",
        flags=re.UNICODE,
    )
    return emoji_pattern.sub("", s).strip()


def looks_like_repo_path(title: str) -> bool:
    title = safe_str(title)
    if not title:
        return False
    return (
        "/" in title
        or title in {".gitignore", "README.md", "estructura.txt", "scripts.txt", "contratos.txt"}
        or bool(PATHISH_SUFFIX_RE.search(title))
    )


def looks_like_build_artifact_path(title: str) -> bool:
    title_lower = safe_str(title).lower()
    return (
        "/target/" in title_lower
        or ".fingerprint/" in title_lower
        or "/debug/build/" in title_lower
    )


def looks_like_inventory_manifest(title: str) -> bool:
    title_lower = safe_str(title).lower()
    inventory_names = {"contratos.txt", "estructura.txt", "scripts.txt"}
    inventory_suffixes = (
        "/contratos.txt",
        "/esquemas.txt",
        "/go.txt",
        "/packaging.txt",
        "/python.txt",
        "/rust.txt",
        "/runtime.txt",
        "/scripts.txt",
    )
    return title_lower in inventory_names or title_lower.endswith(inventory_suffixes)


# ── Semantic classifier ────────────────────────────────────────────────────────

def classify_role(rec: dict) -> str:
    """
    Classify role_primary using the controlled S79 contract.
    Uses title, tags, section_path, content_type, and source fields.
    """
    existing = rec.get("role_primary")
    role_check = classify_role_primary_value(existing, CANON_POLICY_BUNDLE)
    if role_check["verdict"] in {"role_ok", "role_alias_mapped", "role_legacy_detected"}:
        canonical_role = role_check.get("canonical_role")
        if canonical_role in VALID_ROLES:
            return canonical_role

    title = safe_str(rec.get("title"))
    title_lower = title.lower()
    title_stripped = strip_emoji(title).lower()
    ct = safe_str(rec.get("content_type"))
    section_path = rec.get("section_path") or []
    sp_joined = " ".join(safe_str(s).lower() for s in section_path)
    tags = rec.get("tags") or []
    tags_lower = [safe_str(t).lower() for t in tags]
    tags_joined = " ".join(tags_lower)
    source_fields = rec.get("source_fields") or {}
    source_tags_raw = safe_str(source_fields.get("tags", "")).lower()

    # Helper: check any of these patterns appear in text
    def match_any(text, patterns):
        return any(p in text for p in patterns)

    # ── Session tiddlers ──
    # "#### 🌀 Sesión NN = ..."
    if re.match(r"####\s+[🌀 ]+sesión\s+\d+", title_lower):
        # Check if it's NOT hypothesis or provenance
        if "hipótesis" not in title_lower and "hipotesis" not in title_lower and "procedencia" not in title_lower:
            return "session"

    # "#### 🌀🧪 Hipótesis de sesión NN = ..."
    if re.search(r"(hipótesis|hipotesis)\s+de\s+sesión", title_lower):
        return "hypothesis"
    if match_any(title_lower, ["🧪 hipótesis de sesión", "🧪 hipotesis de sesion"]):
        return "hypothesis"

    # "#### 🌀🧾 Procedencia de sesión NN"
    if "procedencia de sesión" in title_lower or "procedencia de sesion" in title_lower:
        return "provenance"
    if "🧾 procedencia de sesión" in title_lower or "🧾 procedencia" in title_lower:
        return "provenance"

    # ── Dependency tiddlers ──
    if "hipótesis de dependencias" in title_lower or "hipotesis de dependencias" in title_lower:
        return "hypothesis"
    if "procedencia de dependencias" in title_lower:
        return "provenance"
    if "política de dependencias" in title_lower or "politica de dependencias" in title_lower:
        return "policy"
    if "registro de dependencias" in title_lower:
        return "report"

    # ── Protocol ──
    if "protocolo de sesión" in title_lower or "protocolo" in title_stripped:
        if "🧭" in title or "protocolo" in title_lower:
            return "protocol"

    # ── Glossary / Dictionary ──
    if "glosario" in title_lower:
        return "glossary"
    if "diccionario" in title_lower:
        return "dictionary"

    # ── Hypothesis tiddlers (structural) ──
    if re.match(r"##\s+🧪", title) or title_lower.strip().startswith("## 🧪"):
        return "hypothesis"
    if "hipótesis" in title_lower and title.startswith("##"):
        return "hypothesis"
    if "hipótesis inicial" in title_lower or "hipotesis inicial" in title_lower:
        return "hypothesis"

    # ── Provenance (structural) ──
    if "procedencia epistemológica" in title_lower or "procedencia epistemologica" in title_lower:
        return "provenance"
    if "procedencia inicial" in title_lower:
        return "provenance"

    # ── Policy ──
    if "política de memoria" in title_lower or "politica de memoria" in title_lower:
        return "policy"
    if "principios de gestion" in title_lower or "principios de gestión" in title_lower:
        return "policy"
    if "buen gusto" in title_lower:
        return "policy"
    if "calidad de referencias" in title_lower:
        return "policy"
    if "reglas de relaciones" in title_lower:
        return "policy"
    if "usabilidad y robustez" in title_lower:
        return "policy"
    if "complejidad esencial" in title_lower:
        return "policy"
    if "modularidad y estado" in title_lower:
        return "policy"
    if "diseño" in title_lower and title.startswith("## "):
        return "policy"

    # ── Architecture ──
    if "arquitectura" in title_lower:
        return "architecture"

    # ── Components / Elements ──
    if "elementos específicos" in title_lower or "elementos especificos" in title_lower:
        return "component"

    # ── Objective ──
    if re.search(r"(objetivos|objetivo)", title_lower) and "🎯" in title:
        return "objective"

    # ── Requirements ──
    if "requisitos" in title_lower and title.startswith("###"):
        return "requirements"

    # ── DOFA ──
    if "dofa" in title_lower:
        return "dofa"

    # ── Canon role inheritance ──
    # Preserve explicit canon typing for concrete nodes once structural
    # session/protocol roles have had a chance to resolve.
    if existing in VALID_ROLES and existing != "unclassified":
        return existing

    # ── Path-shaped repository artifacts ──
    # Filesystem-like titles should resolve by artifact family before generic
    # topical keywords such as "audit", "semantic" or "report".
    if looks_like_repo_path(title):
        if looks_like_build_artifact_path(title):
            if ct == "text/html" or title_lower.endswith(".html") or title_lower.endswith(".derived.html"):
                return "html_artifact"
            if title_lower.endswith((".rs", ".go", ".py", ".sh")):
                return "code_source"
            if title_lower.endswith(".json") and "bin-" in title_lower:
                return "report"
            return "manifest"
        if title_lower in (".gitignore", "gitignore", ".gitattributes"):
            return "config"
        if "instructions/" in title_lower and title_lower.endswith(".md"):
            return "policy"
        if title_lower.startswith("contratos/") or "contratos/" in title_lower:
            return "contract"
        if title_lower.startswith("esquemas/") or "esquemas/" in title_lower:
            return "schema"
        if looks_like_inventory_manifest(title):
            if title_lower.startswith("esquemas/"):
                return "schema"
            return "manifest"
        if "readme" in title_lower or title.lower().endswith("readme.md"):
            return "readme"
        if re.search(r"m\d+-s\d+", title_lower):
            return "contract"
        if "manifest" in title_lower or title_lower in ("estructura.txt", "scripts.txt", "contratos.txt"):
            return "manifest"
        if title_lower.endswith("_test.go") or "tests/" in title_lower or "fixture" in title_lower:
            return "test_fixture"
        if re.search(r"\.(go|rs|py|sh|ts|js)$", title_lower):
            if not title_lower.endswith("_test.go") and "test" not in title_lower.rsplit("/", 1)[-1]:
                return "code_source"
        if title_lower.endswith(("/spec.md", "spec.md")):
            return "schema"
        if title_lower.endswith(".md"):
            return "policy"
        if re.search(r"\.(ya?ml|toml|ini|env|cfg|conf)$", title_lower):
            return "config"
        if ct == "text/html" or title_lower.endswith(".html") or title_lower.endswith(".derived.html"):
            return "html_artifact"
        if title_lower.endswith(".json"):
            return "manifest"
        if title_lower.endswith(".txt") and "data" in title_lower:
            return "dataset"
        if title_lower.endswith(".txt"):
            return "manifest"

    # ── Algorithm ──
    if "algoritmos" in title_lower or "matematicas" in title_lower or "matemáticas" in title_lower:
        return "algorithm"
    # Algorithm equations by pattern
    if re.search(r"(algorithm|equation|momentum|continuity|modality)", title_lower):
        return "algorithm"

    # ── Contract ──
    if re.search(r"m\d+-s\d+-.+-contract", title_lower):
        return "contract"
    if re.search(r"m\d+-s\d+", title_lower) and title_lower.endswith((".json", ".md", ".md.json")):
        return "contract"

    # ── Reference (academic papers) ──
    # Pattern: "NN. Some Title" typical of paper lists (both "01. Title" and "08. ¿Puede...")
    if re.match(r"^\d{2}\.\s+", title):
        return "reference"
    if re.search(r"(self-referential|learning module|semantic|knowledge graph|provenance|ecosystem|annotation)", title_lower):
        return "reference"

    # ── Schema ──
    if "schema" in title_lower and "canon" in title_lower:
        return "schema"

    # ── Report ──
    if "report" in title_lower or "reporte" in title_lower:
        return "report"
    if "audit" in title_lower and "session" not in title_lower:
        return "report"

    # ── Config: workflows and CI ──
    if "workflows/" in title_lower or "github/workflows" in title_lower:
        return "config"

    # ── Dataset / data files ──
    if title_lower.endswith(".txt") and "data" in title_lower:
        return "dataset"
    if title_lower.endswith(".csv"):
        return "dataset"

    # ── Documentation stubs: "-- Emoji.md" pattern ──
    if re.match(r"^--\s+", title) and title.endswith(".md"):
        # These are markdown stubs documenting structural tiddlers
        return "policy"

    # ── Draft tiddlers ──
    if title_lower.startswith("draft of"):
        # Extract session type from the title
        inner = title_lower.replace("draft of '", "").replace("'", "")
        if "sesión" in inner or "sesion" in inner:
            return "session"
        if "hipótesis" in inner or "hipotesis" in inner:
            return "hypothesis"
        if "procedencia" in inner:
            return "provenance"
        return "session"  # default for drafts

    # ── Asset (binary / image) ──
    if rec.get("is_binary") or ct in ("image/png", "image/jpeg", "image/gif", "image/svg+xml",
                                       "application/octet-stream"):
        return "asset"

    # ── Default ──
    return "unclassified"


def derive_taxonomy_and_section(rec: dict) -> tuple:
    """
    Improve taxonomy_path and section_path where deterministically derivable.
    Returns (taxonomy_path, section_path) lists.
    """
    title = safe_str(rec.get("title"))
    title_lower = title.lower()
    existing_tp = rec.get("taxonomy_path") or []
    existing_sp = rec.get("section_path") or []
    role = rec.get("_derived_role") or classify_role(rec)

    taxonomy = list(existing_tp) if existing_tp else []
    section = list(existing_sp) if existing_sp else []

    # Derive taxonomy from role when missing
    if not taxonomy:
        role_to_taxonomy = {
            "session": ["project/sessions"],
            "hypothesis": ["project/sessions/hypothesis"],
            "provenance": ["project/sessions/provenance"],
            "protocol": ["project/governance/protocol"],
            "contract": ["project/governance/contract"],
            "policy": ["project/governance/policy"],
            "schema": ["project/governance/schema"],
            "report": ["project/operations/report"],
            "reference": ["project/docs/reference"],
            "glossary": ["project/docs/glossary"],
            "dictionary": ["project/docs/dictionary"],
            "architecture": ["project/architecture"],
            "component": ["project/architecture/component"],
            "requirements": ["project/governance/requirements"],
            "objective": ["project/governance/objective"],
            "dofa": ["project/governance/dofa"],
            "algorithm": ["project/algorithms"],
            "code_source": ["project/code"],
            "test_fixture": ["project/tests/fixture"],
            "dataset": ["project/data"],
            "manifest": ["project/artifacts/manifest"],
            "html_artifact": ["project/artifacts/html"],
            "readme": ["project/docs/readme"],
            "config": ["project/config"],
            "asset": ["project/assets"],
        }
        derived = role_to_taxonomy.get(role)
        if derived:
            taxonomy = derived

    # Derive section from title when missing
    if not section and title:
        # If title contains markdown heading info
        if re.match(r"#{1,5}\s+", title):
            level = len(re.match(r"(#{1,5})\s+", title).group(1))
            section = [title]
        elif title.startswith("#### 🌀"):
            section = [title]

    return taxonomy, section


# ── Text field computation ─────────────────────────────────────────────────────

def compute_preview_text(rec: dict, max_chars: int = 400) -> str:
    """
    preview_text: deterministic head-tail preview of the content.
    Not a summary — literally the beginning (and end if long) of the text.
    """
    text = safe_str(rec.get("text"))
    if not text:
        content = rec.get("content") or {}
        text = safe_str(content.get("plain"))
    if not text:
        return ""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    head = text[: max_chars // 2].strip()
    tail = text[-(max_chars // 2) :].strip()
    return head + " … " + tail


def compute_semantic_text(rec: dict, max_chars: int = 600) -> str:
    """
    semantic_text: the most semantically useful text fragment for this node.
    Uses content.plain preferentially; falls back to text.
    This is usable base text for AI indexing — not a summary.
    """
    existing = rec.get("semantic_text")
    if isinstance(existing, str):
        existing = existing.strip()
        if existing:
            return existing

    content = rec.get("content") or {}
    plain = safe_str(content.get("plain")).strip()
    if plain:
        if len(plain) <= max_chars:
            return plain
        # Try to end at sentence boundary
        truncated = plain[:max_chars]
        for sep in (". ", ".\n", "! ", "? "):
            pos = truncated.rfind(sep)
            if pos > max_chars * 0.5:
                return truncated[: pos + 1].strip()
        return truncated.rstrip() + "…"
    text = safe_str(rec.get("text")).strip()
    if text:
        if len(text) <= max_chars:
            return text
        truncated = text[:max_chars]
        for sep in (". ", ".\n", "! ", "? "):
            pos = truncated.rfind(sep)
            if pos > max_chars * 0.5:
                return truncated[: pos + 1].strip()
        return truncated.rstrip() + "…"
    return ""


def compute_ai_summary(rec: dict, role: str) -> str:
    """
    ai_summary: a short, intentional description of the node's purpose.
    Constructed deterministically from title, role, and text beginning.
    This is NOT a mechanical truncation — it's a short purposeful description.
    """
    title = safe_str(rec.get("title")).strip()
    content = rec.get("content") or {}
    plain = safe_str(content.get("plain")).strip()
    text = safe_str(rec.get("text")).strip()

    # For sessions, hypothesis, provenance: use first meaningful sentence
    if role in ("session", "hypothesis", "provenance"):
        body = plain or text
        if body:
            # Extract first non-empty line that is not a markdown heading
            for line in body.splitlines():
                line = line.strip()
                if line and not line.startswith("#") and len(line) > 20:
                    return line[:300]
        return f"{role.capitalize()}: {title}"

    # For reference: use title as summary (it IS the reference)
    if role == "reference":
        return f"Academic reference: {title}"

    # For algorithm: use title + first equation-like line
    if role == "algorithm":
        body = plain or text
        if body:
            for line in body.splitlines():
                line = line.strip()
                if line and len(line) > 10:
                    return line[:250]
        return f"Algorithm: {title}"

    # For policy/protocol/contract: use first substantive line
    if role in ("policy", "protocol", "contract", "schema"):
        body = plain or text
        if body:
            for line in body.splitlines():
                line = line.strip()
                if line and not line.startswith("#") and len(line) > 15:
                    return line[:280]
        return f"{role.capitalize()}: {title}"

    # Default: first substantive sentence
    body = plain or text
    if body:
        for line in body.splitlines():
            line = line.strip()
            if line and not line.startswith("#") and len(line) > 10:
                return line[:280]

    return title[:200] if title else ""


# ── Retrieval hints ────────────────────────────────────────────────────────────

def build_retrieval_hints(rec: dict, role: str) -> dict:
    """
    Build retrieval_terms and retrieval_aliases.
    - retrieval_terms: canonical, normalized, deduplicated
    - retrieval_aliases: useful variants (accented vs non-accented, etc.)
    Returns {"retrieval_terms": [...], "retrieval_aliases": [...], "retrieval_hints": [...]}
    """
    seen_normalized = {}   # normalized_form -> canonical form
    terms = []
    aliases = []

    def add_term(word: str):
        """Add word as canonical term if not already seen."""
        w = word.strip()
        if not w or len(w) < 3 or w in STOP_WORDS:
            return
        norm = normalize_for_dedup(w)
        if norm not in seen_normalized:
            seen_normalized[norm] = w
            terms.append(w)

    def add_alias(word: str):
        """Add word as alias if it provides value beyond existing terms."""
        w = word.strip()
        if not w or len(w) < 3 or w in STOP_WORDS:
            return
        norm = normalize_for_dedup(w)
        if norm in seen_normalized:
            # Already have canonical; add as alias if different spelling
            canonical = seen_normalized[norm]
            if w.lower() != canonical.lower() and w not in aliases and w not in terms:
                aliases.append(w)
        else:
            # Not seen — treat as a new term
            seen_normalized[norm] = w
            terms.append(w)

    title = safe_str(rec.get("title")).strip()
    # Clean title: remove emoji, markdown syntax
    clean_title = strip_emoji(title)
    clean_title = re.sub(r"^#+\s*", "", clean_title)
    clean_title = re.sub(r"^-+\s*", "", clean_title)

    # Add meaningful words from title
    for word in re.findall(r"[^\W\d_]{3,}", clean_title, re.UNICODE):
        add_term(word.lower())

    # Session/hypothesis/provenance number as term
    m = re.search(r"sesión\s+(\d+)|sesion\s+(\d+)", title.lower())
    if m:
        num = m.group(1) or m.group(2)
        add_term(f"sesion-{num}")
        add_alias(f"sesión-{num}")

    # Tags as terms
    for tag in (rec.get("tags") or []):
        clean_tag = strip_emoji(safe_str(tag))
        clean_tag = re.sub(r"^#+\s*", "", clean_tag)
        for word in re.findall(r"[^\W\d_]{3,}", clean_tag, re.UNICODE):
            add_alias(word.lower())

    # normalized_tags
    for tag in (rec.get("normalized_tags") or []):
        for word in re.findall(r"[^\W\d_]{3,}", safe_str(tag), re.UNICODE):
            add_alias(word.lower())

    # taxonomy_path
    for path_part in (rec.get("taxonomy_path") or []):
        clean_p = strip_emoji(safe_str(path_part))
        for word in re.findall(r"[^\W\d_]{3,}", clean_p, re.UNICODE):
            add_alias(word.lower())

    # role as a term
    if role and role != "unclassified":
        add_term(role)

    # Limit output
    final_terms = [t for t in terms if len(t) >= 3][:15]
    final_aliases = [a for a in aliases if len(a) >= 3 and a not in final_terms][:10]

    return {
        "retrieval_terms": final_terms,
        "retrieval_aliases": final_aliases,
        "retrieval_hints": final_terms + final_aliases,  # combined for compatibility
    }


# ── Secondary roles ────────────────────────────────────────────────────────────

def build_secondary_roles(rec: dict, role: str) -> list:
    """
    Derive secondary_roles with deduplication and maximum of 4.
    Must not be a semantic garbage dump.
    """
    existing = rec.get("roles_secondary")
    if isinstance(existing, list):
        seen = {role}
        final = []
        for item in existing:
            val = safe_str(item).strip()
            if not val or val in seen or len(final) >= 4:
                continue
            seen.add(val)
            final.append(val)
        if final:
            return final

    roles = []
    title_lower = safe_str(rec.get("title")).lower()
    tags_lower = [safe_str(t).lower() for t in (rec.get("tags") or [])]
    tags_joined = " ".join(tags_lower)
    ct = safe_str(rec.get("content_type"))

    # Cross-cutting secondary roles
    if "hipótesis" in tags_joined or "hipotesis" in tags_joined:
        if role != "hypothesis":
            roles.append("hypothesis")
    if "procedencia" in tags_joined:
        if role != "provenance":
            roles.append("provenance")
    if "sesion" in tags_joined or "sesión" in tags_joined:
        if role != "session":
            roles.append("session")
    if "protocolo" in tags_joined:
        if role != "protocol":
            roles.append("protocol")

    # Content-type based
    if ct == "application/json" and role not in ("config", "manifest", "schema"):
        roles.append("config")
    if ct in ("image/png", "image/jpeg") and role != "asset":
        roles.append("asset")

    # Title-based
    if "readme" in title_lower and role != "readme":
        roles.append("readme")

    # Deduplicate, remove primary role, cap at 4
    seen = {role}
    final = []
    for r in roles:
        if r not in seen and len(final) < 4:
            seen.add(r)
            final.append(r)
    return final


# ── Confidence ─────────────────────────────────────────────────────────────────

def compute_confidence(rec: dict, role: str, qflags: dict) -> int:
    """
    Confidence score 1–5 based on data completeness and role certainty.
    5 = high confidence in classification and data quality
    1 = very low confidence
    """
    score = 5

    # Role uncertainty
    if role == "unclassified":
        score -= 2
    elif role == "config":
        # config might be misclassified
        score -= 1

    # Data quality issues
    source_fields = rec.get("source_fields") or {}
    if "PENDIENTE" in safe_str(source_fields.get("tmap.id", "")):
        score -= 1
    if qflags.get("has_unknown_content_type"):
        score -= 1
    if qflags.get("has_empty_normalized_tags"):
        score -= 1
    if qflags.get("has_minimal_text"):
        score -= 1

    # taxonomy/section coverage bonus
    if rec.get("taxonomy_path"):
        score += 0  # already good
    else:
        score -= 1

    return max(1, min(5, score))


# ── Quality flags ──────────────────────────────────────────────────────────────

def compute_quality_flags(rec: dict) -> dict:
    flags = {}
    source_fields = rec.get("source_fields") or {}
    if "PENDIENTE" in safe_str(source_fields.get("tmap.id", "")):
        flags["has_pendiente_tmap_id"] = True
    if rec.get("content_type") == "unknown":
        flags["has_unknown_content_type"] = True
    if not rec.get("normalized_tags"):
        flags["has_empty_normalized_tags"] = True
    text = safe_str(rec.get("text"))
    if len(text.strip()) < 10:
        flags["has_minimal_text"] = True
    content = rec.get("content") or {}
    if not content.get("plain") and len(text.strip()) < 10:
        flags["has_empty_content"] = True
    return flags


# ── is_reference_only ──────────────────────────────────────────────────────────

def compute_is_reference_only(rec: dict, role: str) -> bool:
    """
    True only if the node genuinely contains just a link/reference and no
    substantive text payload.
    """
    text = safe_str(rec.get("text")).strip()
    content = rec.get("content") or {}
    plain = safe_str(content.get("plain")).strip()
    # If text is very short and role is reference → reference_only
    if role == "reference" and len(text) < 80 and len(plain) < 80:
        return True
    # If node has no text at all
    if not text and not plain:
        return True
    return False


def get_layer_registry_entry(layer_id: str) -> dict:
    for layer in LAYER_REGISTRY["layers"]:
        if layer.get("layer_id") == layer_id:
            return layer
    raise KeyError(f"unknown governed layer: {layer_id}")


def derive_corpus_policy(rec: dict, role: str) -> dict:
    """Assign corpus state and chunking policy from governed machine rules."""
    del role  # corpus_state currently depends on governed source evidence, not role
    return resolve_corpus_policy(rec, CANON_POLICY_BUNDLE)


# ── Chunker ────────────────────────────────────────────────────────────────────

def classify_payload(rec: dict, role: str, target_tokens: int) -> dict:
    """
    Classify payload for chunking decisions and corpus eligibility.
    """
    ct = safe_str(rec.get("content_type"))
    text = safe_str(rec.get("text"))
    is_binary = rec.get("is_binary", False)
    token_est = estimate_tokens(text)
    corpus_policy = derive_corpus_policy(rec, role)

    chunkable_types = {
        "text/markdown", "text/vnd.tiddlywiki", "text/plain", "text/html",
    }
    binary_types = {
        "image/png", "image/jpeg", "image/gif", "image/svg+xml",
        "application/octet-stream",
    }

    is_textual_payload = (
        not is_binary
        and ct in chunkable_types
        and bool(text.strip())
    )
    is_large_payload = token_est > target_tokens
    is_chunkable_text = False

    if is_binary or ct in binary_types:
        strategy = "binary_skip"
        eligibility = "excluded"
        exclusion_reason = "binary_skip"
    elif ct == "application/json":
        strategy = "json_no_chunk"
        eligibility = "excluded"
        exclusion_reason = "json_no_chunk"
    elif corpus_policy["chunk_eligibility"] == "excluded":
        strategy = corpus_policy["chunk_exclusion_reason"]
        eligibility = corpus_policy["chunk_eligibility"]
        exclusion_reason = corpus_policy["chunk_exclusion_reason"]
    elif not is_textual_payload:
        strategy = "no_chunk_type"
        eligibility = "excluded"
        exclusion_reason = "no_chunk_type"
    elif token_est <= target_tokens:
        strategy = "no_chunk_small"
        eligibility = corpus_policy["chunk_eligibility"]
        exclusion_reason = None
        is_chunkable_text = True
    elif ct == "text/html":
        strategy = "html_defensive"
        eligibility = corpus_policy["chunk_eligibility"]
        exclusion_reason = None
        is_chunkable_text = True
    elif is_textual_payload:
        strategy = "structured_chunk"
        eligibility = corpus_policy["chunk_eligibility"]
        exclusion_reason = None
        is_chunkable_text = True
    else:
        strategy = "no_chunk_type"
        eligibility = "excluded"
        exclusion_reason = "no_chunk_type"

    return {
        "is_large_payload": is_large_payload,
        "is_textual_payload": is_textual_payload,
        "is_chunkable_text": is_chunkable_text,
        "chunk_strategy": strategy,
        "token_estimate": token_est,
        "corpus_state": corpus_policy["corpus_state"],
        "corpus_state_rule_id": corpus_policy["corpus_state_rule_id"],
        "chunk_eligibility": eligibility,
        "chunk_exclusion_reason": exclusion_reason,
    }


def chunk_by_headers(text: str) -> list:
    """Split text by markdown headers into sections."""
    # Split on lines starting with # heading
    sections = []
    current = []
    for line in text.splitlines(keepends=True):
        if MARKDOWN_HEADER_RE.match(line) and current:
            sections.append("".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append("".join(current))
    return [s for s in sections if s.strip()]


def chunk_by_paragraphs(text: str) -> list:
    """Split text by double newlines (paragraph breaks)."""
    paras = re.split(r"\n{2,}", text)
    return [p.strip() for p in paras if p.strip()]


def chunk_by_sentences(text: str) -> list:
    """Split text by sentence-ending punctuation."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return [s.strip() for s in sentences if s.strip()]


def chunk_by_code_boundaries(text: str) -> list:
    """Split code-ish text by function/class/section boundaries."""
    sections = []
    current = []
    for line in text.splitlines(keepends=True):
        if CODE_BOUNDARY_RE.match(line) and current:
            sections.append("".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append("".join(current))
    return [s for s in sections if s.strip()]


def hard_split(text: str, limit_tokens: int) -> list:
    """Emergency split near natural boundaries using a token ceiling."""
    max_chars = max(400, int(limit_tokens * 4.2))
    chunks = []
    remaining = text.strip()
    while len(remaining) > max_chars:
        cut = remaining.rfind("\n\n", 0, max_chars)
        if cut < int(max_chars * 0.6):
            cut = remaining.rfind("\n", 0, max_chars)
        if cut < int(max_chars * 0.6):
            cut = remaining.rfind(" ", 0, max_chars)
        if cut <= 0:
            cut = max_chars
        chunks.append(remaining[:cut].strip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


def merge_segments(segments: list, target_tokens: int, max_tokens: int) -> list:
    """
    Merge small segments up to target_tokens, never exceeding max_tokens.
    Any single segment exceeding max_tokens gets hard-split first.
    """
    result = []
    current = ""
    current_tokens = 0

    for seg in segments:
        seg_tokens = estimate_tokens(seg)

        # If single segment still exceeds target, split it conservatively first.
        if seg_tokens > target_tokens:
            # Flush current
            if current.strip():
                result.append(current.strip())
                current = ""
                current_tokens = 0
            for part in hard_split(seg, min(target_tokens, max_tokens)):
                result.append(part.strip())
            continue

        if current_tokens + seg_tokens > target_tokens and current:
            result.append(current.strip())
            current = seg + "\n\n"
            current_tokens = seg_tokens
        else:
            current += seg + "\n\n"
            current_tokens += seg_tokens

    if current.strip():
        result.append(current.strip())

    return result


def is_code_like_payload(title: str, role: str) -> bool:
    title_lower = safe_str(title).lower()
    if role in ("code_source", "test_fixture", "config"):
        return True
    return bool(re.search(r"\.(go|rs|py|sh|ts|js)$", title_lower))


def split_structurally(text: str, title: str, role: str,
                       target_tokens: int, max_tokens: int) -> list:
    """Recursively split text while preserving high-value structural boundaries."""
    text = text.strip()
    if not text:
        return []
    if estimate_tokens(text) <= target_tokens:
        return [text]

    if is_code_like_payload(title, role):
        code_sections = chunk_by_code_boundaries(text)
        if len(code_sections) > 1:
            refined = []
            for section in code_sections:
                refined.extend(split_structurally(section, title, role, target_tokens, max_tokens))
            return refined

    header_sections = chunk_by_headers(text)
    if len(header_sections) > 1:
        refined = []
        for section in header_sections:
            refined.extend(split_structurally(section, title, role, target_tokens, max_tokens))
        return refined

    paragraphs = chunk_by_paragraphs(text)
    if len(paragraphs) > 1:
        refined = []
        for para in paragraphs:
            if estimate_tokens(para) <= target_tokens:
                refined.append(para.strip())
            else:
                refined.extend(split_structurally(para, title, role, target_tokens, max_tokens))
        return merge_segments(refined, target_tokens, max_tokens)

    sentences = chunk_by_sentences(text)
    if len(sentences) > 1:
        return merge_segments(sentences, target_tokens, max_tokens)

    return hard_split(text, min(target_tokens, max_tokens))


def join_chunk_text(left: str, right: str) -> str:
    left = left.rstrip()
    right = right.lstrip()
    if not left:
        return right
    if not right:
        return left
    return left + "\n\n" + right


def is_separator_only_chunk(chunk_text: str) -> bool:
    lines = [line.strip() for line in chunk_text.splitlines() if line.strip()]
    if not lines:
        return True
    return all(
        HEADING_LINE_RE.match(line)
        or bool(re.fullmatch(r"[-=`*_]{3,}", line))
        or line.startswith("```")
        for line in lines
    )


def is_microchunk(chunk_text: str, token_estimate: int) -> bool:
    lines = [line.strip() for line in chunk_text.splitlines() if line.strip()]
    if token_estimate < 50:
        return True
    if is_separator_only_chunk(chunk_text):
        return True
    return token_estimate < DEFAULT_MICROCHUNK_MIN_TOKENS and len(lines) <= 3


def densify_microchunks(chunks_text: list[str], target_tokens: int) -> list[str]:
    """
    Merge heading-only or context-poor fragments into adjacent chunks while
    preserving order and respecting the target token budget.
    """
    dense = [chunk.strip() for chunk in chunks_text if chunk and chunk.strip()]
    if len(dense) <= 1:
        return dense

    idx = 0
    while idx < len(dense) - 1:
        current = dense[idx]
        merged = join_chunk_text(current, dense[idx + 1])
        if is_separator_only_chunk(current) and estimate_tokens(merged) <= target_tokens:
            dense[idx + 1] = merged
            del dense[idx]
            if idx:
                idx -= 1
            continue
        idx += 1

    idx = 0
    while idx < len(dense) - 1:
        current = dense[idx]
        current_tokens = estimate_tokens(current)
        merged = join_chunk_text(current, dense[idx + 1])
        if is_microchunk(current, current_tokens) and estimate_tokens(merged) <= target_tokens:
            dense[idx + 1] = merged
            del dense[idx]
            if idx:
                idx -= 1
            continue
        idx += 1

    idx = 1
    while idx < len(dense):
        current = dense[idx]
        current_tokens = estimate_tokens(current)
        merged = join_chunk_text(dense[idx - 1], current)
        if is_microchunk(current, current_tokens) and estimate_tokens(merged) <= target_tokens:
            dense[idx - 1] = merged
            del dense[idx]
            continue
        idx += 1

    return dense


def extract_chunk_heading(chunk_text: str, section_path: list, title: str) -> str:
    """Best-effort structural label for a chunk."""
    for line in chunk_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if HEADING_LINE_RE.match(stripped):
            heading_lower = stripped.lower()
            if "[[tags]]" in heading_lower or "[[created]]" in heading_lower or "[[modified]]" in heading_lower:
                continue
            return stripped[:160]
        break
    if section_path:
        return safe_str(section_path[-1])[:160]
    return safe_str(title)[:160]


def normalize_relation_targets(relation_targets: list | None) -> list[dict]:
    """Return deterministic compact relation targets for AI projections."""
    normalized: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for rel in relation_targets or []:
        if isinstance(rel, dict):
            target = rel.get("target_id") or rel.get("target") or rel.get("id")
            rel_type = rel.get("type") or ""
            evidence = rel.get("evidence") or ""
        elif isinstance(rel, str):
            target = rel
            rel_type = ""
            evidence = ""
        else:
            continue
        if not target:
            continue
        key = (safe_str(rel_type), safe_str(target), safe_str(evidence))
        if key in seen:
            continue
        seen.add(key)
        compact = {"target_id": safe_str(target)}
        if rel_type:
            compact["type"] = safe_str(rel_type)
        if evidence:
            compact["evidence"] = safe_str(evidence)
        normalized.append(compact)
    return normalized


def relation_targets_from_relations(relations: list | None) -> list[dict]:
    """Derive compact relation_targets from canonical relations."""
    return normalize_relation_targets(relations)


def relation_targets_from_record(rec: dict) -> list[dict]:
    """Prefer existing relation_targets; fall back to canonical relations."""
    if isinstance(rec.get("relation_targets"), list):
        return normalize_relation_targets(rec.get("relation_targets"))
    return relation_targets_from_relations(rec.get("relations") or [])


def chunk_node(
    rec: dict,
    node_id: str,
    shard_file: str,
    line_num: int,
    role: str,
    taxonomy: list,
    section: list,
    retrieval_hints: list,
    payload_info: dict,
    target_tokens: int,
    max_tokens: int,
    relation_targets: list | None = None,
) -> tuple:
    """
    Chunk a node using hierarchical strategy.
    Returns (chunks: list, fallback_used: bool, exclusion_reason: str or None)
    """
    strategy = payload_info["chunk_strategy"]
    text = safe_str(rec.get("text")).strip()
    title = safe_str(rec.get("title"))
    source_anchor = {
        "canon_id": node_id,
        "shard_file": shard_file,
        "shard_line": line_num,
        "source_position": rec.get("source_position"),
    }

    # Non-chunkable cases
    if strategy in (
        "binary_skip",
        "no_chunk_type",
        "archival_only",
        "archival_only_skip",
        "historical_snapshot",
        "historical_out_artifact_skip",
    ):
        return [], False, strategy
    if strategy == "json_no_chunk":
        return [], False, "json_payload_no_chunk"
    if strategy == "no_chunk_small":
        return [], False, None  # small enough, no chunk needed

    if not text:
        return [], False, "empty_text"

    # HTML: defensive chunk (extract text content, then chunk)
    if strategy == "html_defensive":
        # Strip HTML tags for chunking
        clean = re.sub(r"<[^>]+>", " ", text)
        clean = re.sub(r"\s+", " ", clean).strip()
        if not clean or estimate_tokens(clean) <= target_tokens:
            return [], False, "html_small_after_strip"
        chunks_text = split_structurally(clean, title, role, target_tokens, max_tokens)
    elif strategy == "structured_chunk":
        chunks_text = split_structurally(text, title, role, target_tokens, max_tokens)
    else:
        return [], False, "no_chunk_strategy_matched"

    # Validate all chunks are within hard max
    fallback_used = False
    validated = []
    for ct in chunks_text:
        tok = estimate_tokens(ct)
        if tok > max_tokens:
            # Emergency hard split
            for part in hard_split(ct, max_tokens):
                validated.append(part)
            fallback_used = True
        else:
            validated.append(ct)

    validated = densify_microchunks(validated, target_tokens)
    compact_relation_targets = (
        normalize_relation_targets(relation_targets)
        if relation_targets is not None
        else relation_targets_from_record(rec)
    )

    # Build chunk records
    chunks = []
    for idx, chunk_text in enumerate(validated):
        tok = estimate_tokens(chunk_text)
        chunks.append({
            "chunk_id": f"{node_id}::chunk:{idx}",
            "source_id": node_id,
            "tiddler_id": node_id,
            "node_id": node_id,
            "title": title,
            "role_primary": role,
            "chunk_index": idx,
            "chunk_total": len(validated),
            "chunk_heading": extract_chunk_heading(chunk_text, section, title),
            "text": chunk_text,
            "token_estimate": tok,
            "within_target": tok <= target_tokens,
            "within_hard_max": tok <= max_tokens,
            "derivation_method": strategy,
            "fallback": fallback_used,
            "content_type": rec.get("content_type"),
            "document_id": rec.get("document_id"),
            "section_path": section,
            "taxonomy_path": taxonomy,
            "retrieval_hints": retrieval_hints[:8],
            "relation_targets": list(compact_relation_targets),
            "relation_count": len(compact_relation_targets),
            "corpus_state": payload_info["corpus_state"],
            "corpus_state_rule_id": payload_info["corpus_state_rule_id"],
            "chunk_eligibility": payload_info["chunk_eligibility"],
            "source_anchor": source_anchor,
            "source_position": rec.get("source_position"),
            "source_version_id": rec.get("version_id"),
        })

    return chunks, fallback_used, None


# ── Relations validation ───────────────────────────────────────────────────────

def validate_relations(relations: list, known_ids: set) -> tuple:
    """
    Validate relation targets against known node IDs.
    Returns (valid_relations, invalid_relations).
    """
    valid = []
    invalid = []
    for rel in (relations or []):
        target = rel.get("target_id") or rel.get("target") or ""
        if target and target not in known_ids:
            invalid.append({"type": rel.get("type"), "target_id": target, "reason": "target_not_found"})
        else:
            valid.append(rel)
    return valid, invalid


# S84: capa-2 semantic embedded relation types
_EMBEDDED_RELATION_TYPES = frozenset({
    "usa", "define", "requiere", "parte_de",
    "pertenece_a", "contiene", "prueba_de",
})


def extract_embedded_content_rels(rec: dict, by_title: dict) -> tuple[list[dict], int, int]:
    """
    Extract capa-2 semantic relations from the content.plain JSON payload.

    Returns (resolved_rels, stale_count, urn_count) where resolved_rels is a
    list of dicts with keys type, target_id, target_title, evidence='content_embedded'.
    Only types in _EMBEDDED_RELATION_TYPES are extracted; canonical types
    (child_of, references) are intentionally excluded.
    Stale targets (not in by_title, not URN) increment stale_count.
    URN targets (urn:uuid:...) that don't resolve increment urn_count.
    """
    try:
        content = rec.get("content") or {}
        plain = content.get("plain") if isinstance(content, dict) else None
        if not plain:
            return [], 0, 0
        inner = json.loads(plain)
        raw_rels = inner.get("relations") or []
    except Exception:
        return [], 0, 0

    resolved = []
    stale = 0
    urn = 0
    own_title = rec.get("title", "")

    for r in raw_rels:
        rtype = (r.get("type") or "").lower().strip()
        if rtype not in _EMBEDDED_RELATION_TYPES:
            continue
        target = (r.get("target") or r.get("target_id") or "").strip()
        if not target:
            continue
        if target == own_title:
            continue  # suppress self-references
        if target in by_title:
            resolved.append({
                "type": rtype,
                "target_id": by_title[target],
                "target_title": target,
                "evidence": "content_embedded",
            })
        elif target.startswith("urn:uuid:"):
            urn += 1
        else:
            stale += 1

    return resolved, stale, urn


# ── Load canon shards ──────────────────────────────────────────────────────────

def discover_shards(input_dir: Path) -> list:
    """Discover all canon shards matching tiddlers_*.jsonl pattern."""
    shards = sorted_canon_shards(input_dir)
    if not shards:
        print(f"ERROR: No tiddlers_*.jsonl shards found in {input_dir}", file=sys.stderr)
        sys.exit(1)
    return shards


def load_canon(input_dir: Path) -> tuple:
    """
    Load all canon shards. Returns (records_list, shard_paths).
    records_list: list of (record_dict, shard_filename, line_num)
    """
    shard_paths = discover_shards(input_dir)
    records = []
    for shard_path in shard_paths:
        with open(shard_path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                records.append((rec, shard_path.name, line_num))
    return records, shard_paths


# ── Sharding writer ────────────────────────────────────────────────────────────

def write_sharded(records: list, output_dir: Path, prefix: str, shard_size: int) -> list:
    """Write records to sharded JSONL files. Returns shard info list."""
    output_dir.mkdir(parents=True, exist_ok=True)
    shards_info = []
    shard_num = 1
    count_in_shard = 0
    current_file = None

    for rec in records:
        if count_in_shard == 0 or count_in_shard >= shard_size:
            if current_file:
                current_file.close()
                shards_info[-1]["record_count"] = count_in_shard
            fname = f"{prefix}_{shard_num}.jsonl"
            fpath = output_dir / fname
            current_file = open(fpath, "w", encoding="utf-8")
            shards_info.append({
                "file": fname,
                "shard_index": shard_num,
                "record_count": 0,
            })
            shard_num += 1
            count_in_shard = 0

        current_file.write(json.dumps(rec, ensure_ascii=False) + "\n")
        count_in_shard += 1

    if current_file:
        current_file.close()
        if shards_info:
            shards_info[-1]["record_count"] = count_in_shard

    return shards_info


def write_manifest(output_dir: Path, layer_name: str, shards_info: list,
                   total_records: int, source_shard_count: int,
                   source_shard_files: list, extra: dict = None,
                   layer_id: str | None = None):
    """Write manifest.json for a layer."""
    manifest = {
        "layer": layer_name,
        "session": SESSION,
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": {
            "canon_shard_count": source_shard_count,
            "canon_dir": "data/out/local",
            "canon_pattern": "tiddlers_*.jsonl",
            "canon_shard_files": [as_display_path(p) if hasattr(p, 'parts') else str(p) for p in source_shard_files],
        },
        "output": {
            "total_records": total_records,
            "shard_count": len(shards_info),
            "shards": shards_info,
        },
    }
    if layer_id:
        layer = get_layer_registry_entry(layer_id)
        manifest["governance"] = {
            "policy_bundle_ref": CANON_POLICY_BUNDLE_REL,
            "layer_registry_ref": DERIVED_LAYERS_REGISTRY_REL,
            "layer_id": layer_id,
            "layer_class": layer.get("layer_class"),
            "authority": layer.get("authority"),
            "lineage_parents": layer.get("lineage_parents"),
            "validation_inputs": layer.get("validation_inputs"),
        }
    if extra:
        manifest.update(extra)
    manifest_path = output_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    return manifest_path


def write_json_file(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    return path


def load_optional_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def shard_path_for_record(output_dir: Path, prefix: str, record_index: int, shard_size: int) -> str:
    shard_index = ((record_index - 1) // shard_size) + 1
    return as_display_path(output_dir / f"{prefix}_{shard_index}.jsonl")


def collect_microsoft_copilot_source_inventory(
    shard_paths: list,
    enriched_dir: Path,
    enriched_shards_info: list,
    ai_dir: Path,
    ai_shards_info: list,
    chunk_shards_info: list,
    reports_dir: Path,
    audit_dir: Path,
    export_dir: Path,
) -> dict:
    audit_manifest = load_optional_json(audit_dir / "manifest.json")
    export_files = sorted(path for path in export_dir.rglob("*") if path.is_file()) if export_dir.exists() else []
    ai_report_files = sorted(path for path in reports_dir.glob("*.json")) if reports_dir.exists() else []

    return {
        "canon": {
            "path": as_display_path(DEFAULT_CANON_DIR),
            "pattern": "tiddlers_*.jsonl",
            "shards": [as_display_path(path) for path in shard_paths],
        },
        "enriched": {
            "path": as_display_path(enriched_dir),
            "manifest_path": as_display_path(enriched_dir / "manifest.json"),
            "shards": [as_display_path(enriched_dir / shard["file"]) for shard in enriched_shards_info],
        },
        "ai": {
            "path": as_display_path(ai_dir),
            "manifest_path": as_display_path(ai_dir / "manifest.json"),
            "shards": [as_display_path(ai_dir / shard["file"]) for shard in ai_shards_info],
            "chunk_shards": [as_display_path(ai_dir / shard["file"]) for shard in chunk_shards_info],
            "reports": [as_display_path(path) for path in ai_report_files],
        },
        "audit": {
            "path": as_display_path(audit_dir),
            "present": audit_dir.exists(),
            "manifest_path": as_display_path(audit_dir / "manifest.json") if (audit_dir / "manifest.json").exists() else None,
            "summary_path": as_display_path(audit_dir / "compliance_summary.md") if (audit_dir / "compliance_summary.md").exists() else None,
            "latest_snapshot": {
                "generated_at": audit_manifest.get("generated_at"),
                "corpus": audit_manifest.get("corpus"),
                "audit": audit_manifest.get("audit"),
            } if audit_manifest else None,
        },
        "export": {
            "path": as_display_path(export_dir),
            "present": bool(export_files),
            "artifacts": [as_display_path(path) for path in export_files[:12]],
        },
        "governance_inputs": [
            "docs/Informe_Tecnico_de_Tiddler (Esp).md",
            "README.md",
            "data/README.md",
            ".github/instructions/tiddlers_sesiones.instructions.md",
            ".github/instructions/contratos.instructions.md",
            ".github/instructions/sesiones.instructions.md",
            "contratos/projections/derived_layers_registry.json",
            "contratos/m03-s59-microsoft-copilot-projection-governance-v0.md.json",
            "contratos/m03-s60-microsoft-copilot-derived-projection-mvp-v0.md.json",
            "contratos/m03-s61-microsoft-copilot-json-csv-txt-projection-mvp-v0.md.json",
        ],
    }


def derive_microsoft_copilot_summary(canon_rec: dict, ai_rec: dict, role: str) -> str:
    if canon_rec.get("is_binary"):
        title = safe_str(canon_rec.get("title")).strip()
        return f"Binary asset metadata for: {title}" if title else "Binary asset metadata"

    fallback = safe_str(ai_rec.get("ai_summary")).strip()
    if canon_rec.get("content_type") != "application/json":
        return fallback

    text = safe_str(canon_rec.get("text")).strip()
    if not text.startswith("{"):
        return fallback

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return fallback

    if role == "session":
        content = payload.get("content") or {}
        summary = safe_str(content.get("plain")).strip()
        return summary[:280] if summary else fallback
    if role == "hypothesis":
        summary = safe_str(payload.get("hipotesis")).strip()
        return summary[:280] if summary else fallback
    if role == "provenance":
        summary = safe_str(payload.get("origen")).strip()
        return summary[:280] if summary else fallback
    return fallback


# ── Microsoft Copilot S61 JSON/CSV/TXT projection ─────────────────────────────

S61_SPEC_SUMMARIES = [
    {
        "slug": "contratos-instructions",
        "title": "contratos.instructions.md",
        "source_files": [".github/instructions/contratos.instructions.md"],
        "summary": "Define que toda sesion sustantiva debe cerrar con contrato `.md.json` importable en TiddlyWiki, artefactos afectados, decisiones, validaciones y absorcion canónica del nodo de contrato cuando corresponda.",
        "rules": [
            "emitir contrato `.md.json` por sesion sustantiva",
            "documentar alcance, decisiones, archivos tocados, limites y validaciones",
            "mantener contrato legible por humano e importable por TiddlyWiki",
            "absorber el nodo de contrato en canon cuando la sesion produce memoria documental",
        ],
        "artifacts": ["contratos/m03-s61-microsoft-copilot-json-csv-txt-projection-mvp-v0.md.json"],
        "impact": "Obliga a que S61 no cierre solo con outputs derivados; debe dejar contrato trazable y canon reversible.",
        "projection_impact": ["procedencia", "autoridad", "regeneracion"],
    },
    {
        "slug": "dependencia-y-superficie-externa",
        "title": "dependencia_y_superficie_externa.instructions.md",
        "source_files": [".github/instructions/dependencia_y_superficie_externa.instructions.md"],
        "summary": "Gobierna dependencias, superficie externa, seguridad y reproducibilidad; exige justificar referencias externas sin convertirlas en nuevas dependencias del sistema.",
        "rules": [
            "separar referencia externa de dependencia operativa",
            "no introducir integraciones cloud ni nuevas credenciales por defecto",
            "registrar superficie externa solo si afecta decisiones reales",
            "mantener reproducibilidad local-first",
        ],
        "artifacts": ["source_arbitration_report.json", "spec/summaries/microsoft-support-formats.json"],
        "impact": "La fuente de Microsoft se usa solo para confirmar coherencia de formatos, no como autoridad del canon.",
        "projection_impact": ["seleccion de fuentes", "procedencia", "autoridad"],
    },
    {
        "slug": "desarrollo-y-evolucion",
        "title": "desarrollo_y_evolucion.instructions.md",
        "source_files": [".github/instructions/desarrollo_y_evolucion.instructions.md"],
        "summary": "Ordena registrar cambios de estado del proyecto, razones, pendientes y continuidad historica sin borrar contexto previo.",
        "rules": [
            "explicar que cambio y por que",
            "preservar continuidad entre S59, S60 y S61",
            "distinguir cierre operativo de deuda residual",
            "no borrar decisiones anteriores sin declarar reemplazo",
        ],
        "artifacts": ["spec/memoria_decisiones_s61.md", "bundles/recent_sessions.txt"],
        "impact": "S61 documenta la transicion de JSONL de S60 a JSON/CSV/TXT sin ocultar el reemplazo.",
        "projection_impact": ["bundles TXT", "regeneracion", "procedencia"],
    },
    {
        "slug": "detalles-del-tema",
        "title": "detalles_del_tema.instructions.md",
        "source_files": [".github/instructions/detalles_del_tema.instructions.md"],
        "summary": "Delimita alcance tematico, evita mezclar normativa, ejecucion y contenido sustantivo sin senalarlo.",
        "rules": [
            "separar diseno de proyeccion de autoridad canónica",
            "mantener foco en utilidad real para agentes",
            "evitar expansion conceptual innecesaria",
        ],
        "artifacts": ["overview.txt", "reading_guide.txt"],
        "impact": "La capa se describe como superficie de lectura, no como regimen normativo nuevo.",
        "projection_impact": ["estructura JSON", "bundles TXT", "autoridad"],
    },
    {
        "slug": "elementos-especificos",
        "title": "elementos_especificos.istructions.md",
        "source_files": [".github/instructions/elementos_especificos.istructions.md"],
        "summary": "Exige preservar artefactos concretos con identidad, contexto y recuperabilidad.",
        "rules": [
            "no dejar artefactos huerfanos",
            "cada recurso debe tener ruta y rol",
            "la salida debe ser navegable por agente",
            "las referencias deben conservar identidad",
        ],
        "artifacts": ["artifacts.csv", "navigation_index.json"],
        "impact": "Todos los outputs de S61 quedan inventariados y enlazados desde manifest/navigation.",
        "projection_impact": ["tablas CSV", "estructura JSON", "procedencia"],
    },
    {
        "slug": "glosario-y-convenciones",
        "title": "glosario_y_convenciones.instructions.md",
        "source_files": [".github/instructions/glosario_y_convenciones.instructions.md"],
        "summary": "Estabiliza nombres, alias y convenciones compartidas para reducir ambiguedad semantica.",
        "rules": [
            "usar nombres consistentes para capas y artefactos",
            "no cambiar convenciones sin justificacion",
            "declarar equivalencias cuando existan",
        ],
        "artifacts": ["entities.json", "topics.json", "nodes.csv"],
        "impact": "Fija `JSON/CSV/TXT` como familias de salida y evita que `.jsonl` siga nombrado como target final.",
        "projection_impact": ["estructura JSON", "tablas CSV", "regeneracion"],
    },
    {
        "slug": "hipotesis",
        "title": "hipotesis.instructions.md",
        "source_files": [".github/instructions/hipotesis.instructions.md"],
        "summary": "Gobierna afirmaciones tentativas: deben declararse como hipotesis, con evidencia base y sin confundirse con hechos.",
        "rules": [
            "formular hipotesis de trabajo con evidencia",
            "mantener estatuto tentativo hasta validacion",
            "no presentar preferencia de formato como verdad canónica",
        ],
        "artifacts": ["spec/memoria_decisiones_s61.md", "canon:hipotesis_s61"],
        "impact": "La hipotesis JSON/CSV/TXT queda registrada en memoria y canon, no dispersa en conversacion.",
        "projection_impact": ["procedencia", "autoridad", "bundles TXT"],
    },
    {
        "slug": "politica-de-memoria-activa",
        "title": "politica_de_memoria_activa.instructions.md",
        "source_files": [".github/instructions/politica_de_memoria_activa.instructions.md"],
        "summary": "Ordena memoria selectiva, situada y util, evitando copiar todo sin criterio.",
        "rules": [
            "seleccionar memoria por relevancia",
            "evitar duplicacion indiscriminada",
            "preservar texto sustantivo cuando sea util",
            "declarar transformaciones y limites",
        ],
        "artifacts": ["bundles/*.txt", "spec/memoria_decisiones_s61.md"],
        "impact": "Los bundles TXT preservan texto relevante de sesiones, contratos y gobernanza sin clonar todo el canon.",
        "projection_impact": ["bundles TXT", "seleccion de fuentes", "procedencia"],
    },
    {
        "slug": "prcommits",
        "title": "PRcommits.instructions.md",
        "source_files": [".github/instructions/PRcommits.instructions.md"],
        "summary": "Regula propuestas de PR y commits; en S61 aplica solo como cautela documental, no como obligacion de abrir PR.",
        "rules": [
            "si hay PR, usar estructura de commits vigente",
            "todo cambio sustantivo conserva contrato",
            "no convertir la sesion en PR si el usuario no lo pide",
        ],
        "artifacts": ["contrato S61"],
        "impact": "No altera el output Copilot; confirma que el cierre contractual es independiente de PR.",
        "projection_impact": ["procedencia"],
    },
    {
        "slug": "principios-de-gestion",
        "title": "principios_de_gestion.instructions.md",
        "source_files": [".github/instructions/principios_de_gestion.instructions.md"],
        "summary": "Fija principios transversales y resolucion de tensiones entre coherencia, utilidad, trazabilidad, simplicidad y documentacion.",
        "rules": [
            "priorizar coherencia con sistema actual",
            "evitar complejidad accidental",
            "resolver conflictos explicitamente",
            "documentar decisiones necesarias",
        ],
        "artifacts": ["spec/plan_de_implementacion_s61.md", "source_arbitration_report.json"],
        "impact": "La resolucion principal reemplaza el JSONL final por JSON/CSV/TXT sin crear subsistema nuevo.",
        "projection_impact": ["estructura JSON", "tablas CSV", "bundles TXT", "autoridad"],
    },
    {
        "slug": "procedencia-epistemologica",
        "title": "procedencia_epistemologica.instructions.md",
        "source_files": [".github/instructions/procedencia_epistemologica.instructions.md"],
        "summary": "Exige declarar origen, metodo, actor y estatuto de lo generado, distinguiendo observacion, inferencia y transformacion.",
        "rules": [
            "cada artefacto declara fuentes usadas",
            "distinguir observacion de inferencia",
            "registrar fuente externa oficial cuando se usa",
            "mantener reversible la transformacion",
        ],
        "artifacts": ["source_arbitration_report.json", "coverage.csv", "canon:procedencia_s61"],
        "impact": "La proyeccion declara `source_of_truth`, `source_inputs`, linaje y autoridad no autoritativa.",
        "projection_impact": ["procedencia", "autoridad", "regeneracion"],
    },
    {
        "slug": "protocolo-de-sesion",
        "title": "protocolo_de_sesion.instructions.md",
        "source_files": [".github/instructions/protocolo_de_sesion.instructions.md"],
        "summary": "Define disciplina de sesion: leer situado, actuar sobre archivos reales, validar y cerrar con artefactos.",
        "rules": [
            "no cerrar solo con analisis",
            "leer lo minimo suficiente y pertinente",
            "mantener autoridad humana",
            "validar el flujo afectado",
        ],
        "artifacts": ["checklist_global_s61.md", "contrato S61", "canon family S61"],
        "impact": "S61 implementa y valida la capa, no solo la especifica.",
        "projection_impact": ["regeneracion", "procedencia"],
    },
    {
        "slug": "sesiones",
        "title": "sesiones.instructions.md",
        "source_files": [".github/instructions/sesiones.instructions.md"],
        "summary": "Establece que el canon local manda, que los derivados son subordinados y que toda sesion con memoria debe cerrar en canon con validacion strict/reverse.",
        "rules": [
            "canon local `tiddlers_*.jsonl` es fuente de verdad",
            "derivados no sustituyen canon",
            "cerrar con contrato, sesion, hipotesis y procedencia",
            "si cambia canon, correr strict, reverse-preflight y reverse real",
        ],
        "artifacts": ["canon:session_s61", "canon:hypothesis_s61", "canon:provenance_s61", "canon:contract_s61"],
        "impact": "Obliga a que la materializacion Copilot no sea el unico cierre de S61.",
        "projection_impact": ["autoridad", "procedencia", "regeneracion"],
    },
    {
        "slug": "tiddlers-sesiones",
        "title": "tiddlers_sesiones.instructions.md",
        "source_files": [".github/instructions/tiddlers_sesiones.instructions.md"],
        "summary": "Detalle operativo de cierre directo en canon: familia minima de sesion, hipotesis, procedencia y nodo de contrato, todos reverse-ready.",
        "rules": [
            "crear nodo de sesion",
            "crear nodo de hipotesis",
            "crear nodo de procedencia",
            "crear nodo path-like del contrato",
            "validar canon y reverse",
        ],
        "artifacts": ["data/out/local/tiddlers_7.jsonl", "contrato S61"],
        "impact": "S61 agrega las cuatro lineas canonicas reversibles y actualiza derivados desde ese canon.",
        "projection_impact": ["procedencia", "regeneracion", "autoridad"],
    },
    {
        "slug": "contratos-s58-s59-s60",
        "title": "Contratos S58-S60",
        "source_files": [
            "contratos/m03-s58-route-fix-readme-structural-cleanup.md.json",
            "contratos/m03-s59-microsoft-copilot-projection-governance-v0.md.json",
            "contratos/m03-s60-microsoft-copilot-derived-projection-mvp-v0.md.json",
        ],
        "summary": "S58 estabiliza rutas y README, S59 registra la capa como derivada gobernada, S60 la materializa como MVP JSONL que S61 debe sustituir por JSON/CSV/TXT.",
        "rules": [
            "mantener rutas reales `python_scripts/` y `shell_scripts/`",
            "microsoft_copilot no es canon",
            "registrar linaje multifuente",
            "reemplazar el MVP JSONL de S60 sin borrar su memoria historica",
        ],
        "artifacts": ["bundles/recent_sessions.txt", "spec/memoria_decisiones_s61.md"],
        "impact": "Aporta la base historica que explica por que S61 conserva la capa pero cambia el formato final.",
        "projection_impact": ["bundles TXT", "procedencia", "regeneracion"],
    },
    {
        "slug": "repo-y-derivados-actuales",
        "title": "Estructura vigente y derivados actuales",
        "source_files": [
            "README.md",
            "data/README.md",
            "data/out/local/enriched/manifest.json",
            "data/out/local/ai/manifest.json",
            "data/out/local/audit/manifest.json",
            "contratos/projections/derived_layers_registry.json",
        ],
        "summary": "El repo ya tiene canon shardeado, derivados enriched/ai/audit/export/reverse y registry machine-readable; `microsoft_copilot` debe quedar integrada al mismo sistema.",
        "rules": [
            "usar `derive_layers.py` como flujo real de generacion",
            "mantener registry alineado con outputs existentes",
            "no dejar carpeta huerfana",
            "validar presencia y autoridad de la capa",
        ],
        "artifacts": ["manifest.json", "coverage.csv", "artifacts.csv"],
        "impact": "S61 queda como salida regenerable del pipeline, no como salida manual.",
        "projection_impact": ["regeneracion", "tablas CSV", "estructura JSON"],
    },
    {
        "slug": "microsoft-support-formats",
        "title": "Microsoft Support file formats",
        "source_files": [MICROSOFT_COPILOT_MICROSOFT_SUPPORT_REF["url"]],
        "summary": "La documentacion oficial de Microsoft 365 Copilot lista `.json`, `.txt` y `.csv` como formatos soportados en categorias de markup/configuracion, documentos y analisis de datos.",
        "rules": [
            "usar JSON para estructura y metadatos",
            "usar CSV para datos tabulares y relaciones",
            "usar TXT para lectura narrativa",
            "recordar que rutas locales requieren carga o ubicacion cloud para Copilot",
        ],
        "artifacts": ["source_arbitration_report.json", "spec/summaries/microsoft-support-formats.md"],
        "impact": "Confirma que el enfoque JSON/CSV/TXT es coherente con superficie soportada, sin crear dependencia cloud.",
        "projection_impact": ["estructura JSON", "tablas CSV", "bundles TXT", "seleccion de fuentes"],
    },
]


def json_cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return safe_str(value)


def write_csv_file(path: Path, fieldnames: list[str], rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: json_cell(row.get(field)) for field in fieldnames})
    return path


def write_text_file(path: Path, lines: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines).rstrip() + "\n")
    return path


def text_artifact_lines(title: str, purpose: str, source: str,
                        tags: list[str], content_lines: list[str],
                        updated_at: str) -> list[str]:
    return [
        f"TITLE: {title}",
        f"PURPOSE: {purpose}",
        "AUTHORITY: derived_non_authoritative_agent_projection",
        f"SOURCE: {source}",
        f"UPDATED_AT: {updated_at}",
        f"TAGS: {', '.join(tags)}",
        "",
        "CONTENT:",
        *content_lines,
    ]


def parse_embedded_json_payload(rec: dict) -> dict | None:
    text = safe_str(rec.get("text")).strip()
    if not text.startswith("{"):
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def embedded_json_primary_text(payload: dict) -> str:
    content = payload.get("content") or {}
    if isinstance(content, dict):
        markdown = safe_str(content.get("markdown")).strip()
        plain = safe_str(content.get("plain")).strip()
        if markdown:
            return markdown
        if plain:
            return plain
    for key in (
        "descripcion",
        "descripcion_breve",
        "hallazgo_clave",
        "hipotesis",
        "origen",
        "objetivo",
        "purpose",
        "summary",
        "resultado_esperado",
    ):
        value = safe_str(payload.get(key)).strip()
        if value:
            return value
    return ""


def canonical_reading_text(rec: dict) -> str:
    payload = parse_embedded_json_payload(rec)
    if payload:
        primary_text = embedded_json_primary_text(payload)
        if primary_text:
            return primary_text
    content = rec.get("content") or {}
    return safe_str(content.get("plain") or rec.get("text")).strip()


def truncate_declared(text: str, max_chars: int, source_label: str) -> str:
    text = safe_str(text).strip()
    if len(text) <= max_chars:
        return text
    return (
        text[:max_chars].rstrip()
        + f"\n\n[TRUNCATED_DECLARED: {source_label} excede {max_chars} caracteres; "
        + "consultar la fuente canonica o archivo fuente indicado para texto completo.]"
    )


def source_ref_for_record(canon_rec: dict, shard_file: str, line_num: int,
                          record_index: int, enriched_dir: Path, ai_dir: Path,
                          tiddler_shard_size: int) -> dict:
    return {
        "canon": {
            "path": as_display_path(DEFAULT_CANON_DIR / shard_file),
            "line": line_num,
            "id": canon_rec.get("id"),
            "source_position": canon_rec.get("source_position"),
            "content_hash": canon_rec.get("version_id"),
        },
        "enriched": {
            "path": shard_path_for_record(enriched_dir, "tiddlers_enriched", record_index, tiddler_shard_size),
            "id": canon_rec.get("id"),
        },
        "ai": {
            "path": shard_path_for_record(ai_dir, "tiddlers_ai", record_index, tiddler_shard_size),
            "id": canon_rec.get("id"),
        },
    }


def build_s61_projection_items(
    classified: list,
    enriched_records: list,
    ai_records: list,
    enriched_dir: Path,
    ai_dir: Path,
    tiddler_shard_size: int,
) -> list[dict]:
    copilot_layer = get_layer_registry_entry("microsoft_copilot")
    items = []
    for record_index, ((canon_rec, shard_file, line_num, _, _, _), enriched_rec, ai_rec) in enumerate(
        zip(classified, enriched_records, ai_records),
        start=1,
    ):
        role = enriched_rec.get("role_primary") or ai_rec.get("role_primary") or canon_rec.get("role_primary")
        source_refs = source_ref_for_record(
            canon_rec,
            shard_file,
            line_num,
            record_index,
            enriched_dir,
            ai_dir,
            tiddler_shard_size,
        )
        relation_targets = []
        for rel in canon_rec.get("relations") or []:
            target = rel.get("target_id") or rel.get("target")
            if target:
                relation_targets.append(target)
        for rel in ai_rec.get("relation_targets") or []:
            target = rel.get("target_id") if isinstance(rel, dict) else safe_str(rel)
            if target and target not in relation_targets:
                relation_targets.append(target)
        tags = canon_rec.get("normalized_tags") or canon_rec.get("tags") or []
        items.append(
            {
                "id": canon_rec.get("id"),
                "title": canon_rec.get("title"),
                "type": role,
                "summary": derive_microsoft_copilot_summary(canon_rec, ai_rec, role),
                "tags": tags,
                "source_refs": source_refs,
                "authority_level": copilot_layer.get("authority"),
                "derived_from": ["canon", "enriched", "ai"],
                "lineage_parents": copilot_layer.get("lineage_parents"),
                "related_ids": relation_targets[:50],
                "bundle_path": None,
                "updated_at": None,
                "content_hash": canon_rec.get("version_id"),
                "content_type": canon_rec.get("content_type"),
                "is_binary": bool(canon_rec.get("is_binary")),
                "corpus_state": ai_rec.get("corpus_state") or enriched_rec.get("corpus_state"),
                "retrieval_terms": ai_rec.get("retrieval_terms") or [],
                "retrieval_aliases": ai_rec.get("retrieval_aliases") or [],
                "confidence": ai_rec.get("confidence"),
                "taxonomy_path": enriched_rec.get("taxonomy_path") or ai_rec.get("taxonomy_path") or [],
                "section_path": enriched_rec.get("section_path") or ai_rec.get("section_path") or [],
                "canon_ref": source_refs["canon"],
                "source_primary": source_refs["canon"]["path"],
                "_canon_rec": canon_rec,
                "_ai_rec": ai_rec,
            }
        )
    return items


def select_bundle_members(items: list[dict]) -> dict[str, list[dict]]:
    recent_session_re = re.compile(r"(sesión|sesion)\s+(5[8-9]|6[0-1])|m03-s(58|59|60|61)", re.IGNORECASE)
    bundles = {
        "bundles/recent_sessions.txt": [],
        "bundles/governance_core.txt": [],
        "bundles/pipeline_and_layers.txt": [],
    }
    governance_titles = {
        "_🧱README.md",
        "README.md",
        "data/README.md",
        "docs/Informe_Tecnico_de_Tiddler (Esp).md",
        "contratos/projections/derived_layers_registry.json",
        "contratos/policy/canon_policy_bundle.json",
    }
    pipeline_titles = {
        "python_scripts/derive_layers.py",
        "python_scripts/corpus_governance.py",
        "python_scripts/path_governance.py",
        "python_scripts/validate_corpus_governance.py",
        "data/out/local/enriched/manifest.json",
        "data/out/local/ai/manifest.json",
        "data/out/local/audit/manifest.json",
    }
    for item in items:
        title = safe_str(item.get("title"))
        role = safe_str(item.get("type"))
        if recent_session_re.search(title):
            bundles["bundles/recent_sessions.txt"].append(item)
        if title in governance_titles or role in {"protocol", "policy", "readme", "glossary", "schema"}:
            if len(bundles["bundles/governance_core.txt"]) < 24:
                bundles["bundles/governance_core.txt"].append(item)
        if title in pipeline_titles:
            bundles["bundles/pipeline_and_layers.txt"].append(item)
    for bundle_path, members in bundles.items():
        for item in members:
            item["bundle_path"] = bundle_path
    return bundles


def build_topics_payload(items: list[dict], updated_at: str) -> dict:
    role_counts = Counter(safe_str(item.get("type") or "unknown") for item in items)
    tag_counts = Counter()
    for item in items:
        for tag in item.get("tags") or []:
            tag_counts[safe_str(tag)] += 1
    role_topics = [
        {
            "id": f"role:{role}",
            "title": role,
            "type": "role_topic",
            "summary": f"{count} nodos clasificados como {role}",
            "source_refs": ["data/out/local/enriched/manifest.json", "data/out/local/ai/manifest.json"],
            "authority_level": "derived_non_authoritative_agent_projection",
            "derived_from": ["enriched", "ai"],
            "related_ids": [item["id"] for item in items if item.get("type") == role][:50],
            "bundle_path": None,
            "updated_at": updated_at,
        }
        for role, count in role_counts.most_common()
    ]
    tag_topics = [
        {
            "id": f"tag:{normalize_for_dedup(tag).replace(' ', '-')[:80]}",
            "title": tag,
            "type": "tag_topic",
            "summary": f"{count} nodos con tag normalizado {tag}",
            "source_refs": ["data/out/local/tiddlers_*.jsonl", "data/out/local/enriched/"],
            "authority_level": "derived_non_authoritative_agent_projection",
            "derived_from": ["canon", "enriched"],
            "related_ids": [item["id"] for item in items if tag in (item.get("tags") or [])][:50],
            "bundle_path": None,
            "updated_at": updated_at,
        }
        for tag, count in tag_counts.most_common(40)
    ]
    return {
        "layer_id": "microsoft_copilot",
        "source_of_truth": "data/out/local/tiddlers_*.jsonl",
        "authority_class": "derived_non_authoritative_agent_projection",
        "projection_purpose": "topic and role map for agent navigation in JSON",
        "generated_from_session": MICROSOFT_COPILOT_GENERATED_FROM_SESSION,
        "updated_at": updated_at,
        "topics": role_topics + tag_topics,
    }


def build_navigation_index_s61(items: list[dict], source_inventory: dict,
                               bundles: dict[str, list[dict]], updated_at: str) -> dict:
    copilot_layer = get_layer_registry_entry("microsoft_copilot")
    role_dist = Counter(item.get("type", "unknown") for item in items)
    by_title = {safe_str(item.get("title")): item for item in items}
    foundational_titles = [
        "README.md",
        "data/README.md",
        "_🧱README.md",
        "contratos/policy/canon_policy_bundle.json",
        "contratos/projections/derived_layers_registry.json",
    ]
    foundational_nodes = [
        {
            "id": by_title[title].get("id"),
            "title": by_title[title].get("title"),
            "type": by_title[title].get("type"),
            "summary": by_title[title].get("summary"),
            "source_refs": by_title[title].get("source_refs"),
            "bundle_path": by_title[title].get("bundle_path"),
        }
        for title in foundational_titles
        if title in by_title
    ]
    recent_sessions = [
        {
            "id": item.get("id"),
            "title": item.get("title"),
            "type": item.get("type"),
            "summary": item.get("summary"),
            "source_refs": item.get("source_refs"),
            "bundle_path": item.get("bundle_path"),
        }
        for item in sorted(
            [item for item in items if safe_str(item.get("title")).lower().find("sesión") >= 0 or safe_str(item.get("title")).lower().find("sesion") >= 0],
            key=lambda entry: (entry.get("canon_ref") or {}).get("line") or 0,
            reverse=True,
        )[:MICROSOFT_COPILOT_OVERVIEW_MAX_ITEMS]
    ]
    return {
        "layer_id": "microsoft_copilot",
        "format_version": MICROSOFT_COPILOT_FORMAT_VERSION,
        "source_of_truth": "data/out/local/tiddlers_*.jsonl",
        "source_inputs": source_inventory,
        "authority_class": copilot_layer.get("authority"),
        "lineage_parents": copilot_layer.get("lineage_parents"),
        "projection_purpose": "start-here navigation map for JSON/CSV/TXT Microsoft Copilot projection",
        "generated_from_session": MICROSOFT_COPILOT_GENERATED_FROM_SESSION,
        "updated_at": updated_at,
        "multisource_arbitration": True,
        "corpus_snapshot": {
            "total_records": len(items),
            "role_distribution": dict(role_dist.most_common()),
            "json_final": ["manifest.json", "navigation_index.json", "entities.json", "topics.json", "source_arbitration_report.json"],
            "csv_final": ["nodes.csv", "edges.csv", "artifacts.csv", "coverage.csv"],
            "txt_final": ["overview.txt", "reading_guide.txt", "bundles/*.txt"],
            "jsonl_final_primary": False,
        },
        "navigation": {
            "start_here": [
                {"path": "data/out/local/microsoft_copilot/overview.txt", "purpose": "plain-text orientation for agents"},
                {"path": "data/out/local/microsoft_copilot/manifest.json", "purpose": "layer identity, authority and artifact inventory"},
                {"path": "data/out/local/microsoft_copilot/navigation_index.json", "purpose": "navigation map"},
                {"path": "data/out/local/microsoft_copilot/entities.json", "purpose": "structured entity index"},
                {"path": "data/out/local/microsoft_copilot/nodes.csv", "purpose": "tabular node list"},
                {"path": "data/out/local/microsoft_copilot/edges.csv", "purpose": "tabular relation list"},
                {"path": "data/out/local/microsoft_copilot/reading_guide.txt", "purpose": "plain-text reading flow"},
            ],
            "foundational_nodes": foundational_nodes,
            "recent_sessions": recent_sessions,
            "bundles": [
                {
                    "path": f"data/out/local/microsoft_copilot/{bundle_path}",
                    "member_count": len(members),
                    "purpose": "preserve substantive text for agent reading",
                }
                for bundle_path, members in bundles.items()
            ],
        },
        "layer_status": {
            "audit_manifest": (source_inventory.get("audit") or {}).get("manifest_path"),
            "export_present": (source_inventory.get("export") or {}).get("present"),
            "external_format_reference": MICROSOFT_COPILOT_MICROSOFT_SUPPORT_REF,
        },
    }


def build_edges_rows(items: list[dict]) -> list[dict]:
    rows = []
    seen = set()
    for item in items:
        source_id = item.get("id")
        canon_rec = item.get("_canon_rec") or {}
        ai_rec = item.get("_ai_rec") or {}
        source_file = ((item.get("source_refs") or {}).get("canon") or {}).get("path")
        for rel in canon_rec.get("relations") or []:
            target = rel.get("target_id") or rel.get("target")
            relation_type = rel.get("type") or "canonical_relation"
            key = (source_id, target, relation_type, "canon")
            if target and key not in seen:
                seen.add(key)
                rows.append(
                    {
                        "source_id": source_id,
                        "target_id": target,
                        "relation_type": relation_type,
                        "provenance": "canon.relations",
                        "confidence": "1.0",
                        "source_file": source_file,
                    }
                )
        for rel in ai_rec.get("relation_targets") or []:
            if not isinstance(rel, dict):
                continue
            target = rel.get("target_id")
            relation_type = rel.get("type") or "ai_relation_target"
            key = (source_id, target, relation_type, "ai")
            if target and key not in seen:
                seen.add(key)
                rows.append(
                    {
                        "source_id": source_id,
                        "target_id": target,
                        "relation_type": relation_type,
                        "provenance": f"ai.relation_targets:{rel.get('evidence') or 'derived'}",
                        "confidence": safe_str(item.get("confidence") or ""),
                        "source_file": source_file,
                    }
                )
        # S84: add capa-2 embedded relations to edges
        for rel in ai_rec.get("embedded_relations") or []:
            if not isinstance(rel, dict):
                continue
            target = rel.get("target_id")
            relation_type = rel.get("type") or "embedded"
            key = (source_id, target, relation_type, "embedded")
            if target and key not in seen:
                seen.add(key)
                rows.append(
                    {
                        "source_id": source_id,
                        "target_id": target,
                        "relation_type": relation_type,
                        "provenance": "content_embedded",
                        "confidence": "0.9",
                        "source_file": source_file,
                    }
                )
    return rows


def build_coverage_rows(source_inventory: dict) -> list[dict]:
    return [
        {"source_layer": "canon", "artifact_target": "entities.json,nodes.csv,edges.csv,bundles/*.txt", "coverage_status": "used", "notes": "source of truth for IDs, titles, text, relations, hashes and line refs"},
        {"source_layer": "enriched", "artifact_target": "entities.json,topics.json,nodes.csv", "coverage_status": "used", "notes": "roles, taxonomy, section paths, quality flags"},
        {"source_layer": "ai", "artifact_target": "entities.json,topics.json,edges.csv,navigation_index.json", "coverage_status": "used", "notes": "summaries, retrieval terms, relation targets and confidence"},
        {"source_layer": "audit", "artifact_target": "manifest.json,coverage.csv,navigation_index.json", "coverage_status": "used_if_present", "notes": "latest validation context from audit manifest/summary"},
        {"source_layer": "export", "artifact_target": "manifest.json,coverage.csv", "coverage_status": "optional_present" if (source_inventory.get("export") or {}).get("present") else "optional_absent", "notes": "export artifacts are not required for S61 MVP"},
        {"source_layer": "manifests", "artifact_target": "manifest.json,source_arbitration_report.json", "coverage_status": "used", "notes": "layer counts, authority, lineage and last derived status"},
        {"source_layer": "contratos_recientes", "artifact_target": "bundles/recent_sessions.txt,spec/*.md", "coverage_status": "used", "notes": "S58-S60 historical decisions and S61 closure"},
        {"source_layer": "microsoft_support", "artifact_target": "source_arbitration_report.json,spec/summaries/microsoft-support-formats.*", "coverage_status": "used_as_external_reference", "notes": "format coherence only; no authority over canon"},
    ]


def write_bundle_files(copilot_dir: Path, bundles: dict[str, list[dict]], updated_at: str) -> list[Path]:
    written = []
    purposes = {
        "bundles/recent_sessions.txt": "Preservar memoria reciente S58-S61 y la transicion S60 JSONL -> S61 JSON/CSV/TXT.",
        "bundles/governance_core.txt": "Exponer reglas y documentos fundacionales necesarios para leer la proyeccion.",
        "bundles/pipeline_and_layers.txt": "Explicar el flujo de derivacion y estado de capas sin convertirlo en canon.",
    }
    for bundle_path, members in bundles.items():
        content = [
            "Este bundle es texto plano derivado y no autoritativo.",
            "No reemplaza `data/out/local/tiddlers_*.jsonl` ni los archivos fuente.",
            "",
        ]
        for item in members:
            canon_rec = item.get("_canon_rec") or {}
            source = ((item.get("source_refs") or {}).get("canon") or {})
            content.extend(
                [
                    f"--- SOURCE_TITLE: {item.get('title')}",
                    f"SOURCE_ID: {item.get('id')}",
                    f"SOURCE_REF: {source.get('path')}:{source.get('line')}",
                    f"CONTENT_HASH: {item.get('content_hash')}",
                    "",
                    truncate_declared(canonical_reading_text(canon_rec), 14000, safe_str(item.get("title"))),
                    "",
                ]
            )
        path = copilot_dir / bundle_path
        lines = text_artifact_lines(
            title=bundle_path.rsplit("/", 1)[-1],
            purpose=purposes[bundle_path],
            source="canon + enriched + ai + recent contracts, selected by S61 relevance",
            tags=["microsoft_copilot", "bundle", "txt", "derived"],
            content_lines=content,
            updated_at=updated_at,
        )
        written.append(write_text_file(path, lines))
    return written


def write_overview_and_reading_guide(copilot_dir: Path, navigation_index: dict,
                                     source_inventory: dict, updated_at: str) -> list[Path]:
    snapshot = navigation_index.get("corpus_snapshot") or {}
    overview_lines = text_artifact_lines(
        title="microsoft_copilot JSON/CSV/TXT projection",
        purpose="Superficie de lectura derivada para Microsoft Copilot y agentes remotos.",
        source="canon local + enriched + ai + audit/export manifests + contratos recientes",
        tags=["microsoft_copilot", "overview", "txt", "derived"],
        updated_at=updated_at,
        content_lines=[
            "`microsoft_copilot/` es derivada y no autoritativa.",
            "El canon local sigue siendo `data/out/local/tiddlers_*.jsonl`.",
            "S61 elimina `.jsonl` como salida final primaria de esta capa.",
            "",
            "FORMAT FAMILIES:",
            "- JSON: manifest, navigation, entities, topics, source arbitration.",
            "- CSV: nodes, edges, artifacts, coverage.",
            "- TXT: overview, reading guide and curated bundles.",
            "",
            f"TOTAL_RECORDS: {snapshot.get('total_records')}",
            f"JSONL_FINAL_PRIMARY: {snapshot.get('jsonl_final_primary')}",
            "",
            "START:",
            "- Leer `reading_guide.txt` para flujo narrativo.",
            "- Usar `navigation_index.json` para explorar sesiones, documentos fundacionales y bundles.",
            "- Usar `entities.json` y `nodes.csv` para buscar nodos.",
            "- Usar `edges.csv` para relaciones.",
            "- Usar `source_arbitration_report.json` para verificar fuentes reales por artefacto.",
        ],
    )
    guide_lines = text_artifact_lines(
        title="reading guide",
        purpose="Ruta de lectura para agentes remotos que no conocen la jerarquia del repo.",
        source="manifest + navigation_index + source_arbitration_report",
        tags=["microsoft_copilot", "reading-guide", "txt", "derived"],
        updated_at=updated_at,
        content_lines=[
            "1. Confirmar autoridad: esta capa no es canon.",
            "2. Leer `overview.txt` para alcance y familias de formato.",
            "3. Abrir `manifest.json` para linaje, conteos y artefactos.",
            "4. Abrir `navigation_index.json` para nodos fundacionales y sesiones recientes.",
            "5. Consultar `bundles/recent_sessions.txt` para S58-S61.",
            "6. Consultar `bundles/governance_core.txt` para reglas y documentos base.",
            "7. Usar `entities.json` para estructura semantica y `nodes.csv` para tabla plana.",
            "8. Usar `edges.csv` para relaciones y `coverage.csv` para saber que capas alimentaron cada salida.",
            "",
            "Si una respuesta exige texto exacto o codigo completo, volver al canon o a la fuente indicada por `source_refs`.",
        ],
    )
    return [
        write_text_file(copilot_dir / "overview.txt", overview_lines),
        write_text_file(copilot_dir / "reading_guide.txt", guide_lines),
    ]


def write_s61_spec_artifacts(copilot_dir: Path, updated_at: str) -> list[Path]:
    written = []
    summaries_dir = copilot_dir / "spec" / "summaries"
    for summary in S61_SPEC_SUMMARIES:
        payload = {
            "id": summary["slug"],
            "title": summary["title"],
            "summary": summary["summary"],
            "source_files": summary["source_files"],
            "rules": summary["rules"],
            "required_artifacts": summary["artifacts"],
            "impact": summary["impact"],
            "reference": summary["source_files"],
            "projection_impact": summary["projection_impact"],
            "authority": "derived_non_authoritative",
            "updated_at": updated_at,
        }
        written.append(write_json_file(summaries_dir / f"{summary['slug']}.json", payload))
        md_lines = [
            f"# {summary['title']}",
            "",
            "## Resumen",
            summary["summary"],
            "",
            "## Reglas",
            *[f"- {rule}" for rule in summary["rules"]],
            "",
            "## Artefactos",
            *[f"- {artifact}" for artifact in summary["artifacts"]],
            "",
            "## Impacto",
            summary["impact"],
            "",
            "## Referencia",
            *[f"- `{ref}`" for ref in summary["source_files"]],
            "",
            "## Impacto en proyeccion Copilot",
            *[f"- {impact}" for impact in summary["projection_impact"]],
            "",
            f"UPDATED_AT: {updated_at}",
        ]
        written.append(write_text_file(summaries_dir / f"{summary['slug']}.md", md_lines))

    mapping = [
        {
            "id": "s61-json-structure",
            "title": "JSON estructural",
            "summary": "Manifest, navegacion, entidades, topicos y arbitraje.",
            "source_files": ["canon", "enriched", "ai", "manifests", "contratos recientes"],
            "required_artifacts": ["manifest.json", "navigation_index.json", "entities.json", "topics.json", "source_arbitration_report.json"],
            "actions": ["generar objetos compactos", "mantener source_refs", "declarar autoridad"],
            "priority": "P0",
            "projection_role": "estructura y navegacion",
        },
        {
            "id": "s61-csv-tables",
            "title": "CSV relacional y tabular",
            "summary": "Nodos, edges, artefactos y cobertura.",
            "source_files": ["canon", "ai", "registry", "manifest outputs"],
            "required_artifacts": ["nodes.csv", "edges.csv", "artifacts.csv", "coverage.csv"],
            "actions": ["materializar tablas simples", "serializar listas como JSON en celdas", "mantener rutas fuente"],
            "priority": "P0",
            "projection_role": "relaciones y cobertura",
        },
        {
            "id": "s61-txt-reading",
            "title": "TXT contextual",
            "summary": "Overview, guia y bundles narrativos seleccionados.",
            "source_files": ["canon", "contratos recientes", "README", "registry"],
            "required_artifacts": ["overview.txt", "reading_guide.txt", "bundles/*.txt"],
            "actions": ["preservar texto sustantivo", "declarar truncados", "no copiar todo indiscriminadamente"],
            "priority": "P0",
            "projection_role": "lectura contextual",
        },
        {
            "id": "s61-registry-docs",
            "title": "Registro y documentacion",
            "summary": "Actualizar registry, README y data/README para reflejar JSON/CSV/TXT.",
            "source_files": ["contratos/projections/derived_layers_registry.json", "README.md", "data/README.md"],
            "required_artifacts": ["registry actualizado", "docs actualizadas"],
            "actions": ["retirar path patterns JSONL", "declarar no autoridad", "mantener flujo derive_layers.py"],
            "priority": "P1",
            "projection_role": "gobernanza minima",
        },
    ]
    plan_lines = [
        "# Plan de implementacion S61",
        "",
        "## Mapeo",
        "```json",
        json.dumps(mapping, indent=2, ensure_ascii=False),
        "```",
        "",
        "## Conflictos y resoluciones",
        "- Conflicto: S60 emitia `tiddlers_microsoft_copilot_*.jsonl` como lectura final; S61 fija JSON/CSV/TXT. Opcion A: conservar JSONL como legacy oculto, pro: compatibilidad, contra: ambiguedad. Opcion B: eliminar JSONL final y registrar reemplazo, pro: cumple S61, contra: requiere regeneracion. Resolucion aplicada: opcion B.",
        "- Conflicto: preservar texto vs evitar duplicacion. Opcion A: copiar todo el canon a TXT, pro: maxima disponibilidad, contra: costo y ruido. Opcion B: bundles seleccionados con source_refs, pro: util y mantenible, contra: exige volver al canon para texto completo. Resolucion aplicada: opcion B con truncado declarado.",
        "- Conflicto: instruccion propia de Copilot vs derivado normal. Opcion A: recrear instruccion, pro: visibilidad local, contra: complejidad normativa. Opcion B: registry/manifests/spec, pro: menor complejidad. Resolucion aplicada: opcion B.",
        "",
        "## Backlog priorizado",
        "- P0: Generar JSON/CSV/TXT desde `derive_layers.py`; depende de canon/enriched/ai.",
        "- P0: Retirar JSONL como salida final primaria; depende de limpieza de outputs obsoletos.",
        "- P1: Actualizar registry y docs; depende de modelo de artefactos cerrado.",
        "- P1: Crear contrato y familia canonica S61; depende de implementacion validable.",
        "- P1: Validar strict, reverse-preflight, reverse real, derivacion y tests focalizados.",
        "",
        "## Arbitraje de fuentes",
        "- Canon: IDs, texto, relaciones, hashes y reversibilidad.",
        "- Enriched: roles, taxonomia, contexto estructural y calidad.",
        "- AI: resumen, retrieval terms, relation_targets y confianza.",
        "- Audit/export/manifests: estado, cobertura y validacion.",
        "- Contratos recientes/docs: decisiones activas y continuidad S58-S61.",
    ]
    written.append(write_text_file(copilot_dir / "spec" / "plan_de_implementacion_s61.md", plan_lines))

    checklist_lines = [
        "# Checklist global S61",
        "",
        "- [x] Leer gobernanza interna obligatoria.",
        "- [x] Revisar S58, S59 y S60.",
        "- [x] Revisar estructura `data/out/local/` y `microsoft_copilot/` actual.",
        "- [x] Confirmar referencia oficial Microsoft para JSON/CSV/TXT.",
        "- [x] Reemplazar salida final JSONL por JSON/CSV/TXT.",
        "- [x] Mantener autoridad del canon intacta.",
        "- [x] Declarar fuentes y arbitraje por artefacto.",
        "- [x] Cerrar contrato S61 y familia canonica.",
        "- [x] Ejecutar validaciones finales tras cierre canonico.",
    ]
    written.append(write_text_file(copilot_dir / "spec" / "checklist_global_s61.md", checklist_lines))

    memory_lines = [
        "# Memoria de decisiones S61",
        "",
        "## Hipotesis inicial",
        "Si `microsoft_copilot/` usa JSON para estructura, CSV para relaciones/tablas y TXT para lectura contextual, entonces mejora su legibilidad por agentes externos sin invertir la autoridad del canon.",
        "",
        "## Decisiones",
        "- `microsoft_copilot/` sigue siendo derivada y no autoritativa.",
        "- `.jsonl` queda excluido como salida final primaria de S61.",
        "- JSON se usa para navegacion, entidades, topicos, manifest y arbitraje.",
        "- CSV se usa para nodos, relaciones, artefactos y cobertura.",
        "- TXT se usa para overview, guia y bundles narrativos seleccionados.",
        "- No se recrea una instruccion especifica de Copilot; se usa registry, manifest y spec.",
        "",
        "## Procedencia",
        "- Fuentes internas: instrucciones, contratos S58-S60, README, data/README, registry, manifests y canon.",
        f"- Fuente externa oficial: {MICROSOFT_COPILOT_MICROSOFT_SUPPORT_REF['url']}",
        "",
        "## Reversibilidad",
        "Los cambios al canon se cierran con familia S61 y validaciones strict, reverse-preflight y reverse real. Los outputs de `microsoft_copilot/` son regenerables por `python_scripts/derive_layers.py`.",
    ]
    written.append(write_text_file(copilot_dir / "spec" / "memoria_decisiones_s61.md", memory_lines))
    return written


def build_source_arbitration_report_s61(copilot_dir: Path, source_inventory: dict,
                                        artifacts: list[dict], updated_at: str) -> dict:
    copilot_layer = get_layer_registry_entry("microsoft_copilot")
    return {
        "layer_id": "microsoft_copilot",
        "format_version": MICROSOFT_COPILOT_FORMAT_VERSION,
        "source_of_truth": "data/out/local/tiddlers_*.jsonl",
        "source_inputs": source_inventory,
        "authority_class": copilot_layer.get("authority"),
        "lineage_parents": copilot_layer.get("lineage_parents"),
        "projection_purpose": "artifact-level source arbitration for JSON/CSV/TXT agent projection",
        "generated_from_session": MICROSOFT_COPILOT_GENERATED_FROM_SESSION,
        "updated_at": updated_at,
        "multisource_arbitration": True,
        "format_decision": {
            "json": "structure, nodes, metadata, navigation and arbitration",
            "csv": "relations, artifact inventory and coverage tables",
            "txt": "plain contextual reading and curated substantive bundles",
            "excluded_as_final_primary": [".jsonl", ".rdf", ".owl", ".graphml"],
        },
        "external_format_reference": MICROSOFT_COPILOT_MICROSOFT_SUPPORT_REF,
        "artifacts": artifacts,
        "arbitration_by_family": [
            {
                "family": "json",
                "source_priority": ["canon", "enriched", "ai", "manifests", "audit/export"],
                "reason": "needs structure, source refs, semantic navigation and authority metadata",
                "reversible_by": "source_refs + content_hash + canon shard line",
            },
            {
                "family": "csv",
                "source_priority": ["canon", "ai", "registry", "manifest outputs"],
                "reason": "needs tabular relation and coverage extraction",
                "reversible_by": "source_id/target_id plus source_file/provenance",
            },
            {
                "family": "txt",
                "source_priority": ["canon", "contracts", "README", "registry"],
                "reason": "needs contextual reading without hiding source authority",
                "reversible_by": "SOURCE_REF and CONTENT_HASH headers per bundle section",
            },
        ],
    }


# ── Copilot Agent compressed sublayer (S64) ───────────────────────────────────

def compact_agent_text(text: str, max_chars: int) -> str:
    text = safe_str(text).replace("\r", "\n")
    if not text.strip():
        return ""

    text = re.sub(r"```.*?```", " [code omitted] ", text, flags=re.DOTALL)
    cleaned_lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("```"):
            continue
        if line.startswith(("TITLE:", "PURPOSE:", "AUTHORITY:", "SOURCE:", "UPDATED_AT:", "TAGS:")):
            continue
        line = re.sub(r"\[\[([^\]]+)\]\]", r"\1", line)
        line = re.sub(r"^[-*#>\s]+", "", line)
        line = line.replace("|", " ")
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            cleaned_lines.append(line)
        if len(cleaned_lines) >= 8:
            break

    compact = re.sub(r"\s+", " ", " ".join(cleaned_lines)).strip()
    if len(compact) <= max_chars:
        return compact
    shortened = compact[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:.")
    return f"{shortened}..."


def infer_copilot_agent_entity_type(item: dict) -> str:
    if item.get("synthetic"):
        return "layer"

    title = safe_str(item.get("title")).strip()
    role = safe_str(item.get("type")).strip() or "unclassified"

    if title.startswith("contratos/") and title.endswith(".md.json"):
        return "contract"
    if title.endswith("/manifest.json"):
        return "manifest"
    if title in {
        "contratos/policy/canon_policy_bundle.json",
        "contratos/projections/derived_layers_registry.json",
    }:
        return "structural_node"
    if role == "config" and title.startswith(("# ", "## ", "### ", "#### ")):
        return "structural_node"
    return role


def infer_copilot_agent_family(item: dict, entity_type: str) -> str:
    title = normalize_for_dedup(safe_str(item.get("title")))
    summary = normalize_for_dedup(safe_str(item.get("summary")))
    source = normalize_for_dedup(safe_str(item.get("source_primary")))
    tags = " ".join(normalize_for_dedup(safe_str(tag)) for tag in (item.get("tags") or []))
    haystack = " ".join(part for part in (title, summary, source, tags) if part)

    if item.get("synthetic"):
        return "integration_flow"
    if (
        "microsoft-copilot" in haystack
        or "microsoft_copilot" in haystack
        or "copilot-agent" in haystack
        or "copilot_agent" in haystack
        or re.search(r"m03-s(59|60|61|62|63|64)", haystack)
    ):
        return "copilot_projection"
    if (
        "reverse" in haystack
        or "authoritative-upsert" in haystack
        or "reverse-preflight" in haystack
        or "canonical_slug" in haystack
        or "version_id" in haystack
        or "normalized_tags" in haystack
        or "embedded_json" in haystack
        or "go/canon/" in haystack
        or "canon_policy" in haystack
        or "identity.go" in haystack
        or "normalizer.go" in haystack
        or "embedded_json_text.go" in haystack
    ):
        return "strict_reversibility"
    if entity_type in {"session", "hypothesis", "provenance", "contract"}:
        return "minimal_canon"
    if entity_type in {"policy", "protocol", "glossary", "schema"}:
        return "semantic_compression"
    return "integration_flow"


def copilot_agent_priority_score(item: dict, entity_type: str, family: str) -> int:
    family_weight = {
        "integration_flow": 70,
        "semantic_compression": 75,
        "copilot_projection": 90,
        "minimal_canon": 68,
        "strict_reversibility": 85,
    }
    type_weight = {
        "layer": 80,
        "policy": 50,
        "protocol": 48,
        "contract": 46,
        "session": 38,
        "hypothesis": 32,
        "provenance": 32,
        "readme": 28,
        "architecture": 28,
        "manifest": 24,
        "structural_node": 24,
        "code_source": 24,
        "glossary": 20,
        "schema": 20,
    }

    title = normalize_for_dedup(safe_str(item.get("title")))
    source = normalize_for_dedup(safe_str(item.get("source_primary")))
    marker = extract_session_marker(item)
    score = family_weight.get(family, 40) + type_weight.get(entity_type, 12)
    score += min(len(item.get("related_ids") or []), 12)
    score += min(len(item.get("tags") or []), 8)

    if item.get("synthetic"):
        return score + 1000
    if title in {
        "readme.md",
        "## 🗂🧱 principios de gestion",
        "## 🧭🧱 protocolo de sesion",
        "## 🎯🧱 detalles del tema",
        "contratos/policy/canon_policy_bundle.json",
        "contratos/projections/derived_layers_registry.json",
        "python_scripts/derive_layers.py",
    }:
        score += 35
    if marker in COPILOT_AGENT_RECENT_MARKERS or re.search(r"m03-s(59|60|61|62|63|64)", title):
        score += 55
    if marker in COPILOT_AGENT_REVERSE_MARKERS:
        score += 30
    if "microsoft-copilot" in title or "copilot-agent" in title:
        score += 35
    if source.startswith("go/canon/") or source.startswith("python_scripts/"):
        score += 18
    if entity_type == "session" and marker in COPILOT_AGENT_RECENT_MARKERS:
        score += 30
    if entity_type in {"contract", "hypothesis", "provenance"} and marker and marker not in (COPILOT_AGENT_RECENT_MARKERS | COPILOT_AGENT_REVERSE_MARKERS):
        score -= 120
    if entity_type == "session" and marker and marker not in (COPILOT_AGENT_RECENT_MARKERS | COPILOT_AGENT_REVERSE_MARKERS):
        score -= 260
    return score


def copilot_agent_selection_reason(entity_type: str, family: str) -> str:
    if entity_type == "layer":
        return "captures official layer lineage and authority boundaries."
    if family == "integration_flow":
        return "keeps the real pipeline surface legible without reopening the architecture."
    if family == "semantic_compression":
        return "preserves the rules that make the compressed pack cognitively readable."
    if family == "copilot_projection":
        return "anchors the Microsoft Copilot and copilot_agent lineage inside the real flow."
    if family == "minimal_canon":
        return "tracks the minimum session closure that must remain absorbed in canon."
    if family == "strict_reversibility":
        return "pins the deterministic inputs required for strict reverse compatibility."
    return "retained as a high-value structural anchor."


def build_copilot_agent_layer_entities() -> list[dict]:
    canon_layer = get_layer_registry_entry("canon")
    enriched_layer = get_layer_registry_entry("enriched")
    ai_layer = get_layer_registry_entry("ai")
    copilot_layer = get_layer_registry_entry("microsoft_copilot")
    return [
        {
            "id": "layer:canon",
            "title": "Layer: canon",
            "summary": "Local source of truth backed by data/out/local/tiddlers_*.jsonl and required for strict, reverse-preflight and reverse authoritativo.",
            "type": "layer",
            "authority_level": canon_layer.get("authority"),
            "source_primary": "data/out/local/tiddlers_*.jsonl",
            "tags": ["layer:canon", "authority:local-source-of-truth"],
            "related_ids": ["layer:enriched", "layer:ai", "layer:microsoft_copilot"],
            "taxonomy_path": ["layer", "canon"],
            "synthetic": True,
        },
        {
            "id": "layer:enriched",
            "title": "Layer: enriched",
            "summary": "First derived layer that adds structural enrichment, role inference, taxonomy and section context without changing canonical authority.",
            "type": "layer",
            "authority_level": enriched_layer.get("authority"),
            "source_primary": "data/out/local/enriched/manifest.json",
            "tags": ["layer:enriched", "derived:non-authoritative"],
            "related_ids": ["layer:canon", "layer:microsoft_copilot"],
            "taxonomy_path": ["layer", "enriched"],
            "synthetic": True,
        },
        {
            "id": "layer:ai",
            "title": "Layer: ai",
            "summary": "Second derived layer for summaries, retrieval hints, relation targets and chunk-ready records used by downstream agent projections.",
            "type": "layer",
            "authority_level": ai_layer.get("authority"),
            "source_primary": "data/out/local/ai/manifest.json",
            "tags": ["layer:ai", "derived:non-authoritative"],
            "related_ids": ["layer:canon", "layer:microsoft_copilot"],
            "taxonomy_path": ["layer", "ai"],
            "synthetic": True,
        },
        {
            "id": "layer:microsoft_copilot",
            "title": "Layer: microsoft_copilot",
            "summary": "Official JSON/CSV/TXT projection introduced in S61. It remains derived, traces to canon plus enriched/ai and feeds copilot_agent.",
            "type": "layer",
            "authority_level": copilot_layer.get("authority"),
            "source_primary": "data/out/local/microsoft_copilot/manifest.json",
            "tags": ["layer:microsoft_copilot", "derived:agent-projection"],
            "related_ids": ["layer:canon", "layer:enriched", "layer:ai", "layer:copilot_agent"],
            "taxonomy_path": ["layer", "microsoft_copilot"],
            "synthetic": True,
        },
        {
            "id": "layer:copilot_agent",
            "title": "Layer: copilot_agent",
            "summary": "Compressed three-file snapshot for external agents. S63 integrated it into the pipeline and S64 hardens semantic balance plus reversibility constraints.",
            "type": "layer",
            "authority_level": "derived_non_authoritative_agent_projection",
            "source_primary": "data/out/local/microsoft_copilot/copilot_agent/",
            "tags": ["layer:copilot_agent", "derived:agent-projection", "format:three-file-pack"],
            "related_ids": ["layer:microsoft_copilot", "layer:canon"],
            "taxonomy_path": ["layer", "copilot_agent"],
            "synthetic": True,
        },
    ]


def decorate_copilot_agent_item(item: dict) -> dict:
    entity_type = infer_copilot_agent_entity_type(item)
    family = infer_copilot_agent_family(item, entity_type)
    decorated = dict(item)
    decorated["entity_type"] = entity_type
    decorated["semantic_family"] = family
    decorated["related_count"] = len(item.get("related_ids") or [])
    decorated["priority_score"] = copilot_agent_priority_score(item, entity_type, family)
    decorated["selection_reason"] = copilot_agent_selection_reason(entity_type, family)
    decorated["tier"] = 1 if decorated["priority_score"] >= 120 else 2
    return decorated


def sort_copilot_agent_entities(items: list[dict]) -> list[dict]:
    family_order = {family: idx for idx, family in enumerate(COPILOT_AGENT_FAMILY_ORDER)}
    return sorted(
        items,
        key=lambda item: (
            family_order.get(item.get("semantic_family"), 99),
            -int(item.get("priority_score") or 0),
            normalize_for_dedup(safe_str(item.get("title"))),
        ),
    )


def select_copilot_agent_entities(items: list[dict]) -> list[dict]:
    synthetic_entities = [decorate_copilot_agent_item(item) for item in build_copilot_agent_layer_entities()]
    decorated_items = [decorate_copilot_agent_item(item) for item in items]

    selected = []
    seen_ids = set()
    type_counts = Counter()

    def add_candidate(candidate: dict) -> bool:
        candidate_id = safe_str(candidate.get("id"))
        if not candidate_id or candidate_id in seen_ids:
            return False
        entity_type = safe_str(candidate.get("entity_type"))
        marker = extract_session_marker(candidate)
        if entity_type == "session":
            title_norm = normalize_for_dedup(safe_str(candidate.get("title")))
            title_is_priority_session = bool(
                re.search(r"sesion\s+(50|57|59|60|61|62|63|64)\b", title_norm)
                or "microsoft-copilot" in title_norm
                or "copilot-agent" in title_norm
                or "reverse" in title_norm
                or "canon-direct-close" in title_norm
            )
            if marker not in (COPILOT_AGENT_RECENT_MARKERS | COPILOT_AGENT_REVERSE_MARKERS) and not title_is_priority_session:
                return False
        type_cap = COPILOT_AGENT_TYPE_CAPS.get(entity_type)
        if type_cap is not None and type_counts[entity_type] >= type_cap:
            return False
        selected.append(candidate)
        seen_ids.add(candidate_id)
        type_counts[entity_type] += 1
        return True

    for candidate in synthetic_entities:
        add_candidate(candidate)

    recent_session_candidates = sorted(
        [
            candidate
            for candidate in decorated_items
            if candidate.get("entity_type") == "session"
            and extract_session_marker(candidate) in (COPILOT_AGENT_RECENT_MARKERS | COPILOT_AGENT_REVERSE_MARKERS)
        ],
        key=lambda item: (-int(item.get("priority_score") or 0), normalize_for_dedup(safe_str(item.get("title")))),
    )
    for candidate in recent_session_candidates[:5]:
        if len(selected) >= COPILOT_AGENT_ENTITY_LIMIT:
            break
        add_candidate(candidate)

    strict_anchor_candidates = sort_copilot_agent_entities(
        [
            candidate
            for candidate in decorated_items
            if candidate.get("semantic_family") == "strict_reversibility"
            and safe_str(candidate.get("title")) in COPILOT_AGENT_STRICT_ANCHOR_TITLES
        ]
    )
    for candidate in strict_anchor_candidates:
        if len(selected) >= COPILOT_AGENT_ENTITY_LIMIT:
            break
        add_candidate(candidate)

    reverse_session_candidates = sort_copilot_agent_entities(
        [
            candidate
            for candidate in decorated_items
            if candidate.get("semantic_family") == "strict_reversibility"
            and candidate.get("entity_type") == "session"
            and extract_session_marker(candidate) in COPILOT_AGENT_REVERSE_MARKERS
        ]
    )
    for candidate in reverse_session_candidates:
        if len(selected) >= COPILOT_AGENT_ENTITY_LIMIT:
            break
        add_candidate(candidate)

    by_family = defaultdict(list)
    for candidate in decorated_items:
        by_family[candidate.get("semantic_family")].append(candidate)
    for family in COPILOT_AGENT_FAMILY_ORDER:
        by_family[family] = sort_copilot_agent_entities(by_family.get(family, []))

    for family in COPILOT_AGENT_FAMILY_ORDER:
        target = COPILOT_AGENT_FAMILY_TARGETS.get(family, 0)
        added = 0
        for candidate in by_family.get(family, []):
            if len(selected) >= COPILOT_AGENT_ENTITY_LIMIT:
                break
            if add_candidate(candidate):
                added += 1
            if added >= target:
                break

    for candidate in sorted(
        decorated_items,
        key=lambda item: (-int(item.get("priority_score") or 0), normalize_for_dedup(safe_str(item.get("title")))),
    ):
        if len(selected) >= COPILOT_AGENT_ENTITY_LIMIT:
            break
        add_candidate(candidate)

    return sort_copilot_agent_entities(selected[:COPILOT_AGENT_ENTITY_LIMIT])


def copilot_agent_source_ref(item: dict) -> str:
    source = safe_str(item.get("source_primary"))
    line = ((item.get("canon_ref") or {}).get("line"))
    if line:
        return f"{source}:{line}"
    return source or "derived"


def extract_copilot_agent_signals(item: dict) -> list[str]:
    payload = parse_embedded_json_payload(item.get("_canon_rec") or {})
    signals = []
    seen = set()

    def add_signal(value, max_chars: int) -> None:
        compact = compact_agent_text(value, max_chars)
        if compact and compact not in seen:
            seen.add(compact)
            signals.append(compact)

    if payload:
        add_signal(embedded_json_primary_text(payload), 160)
        for key in ("content",):
            content = payload.get(key)
            if isinstance(content, dict):
                add_signal(content.get("plain") or content.get("markdown"), 160)
        for key in ("descripcion", "descripcion_breve", "hallazgo_clave", "hipotesis", "origen", "objetivo", "purpose", "summary"):
            add_signal(payload.get(key), 160)
        for key in ("decisiones_documentadas", "decisiones", "evidencia_base", "rules", "required_artifacts"):
            values = payload.get(key)
            if isinstance(values, list):
                for value in values[:2]:
                    add_signal(value, 120)
        if len(signals) < 2:
            for key in ("fuentes_usadas", "source_files", "reference"):
                values = payload.get(key)
                if isinstance(values, list):
                    for value in values[:2]:
                        add_signal(value, 90)
                if len(signals) >= 2:
                    break

    if not signals:
        fallback_signal = safe_str(item.get("summary")).strip()
        if fallback_signal.startswith(("{", "[")):
            fallback_signal = canonical_reading_text(item.get("_canon_rec") or {})
        add_signal(fallback_signal, 160)
    return signals[:2]


def copilot_agent_display_summary(item: dict, max_chars: int) -> str:
    summary = safe_str(item.get("summary")).strip()
    if summary.startswith(("{", "[")):
        summary = canonical_reading_text(item.get("_canon_rec") or {})
    if not summary and not item.get("synthetic"):
        summary = canonical_reading_text(item.get("_canon_rec") or {})
    if not summary and item.get("synthetic"):
        summary = safe_str(item.get("summary"))
    return compact_agent_text(summary, max_chars)


def resolve_copilot_agent_target_id(target, selected_by_id: dict, selected_title_to_id: dict) -> str | None:
    target_str = safe_str(target).strip()
    if not target_str:
        return None
    if target_str in selected_by_id:
        return target_str
    return selected_title_to_id.get(normalize_for_dedup(target_str))


def extract_session_marker(item: dict) -> str:
    for tag in (item.get("tags") or []):
        tag_str = safe_str(tag).strip()
        if tag_str.startswith("session:"):
            return tag_str.removeprefix("session:")
    title = normalize_for_dedup(safe_str(item.get("title")))
    match = re.search(r"m\d\d-s\d\d", title)
    return match.group(0) if match else ""


def build_copilot_agent_relations(selected_entities: list[dict]) -> list[dict]:
    relation_rows = []
    seen = set()
    selected_by_id = {safe_str(item.get("id")): item for item in selected_entities}
    selected_title_to_id = {
        normalize_for_dedup(safe_str(item.get("title"))): safe_str(item.get("id"))
        for item in selected_entities
    }

    def add_relation(source_id: str, target_id: str, relation_type: str,
                     provenance: str, confidence: str, source_layer: str, notes: str) -> None:
        if not source_id or not target_id or source_id == target_id:
            return
        key = (source_id, target_id, relation_type)
        if key in seen:
            return
        seen.add(key)
        relation_rows.append(
            {
                "source_id": source_id,
                "target_id": target_id,
                "relation_type": relation_type,
                "provenance": provenance,
                "confidence": confidence,
                "source_layer": source_layer,
                "notes": notes,
            }
        )

    for item in selected_entities:
        if item.get("synthetic"):
            continue
        source_id = safe_str(item.get("id"))
        source_ref = copilot_agent_source_ref(item)
        for rel in (item.get("_canon_rec") or {}).get("relations") or []:
            target_id = resolve_copilot_agent_target_id(
                rel.get("target_id") or rel.get("target"),
                selected_by_id,
                selected_title_to_id,
            )
            relation_type = safe_str(rel.get("type")) or "canonical_relation"
            add_relation(source_id, target_id, relation_type, "canon.relations", "1.0", "canon", source_ref)
        for rel in (item.get("_ai_rec") or {}).get("relation_targets") or []:
            if not isinstance(rel, dict):
                continue
            target_id = resolve_copilot_agent_target_id(rel.get("target_id"), selected_by_id, selected_title_to_id)
            relation_type = safe_str(rel.get("type")) or "ai_relation_target"
            add_relation(
                source_id,
                target_id,
                relation_type,
                f"ai.relation_targets:{rel.get('evidence') or 'derived'}",
                safe_str(item.get("confidence") or ""),
                "ai",
                source_ref,
            )

    synthetic_layer_edges = [
        ("layer:enriched", "layer:canon", "layer_derives_from"),
        ("layer:ai", "layer:canon", "layer_derives_from"),
        ("layer:microsoft_copilot", "layer:canon", "layer_derives_from"),
        ("layer:microsoft_copilot", "layer:enriched", "layer_uses_as_source"),
        ("layer:microsoft_copilot", "layer:ai", "layer_uses_as_source"),
        ("layer:copilot_agent", "layer:microsoft_copilot", "layer_derives_from"),
        ("layer:copilot_agent", "layer:canon", "canon_is_source_of"),
    ]
    for source_id, target_id, relation_type in synthetic_layer_edges:
        add_relation(
            source_id,
            target_id,
            relation_type,
            "copilot_agent.layer_model",
            "1.0",
            "copilot_agent",
            "layer lineage synthesized for graph reconstruction",
        )

    session_groups = defaultdict(list)
    for item in selected_entities:
        marker = extract_session_marker(item)
        if marker:
            session_groups[marker].append(item)

    layer_by_session = {
        "m03-s59": ("layer:microsoft_copilot", "session_governs_layer"),
        "m03-s60": ("layer:microsoft_copilot", "session_generates_layer"),
        "m03-s61": ("layer:microsoft_copilot", "session_generates_layer"),
        "m03-s62": ("layer:copilot_agent", "session_defines_pack"),
        "m03-s63": ("layer:copilot_agent", "session_integrates_layer"),
        "m03-s64": ("layer:copilot_agent", "session_hardens_layer"),
        "m03-s50": ("layer:canon", "session_repairs_reversibility"),
        "m03-s57": ("layer:canon", "session_governs_layer"),
    }

    for marker, members in session_groups.items():
        sessions = [item for item in members if item.get("entity_type") == "session"]
        hypotheses = [item for item in members if item.get("entity_type") == "hypothesis"]
        provenances = [item for item in members if item.get("entity_type") == "provenance"]
        contracts = [item for item in members if item.get("entity_type") == "contract"]

        for session in sessions:
            session_id = safe_str(session.get("id"))
            for hypothesis in hypotheses:
                add_relation(
                    session_id,
                    safe_str(hypothesis.get("id")),
                    "defines",
                    "copilot_agent.session_family",
                    "1.0",
                    "copilot_agent",
                    marker,
                )
            for provenance in provenances:
                add_relation(
                    session_id,
                    safe_str(provenance.get("id")),
                    "defines",
                    "copilot_agent.session_family",
                    "1.0",
                    "copilot_agent",
                    marker,
                )
            for contract in contracts:
                add_relation(
                    session_id,
                    safe_str(contract.get("id")),
                    "session_closes_contract",
                    "copilot_agent.session_family",
                    "1.0",
                    "copilot_agent",
                    marker,
                )

            layer_target = layer_by_session.get(marker)
            if layer_target:
                target_id, relation_type = layer_target
                add_relation(
                    session_id,
                    target_id,
                    relation_type,
                    "copilot_agent.session_layer_map",
                    "1.0",
                    "copilot_agent",
                    marker,
                )

        for contract in contracts:
            layer_target = layer_by_session.get(marker)
            if not layer_target:
                continue
            target_id, _ = layer_target
            add_relation(
                safe_str(contract.get("id")),
                target_id,
                "defines",
                "copilot_agent.contract_layer_map",
                "1.0",
                "copilot_agent",
                marker,
            )

    governance_edges = [
        ("## 🗂🧱 Principios de Gestion", "## 🎯🧱 Detalles del tema", "governs"),
        ("## 🧭🧱 Protocolo de Sesión", "layer:copilot_agent", "governs"),
        ("## 🧭🧱 Protocolo de Sesión", "## 🌀🧱 Desarrollo y Evolución", "informs"),
        ("contratos/policy/canon_policy_bundle.json", "layer:canon", "governs"),
        ("contratos/projections/derived_layers_registry.json", "layer:microsoft_copilot", "defines"),
        ("contratos/projections/derived_layers_registry.json", "layer:copilot_agent", "defines"),
        ("python_scripts/derive_layers.py", "layer:microsoft_copilot", "generates"),
        ("python_scripts/derive_layers.py", "layer:copilot_agent", "generates"),
        ("README.md", "layer:canon", "informs"),
        ("go/canon/identity.go", "layer:canon", "defines"),
        ("go/canon/normalizer.go", "layer:canon", "hardens"),
    ]
    for source_title, target_ref, relation_type in governance_edges:
        source_id = selected_title_to_id.get(normalize_for_dedup(source_title))
        target_id = resolve_copilot_agent_target_id(target_ref, selected_by_id, selected_title_to_id)
        add_relation(
            source_id,
            target_id,
            relation_type,
            "copilot_agent.governance_map",
            "0.95",
            "copilot_agent",
            "governance anchors retained in compressed graph",
        )

    protocol_id = selected_title_to_id.get(normalize_for_dedup("## 🧭🧱 Protocolo de Sesión"))
    evolution_id = selected_title_to_id.get(normalize_for_dedup("## 🌀🧱 Desarrollo y Evolución"))
    for item in selected_entities:
        marker = extract_session_marker(item)
        entity_type = safe_str(item.get("entity_type"))
        source_id = safe_str(item.get("id"))
        if entity_type in {"session", "hypothesis", "provenance", "contract"} and evolution_id:
            add_relation(
                source_id,
                evolution_id,
                "part_of",
                "copilot_agent.session_context",
                "0.95",
                "copilot_agent",
                marker or "session family context",
            )
        if entity_type in {"session", "hypothesis", "provenance", "contract"} and protocol_id:
            add_relation(
                source_id,
                protocol_id,
                "uses",
                "copilot_agent.session_context",
                "0.9",
                "copilot_agent",
                marker or "session family context",
            )

    return sorted(
        relation_rows,
        key=lambda row: (
            safe_str(row.get("source_id")),
            safe_str(row.get("target_id")),
            safe_str(row.get("relation_type")),
        ),
    )


def assign_copilot_agent_anchors(selected_entities: list[dict]) -> list[dict]:
    family_prefix = {
        "integration_flow": "INT",
        "semantic_compression": "SEM",
        "copilot_projection": "COP",
        "minimal_canon": "CAN",
        "strict_reversibility": "REV",
    }
    counters = Counter()
    anchored = []
    for item in selected_entities:
        family = safe_str(item.get("semantic_family"))
        counters[family] += 1
        anchored_item = dict(item)
        anchored_item["txt_anchor"] = f"{family_prefix.get(family, 'DOC')}-{counters[family]:02d}"
        anchored.append(anchored_item)
    return anchored


def render_copilot_agent_corpus_lines(
    selected_entities: list[dict],
    relation_rows: list[dict],
    updated_at: str,
    *,
    summary_max_chars: int,
    signal_max_chars: int,
    max_signals: int,
    max_related: int,
    include_signals: bool,
    include_related: bool,
    include_why: bool,
) -> list[str]:
    relation_adjacency = defaultdict(list)
    title_by_id = {
        safe_str(item.get("id")): safe_str(item.get("title"))
        for item in selected_entities
    }
    for row in relation_rows:
        relation_adjacency[safe_str(row.get("source_id"))].append(
            {
                "target_title": title_by_id.get(safe_str(row.get("target_id")), safe_str(row.get("target_id"))),
                "relation_type": safe_str(row.get("relation_type")),
            }
        )

    by_family = defaultdict(list)
    for item in selected_entities:
        by_family[safe_str(item.get("semantic_family"))].append(item)

    type_counts = Counter(safe_str(item.get("entity_type")) for item in selected_entities)
    family_counts = Counter(safe_str(item.get("semantic_family")) for item in selected_entities)
    relation_types = Counter(safe_str(row.get("relation_type")) for row in relation_rows)

    lines = [
        "PROJECT_ID: tiddly-data-converter",
        f"PROFILE: {COPILOT_AGENT_FORMAT_VERSION}",
        f"GENERATED_FROM_SESSION: {COPILOT_AGENT_GENERATED_FROM_SESSION}",
        f"INTEGRATION_BASELINE: {COPILOT_AGENT_INTEGRATION_BASELINE_SESSION}",
        f"SEMANTIC_REFERENCE: {COPILOT_AGENT_SEMANTIC_REFERENCE_SESSION}",
        f"PARENT_LAYER_SESSION: {MICROSOFT_COPILOT_GENERATED_FROM_SESSION}",
        "AUTHORITY: derived_non_authoritative_agent_projection",
        f"UPDATED_AT: {updated_at}",
        "SOURCE_OF_TRUTH: data/out/local/tiddlers_*.jsonl",
        "OFFICIAL_PATH: data/out/local/microsoft_copilot/copilot_agent/",
        "NOISE_POLICY: compact summaries only; exact text stays in canon and microsoft_copilot/",
        "",
    ]

    for family in COPILOT_AGENT_FAMILY_ORDER:
        family_entities = by_family.get(family, [])
        lines.extend(
            [
                f"SECTION_ID: {family}",
                f"PURPOSE: {COPILOT_AGENT_FAMILY_PURPOSES[family]}",
                f"ENTITY_COUNT: {len(family_entities)}",
                "",
            ]
        )
        for item in family_entities:
            related = relation_adjacency.get(safe_str(item.get("id")), [])
            related_bits = []
            if include_related:
                for rel in related[:max_related]:
                    related_bits.append(f"{rel['relation_type']} -> {rel['target_title']}")
            summary = copilot_agent_display_summary(item, summary_max_chars)
            signals = []
            if include_signals:
                for signal in extract_copilot_agent_signals(item)[:max_signals]:
                    compact_signal = compact_agent_text(signal, signal_max_chars)
                    if compact_signal:
                        signals.append(compact_signal)
            lines.extend(
                [
                    f"DOC_ID: {item.get('txt_anchor')}",
                    f"ENTITY_ID: {item.get('id')}",
                    f"TITLE: {item.get('title')}",
                    f"TYPE: {item.get('entity_type')}",
                    f"SOURCE_REF: {copilot_agent_source_ref(item)}",
                    f"SUMMARY: {summary}",
                ]
            )
            if include_why:
                lines.append(f"WHY_IT_MATTERS: {item.get('selection_reason')}")
            if signals:
                lines.append(f"SIGNALS: {' | '.join(signals)}")
            if related_bits:
                lines.append(f"RELATED: {' | '.join(related_bits)}")
            lines.append("")

    lines.extend(
        [
            "SECTION_ID: compression_notes",
            "PURPOSE: Balance, density and fallback guidance for the compressed pack.",
            "",
            f"TOTAL_SELECTED_ENTITIES: {len(selected_entities)}",
            f"TOTAL_RELATIONS: {len(relation_rows)}",
            "FAMILY_COUNTS: " + ", ".join(f"{family}={family_counts[family]}" for family in COPILOT_AGENT_FAMILY_ORDER),
            "TYPE_COUNTS: " + ", ".join(f"{entity_type}={count}" for entity_type, count in type_counts.most_common()),
            "RELATION_TYPES: " + ", ".join(f"{rtype}={count}" for rtype, count in relation_types.most_common()),
            "REFERENCE_LINEAGE: S62 semantic pack -> S63 pipeline integration -> S64 semantic and reverse hardening.",
            "FOR_FULL_TEXT: consult data/out/local/tiddlers_*.jsonl and data/out/local/microsoft_copilot/.",
        ]
    )
    return lines


def build_copilot_agent_corpus(selected_entities: list[dict], relation_rows: list[dict], updated_at: str) -> str:
    render_profiles = [
        {
            "summary_max_chars": 220,
            "signal_max_chars": 150,
            "max_signals": 2,
            "max_related": 3,
            "include_signals": True,
            "include_related": True,
            "include_why": True,
        },
        {
            "summary_max_chars": 170,
            "signal_max_chars": 110,
            "max_signals": 1,
            "max_related": 2,
            "include_signals": True,
            "include_related": True,
            "include_why": False,
        },
        {
            "summary_max_chars": 130,
            "signal_max_chars": 90,
            "max_signals": 1,
            "max_related": 1,
            "include_signals": False,
            "include_related": True,
            "include_why": False,
        },
        {
            "summary_max_chars": 105,
            "signal_max_chars": 80,
            "max_signals": 0,
            "max_related": 0,
            "include_signals": False,
            "include_related": False,
            "include_why": False,
        },
    ]

    best_lines = None
    for profile in render_profiles:
        lines = render_copilot_agent_corpus_lines(selected_entities, relation_rows, updated_at, **profile)
        corpus_text = "\n".join(lines).rstrip() + "\n"
        best_lines = lines
        if len(corpus_text) <= COPILOT_AGENT_CORPUS_MAX_CHARS:
            return corpus_text

    fallback_text = "\n".join(best_lines or []).rstrip() + "\n"
    if len(fallback_text) > COPILOT_AGENT_CORPUS_MAX_CHARS:
        return fallback_text[:COPILOT_AGENT_CORPUS_MAX_CHARS].rsplit("\n", 2)[0].rstrip() + "\n"
    return fallback_text


def write_copilot_agent_artifacts(items: list[dict], copilot_agent_dir: Path, updated_at: str) -> list[Path]:
    """
    Generate the hardened three-file pack for copilot_agent/:
      - corpus.txt    : curated cognitive snapshot with DOC_ID anchors
      - entities.json : balanced semantic index
      - relations.csv : reconstructible graph subset
    """
    copilot_agent_dir.mkdir(parents=True, exist_ok=True)
    for stale_path in copilot_agent_dir.iterdir():
        if stale_path.is_file() and stale_path.name not in {"corpus.txt", "entities.json", "relations.csv"}:
            stale_path.unlink()

    written = []
    selected_entities = assign_copilot_agent_anchors(select_copilot_agent_entities(items))
    relation_rows = build_copilot_agent_relations(selected_entities)

    entity_records = []
    for item in selected_entities:
        canon_ref = item.get("canon_ref") or {}
        entity_records.append(
            {
                "id": item.get("id"),
                "type": item.get("entity_type"),
                "source_type": item.get("type"),
                "semantic_family": item.get("semantic_family"),
                "title": item.get("title"),
                "summary": copilot_agent_display_summary(item, 220),
                "authority_level": item.get("authority_level"),
                "source_primary": item.get("source_primary"),
                "source_line": canon_ref.get("line"),
                "txt_anchor": item.get("txt_anchor"),
                "related_count": item.get("related_count"),
                "tier": item.get("tier"),
                "tags": (item.get("tags") or [])[:6],
                "taxonomy_path": (item.get("taxonomy_path") or [])[:4],
                "selection_reason": item.get("selection_reason"),
            }
        )

    entities_payload = {
        "layer_id": "microsoft_copilot/copilot_agent",
        "format_version": COPILOT_AGENT_FORMAT_VERSION,
        "source_of_truth": "data/out/local/tiddlers_*.jsonl",
        "authority_class": "derived_non_authoritative_agent_projection",
        "generated_from_session": COPILOT_AGENT_GENERATED_FROM_SESSION,
        "integration_baseline": COPILOT_AGENT_INTEGRATION_BASELINE_SESSION,
        "semantic_reference": COPILOT_AGENT_SEMANTIC_REFERENCE_SESSION,
        "parent_layer_session": MICROSOFT_COPILOT_GENERATED_FROM_SESSION,
        "updated_at": updated_at,
        "entity_limit": COPILOT_AGENT_ENTITY_LIMIT,
        "balance_policy": {
            "family_targets": COPILOT_AGENT_FAMILY_TARGETS,
            "type_caps": COPILOT_AGENT_TYPE_CAPS,
            "synthetic_layers": 5,
            "family_order": COPILOT_AGENT_FAMILY_ORDER,
        },
        "entity_counts": {
            "by_type": dict(Counter(record["type"] for record in entity_records).most_common()),
            "by_family": dict(Counter(record["semantic_family"] for record in entity_records).most_common()),
        },
        "entities": entity_records,
    }
    written.append(write_json_file(copilot_agent_dir / "entities.json", entities_payload))

    written.append(
        write_csv_file(
            copilot_agent_dir / "relations.csv",
            ["source_id", "target_id", "relation_type", "provenance", "confidence", "source_layer", "notes"],
            relation_rows,
        )
    )

    corpus_text = build_copilot_agent_corpus(selected_entities, relation_rows, updated_at)
    written.append(write_text_file(copilot_agent_dir / "corpus.txt", corpus_text.splitlines()))
    return written


def cleanup_s61_copilot_output(copilot_dir: Path) -> None:
    copilot_dir.mkdir(parents=True, exist_ok=True)
    for pattern in ("tiddlers_microsoft_copilot_*.jsonl", "overview.md"):
        for path in copilot_dir.glob(pattern):
            path.unlink()


def write_microsoft_copilot_s61_artifacts(
    classified: list,
    enriched_records: list,
    enriched_shards_info: list,
    ai_records: list,
    ai_shards_info: list,
    chunk_shards_info: list,
    shard_paths: list,
    enriched_dir: Path,
    ai_dir: Path,
    reports_dir: Path,
    audit_dir: Path,
    export_dir: Path,
    copilot_dir: Path,
    tiddler_shard_size: int,
) -> dict:
    cleanup_s61_copilot_output(copilot_dir)
    updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    source_inventory = collect_microsoft_copilot_source_inventory(
        shard_paths,
        enriched_dir,
        enriched_shards_info,
        ai_dir,
        ai_shards_info,
        chunk_shards_info,
        reports_dir,
        audit_dir,
        export_dir,
    )
    source_inventory["governance_inputs"] = source_inventory.get("governance_inputs", []) + [
        ".github/instructions/contratos.instructions.md",
        ".github/instructions/sesiones.instructions.md",
        ".github/instructions/tiddlers_sesiones.instructions.md",
        "contratos/m03-s61-microsoft-copilot-json-csv-txt-projection-mvp-v0.md.json",
    ]
    source_inventory["external_reference"] = MICROSOFT_COPILOT_MICROSOFT_SUPPORT_REF

    items = build_s61_projection_items(
        classified,
        enriched_records,
        ai_records,
        enriched_dir,
        ai_dir,
        tiddler_shard_size,
    )
    bundles = select_bundle_members(items)
    public_entities = [
        {key: value for key, value in item.items() if not key.startswith("_")}
        for item in items
    ]
    topics_payload = build_topics_payload(items, updated_at)
    navigation_index = build_navigation_index_s61(items, source_inventory, bundles, updated_at)

    paths = []
    paths.append(write_json_file(copilot_dir / "entities.json", {
        "layer_id": "microsoft_copilot",
        "format_version": MICROSOFT_COPILOT_FORMAT_VERSION,
        "source_of_truth": "data/out/local/tiddlers_*.jsonl",
        "authority_class": get_layer_registry_entry("microsoft_copilot").get("authority"),
        "projection_purpose": "structured entity index for agent navigation",
        "generated_from_session": MICROSOFT_COPILOT_GENERATED_FROM_SESSION,
        "updated_at": updated_at,
        "entities": public_entities,
    }))
    paths.append(write_json_file(copilot_dir / "topics.json", topics_payload))
    paths.append(write_json_file(copilot_dir / "navigation_index.json", navigation_index))

    nodes_rows = [
        {
            "id": item.get("id"),
            "title": item.get("title"),
            "type": item.get("type"),
            "authority_level": item.get("authority_level"),
            "bundle_path": item.get("bundle_path"),
            "source_primary": item.get("source_primary"),
            "tags": item.get("tags") or [],
        }
        for item in items
    ]
    paths.append(write_csv_file(
        copilot_dir / "nodes.csv",
        ["id", "title", "type", "authority_level", "bundle_path", "source_primary", "tags"],
        nodes_rows,
    ))
    paths.append(write_csv_file(
        copilot_dir / "edges.csv",
        ["source_id", "target_id", "relation_type", "provenance", "confidence", "source_file"],
        build_edges_rows(items),
    ))
    coverage_rows = build_coverage_rows(source_inventory)
    paths.append(write_csv_file(
        copilot_dir / "coverage.csv",
        ["source_layer", "artifact_target", "coverage_status", "notes"],
        coverage_rows,
    ))

    paths.extend(write_bundle_files(copilot_dir, bundles, updated_at))
    paths.extend(write_overview_and_reading_guide(copilot_dir, navigation_index, source_inventory, updated_at))
    paths.extend(write_s61_spec_artifacts(copilot_dir, updated_at))

    artifact_rows = [
        {
            "artifact_id": path.relative_to(copilot_dir).as_posix().replace("/", ":"),
            "artifact_type": path.suffix.lstrip(".") or "directory",
            "generated_from": MICROSOFT_COPILOT_GENERATED_FROM_SESSION,
            "path": as_display_path(path),
            "status": "generated",
        }
        for path in sorted(paths, key=lambda p: p.as_posix())
    ]
    artifact_rows.append(
        {
            "artifact_id": "manifest.json",
            "artifact_type": "json",
            "generated_from": MICROSOFT_COPILOT_GENERATED_FROM_SESSION,
            "path": as_display_path(copilot_dir / "manifest.json"),
            "status": "generated",
        }
    )
    artifact_rows.append(
        {
            "artifact_id": "source_arbitration_report.json",
            "artifact_type": "json",
            "generated_from": MICROSOFT_COPILOT_GENERATED_FROM_SESSION,
            "path": as_display_path(copilot_dir / "source_arbitration_report.json"),
            "status": "generated",
        }
    )
    artifact_rows.append(
        {
            "artifact_id": "artifacts.csv",
            "artifact_type": "csv",
            "generated_from": MICROSOFT_COPILOT_GENERATED_FROM_SESSION,
            "path": as_display_path(copilot_dir / "artifacts.csv"),
            "status": "generated",
        }
    )

    artifact_descriptions = [
        {
            "artifact": row["path"],
            "artifact_type": row["artifact_type"],
            "source_inputs": {
                "json": ["canon", "enriched", "ai", "manifests"],
                "csv": ["canon", "ai", "registry"],
                "txt": ["canon", "contracts", "README", "registry"],
            }.get(row["artifact_type"], ["self_outputs"]),
            "selection_reason": "selected by S61 JSON/CSV/TXT MVP according to artifact family",
            "transformation_notes": "non-authoritative derived projection; source refs preserve reversibility",
        }
        for row in artifact_rows
    ]
    source_report = build_source_arbitration_report_s61(
        copilot_dir,
        source_inventory,
        artifact_descriptions,
        updated_at,
    )
    paths.append(write_json_file(copilot_dir / "source_arbitration_report.json", source_report))
    paths.append(write_csv_file(
        copilot_dir / "artifacts.csv",
        ["artifact_id", "artifact_type", "generated_from", "path", "status"],
        artifact_rows,
    ))

    manifest_path = write_manifest(
        copilot_dir,
        "microsoft_copilot_json_csv_txt_projection_mvp",
        [],
        len(items),
        len(shard_paths),
        shard_paths,
        extra={
            "session": MICROSOFT_COPILOT_GENERATED_FROM_SESSION,
            "pipeline_session": SESSION,
            "projection": {
                "format_version": MICROSOFT_COPILOT_FORMAT_VERSION,
                "source_of_truth": "data/out/local/tiddlers_*.jsonl",
                "authority_class": get_layer_registry_entry("microsoft_copilot").get("authority"),
                "lineage_parents": get_layer_registry_entry("microsoft_copilot").get("lineage_parents"),
                "projection_purpose": "JSON/CSV/TXT agent-readable surface derived from canon with contextual source arbitration",
                "generated_from_session": MICROSOFT_COPILOT_GENERATED_FROM_SESSION,
                "generated_via_pipeline_session": SESSION,
                "multisource_arbitration": True,
                "jsonl_final_primary": False,
                "authority_note": "derived and non-authoritative; does not replace canon, enriched or ai",
            },
            "artifacts": artifact_rows,
            "corpus_snapshot": navigation_index.get("corpus_snapshot"),
            "source_inventory": source_inventory,
            "external_format_reference": MICROSOFT_COPILOT_MICROSOFT_SUPPORT_REF,
        },
        layer_id="microsoft_copilot",
    )

    return {
        "records": public_entities,
        "manifest_path": manifest_path,
        "navigation_path": copilot_dir / "navigation_index.json",
        "source_report_path": copilot_dir / "source_arbitration_report.json",
        "overview_path": copilot_dir / "overview.txt",
        "artifact_count": len(artifact_rows),
        "copilot_agent_paths": write_copilot_agent_artifacts(
            items,
            copilot_dir / "copilot_agent",
            updated_at,
        ),
    }


# ── Enriched record builder ────────────────────────────────────────────────────

def build_enriched_record(rec: dict, shard_file: str, line_num: int,
                           role: str, taxonomy: list, section: list) -> dict:
    text = safe_str(rec.get("text"))
    content = rec.get("content") or {}
    token_est = estimate_tokens(text)
    qflags = compute_quality_flags(rec)
    corpus_policy = derive_corpus_policy(rec, role)
    role_check = classify_role_primary_value(rec.get("role_primary"), CANON_POLICY_BUNDLE)

    ct = safe_str(rec.get("content_type"))
    is_prose = ct in ("text/markdown", "text/vnd.tiddlywiki", "text/plain")

    enriched = {
        # Copied deterministic fields
        "id": rec.get("id"),
        "title": rec.get("title"),
        "canon_role_primary": rec.get("role_primary"),
        "role_primary": role,
        "role_primary_contract_verdict": role_check["verdict"],
        "role_primary_contract_canonical": role_check.get("canonical_role"),
        "text": text,
        "content_type": ct,
        "source_type": rec.get("source_type"),
        "source_fields": rec.get("source_fields"),
        "source_tags": rec.get("source_tags"),
        "normalized_tags": rec.get("normalized_tags"),
        "source_ref": rec.get("raw_payload_ref"),
        "relations": rec.get("relations"),
        "document_id": rec.get("document_id"),
        "section_path": section,
        "taxonomy_path": taxonomy,
        "order_in_document": rec.get("order_in_document"),
        "tags": rec.get("tags"),
        "schema_version": rec.get("schema_version"),
        "key": rec.get("key"),
        "canonical_slug": rec.get("canonical_slug"),
        "version_id": rec.get("version_id"),
        "modality": rec.get("modality"),
        "encoding": rec.get("encoding"),
        "is_binary": rec.get("is_binary"),
        "is_reference_only": compute_is_reference_only(rec, role),
        "mime_type": rec.get("mime_type"),
        "source_position": rec.get("source_position"),
        "created": rec.get("created"),
        "modified": rec.get("modified"),
        "corpus_state": corpus_policy["corpus_state"],
        "chunk_eligibility": corpus_policy["chunk_eligibility"],
        "chunk_exclusion_reason": corpus_policy["chunk_exclusion_reason"],
        "corpus_state_rule_id": corpus_policy["corpus_state_rule_id"],
        # Derived deterministic fields
        "preview_text": compute_preview_text(rec),
        "semantic_text": compute_semantic_text(rec),
        "content": {
            "plain": safe_str(content.get("plain")),
            "markdown": text if is_prose else None,
        },
        "size_metrics": {
            "text_length": len(text),
            "content_plain_length": len(safe_str(content.get("plain"))),
            "token_estimate": token_est,
        },
        # Heuristic fields (marked)
        "secondary_roles": build_secondary_roles(rec, role),
        "quality_flags": qflags,
        "readability": "prose" if is_prose else "structured",
        # Derivation traceability
        "derivation": {
            "session": SESSION,
            "source_shard": shard_file,
            "source_line": line_num,
            "role_source": "canon_contract_inherited" if role_check.get("canonical_role") == role else "s52_classifier",
            "role_contract_ref": CANON_POLICY_BUNDLE_REL + "#role_primary_contract",
            "taxonomy_source": "s52_derived" if not rec.get("taxonomy_path") else "canon_inherited",
            "corpus_state_rule_id": corpus_policy["corpus_state_rule_id"],
            "governance_policy_ref": CANON_POLICY_BUNDLE_REL,
        },
    }
    return enriched


# ── AI record builder ──────────────────────────────────────────────────────────

def build_ai_record(rec: dict, shard_file: str, line_num: int,
                     role: str, taxonomy: list, section: list,
                     known_ids: set, by_title_to_id: dict,
                     target_tokens: int, max_tokens: int) -> tuple:
    """
    Build AI-friendly record and optional chunks.
    Returns (ai_record, chunks, invalid_relations, payload_info)
    """
    text = safe_str(rec.get("text"))
    token_est = estimate_tokens(text)
    qflags = compute_quality_flags(rec)
    node_id = rec.get("id")
    canon_role = rec.get("role_primary")
    role_check = classify_role_primary_value(canon_role, CANON_POLICY_BUNDLE)

    hints = build_retrieval_hints(rec, role)
    payload_info = classify_payload(rec, role, target_tokens)
    role_source = "canon_contract_inherited" if role_check.get("canonical_role") == role else "s52_classifier"

    # Validate capa-1 relations (top-level)
    raw_rels = rec.get("relations") or []
    valid_rels, invalid_rels = validate_relations(raw_rels, known_ids)

    # Compact relation targets (capa-1 plus any content_embedded relations
    # already materialized in the canonical top-level relations field).
    rel_targets = relation_targets_from_relations(valid_rels)

    # S84: extract capa-2 embedded relations from content.plain
    embedded_rels, _stale, _urn = extract_embedded_content_rels(rec, by_title_to_id)

    ai_rec = {
        "id": node_id,
        "node_id": node_id,
        "title": rec.get("title"),
        "canon_role_primary": canon_role,
        "role_primary": role,
        "role_primary_source": role_source,
        "role_primary_contract_verdict": role_check["verdict"],
        "role_primary_contract_canonical": role_check.get("canonical_role"),
        "secondary_roles": build_secondary_roles(rec, role),
        # Three distinct text fields
        "preview_text": compute_preview_text(rec),
        "semantic_text": compute_semantic_text(rec),
        "ai_summary": compute_ai_summary(rec, role),
        # Retrieval
        "retrieval_terms": hints["retrieval_terms"],
        "retrieval_aliases": hints["retrieval_aliases"],
        "retrieval_hints": hints["retrieval_hints"],
        # Relations: capa-1 (authoritative) and capa-2 embedded (S84)
        "relation_targets": rel_targets,
        "embedded_relations": embedded_rels,
        # Source anchor
        "source_anchor": {
            "canon_id": node_id,
            "shard_file": shard_file,
            "shard_line": line_num,
            "source_position": rec.get("source_position"),
        },
        # Quality and classification signals
        "quality_flags": qflags,
        "confidence": compute_confidence(rec, role, qflags),
        "is_reference_only": compute_is_reference_only(rec, role),
        "is_foundational": _is_foundational(rec, role),
        # Payload signals
        "is_large_payload": payload_info["is_large_payload"],
        "is_textual_payload": payload_info["is_textual_payload"],
        "is_chunkable_text": payload_info["is_chunkable_text"],
        "chunk_eligibility": payload_info["chunk_eligibility"],
        "chunk_exclusion_reason": payload_info["chunk_exclusion_reason"],
        "corpus_state": payload_info["corpus_state"],
        "corpus_state_rule_id": payload_info["corpus_state_rule_id"],
        "chunk_strategy": payload_info["chunk_strategy"],
        "token_estimate": token_est,
        # Structure
        "document_id": rec.get("document_id"),
        "section_path": section,
        "taxonomy_path": taxonomy,
        "content_type": rec.get("content_type"),
        "derivation": {
            "session": SESSION,
            "method": "projection_v2",
            "role_source": role_source,
            "corpus_state_rule_id": payload_info["corpus_state_rule_id"],
            "governance_policy_ref": CANON_POLICY_BUNDLE_REL,
        },
    }

    # Generate chunks
    chunks = []
    if payload_info["is_chunkable_text"] and token_est > target_tokens:
        chunks, _, _ = chunk_node(
            rec,
            node_id,
            shard_file,
            line_num,
            role,
            taxonomy,
            section,
            hints["retrieval_hints"],
            payload_info,
            target_tokens,
            max_tokens,
            relation_targets=rel_targets,
        )

    return ai_rec, chunks, invalid_rels, payload_info


def _is_foundational(rec: dict, role: str) -> bool:
    """Foundational = high-level structural node."""
    title = safe_str(rec.get("title"))
    if role in ("protocol", "policy", "architecture", "schema", "readme"):
        return True
    if title.startswith("## ") or title.startswith("# "):
        return True
    sp = rec.get("section_path") or []
    if len(sp) == 1:
        return True
    return False


# ── QC Reports ────────────────────────────────────────────────────────────────

def write_classification_report(output_dir: Path, ai_records: list,
                                  enriched_records: list) -> Path:
    role_dist = Counter(r["role_primary"] for r in ai_records)
    unclassified_count = role_dist.get("unclassified", 0)
    total = len(ai_records)

    with_taxonomy = sum(1 for r in enriched_records if r.get("taxonomy_path"))
    with_section = sum(1 for r in enriched_records if r.get("section_path"))
    taxonomy_coverage = round(with_taxonomy / total, 4) if total else 0
    section_coverage = round(with_section / total, 4) if total else 0

    # Per-role sample titles for auditability
    role_samples = defaultdict(list)
    for r in ai_records:
        rp = r["role_primary"]
        if len(role_samples[rp]) < 3:
            role_samples[rp].append(safe_str(r.get("title"))[:60])

    report = {
        "session": SESSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_nodes": total,
        "role_primary_distribution": dict(role_dist.most_common()),
        "unclassified_count": unclassified_count,
        "unclassified_fraction": round(unclassified_count / total, 4) if total else 0,
        "taxonomy_path_coverage": {
            "nodes_with_taxonomy": with_taxonomy,
            "total": total,
            "coverage_fraction": taxonomy_coverage,
        },
        "section_path_coverage": {
            "nodes_with_section": with_section,
            "total": total,
            "coverage_fraction": section_coverage,
        },
        "role_samples": {k: v for k, v in role_samples.items()},
    }
    p = output_dir / "classification_report.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return p


def write_chunk_qc_report(output_dir: Path, ai_records: list,
                            all_chunks: list,
                            chunk_qc_events: list,
                            target_tokens: int, max_tokens: int) -> Path:
    text_capable_nodes = [r for r in ai_records if r.get("is_textual_payload")]
    chunkable_nodes = [r for r in ai_records if r.get("is_chunkable_text")]
    chunked_node_ids = {c.get("node_id") for c in all_chunks if c.get("node_id")}

    over_target = [c for c in all_chunks if not c.get("within_target")]
    over_max = [c for c in all_chunks if not c.get("within_hard_max")]
    with_fallback = [c for c in all_chunks if c.get("fallback")]

    excluded_reasons = Counter()
    for ev in chunk_qc_events:
        if ev.get("exclusion_reason"):
            excluded_reasons[ev["exclusion_reason"]] += 1

    eligibility_dist = Counter(r.get("chunk_eligibility", "unknown") for r in ai_records)
    token_sizes = [c.get("token_estimate", 0) for c in all_chunks]
    microchunks = [c for c in all_chunks if c.get("token_estimate", 0) < DEFAULT_MICROCHUNK_MIN_TOKENS]
    heading_only = [c for c in all_chunks if is_separator_only_chunk(safe_str(c.get("text")))]
    size_stats = {}
    if token_sizes:
        ordered = sorted(token_sizes)
        size_stats = {
            "avg_tokens": round(statistics.mean(token_sizes), 2),
            "median_tokens": statistics.median(ordered),
            "p95_tokens": ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)],
            "max_tokens": ordered[-1],
        }
    top_oversized = Counter(
        (c.get("title"), c.get("node_id"))
        for c in over_target
    )

    report = {
        "session": SESSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "config": {
            "chunk_target_tokens": target_tokens,
            "chunk_hard_max_tokens": max_tokens,
            "microchunk_threshold_tokens": DEFAULT_MICROCHUNK_MIN_TOKENS,
        },
        "total_nodes": len(ai_records),
        "text_capable_nodes": len(text_capable_nodes),
        "chunkable_nodes": len(chunkable_nodes),
        "nodes_that_produced_chunks": len(chunked_node_ids),
        "total_chunks_generated": len(all_chunks),
        "chunks_above_target": len(over_target),
        "chunks_above_hard_max": len(over_max),
        "chunks_below_micro_threshold": len(microchunks),
        "heading_only_chunks": len(heading_only),
        "chunks_with_fallback": len(with_fallback),
        "nodes_excluded_from_chunking": sum(excluded_reasons.values()),
        "exclusion_reasons": dict(excluded_reasons),
        "chunk_eligibility_distribution": dict(eligibility_dist),
        "chunk_size_distribution": size_stats,
        "traceability_summary": {
            "chunks_with_source_anchor": sum(1 for c in all_chunks if c.get("source_anchor")),
            "chunks_with_section_path": sum(1 for c in all_chunks if c.get("section_path")),
            "chunks_with_taxonomy_path": sum(1 for c in all_chunks if c.get("taxonomy_path")),
        },
        "hard_max_violated": len(over_max) > 0,
    }
    if over_target:
        report["top_oversized_nodes"] = [
            {
                "title": title,
                "node_id": node_id,
                "oversized_chunks": count,
            }
            for (title, node_id), count in top_oversized.most_common(10)
        ]
    if over_max:
        report["hard_max_violations"] = [
            {"chunk_id": c["chunk_id"], "token_estimate": c["token_estimate"]}
            for c in over_max[:10]
        ]
    p = output_dir / "chunk_qc_report.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return p


def write_retrieval_qc_report(output_dir: Path, ai_records: list) -> Path:
    total_hints = 0
    total_terms = 0
    total_aliases = 0
    nodes_with_aliases = 0
    nodes_with_empty_hints = 0
    dedup_resolved = 0

    for r in ai_records:
        terms = r.get("retrieval_terms") or []
        aliases = r.get("retrieval_aliases") or []
        hints = r.get("retrieval_hints") or []
        total_terms += len(terms)
        total_aliases += len(aliases)
        total_hints += len(hints)
        if aliases:
            nodes_with_aliases += 1
        if not hints:
            nodes_with_empty_hints += 1
        # Measure how many aliases were resolved from duplicates
        dedup_resolved += max(0, len(terms) + len(aliases) - len(set(normalize_for_dedup(h) for h in hints)))

    report = {
        "session": SESSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_nodes": len(ai_records),
        "total_retrieval_hints": total_hints,
        "total_retrieval_terms": total_terms,
        "total_retrieval_aliases": total_aliases,
        "nodes_with_aliases": nodes_with_aliases,
        "nodes_with_empty_hints": nodes_with_empty_hints,
        "avg_hints_per_node": round(total_hints / len(ai_records), 2) if ai_records else 0,
        "dedup_resolved_count": dedup_resolved,
    }
    p = output_dir / "retrieval_qc_report.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return p


def write_relations_qc_report(output_dir: Path, ai_records: list,
                                all_invalid_rels: list) -> Path:
    total_rels = sum(len(r.get("relation_targets") or []) for r in ai_records)
    type_dist = Counter()
    for r in ai_records:
        for rel in (r.get("relation_targets") or []):
            type_dist[rel.get("type", "unknown")] += 1

    report = {
        "session": SESSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_nodes": len(ai_records),
        "total_valid_relations": total_rels,
        "relation_type_distribution": dict(type_dist.most_common()),
        "total_invalid_relations_discarded": len(all_invalid_rels),
        "invalid_relation_samples": all_invalid_rels[:20],
    }
    p = output_dir / "relations_qc_report.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return p


def write_derivation_report(output_dir: Path, canon: list,
                              enriched_records: list, ai_records: list,
                              all_chunks: list, shard_paths: list,
                              target_tokens: int, max_tokens: int) -> Path:
    role_dist = Counter(r["role_primary"] for r in ai_records)
    ct_dist = Counter(rec.get("content_type", "<missing>") for rec, _, _ in canon)
    corpus_state_dist = Counter(r.get("corpus_state", "unknown") for r in ai_records)
    corpus_state_rule_dist = Counter(r.get("corpus_state_rule_id", "unknown") for r in ai_records)

    report = {
        "session": SESSION,
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "input": {
            "canon_shard_count": len(shard_paths),
            "canon_shard_files": [p.name for p in shard_paths],
            "total_records": len(canon),
        },
        "output": {
            "enriched_records": len(enriched_records),
            "ai_records": len(ai_records),
            "total_chunks": len(all_chunks),
        },
        "identity_check": {
            "ids_match": len(canon) == len(enriched_records) == len(ai_records),
            "canon_count": len(canon),
            "enriched_count": len(enriched_records),
            "ai_count": len(ai_records),
        },
        "classification_summary": {
            "role_distribution": dict(role_dist.most_common()),
            "unclassified_count": role_dist.get("unclassified", 0),
            "unclassified_fraction": round(
                role_dist.get("unclassified", 0) / len(canon), 4
            ) if canon else 0,
        },
        "governance": {
            "policy_bundle_ref": CANON_POLICY_BUNDLE_REL,
            "layer_registry_ref": DERIVED_LAYERS_REGISTRY_REL,
            "defined_corpus_states": list(CANON_POLICY_BUNDLE["corpus_state_catalog"].keys()),
            "observed_corpus_state_distribution": dict(corpus_state_dist.most_common()),
            "observed_corpus_state_rule_distribution": dict(corpus_state_rule_dist.most_common()),
        },
        "content_type_distribution": dict(ct_dist.most_common()),
        "chunking_summary": {
            "target_tokens": target_tokens,
            "hard_max_tokens": max_tokens,
            "total_chunks": len(all_chunks),
            "over_hard_max": sum(1 for c in all_chunks if not c.get("within_hard_max")),
            "over_target": sum(1 for c in all_chunks if not c.get("within_target")),
        },
        "hardening_notes": {
            "shard_discovery": "dynamic — pattern tiddlers_*.jsonl",
            "role_vocabulary": "controlled — 26 roles",
            "chunker": "token-aware structural chunker with recursive boundary refinement and post-pass microchunk densification",
            "chunk_eligibility": "resolved from canon_policy_bundle.json before chunking or AI projection",
            "retrieval": "normalized dedup with terms + aliases",
            "relations": "validated against known node IDs",
            "text_fields": "three distinct: preview_text, semantic_text, ai_summary",
            "traceability": "chunks include source_id/tiddler_id aliases, source_anchor, section_path and taxonomy_path",
        },
    }
    p = output_dir / "derivation_report.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return p


# ── CLI ────────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="derive_layers.py — S55 governed derivation entrypoint for tiddly-data-converter"
    )
    parser.add_argument(
        "--input-dir", default=None,
        help="Directory containing canon shards tiddlers_*.jsonl (default: data/out/local)"
    )
    parser.add_argument(
        "--enriched-dir", default=None,
        help="Output directory for enriched layer (default: data/out/local/enriched)"
    )
    parser.add_argument(
        "--ai-dir", default=None,
        help="Output directory for AI-friendly layer (default: data/out/local/ai)"
    )
    parser.add_argument(
        "--reports-dir", default=None,
        help="Output directory for QC reports (default: <ai-dir>/reports)"
    )
    parser.add_argument(
        "--audit-dir", default=None,
        help="Optional audit layer directory consulted for last known validation context (default: data/out/local/audit)"
    )
    parser.add_argument(
        "--export-dir", default=None,
        help="Optional export layer directory consulted for current export visibility (default: data/out/local/export)"
    )
    parser.add_argument(
        "--microsoft-copilot-dir", default=None,
        help="Output directory for microsoft_copilot derived projection (default: data/out/local/microsoft_copilot)"
    )
    parser.add_argument(
        "--chunk-target-tokens", type=int, default=DEFAULT_CHUNK_TARGET_TOKENS,
        help=f"Target tokens per chunk (default: {DEFAULT_CHUNK_TARGET_TOKENS})"
    )
    parser.add_argument(
        "--chunk-max-tokens", type=int, default=DEFAULT_CHUNK_MAX_TOKENS,
        help=f"Hard max tokens per chunk — no chunk may exceed this (default: {DEFAULT_CHUNK_MAX_TOKENS})"
    )
    parser.add_argument(
        "--tiddler-shard-size", type=int, default=DEFAULT_TIDDLER_SHARD_SIZE,
        help=f"Records per tiddler shard (default: {DEFAULT_TIDDLER_SHARD_SIZE})"
    )
    parser.add_argument(
        "--chunk-shard-size", type=int, default=DEFAULT_CHUNK_SHARD_SIZE_ARG,
        help=f"Chunks per chunk shard (default: {DEFAULT_CHUNK_SHARD_SIZE_ARG})"
    )
    parser.add_argument(
        "--overwrite", action="store_true",
        help="Overwrite existing outputs (default: overwrite always; flag kept for explicitness)"
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="Exit with error if any chunk exceeds hard max"
    )
    parser.add_argument(
        "--fail-on-chunk-violation", action="store_true",
        help="Exit with error code 2 if any chunk exceeds hard max"
    )
    return parser.parse_args()


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    args = parse_args()

    input_dir = resolve_repo_path(args.input_dir, DEFAULT_CANON_DIR)
    enriched_dir = resolve_repo_path(args.enriched_dir, DEFAULT_ENRICHED_DIR)
    ai_dir = resolve_repo_path(args.ai_dir, DEFAULT_AI_DIR)
    reports_dir = resolve_repo_path(args.reports_dir, DEFAULT_AI_REPORTS_DIR)
    audit_dir = resolve_repo_path(args.audit_dir, DEFAULT_AUDIT_DIR)
    export_dir = resolve_repo_path(args.export_dir, DEFAULT_EXPORT_DIR)
    microsoft_copilot_dir = resolve_repo_path(args.microsoft_copilot_dir, DEFAULT_MICROSOFT_COPILOT_DIR)

    target_tokens = args.chunk_target_tokens
    max_tokens = args.chunk_max_tokens
    tiddler_shard_size = args.tiddler_shard_size
    chunk_shard_size = args.chunk_shard_size

    print(f"[{SESSION}] derive_layers.py — hardened derivation pipeline with governed corpus_state")
    print(f"  input_dir:       {input_dir}")
    print(f"  enriched_dir:    {enriched_dir}")
    print(f"  ai_dir:          {ai_dir}")
    print(f"  reports_dir:     {reports_dir}")
    print(f"  audit_dir:       {audit_dir}")
    print(f"  export_dir:      {export_dir}")
    print(f"  copilot_dir:     {microsoft_copilot_dir}")
    print(f"  chunk_target:    {target_tokens} tokens")
    print(f"  chunk_hard_max:  {max_tokens} tokens")

    # ── Load canon ──
    print(f"\n[{SESSION}] Discovering and loading canon shards from {input_dir}...")
    canon, shard_paths = load_canon(input_dir)
    print(f"  Found {len(shard_paths)} shards: {[p.name for p in shard_paths]}")
    print(f"  Loaded {len(canon)} records total.")

    if not canon:
        print("ERROR: No canon records found.", file=sys.stderr)
        sys.exit(1)

    # ── Build known IDs set for relation validation ──
    known_ids = {rec.get("id") for rec, _, _ in canon if rec.get("id")}
    print(f"  Known node IDs: {len(known_ids)}")

    # S84: title→id map for embedded capa-2 relation resolution
    by_title_to_id: dict[str, str] = {
        rec.get("title"): rec.get("id")
        for rec, _, _ in canon
        if rec.get("title") and rec.get("id")
    }

    # ── Phase 1: Classify roles and derive taxonomy ──
    print(f"\n[{SESSION}] Phase 1: Classifying roles and deriving taxonomy...")
    classified = []
    for rec, shard_file, line_num in canon:
        role = classify_role(rec)
        rec["_derived_role"] = role  # temp field for taxonomy derivation
        taxonomy, section = derive_taxonomy_and_section(rec)
        del rec["_derived_role"]
        classified.append((rec, shard_file, line_num, role, taxonomy, section))

    role_counts = Counter(role for _, _, _, role, _, _ in classified)
    print(f"  Classification summary: {dict(role_counts.most_common())}")

    # ── Phase 2: Build enriched layer (Capa A) ──
    print(f"\n[{SESSION}] Phase 2: Building Capa A — Enriched Canonical Export...")
    enriched_records = []
    for rec, shard_file, line_num, role, taxonomy, section in classified:
        enriched_records.append(
            build_enriched_record(rec, shard_file, line_num, role, taxonomy, section)
        )

    enriched_shards_info = write_sharded(
        enriched_records, enriched_dir, "tiddlers_enriched", tiddler_shard_size
    )
    write_manifest(
        enriched_dir, "enriched_canonical_export",
        enriched_shards_info, len(enriched_records),
        len(shard_paths), shard_paths,
        layer_id="enriched",
    )
    print(f"  Wrote {len(enriched_records)} enriched records → {len(enriched_shards_info)} shards in {enriched_dir}")

    # ── Phase 3: Build AI layer (Capa B) ──
    print(f"\n[{SESSION}] Phase 3: Building Capa B — AI-friendly Projection v2...")
    ai_records = []
    all_chunks = []
    all_invalid_rels = []
    chunk_qc_events = []

    for rec, shard_file, line_num, role, taxonomy, section in classified:
        ai_rec, chunks, invalid_rels, payload_info = build_ai_record(
            rec, shard_file, line_num, role, taxonomy, section,
            known_ids, by_title_to_id, target_tokens, max_tokens
        )
        ai_records.append(ai_rec)
        all_chunks.extend(chunks)
        all_invalid_rels.extend(invalid_rels)
        chunk_qc_events.append({
            "node_id": rec.get("id"),
            "chunk_strategy": payload_info["chunk_strategy"],
            "exclusion_reason": payload_info.get("chunk_exclusion_reason"),
        })

    ai_shards_info = write_sharded(
        ai_records, ai_dir, "tiddlers_ai", tiddler_shard_size
    )
    chunk_shards_info = []
    if all_chunks:
        chunk_shards_info = write_sharded(
            all_chunks, ai_dir, "chunks_ai", chunk_shard_size
        )

    write_manifest(
        ai_dir, "ai_friendly_projection_v2",
        ai_shards_info, len(ai_records),
        len(shard_paths), shard_paths,
        extra={
            "chunks": {
                "total_chunks": len(all_chunks),
                "shard_count": len(chunk_shards_info),
                "shards": chunk_shards_info,
                "chunk_target_tokens": target_tokens,
                "chunk_hard_max_tokens": max_tokens,
            }
        },
        layer_id="ai",
    )
    print(f"  Wrote {len(ai_records)} AI records → {len(ai_shards_info)} shards")
    print(f"  Wrote {len(all_chunks)} chunks → {len(chunk_shards_info)} chunk shards")
    print(f"  Invalid relations discarded: {len(all_invalid_rels)}")

    # ── Phase 4: QC Reports ──
    print(f"\n[{SESSION}] Phase 4: Writing QC reports to {reports_dir}...")
    reports_dir.mkdir(parents=True, exist_ok=True)

    p1 = write_classification_report(reports_dir, ai_records, enriched_records)
    p2 = write_chunk_qc_report(reports_dir, ai_records, all_chunks, chunk_qc_events,
                                 target_tokens, max_tokens)
    p3 = write_retrieval_qc_report(reports_dir, ai_records)
    p4 = write_relations_qc_report(reports_dir, ai_records, all_invalid_rels)
    p5 = write_derivation_report(reports_dir, canon, enriched_records, ai_records,
                                   all_chunks, shard_paths, target_tokens, max_tokens)

    print(f"  {p1}")
    print(f"  {p2}")
    print(f"  {p3}")
    print(f"  {p4}")
    print(f"  {p5}")

    # ── Phase 5: Microsoft Copilot derived projection ──
    print(f"\n[{SESSION}] Phase 5: Building microsoft_copilot derived projection...")
    copilot_artifacts = write_microsoft_copilot_s61_artifacts(
        classified,
        enriched_records,
        enriched_shards_info,
        ai_records,
        ai_shards_info,
        chunk_shards_info,
        shard_paths,
        enriched_dir,
        ai_dir,
        reports_dir,
        audit_dir,
        export_dir,
        microsoft_copilot_dir,
        tiddler_shard_size,
    )
    print(
        f"  Wrote {len(copilot_artifacts['records'])} microsoft_copilot entities"
        f" → {copilot_artifacts['artifact_count']} JSON/CSV/TXT artifacts"
    )
    print(f"  {copilot_artifacts['manifest_path']}")
    print(f"  {copilot_artifacts['navigation_path']}")
    print(f"  {copilot_artifacts['source_report_path']}")
    print(f"  {copilot_artifacts['overview_path']}")

    # ── Summary ──
    over_max = sum(1 for c in all_chunks if not c.get("within_hard_max"))
    print(f"\n[{SESSION}] ── Final Summary ──")
    print(f"  Canon shards discovered:  {len(shard_paths)}")
    print(f"  Canon records loaded:     {len(canon)}")
    print(f"  Enriched records:         {len(enriched_records)}")
    print(f"  AI records:               {len(ai_records)}")
    print(f"  Chunks generated:         {len(all_chunks)}")
    print(f"  Copilot entities:         {len(copilot_artifacts['records'])}")
    print(f"  Chunks above hard max:    {over_max}  ({'⚠ VIOLATION' if over_max else 'OK'})")
    print(f"  Relations discarded:      {len(all_invalid_rels)}")
    print(f"  IDs consistent:           {len(canon) == len(enriched_records) == len(ai_records)}")
    print(f"\n  Top roles: {dict(role_counts.most_common(8))}")

    if over_max and (args.strict or args.fail_on_chunk_violation):
        print(f"\nERROR: {over_max} chunks exceed hard max ({max_tokens} tokens). Exiting with code 2.",
              file=sys.stderr)
        sys.exit(2)

    print(f"\n[{SESSION}] Derivation complete.")


if __name__ == "__main__":
    main()
