# Identity Rules — S34

## Structural Identity per Node

Every exported JSONL line must expose five semantically separated identity fields:

| Field | Role | Depends On |
|-------|------|------------|
| `id` | Structural, immutable, deterministic UUID | `key` (source anchor) |
| `key` | Operational/human key for debugging | title (source.key) |
| `title` | Visible name, preserved from source | source tiddler |
| `canonical_slug` | Legible, normalized, reproducible slug | title |
| `version_id` | Content-sensitive version hash | normative shape |

These five roles **must not** collapse into each other.

---

## `id` — Structural Identity

- **Algorithm:** UUIDv5(UUIDNamespaceURL, CanonicalJSON(payload))
- **Payload:** `{"key": "<source_key>", "type": "tiddler_node", "uuid_spec_version": "v1"}`
- **Determinism:** same key → same id, across reruns
- **Does NOT depend on:** canonical_slug, version_id, schema_version
- **Anchor:** uses `key` (= title from TiddlyWiki) as the stable source anchor

### Prohibited
- Constructing `id` from a cosmetic title that might change independently of key
- Constructing `id` from `canonical_slug` (which may vary by collision resolution)

---

## `key` — Operational Key

- Uses the TiddlyWiki title as-is (the stable source anchor)
- If no explicit source key exists, the title IS the key
- Legible, useful for debugging and human traceability
- Does NOT substitute `id` for identity purposes

---

## `title` — Visible Name

- Preserved faithfully from the source tiddler
- Not altered by slug, UUID, or versioning rules
- May change cosmetically without breaking `id` (as long as `key` is stable)

---

## `canonical_slug` — Normalized Slug

### Algorithm (pure, deterministic function)

1. **NFKC normalization** (compatibility decomposition + canonical composition)
2. **NFD decomposition** + strip combining marks → removes diacritics
3. **Lowercase**
4. **Collapse whitespace** → single hyphen `-`
5. **Remove** any character not in `[a-z0-9-]`
6. **Collapse** consecutive hyphens
7. **Trim** leading/trailing hyphens

### Special character treatment

| Category | Treatment | Example |
|----------|-----------|---------|
| Diacritics (é, ñ, ü) | Transliterated via NFD | é → e |
| German ß | Stripped (does not decompose via NFD) | Straße → strae |
| Emojis (🌀, 🧾) | Stripped | 🌀 → (empty) |
| Symbols (#, §, @, _) | Stripped | ## → (empty) |
| Control characters | Stripped | |
| CJK / non-Latin | Stripped | |
| Ligatures (ﬁ) | Decomposed via NFKC | ﬁ → fi |
| Fractions (½) | Decomposed via NFKC, / stripped | ½ → 12 |

### Collision policy

- Two distinct nodes may produce the same `base_slug`
- Resolution: append `-<first 8 hex chars of id>` as suffix
- This does NOT create circular dependency because `id` is computed from `key`, not from slug
- Collision resolution is applied at batch level, after individual identity computation

---

## `version_id` — Content Version Hash

### Algorithm

```
sha256:<hex> of CanonicalJSON(normative shape)
```

### Normative shape

Only material fields, with `version_id` excluded (zero-field policy from S30):

```json
{
  "created": "<created or null>",
  "key": "<key>",
  "modified": "<modified or null>",
  "text": "<text or null>",
  "title": "<title>"
}
```

### Excluded fields

| Field | Reason |
|-------|--------|
| `version_id` | Self-referential (zero-field policy) |
| `id` | Derived from key, not material content |
| `canonical_slug` | Derived from title, not material content |
| `schema_version` | Emission metadata |
| `source_position` | Extraction/logging metadata |

### Sensitivity

- Content change → version_id changes
- Title change → version_id changes
- Timestamp change → version_id changes
- Key change → version_id changes

---

## Centralization

All identity logic is in `go/canon/identity.go`:

- `BuildNodeIdentity(e *CanonEntry) error` — single entry point
- `ComputeNodeUUID(key string) (string, error)` — id computation
- `CanonicalSlugOf(title string) string` — slug computation
- `ComputeVersionID(e CanonEntry) (string, error)` — version hash
- `ResolveSlugCollision(baseSlug, nodeID string) string` — collision suffix

---

## Dependencies

- `golang.org/x/text v0.36.0` — NFKC/NFD Unicode normalization (quasi-stdlib, Go team maintained)
- No other external dependencies introduced

---

## References

- S30 — UUIDv5 recipe, Canonical JSON, zero-field checksum policy
- S29 — Fold order and checksum truth pins
- S13 §B — Identidad canónica mínima
- Informe Técnico — id block, UUID v5 rule
