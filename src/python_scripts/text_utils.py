"""
text_utils.py — Pure text utility functions extracted from derive_layers.py (S0108).

All functions are stateless, have no IO, and depend only on stdlib.
Extracted as Fase A (P3) of the modularization plan documented in DT015/DT016.

Public API:
  estimate_tokens(text)           -> int
  safe_str(val)                   -> str
  normalize_for_dedup(s)          -> str
  strip_emoji(s)                  -> str
  looks_like_repo_path(title)     -> bool
  looks_like_build_artifact_path(title) -> bool
  looks_like_inventory_manifest(title)  -> bool
"""
import math
import re
import unicodedata

# Compiled patterns used by estimate_tokens and looks_like_repo_path
PATHISH_SUFFIX_RE = re.compile(r"\.[A-Za-z0-9._-]+$")
NON_SPACE_RE = re.compile(r"\S")
WORDLIKE_RE = re.compile(r"\w+", flags=re.UNICODE)
PUNCTLIKE_RE = re.compile(r"[^\w\s]", flags=re.UNICODE)


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
        "‍"
        "⃣"
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
