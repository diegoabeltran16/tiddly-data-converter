"""
chunking.py — Pure text chunking functions extracted from derive_layers.py (S0109).

All functions are stateless, have no IO, and depend only on stdlib and text_utils.
Extracted as Fase B (P2) of the modularization plan documented in DT015/DT016.

Public API:
  chunk_by_headers(text)                          -> list[str]
  chunk_by_paragraphs(text)                       -> list[str]
  chunk_by_sentences(text)                        -> list[str]
  chunk_by_code_boundaries(text)                  -> list[str]
  hard_split(text, limit_tokens)                  -> list[str]
  merge_segments(segments, target_tokens, max_tokens) -> list[str]
  is_code_like_payload(title, role)               -> bool
  split_structurally(text, title, role, target_tokens, max_tokens) -> list[str]
  join_chunk_text(left, right)                    -> str
  is_separator_only_chunk(chunk_text)             -> bool
  is_microchunk(chunk_text, token_estimate)       -> bool
  densify_microchunks(chunks_text, target_tokens) -> list[str]
  extract_chunk_heading(chunk_text, section_path, title) -> str

Constants:
  DEFAULT_MICROCHUNK_MIN_TOKENS  = 80
  MARKDOWN_HEADER_RE
  CODE_BOUNDARY_RE
  HEADING_LINE_RE
"""
import re

from text_utils import estimate_tokens, safe_str

# Token threshold below which a chunk is considered a "microchunk"
DEFAULT_MICROCHUNK_MIN_TOKENS = 80

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


def chunk_by_headers(text: str) -> list:
    """Split text by markdown headers into sections."""
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
            if (
                "[[tags]]" in heading_lower
                or "[[created]]" in heading_lower
                or "[[modified]]" in heading_lower
            ):
                continue
            return stripped[:160]
        break
    if section_path:
        return safe_str(section_path[-1])[:160]
    return safe_str(title)[:160]
