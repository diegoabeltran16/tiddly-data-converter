# Export Contract Rules — S38

## 1. What is the Canon

The **canonical JSONL export** is the single, authoritative, auditable representation
of the tiddler corpus. It is:

- **Reversible**: the source of truth for any future reconstruction.
- **One tiddler per line**: each JSON line is a self-contained node.
- **Deterministic**: identical inputs produce identical outputs.
- **Structurally typed**: every node carries identity (S34), reading mode (S35),
  semantic function (S36), and document context (S37) fields.

## 2. What is NOT the Canon

The following are **not** canonical and **not** part of this contract:

- AI-derived projections (`tiddlers.ai.jsonl`, `chunks.ai.jsonl`)
- Parquet / Arrow serializations
- Embedding vectors
- Chunked text segments
- Reverse-writer HTML output
- Provenance metadata chains

These are **derived layers** that may be built from the canon in future sessions.
They do not replace the canonical export and must not be confused with it.

## 3. `semantic_text` Interpretation (S38 §9.1)

`semantic_text` is a **nullable auxiliary projection** within the canonical JSONL.

### Rules

| Condition | Value | Strategy |
|-----------|-------|----------|
| Binary or reference-only node | `null` | `not_applicable` |
| No text content available | `null` | `not_applicable` |
| Extracted semantic text == source `text` | `null` | `suppressed_equal_to_text` |
| Extracted semantic text differs from `text` | populated `string` | `distinct` |

### Key Properties

- `semantic_text` **never** replaces or degrades `text`.
- `text` remains the canonical preserved content, always.
- Reversibility does **not** depend on `semantic_text`.
- The `semantic_text_strategy` field in the export log records which path was taken.

## 4. Manifest Interpretation (S38 §9.3)

The export manifest describes the **complete universe** of a single export run.

### Invariant

```
source_candidate_count == excluded_count + exported_count
```

### Key Fields

| Field | Description |
|-------|-------------|
| `run_id` | Unique identifier for this export run |
| `schema_version` | Schema governing the JSONL shape (`v0`) |
| `artifact_role` | Always `"canon_export"` for canonical exports |
| `source_candidate_count` | Total tiddlers submitted for export |
| `excluded_count` | Tiddlers excluded by any rule |
| `exported_count` | Tiddlers successfully emitted to JSONL |
| `excluded_by_rule` | Per-rule exclusion counts (map) |
| `semantic_text_distinct_count` | Nodes with populated `semantic_text` |
| `semantic_text_null_count` | Nodes with null `semantic_text` |
| `content_type_counts` | Breakdown by content type |
| `modality_counts` | Breakdown by modality |
| `role_primary_counts` | Breakdown by semantic role |
| `binary_count` | Count of binary nodes |
| `reference_only_count` | Count of reference-only nodes |
| `asset_count` | Count of nodes with asset_id |
| `document_count` | Distinct documents in the export |
| `nodes_with_section_path_count` | Nodes with non-empty section paths |
| `nodes_with_relations_count` | Nodes with resolved relations |
| `relation_counts` | Per-type relation counters |

## 5. Export Log Interpretation (S38 §9.5)

The export log records **one terminal decision per candidate**.

### Log Entry Fields

| Field | Description |
|-------|-------------|
| `run_id` | Export run identifier |
| `source_ref` | Title of the source tiddler |
| `decision` | `"exported"` or `"excluded"` — terminal decision |
| `rule_id` | Rule that determined the decision |
| `reason` | Human-readable explanation |
| `id` | Structural UUID (exported entries only) |
| `canonical_slug` | Canonical slug (exported entries only) |
| `semantic_text_strategy` | `distinct`, `suppressed_equal_to_text`, or `not_applicable` |

### Properties

- Every candidate appears **exactly once** in the log.
- Excluded entries have `decision: "excluded"` with `rule_id` and `reason`.
- Exported entries have `decision: "exported"` with full traceability.
- No "magic" steps: every exclusion is traceable to a specific rule.

## 6. Deferred to Future IA Layers

The following are explicitly **not** part of the canonical export and will be
addressed in future sessions:

| Deferred Item | Future Session |
|---------------|----------------|
| `tiddlers.ai.jsonl` (AI-optimized projection) | TBD |
| `chunks.ai.jsonl` (chunked text for retrieval) | TBD |
| Parquet / Arrow serialization | TBD |
| Embedding vectors | TBD |
| Reverse writer (canon → HTML) | TBD |
| Provenance chains | TBD |
| Quality gates and scoring | TBD |
| Strong versioning (semver) | TBD |

The canon remains the **single source of truth**. All derived layers
are projections built from, but never replacing, the canonical export.
