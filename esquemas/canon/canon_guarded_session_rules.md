# S40 Guarded Canon Session Rules

## Purpose

S40 adds a narrow, testable admission circuit on top of the canon governance from S39. The canon remains the only source of truth; candidate lines are accepted only if they already satisfy the canon contract and can be merged without mutating existing nodes.

## Scope

- Validate candidate canon lines against S34-S39 rules.
- Accept valid new nodes deterministically.
- Reject invalid or ambiguous nodes with explicit reasons.
- Preserve base canon entries byte-for-byte at merge time.
- Produce reproducible evidence for acceptance, rejection, merge, and reverse readiness.

## Required Candidate Fields

Each candidate line must already expose, at minimum:

- Structural identity: `schema_version`, `id`, `key`, `title`, `canonical_slug`, `version_id`
- Reading mode: `content_type`, `modality`, `encoding`, `is_binary`, `is_reference_only`
- Semantic layer: `role_primary`, `tags`, `taxonomy_path`, `raw_payload_ref`, `mime_type`
- Context layer: `document_id`, `section_path`, `order_in_document`, `relations`

## Deterministic Checks

### Identity

- `schema_version` must be `v0`.
- `key` must equal `title`.
- `id` must match the S34 UUIDv5 recipe for the title/key.
- `canonical_slug` must match the S34 slug derivation.
- `version_id` must match the S34 content hash derivation.
- A candidate cannot collide with an existing base node by `id`, `key`, or `title`.
- A candidate batch cannot contain duplicate `id`, `key`, or `title`.

### Reading mode

- `content_type`, `modality`, and `encoding` must belong to the S35 catalogues.
- `is_binary` and `is_reference_only` must be coherent with the declared payload shape.

### Semantics

- `role_primary` must belong to the S36 vocabulary.
- If `source_role` exists and maps deterministically, `role_primary` must respect it.
- `tags` must match the deterministic merge of `source_tags` when source tags exist.
- `taxonomy_path` must match the deterministic derivation from tags.
- `raw_payload_ref`, `asset_id`, and `mime_type` must match deterministic recomputation.
- `semantic_text` must remain suppressed when it would duplicate `text`.

### Context and relations

- `document_id` must match deterministic recomputation when source evidence exists.
- `section_path` must match conservative derivation.
- `order_in_document` must be non-negative.
- `relations` must be sorted, deduplicated, and use only allowed `type` and `evidence` values.
- Every `relation.target_id` must resolve against `base + accepted candidates`.
- Self-relations are rejected.

### Placeholder policy

- Placeholder markers such as `PENDIENTE`, `TODO`, or `resolver luego` are rejected in structural and classification fields.

## Merge Rules

- The base canon is copied as-is.
- Accepted nodes are appended in candidate order.
- Rejected nodes never alter existing lines.
- Equivalent runs over the same base and batch produce the same merged JSONL and evidence.

## Evidence

S40 emits a deterministic evidence bundle with:

- merge manifest
- decision log
- validation report
- reverse-preflight report

Fixtures under `tests/fixtures/s40/` pin the expected merged canon, rejection report, and evidence summary.
