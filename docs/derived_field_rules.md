# S41 Derived Field Rules

## Purpose

S41 adds the minimum derived hardening required to prepare a future reverse
flow without changing canonical authority. The new fields are helper
projections only.

## Authority and Asymmetry

- `text` remains the authoritative reversible content source.
- `source_tags` remains the authoritative reversible tag source for TiddlyWiki output.
- `tags` remains the existing semantic tag projection introduced by S36.
- `content.plain` is derived and non-authoritative.
- `content.asset`, `content.code_blocks`, `content.equations`,
  `content.references` and `content.structured_payload` are derived and
  non-authoritative modal projections.
- `normalized_tags` is derived and non-authoritative.
- No derived field may silently correct, overwrite, or replace its source.

## `content.plain`

### Source

`content.plain` is derived only from authoritative textual content already
available in the node, currently `text`.

### Policy

- Only textual, non-binary, non-reference-only nodes may emit `content.plain`.
- Binary and reference-only nodes leave `content.plain` absent.
- Derivation is conservative:
  - normalize line endings to `\n`
  - collapse whitespace runs to a single space
  - trim outer whitespace
- The derivation does not summarize, reinterpret, render or improve content.
- If the normalized result is empty, `content.plain` stays absent.

### Reverse rule

Future reverse must continue reading `text`, never `content.plain`.

## Modal Content Projections

### Source

Modal projections are derived only from fields already preserved in the canon:
`text`, `content_type`, `modality`, `encoding`, `is_binary`,
`is_reference_only`, `raw_payload_ref`, `asset_id` and `mime_type`.

### Policy

- Binary/image assets may emit `content.asset` with payload reference, MIME,
  encoding, payload presence and deterministic payload hash/size when the
  embedded payload is available.
- Textual nodes may emit `content.code_blocks`, `content.equations` and
  `content.references` when conservative syntax is detected.
- Valid full JSON payloads may emit `content.structured_payload`; partial,
  recoverable or pedagogical JSON remains audit evidence, not canonical
  promotion.
- Mixed nodes declare `content.projection_kind: "mixed"` and a deterministic
  `content.modalities` list.
- Projections organize existing evidence; they do not summarize or replace the
  original source text.

### Reverse rule

Reverse must continue reading `text`, `source_tags` and `source_fields`.
Modal projections are inspection and validation helpers only.

## `normalized_tags`

### Source and precedence

- `normalized_tags` is derived from `tags` when that semantic projection is present.
- If `tags` is absent in a local normalization context, the fallback input is `source_tags`.
- `normalized_tags` never rewrites either source field.

### Normalization policy

- trim outer whitespace
- collapse internal whitespace to a single space
- lowercase
- strip diacritics conservatively
- preserve emoji and non-diacritic symbols
- collapse duplicates after normalization
- preserve the order of the first surviving normalized occurrence

### Collision policy

- When two tags normalize to the same value, `normalized_tags` keeps one value.
- The surviving value is the first normalized occurrence in source order.
- Collisions do not mutate `tags` or `source_tags`.

### Use policy

- Reverse must continue using `source_tags`.
- Comparison, filtering and validation may use `normalized_tags` when useful.
- Human-facing inspection may continue to use `tags` or `source_tags` depending on intent.

## Non-authority rule

Derived projections are asymmetric by contract:

- `content.plain` cannot override `text`.
- Modal projections cannot override `text`, payload identity, source tags or
  source fields.
- `normalized_tags` cannot override `tags` or `source_tags`.
- Validation may reject inconsistent derived values, but only recomputation from
  source fields can repair them.
- Reverse readiness must treat derived projections as optional helpers, never as
  primary reconstruction inputs.
