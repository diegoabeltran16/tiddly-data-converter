# Semantic Function and Asset Separation Rules

**Session:** `m02-s36-canon-semantic-function-and-asset-separation-v0`
**Module:** `go/canon/semantic.go`
**Date:** 2026-04-15
**Status:** v0 — initial implementation

---

## 1. Controlled Vocabulary for `role_primary`

| Role | Description |
|------|-------------|
| `concept` | Conceptual or architectural node |
| `procedure` | Procedural or methodological node |
| `evidence` | Evidence, hypothesis, or provenance node |
| `definition` | Definitional node |
| `glossary` | Glossary entry |
| `policy` | Policy or decision node |
| `log` | Session log, event, or report |
| `asset` | Binary or non-textual asset |
| `config` | Configuration or metadata node |
| `code` | Source code node |
| `narrative` | Narrative or documentation node |
| `note` | General note |
| `warning` | Warning or alert |
| `unclassified` | No evidence for classification |

---

## 2. Precedence Hierarchy for Semantic Derivation

| Level | Source | Priority |
|-------|--------|----------|
| 1 | Explicit role declared in tiddler (`source_role`) | Highest |
| 2 | Internal declared tags | High |
| 3 | Native TiddlyWiki tags (`source_tags`) | Medium |
| 4 | Structural patterns (content_type, modality) | Low |
| 5 | Conservative fallback (`unclassified`) | Lowest |

**Rule:** If a node declares its function explicitly, the canonizer reads it, preserves it, normalizes it if needed, and does not substitute it with weaker inferences.

---

## 3. Tag Merge Policy

- `tags` = normalized, deduplicated union of internal + native TiddlyWiki tags
- Internal tags appear first, in source order
- Native tags are appended if not already present
- Deduplication is case-insensitive; first occurrence's casing is preserved
- Empty strings and whitespace-only tags are stripped

---

## 4. Taxonomy Path Policy

- `taxonomy_path` is derived conservatively from structural tags only
- Tags with markdown heading markers (`##`, `###`, `####`) are structural
- Tags containing `🧱` or `🌀` are structural taxonomy markers
- Returns empty `[]` when no structural tags are present
- No speculative taxonomy construction

---

## 5. Semantic Text Policy

| Content Type | semantic_text | Mode |
|-------------|---------------|------|
| text/plain, text/markdown, text/html | Full text | `direct_text` |
| text/vnd.tiddlywiki | Full text (wikitext preserved) | `direct_text` |
| text/csv, application/json | Full text | `direct_text` |
| image/*, application/octet-stream | Empty | `empty_for_binary` |
| Reference-only nodes | Empty | `reference_only` |

**Equations:** Equations embedded in textual content ($$...$$, \(...\), \[...\], <$latex>) remain in `semantic_text`. They are NOT treated as assets.

**Anti-invention:** `semantic_text` never generates summaries, translations, or content not present in the source.

---

## 6. Asset Separation Policy

| Condition | asset_id | asset_mode |
|-----------|----------|------------|
| Purely textual node | Empty | `none` |
| Binary node (is_binary=true) | `asset:<node_id>` | `derived` |
| Reference-only node | `asset:<node_id>` | `reference_only` |
| Image content type | `asset:<node_id>` | `derived` |

**Rule:** `asset_id` is NOT emitted for purely textual nodes, including those with embedded equations.

---

## 7. MIME Type Resolution

| Priority | Source | Example |
|----------|--------|---------|
| 1 | `content_type` from S35 | `text/vnd.tiddlywiki` |
| 2 | `source_type` metadata | `text/x-markdown` |
| 3 | Conservative mapping from modality | `text/plain` |
| 4 | Empty (insufficient evidence) | `""` |

`text/vnd.tiddlywiki` is explicitly supported and preserved.

---

## 8. Raw Payload Reference

- Format: `node:<structural_uuid>`
- Present for all nodes with computed identity
- Deterministic and auditable
- Non-interpretive

---

## 9. Domain-Specific Role Mappings

| Source Term | Maps To |
|------------|---------|
| sesión / sesion | log |
| hipótesis / hipotesis | evidence |
| procedencia | evidence |
| arquitectura | concept |
| documentación / documentacion | narrative |
| reporte | log |
| dato | evidence |
| evento | log |
