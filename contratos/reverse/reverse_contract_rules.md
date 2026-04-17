# Reverse Contract Rules — S39

## 1. Purpose

This contract defines the precise conditions under which a canonical JSONL node
can be reversed (reconstructed) into a TiddlyWiki tiddler. It specifies which
fields participate in reverse, which do not, and what preconditions must be met.

## 2. Reverse Source

Reverse depends **only** on the canonical JSONL export (`tiddlers.jsonl`).
It does **not** depend on:

- `semantic_text`
- manifest
- export.log
- AI-derived layers (`tiddlers.ai.jsonl`, `chunks.ai.jsonl`)
- embeddings
- chunking
- Parquet / Arrow serializations

## 3. Fields That Participate in Reverse

### 3.1 Required for Reverse

| Field | Role in Reverse |
|-------|----------------|
| `title` | Becomes the tiddler title |
| `text` | Becomes the tiddler body content |

A node **must** have a non-empty `title` to be reversible. If `text` is `null`,
the tiddler is reconstructed with an empty body.

### 3.2 Optional for Reverse

| Field | Role in Reverse |
|-------|----------------|
| `created` | Preserved as TW5 `created` field if present |
| `modified` | Preserved as TW5 `modified` field if present |
| `source_type` | Restored as TW5 `type` field if present |
| `source_tags` | Restored as TW5 `tags` field if present |
| `source_fields` | Optional source of extra TW5 fields under controlled validation |

### 3.3 Excluded from Reverse

The following fields are **derived** and do not participate in reverse.
They are computed by the canonizer and would be recomputed on re-ingestion:

- `id`, `canonical_slug`, `version_id` — structural identity (S34)
- `content_type`, `modality`, `encoding`, `is_binary`, `is_reference_only` — reading mode (S35)
- `role_primary`, `roles_secondary`, `tags`, `taxonomy_path` — semantic function (S36)
- `semantic_text`, `content.plain`, `normalized_tags`, `raw_payload_ref`, `asset_id`, `mime_type` — semantic/derived helper projections
- `document_id`, `section_path`, `order_in_document`, `relations` — context (S37)
- `schema_version` — emission metadata
- `key` — derived from title
- `source_role` — extraction metadata

## 4. Tiddler Reconstruction Rules

Given a canonical node `n`:

1. **Title**: `n.title` → TW5 `title`
2. **Body**: `deref(n.text)` → TW5 `text` (if `n.text` is null, body is empty string)
3. **Created**: `deref(n.created)` → TW5 `created` (omit if null)
4. **Modified**: `deref(n.modified)` → TW5 `modified` (omit if null)
5. **Type**: `deref(n.source_type)` → TW5 `type` (omit if null)
6. **Tags**: `n.source_tags` → TW5 `tags` (omit if empty)
7. **Extra fields**: `n.source_fields[k]` → TW5 field `k` only when:
   - `source_fields` is a flat object of strings
   - `k` is not a reserved reverse/TW5 field
   - `k` is not a derived canon field
   - the field is carried explicitly by the canon line

No other fields are emitted in reverse.

`content.plain` and `normalized_tags` may help local validation, filtering or
comparison, but reverse must ignore them and continue using `text` and
`source_tags` as the authoritative reversible sources.

`source_fields` never overrides `title`, `text`, `type`, `tags`, `created`,
`modified`, `source_type`, `source_tags`, or `source_fields` itself. It is an
optional authority only for explicit extra tiddler fields such as `caption`,
`list`, or `tmap.id`.

## 5. Reverse Readiness Preconditions

A canonical JSONL file is **reverse-ready** when every exported node satisfies:

1. `title` is present and non-empty.
2. `schema_version` is `"v0"`.
3. `key` is present and non-empty.

Nodes that fail these checks are **not reversible** and must be reported
as failures in the reverse-preflight diagnostic.

## 6. Reverse Does Not Guarantee Round-Trip Identity

Reverse produces a valid TiddlyWiki tiddler, but re-ingesting that tiddler
through the canon pipeline may produce different derived fields (e.g., different
`order_in_document`, different `relations` resolution). The **material content**
(`title`, `text`, `created`, `modified`) will be preserved, but derived identity
fields (`id`, `version_id`) will be deterministically recomputed and should match
if the material content is unchanged.

## 7. Deferred

- Full reverse writer implementation (HTML output).
- Template selection for TiddlyWiki HTML wrapper.
- Batch reverse with index generation.
- Round-trip verification tests.

These are planned for future sessions and are not part of S39.
