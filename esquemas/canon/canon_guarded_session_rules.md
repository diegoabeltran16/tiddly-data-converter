# Guarded Canon Session Rules

## Purpose

S40 adds a narrow, testable admission circuit on top of the canon governance
from S39. S49 keeps that guarded merge circuit and S57 changes the daily
closure regime for session semantics:

- `data/out/local/tiddlers_*.jsonl` remains the only local source of truth
- direct canon close is the default target for session semantic-documentary work
- `data/out/local/proposals.jsonl` remains available only as a legacy or manual-recovery buffer
- `data/out/remote/` is reserved for remote exchange or cloud projection
- reverse HTML outputs live under `data/out/local/reverse_html/`

Guarded direct write remains constrained and testable; it is not free-form canon editing.

## Scope

- Validate candidate canon lines against S34-S39 rules.
- Accept valid new nodes deterministically.
- Reject invalid or ambiguous nodes with explicit reasons.
- Preserve base canon entries byte-for-byte at merge time.
- Produce reproducible evidence for acceptance, rejection, merge, and reverse readiness.
- Require direct canon absorption for the semantic-documentary closure emitted by a governed session.
- Treat `data/out/local/proposals.jsonl` as an extraordinary path, not daily closure logic.

## Default Workflow After S57

### Direct canon close first

- Agents may read `data/out/local/tiddlers_*.jsonl`.
- Agents may derive from the canon and inspect local derived layers in `data/out/local/enriched/` and `data/out/local/ai/`.
- When a session emits semantic-documentary closure artifacts, agents write them directly into governed targets in `data/out/local/tiddlers_*.jsonl`.
- That closure must pass `strict` and, when relevant, `reverse-preflight`.

### Proposals are extraordinary

`data/out/local/proposals.jsonl` is still allowed only when:

- a manual recovery path is required
- or a historical candidate batch must be staged outside the daily closure flow

It must not replace direct closure of session semantics in canon.

### Direct canon repair outside session closure is still exceptional

Canon repairs beyond the session semantic-documentary family are allowed only
when:

- the user explicitly requests a guarded merge or canon repair
- or a session explicitly scopes itself as a governed merge or repair session

When that happens, the guarded rules below still apply in full.

## Required Candidate Fields

Each candidate line must already expose the full session-proposal shape:

- Structural identity: `schema_version`, `id`, `key`, `title`, `canonical_slug`, `version_id`
- Reading mode: `content_type`, `modality`, `encoding`, `is_binary`, `is_reference_only`
- Semantic layer: `role_primary`, `tags`, `taxonomy_path`, `semantic_text`, `content`, `raw_payload_ref`, `mime_type`
- Context layer: `document_id`, `section_path`, `order_in_document`, `relations`
- Provenance layer: `source_tags`, `normalized_tags`, `source_fields`, `text`, `source_type`, `source_position`, `created`, `modified`

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
- Accepted nodes are appended or updated only at explicitly governed targets.
- Rejected nodes never alter existing lines.
- Equivalent runs over the same base and batch produce the same merged JSONL and evidence.

## Evidence

S40 emits a deterministic evidence bundle with:

- merge manifest
- decision log
- validation report
- reverse-preflight report

Fixtures under `tests/fixtures/s40/` pin the expected merged canon, rejection report, and evidence summary.
