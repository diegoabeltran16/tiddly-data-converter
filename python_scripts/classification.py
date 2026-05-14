"""
classification.py — Semantic role classifier for the derivation pipeline (S0110).

Extracted from derive_layers.py (Fase C of modularisation plan).
Provides classify_role() and derive_taxonomy_and_section(), which are pure
deterministic functions with respect to their inputs and the policy bundle.

The policy bundle and valid-role set are loaded once at module import time,
following the same pattern used by corpus_governance.py.
"""

import re

from corpus_governance import (
    classify_role_primary_value,
    load_canon_policy_bundle,
    role_primary_canonical_roles,
)
from text_utils import (
    safe_str,
    strip_emoji,
    looks_like_repo_path,
    looks_like_build_artifact_path,
    looks_like_inventory_manifest,
)

# ── Policy globals (loaded once at import time) ────────────────────────────────

CANON_POLICY_BUNDLE = load_canon_policy_bundle()
VALID_ROLES = role_primary_canonical_roles(CANON_POLICY_BUNDLE)


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
