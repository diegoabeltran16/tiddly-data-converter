# Guarded Canon Session Rules

## Purpose

S40 introduced a narrow, testable admission circuit on top of canon governance.
S66 keeps that guarded circuit but changes the default session closure regime:

- `data/out/local/tiddlers_*.jsonl` remains the local source of truth.
- `data/sessions/` is the default surface for session artifacts, traceability and candidate canon lines.
- Agents do not write directly into the final canon by default.
- Candidate lines can be admitted only through a local/manual validation flow.
- `data/out/local/proposals.jsonl` remains available only as a legacy or manual-recovery buffer.
- `data/out/remote/` is reserved for remote exchange or cloud projection.
- reverse HTML outputs live under `data/out/local/reverse_html/`.

`data/sessions/` is not a parallel canon. It is staging and evidence.

## Scope

- Validate candidate canon lines against S34-S39 rules.
- Accept valid new nodes deterministically only after local admission.
- Reject invalid or ambiguous nodes with explicit reasons.
- Preserve base canon entries byte-for-byte while testing a temporary admission.
- Produce reproducible evidence for acceptance, rejection, merge and reverse readiness.
- Require a session artifact family before canon admission is considered.
- Treat `data/out/local/proposals.jsonl` as an extraordinary path, not daily closure logic.

## Default Workflow After S66

### Session staging first

- Agents may read `data/out/local/tiddlers_*.jsonl`.
- Agents may derive from the canon and inspect local derived layers in `data/out/local/enriched/` and `data/out/local/ai/`.
- When a session emits semantic-documentary closure artifacts, agents write them under `data/sessions/`.
- When those artifacts must be canonizable, agents write candidate JSONL lines under `data/sessions/`.
- Candidate lines must not claim final canonical authority before admission.

### Local canon admission

A local/manual admission process should:

1. copy the current canon to a temporary directory;
2. append or insert candidate lines into that temporary copy;
3. run `canon_preflight --mode strict`;
4. run `canon_preflight --mode reverse-preflight`;
5. run `reverse_tiddlers --mode authoritative-upsert`;
6. require `Rejected: 0`;
7. run tests related to canon, reverse and derived layers;
8. apply to `data/out/local/tiddlers_*.jsonl` only if all required gates pass.

If any gate fails, the final canon is not modified.

### Proposals are extraordinary

`data/out/local/proposals.jsonl` is still allowed only when:

- a manual recovery path is required;
- or a historical candidate batch must be staged outside the daily closure flow.

It must not replace `data/sessions/` as the default session closure surface.

### Direct canon repair remains exceptional

Canon repairs outside the session candidate flow are allowed only when:

- the user explicitly requests a guarded merge or canon repair;
- or a session explicitly scopes itself as a governed merge or repair session.

When that happens, the guarded rules below still apply in full.

## Required Session Family

Before a session's candidate lines can be considered for admission, the session
must have its minimum family:

- contract;
- provenance;
- session details;
- session hypotheses;
- session balance;
- session proposal;
- session diagnosis.

The diagnosis must record which validations passed, failed or remained pending.

## Required Candidate Fields

Each candidate line must already expose the full session-proposal shape:

- Structural identity: `schema_version`, `id`, `key`, `title`, `canonical_slug`, `version_id`
- Reading mode: `content_type`, `modality`, `encoding`, `is_binary`, `is_reference_only`
- Semantic layer: `role_primary`, `tags`, `taxonomy_path`, `semantic_text`, `content`, `raw_payload_ref`, `mime_type`
- Context layer: `document_id`, `section_path`, `order_in_document`, `relations`
- Provenance layer: `source_tags`, `normalized_tags`, `source_fields`, `text`, `source_type`, `source_position`, `created`, `modified`

Candidate lines must declare:

- origin session;
- artifact family;
- provenance;
- source path under `data/sessions/`;
- non-final canonical status.

Use non-reserved `source_fields` keys for those declarations.

## Deterministic Checks

### Identity

- `schema_version` must be `v0`.
- `key` must equal `title`.
- `id` must match the S34 UUIDv5 recipe for the title/key.
- `canonical_slug` must match the S34 slug derivation.
- `version_id` must match the S34 content hash derivation.
- A candidate cannot collide with an existing base node by `id`, `key` or `title` unless the admission is explicitly an update.
- A candidate batch cannot contain duplicate `id`, `key` or `title`.

### Reading mode

- `content_type`, `modality` and `encoding` must belong to the S35 catalogues.
- `is_binary` and `is_reference_only` must be coherent with the declared payload shape.

### Semantics

- `role_primary` must belong to the S36 vocabulary.
- If `source_role` exists and maps deterministically, `role_primary` must respect it.
- `tags` must match the deterministic merge of `source_tags` when source tags exist.
- `taxonomy_path` must match the deterministic derivation from tags.
- `raw_payload_ref`, `asset_id` and `mime_type` must match deterministic recomputation when applicable.
- `semantic_text` must remain suppressed when it would duplicate `text`.

### Context and relations

- `document_id` must match deterministic recomputation when source evidence exists.
- `section_path` must match conservative derivation or declared source evidence.
- `order_in_document` must be non-negative.
- `relations` must be sorted, deduplicated and use only allowed `type` and `evidence` values.
- Every `relation.target_id` must resolve against `base + accepted candidates`.
- Self-relations are rejected.

### Reverse safety

- `source_fields` must not use reserved reverse fields unless their value is exactly equivalent to the authoritative reverse projection.
- Prefer not to use reserved fields in `source_fields` at all.
- `reverse_tiddlers` must finish with `Rejected: 0` before admission.

### Placeholder policy

- Placeholder markers such as `PENDIENTE`, `TODO` or `resolver luego` are rejected in structural and classification fields.

## Merge Rules

- The base canon is copied as-is into a temporary admission surface.
- Accepted nodes are appended or updated only at explicitly governed targets.
- Rejected nodes never alter existing lines.
- Equivalent runs over the same base and batch produce the same merged JSONL and evidence.

## Evidence

The admission evidence bundle should include:

- session family paths;
- candidate JSONL path;
- merge or temporary-admission manifest;
- decision log;
- strict validation report;
- reverse-preflight report;
- reverse authoritative report;
- test results.

The session is not canonically closed if it only describes the flow but does not
apply it to its own closure package when instructed to do so.
