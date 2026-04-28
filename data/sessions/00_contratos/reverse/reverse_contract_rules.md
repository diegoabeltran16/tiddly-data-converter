# Reverse Contract Rules — S44

## 1. Purpose

This contract defines the exact reverse behavior for the S44 flow:

- source of truth: canonical JSONL shard set or a single canonical JSONL file
- reverse target: the TiddlyWiki store block inside an existing HTML shell
- merge mode: `authoritative-upsert` or `insert-only`

Reverse is not a full HTML rebuild. It is a controlled store update over a real
base HTML.

Operational reverse outputs live under `data/out/local/reverse_html/` as local,
derived, reproducible artifacts. They never become canon.

## 2. Reverse Source

Reverse accepts either:

- a single canonical JSONL file
- or a directory containing ordered shards `tiddlers_<n>.jsonl`

When a shard directory is used, the ordered shard set is treated as a single
canonical sequence. The loader must fail before reverse when it detects:

- invalid JSONL shard content
- unstable shard naming / ordering
- duplicate shard content
- duplicate exact canon lines
- duplicate `title`
- duplicate `key`

Derived layers do not participate in reverse:

- `semantic_text`
- manifest
- `export.log`
- AI-derived layers
- embeddings
- chunking
- Parquet / Arrow serializations

## 3. Authoritative Fields

### 3.1 Reverse-ready prerequisites

A canon line is reverse-ready when:

- `schema_version == "v0"`
- `key` is non-empty
- `title` is non-empty

### 3.2 Reverse-authoritative fields

The reverse projection is built only from:

- `title`
- `text`
- `created`
- `modified`
- `source_type`
- `source_tags`
- `source_fields`

`key`, when present, must equal `title`.

### 3.3 `source_fields`

`source_fields` is optional authority only for explicit extra TiddlyWiki fields.
It must be a flat object of strings.

Allowed behavior:

- extra fields such as `caption`, `list`, `tmap.id`
- reserved copies of authoritative fields only when they are consistent with the authoritative projection

Rejected behavior:

- conflicting reserved fields (`title`, `text`, `type`, `tags`, `created`, `modified`, etc.)
- derived canon fields (`id`, `canonical_slug`, `version_id`, `content`, `normalized_tags`, `document_id`, `section_path`, `order_in_document`, `relations`, etc.)

## 4. Non-Authoritative Fields

The following fields never drive reverse decisions and never overwrite source
authority:

- `id`
- `canonical_slug`
- `version_id`
- `content_type`
- `modality`
- `encoding`
- `is_binary`
- `is_reference_only`
- `role_primary`
- `roles_secondary`
- `tags`
- `taxonomy_path`
- `semantic_text`
- `content.plain`
- `normalized_tags`
- `raw_payload_ref`
- `asset_id`
- `mime_type`
- `document_id`
- `section_path`
- `order_in_document`
- `relations`

If a source field conflicts with one of these derived projections, the source
field wins and the derived field remains non-authoritative.

## 5. Reverse Scope

Reverse does not materialize these nodes from canon:

- system titles `$:/...`
- binary nodes
- reference-only nodes
- nodes whose `source_type` is outside the current textual/metadata scope

These lines are skipped explicitly and reported, not silently normalized.

## 6. Merge Behavior

### 6.1 `insert-only`

- new titles are inserted
- existing titles with equivalent projection are `already_present`
- existing titles with conflicting authoritative projection are rejected

### 6.2 `authoritative-upsert`

- new titles are inserted
- existing titles with equivalent projection are `already_present`
- existing titles with different authoritative projection are updated in place
- unrelated fields already present in the base HTML but not projected by canon are preserved

### 6.3 `store-policy`

`reverse_tiddlers` exposes two explicit store policies:

- `preserve` keeps the base store and applies the selected merge mode over it
- `replace` rebuilds the store array from the eligible canon projections only

Current rule for `replace`:

- non-system base tiddlers are not carried forward implicitly
- system titles from the base HTML are preserved as structural exceptions so the HTML remains reopenable
- system titles from canon remain out of scope under the current textual/metadata reverse contract

## 7. HTML Preservation

Reverse must:

- preserve the original HTML shell
- locate the existing TiddlyWiki store block deterministically
- rewrite only the store content
- preserve non-target zones of the HTML

Reverse must not:

- regenerate the whole HTML document from scratch
- reinterpret derived canon fields as authority
- silently invent missing content

## 8. Fail Conditions Before Write

Reverse must fail before writing output when any of these checks fails:

- shard/source preflight
- strict canon validation
- reverse-preflight
- malformed reverse candidate
- invalid `source_tags`
- invalid `source_fields`
- ambiguous key/title mismatch

## 9. Round-Trip Note

Round-trip may recompute derived projections on re-export, but reverse authority
remains anchored in the source fields listed in section 3. Derived projections
must never overwrite those fields.
