# Node Reading Mode Rules — S35

## Scope

This document defines the rules for the five reading mode fields added by S35
to each canonical JSONL node:

- `content_type`
- `modality`
- `encoding`
- `is_binary`
- `is_reference_only`

## Design Principles

1. **Prefer fidelity over sophistication.**
2. **Prefer conservative classification over aggressive inference.**
3. **Prefer documented `unknown` over false precision.**
4. **Do not transform or rewrite payloads to classify them.**

## Inference Order (§17.1)

The classification follows a stable, deterministic priority:

1. Explicit source signals (tiddler `type` field).
2. Structural analysis of the available payload.
3. Conservative fallback rules.
4. `unknown` when certainty is insufficient.

---

## Field Definitions

### `content_type` (§16.1)

Represents the type of content the node carries.

**Allowed values:**

| Value | Description |
|-------|-------------|
| `text/plain` | Plain text |
| `text/markdown` | Markdown content |
| `text/html` | HTML content |
| `text/vnd.tiddlywiki` | TiddlyWiki native wikitext |
| `application/json` | JSON data |
| `text/csv` | CSV tabular data |
| `image/png` | PNG image |
| `image/jpeg` | JPEG image |
| `image/svg+xml` | SVG image |
| `application/octet-stream` | Binary data |
| `application/x-tiddler` | TiddlyWiki tiddler reference |
| `unknown` | Cannot determine with confidence |

**Rules:**
- Prioritize explicit `type` from source when recognized.
- If no explicit type, check if payload is valid JSON.
- If no explicit type and not JSON, default to `text/vnd.tiddlywiki`.
- Do not parse aggressively just to prove content type.

### `modality` (§16.2)

Represents the primary reading channel for the node.

**Allowed values:**

| Value | Description |
|-------|-------------|
| `text` | Textual content for reading |
| `code` | Source code |
| `table` | Tabular/structured data |
| `image` | Visual content |
| `metadata` | Structural/metadata content |
| `binary` | Binary content |
| `equation` | Mathematical content |
| `mixed` | Mixed modalities |
| `unknown` | Cannot determine |

**Derivation table:**

| `content_type` | Default `modality` |
|----------------|-------------------|
| `text/plain` | `text` |
| `text/markdown` | `text` |
| `text/html` | `text` |
| `text/vnd.tiddlywiki` | `text` (or `equation` if explicit math) |
| `application/json` | `metadata` |
| `text/csv` | `table` |
| `image/png` | `image` |
| `image/jpeg` | `image` |
| `image/svg+xml` | `image` |
| `application/octet-stream` | `binary` |
| `application/x-tiddler` | `metadata` |
| `unknown` | `unknown` |

**Equation exception (§17.4):**
A `text/vnd.tiddlywiki` node is `equation` only with explicit evidence:
- `<$latex>...</$latex>` widget
- `$$...$$` display math
- `\(...\)` inline math
- `\[...\]` display math

### `encoding` (§16.3)

Represents how the payload is encoded.

**Allowed values:**

| Value | Description |
|-------|-------------|
| `utf-8` | UTF-8 text |
| `base64` | Base64-encoded |
| `binary` | Raw binary |
| `unknown` | Cannot determine |

**Rules:**
- Textual content types → `utf-8`
- Image types with base64 payload → `base64`
- Image types without payload → `binary`
- `application/octet-stream` with base64 → `base64`, else `binary`
- Unknown → `unknown`

### `is_binary` (§16.4)

Boolean: does the content require binary treatment?

- `true`: image/png, image/jpeg, application/octet-stream, or encoding=binary
- `false`: all textual content types
- NOT based on: content size, complexity, or unfamiliarity

### `is_reference_only` (§16.5)

Boolean: is the node a pointer/reference without primary content?

- `true`: image type without text content, application/x-tiddler without content
- `false`: node carries its primary content
- NOT inferred merely from empty text (accidental absence vs structural reference)

---

## Version ID Exclusion

Reading mode fields are **excluded** from the `version_id` normative shape
because they are deterministic derivations of existing material fields
(source_type, text structure). Including them would be redundant and would
break backward compatibility with S34 version_id hashes.

---

## Implementation

All logic is centralized in `go/canon/reading_mode.go`:

- `BuildNodeReadingMode(e CanonEntry) ReadingMode` — single entry point
- `DetectContentType(e CanonEntry) string`
- `DetectModality(contentType string, e CanonEntry) string`
- `DetectEncoding(contentType string, e CanonEntry) string`
- `DetectBinaryFlag(contentType, encoding string) bool`
- `DetectReferenceOnlyFlag(contentType string, e CanonEntry) bool`

---

## References

- S33 — JSONL functional export
- S34 — structural identity layer
- S35 — reading mode and typing (this session)
