// Package canon — identity.go
//
// # S34 — canon-node-structural-identity-v0
//
// Defines the structural identity of each node in the canonical JSONL export.
// Every exported line must expose five semantically separated identity fields:
//
//	id             — structural, immutable, deterministic UUID (UUIDv5)
//	key            — operational/human key for debugging and traceability
//	title          — visible name, preserved faithfully from source
//	canonical_slug — legible, normalized, reproducible slug
//	version_id     — content-sensitive version hash (sha256)
//
// These five fields must not collapse into each other.
//
// Dependencies on prior sessions (not reopened here):
//
//	S30 — UUIDv5 recipe (UUIDNamespaceURL, UUIDSpecVersionV1)
//	S30 — Canonical JSON policy
//	S30 — Zero-field checksum policy
//	S29 — Fold order and checksum truth pins
//
// Ref: S34 — canon-node-structural-identity-v0.
// Ref: S30 — UUIDv5 and canonical JSON.
// Ref: S13 §B — Identidad canónica mínima.
// Ref: docs/Informe_Tecnico_de_Tiddler (Esp).md — id block.
package canon

import (
	"crypto/sha256"
	"fmt"
	"regexp"
	"strings"
	"unicode"

	"golang.org/x/text/unicode/norm"
)

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

// CanonKey is the stable canonical identity key for a tiddler.
//
// In S13–S33 the key was derived directly from the title.
// S34 preserves this: key uses the title as the stable source anchor.
//
// Invariant: two CanonEntries with the same CanonKey represent the same
// canonical entity and MUST be examined for collision before admission.
//
// Ref: S13 §B — Identidad canónica mínima.
type CanonKey string

// CanonEntry is the canonical representation of a tiddler node.
//
// S34 enrichment: adds ID, CanonicalSlug, and VersionID to the shape
// defined in S18 (schema v0). These three new fields, together with
// the existing Key and Title, form the five-field structural identity.
//
// Ref: S13 §B — CanonEntry shape.
// Ref: S17 — created/modified enrichment.
// Ref: S18 — schema v0.
// Ref: S34 — structural identity layer.
type CanonEntry struct {
	// SchemaVersion identifies the schema that governs this entry's shape.
	// Set by the writer at emission time; not populated by upstream stages.
	//
	// Ref: S18 — schema v0 explícito.
	SchemaVersion string `json:"schema_version,omitempty"`

	// ID is the structural, immutable, deterministic identity of the node.
	// Computed as UUIDv5(UUIDNamespaceURL, CanonicalJSON(payload)) where
	// payload = {key, type:"tiddler_node", uuid_spec_version:"v1"}.
	// Does not depend on slug or version_id.
	//
	// Ref: S34 §13.1 — id definition.
	// Ref: S30 — UUIDv5 recipe.
	ID string `json:"id,omitempty"`

	// Key is the canonical identity key (derived from Title via KeyOf).
	Key CanonKey `json:"key"`

	// Title is the human-readable identifier, preserved from the raw tiddler.
	Title string `json:"title"`

	// CanonicalSlug is the legible, normalized, reproducible slug.
	// Computed by CanonicalSlugOf: NFKC → NFD strip diacritics → lowercase →
	// collapse whitespace → remove non-alphanumeric → trim hyphens.
	//
	// Ref: S34 §13.4 — canonical_slug definition.
	CanonicalSlug string `json:"canonical_slug,omitempty"`

	// VersionID identifies the specific exported version of this node.
	// Computed as sha256(CanonicalJSON(normative shape with version_id="")).
	// Sensitive to material content changes.
	//
	// Ref: S34 §13.5 — version_id definition.
	// Ref: S30 — Canonical JSON and zero-field policy.
	VersionID string `json:"version_id,omitempty"`

	// --- S35: Reading mode and typing fields ---

	// ContentType identifies the type of content the node carries.
	// Derived by BuildNodeReadingMode from source signals and structure.
	//
	// Ref: S35 §16.1 — content_type definition.
	ContentType string `json:"content_type,omitempty"`

	// Modality identifies the primary reading channel for the node.
	//
	// Ref: S35 §16.2 — modality definition.
	Modality string `json:"modality,omitempty"`

	// Encoding identifies how the payload is represented.
	//
	// Ref: S35 §16.3 — encoding definition.
	Encoding string `json:"encoding,omitempty"`

	// IsBinary indicates whether the content requires binary treatment.
	//
	// Ref: S35 §16.4 — is_binary definition.
	IsBinary bool `json:"is_binary"`

	// IsReferenceOnly indicates whether the node is a reference/pointer
	// rather than carrying its primary content directly.
	//
	// Ref: S35 §16.5 — is_reference_only definition.
	IsReferenceOnly bool `json:"is_reference_only"`

	// --- S36: Semantic function and asset separation fields ---

	// RolePrimary is the canonical semantic function of the node.
	// Drawn from a controlled vocabulary: concept, procedure, evidence,
	// definition, glossary, policy, log, asset, config, code, narrative,
	// note, warning, unclassified.
	//
	// Ref: S36 §10 — role_primary definition.
	RolePrimary string `json:"role_primary,omitempty"`

	// RolesSecondary preserves additional explicit roles, semantic terms,
	// or specific labels that do not fit as role_primary.
	//
	// Ref: S36 §10 — roles_secondary preservation.
	RolesSecondary []string `json:"roles_secondary,omitempty"`

	// Tags is the normalized, deduplicated union of internal declared tags
	// and native TiddlyWiki tags. Internal tags appear first, then native
	// tags that are not already present.
	//
	// Ref: S36 §11 — tag merge policy.
	Tags []string `json:"tags,omitempty"`

	// TaxonomyPath is a conservative, stable taxonomy path derived
	// from declared tags. Empty when evidence is insufficient.
	//
	// Ref: S36 §12 — taxonomy_path policy.
	TaxonomyPath []string `json:"taxonomy_path,omitempty"`

	// SemanticText is the text content useful for semantic reading,
	// retrieval, or reasoning. Nil when:
	//   - binary or reference-only nodes (no semantic text available)
	//   - textual nodes where semantic_text == text (suppressed to avoid duplication)
	// Populated only when a distinct semantic transformation exists.
	//
	// Ref: S36 §13 — semantic_text policy.
	// Ref: S38 §9.1 — semantic_text nullable when redundant.
	SemanticText *string `json:"semantic_text"`

	// RawPayloadRef is a traceable, deterministic, non-interpretive
	// reference to the raw payload or its logical location.
	//
	// Ref: S36 §13 — raw_payload_ref definition.
	RawPayloadRef string `json:"raw_payload_ref,omitempty"`

	// AssetID is emitted only when a distinguishable asset exists
	// separate from the semantic text. Not emitted for purely textual nodes.
	//
	// Ref: S36 §13 — asset_id policy.
	AssetID string `json:"asset_id,omitempty"`

	// MimeType is the MIME type of the node, derived preferentially from
	// content_type, then from metadata, then from conservative mapping.
	// Explicitly supports text/vnd.tiddlywiki.
	//
	// Ref: S36 §13 — mime_type policy.
	MimeType string `json:"mime_type,omitempty"`

	// --- S37: Document context and explicit relations fields ---

	// DocumentID is the canonical deterministic identity of the source
	// document from which this node was exported.
	//
	// Ref: S37 §10.1 — document_id definition.
	DocumentID string `json:"document_id,omitempty"`

	// SectionPath is the conservative structural route where this node
	// lives inside its source document, ordered from general to specific.
	//
	// Ref: S37 §10.2 — section_path definition.
	SectionPath []string `json:"section_path"`

	// OrderInDocument is the stable 0-based source order of the node.
	//
	// Ref: S37 §10.3 — order_in_document definition.
	OrderInDocument int `json:"order_in_document"`

	// Relations contains explicit resolvable relations from this node to
	// other nodes in the same export corpus.
	//
	// Ref: S37 §10.4 — relations definition.
	Relations []NodeRelation `json:"relations"`

	// --- S36: Source semantic fields (input from TiddlyWiki) ---

	// SourceTags carries the raw TiddlyWiki tags from the source tiddler.
	// Used by the semantic detector to merge with internal tags.
	// This field is NOT part of the normative shape for version_id.
	//
	// Ref: S36 §11 — native TiddlyWiki tags.
	SourceTags []string `json:"source_tags,omitempty"`

	// SourceFields carries raw source fields preserved from Ingesta.
	// Used by S37 to read explicit document context hints (e.g. document_key
	// or section_path) without inventing metadata.
	//
	// This field is NOT part of the normative shape for version_id.
	SourceFields map[string]string `json:"source_fields,omitempty"`

	// SourceRole carries explicit role declarations from the source tiddler
	// (e.g., from structured JSON fields inside the tiddler content).
	// Used by the semantic detector for precedence-based role resolution.
	// This field is NOT part of the normative shape for version_id.
	//
	// Ref: S36 §9 — precedence hierarchy.
	SourceRole *string `json:"source_role,omitempty"`

	// --- Content and source fields ---

	// Text is the body content of the tiddler (nil if absent).
	Text *string `json:"text,omitempty"`

	// SourceType carries the raw tiddler "type" field from the source,
	// used by the reading mode detector to derive content_type.
	// This field is NOT part of the normative shape for version_id.
	//
	// Ref: S35 §17.2 — explicit source signal priority.
	SourceType *string `json:"source_type,omitempty"`

	// SourcePosition traces back to the extraction origin for auditability.
	SourcePosition *string `json:"source_position,omitempty"`

	// Created is the tiddler creation timestamp in TW5 format (YYYYMMDDHHmmssSSS).
	// Nil when absent in the source. Carried from Ingesta without transformation.
	//
	// Ref: S09 — ingesta timestamp preservation policy.
	// Ref: S17 — shape enrichment with created/modified.
	Created *string `json:"created,omitempty"`

	// Modified is the tiddler modification timestamp in TW5 format (YYYYMMDDHHmmssSSS).
	// Nil when absent in the source. Carried from Ingesta without transformation.
	//
	// Ref: S09 — ingesta timestamp preservation policy.
	// Ref: S17 — shape enrichment with created/modified.
	Modified *string `json:"modified,omitempty"`
}

// ---------------------------------------------------------------------------
// Key derivation (preserved from S13)
// ---------------------------------------------------------------------------

// KeyOf derives the canonical key from a tiddler title.
//
// The title is used as-is as the stable source anchor for identity.
// This is the primary stable identifier from the pre-canonical Ingesta output.
//
// Ref: S13 §B — identity key derivation.
// Ref: S34 §13.2 — key uses source.key (= title).
func KeyOf(title string) CanonKey {
	return CanonKey(title)
}

// ---------------------------------------------------------------------------
// Canonical slug
// ---------------------------------------------------------------------------

// multiHyphenRe collapses runs of consecutive hyphens into one.
var multiHyphenRe = regexp.MustCompile(`-{2,}`)

// CanonicalSlugOf computes the canonical slug for a tiddler title.
//
// The function is pure and deterministic. Steps:
//  1. NFKC normalization (compatibility decomposition + canonical composition)
//  2. NFD decomposition → strip combining marks (removes diacritics)
//  3. Lowercase
//  4. Replace whitespace runs with single hyphen
//  5. Remove any character that is not [a-z0-9-]
//  6. Collapse consecutive hyphens
//  7. Trim leading/trailing hyphens
//
// Treatment of special characters:
//   - Diacritics (é, ñ, ü, etc.): transliterated to ASCII via NFD decomposition
//   - Emojis: stripped (no ASCII equivalent)
//   - Symbols (#, §, @, etc.): stripped
//   - Control characters: stripped
//   - CJK/non-Latin: stripped (no transliteration)
//
// Ref: S34 §14.3 — canonical slug rules.
func CanonicalSlugOf(title string) string {
	// Step 1: NFKC normalization (e.g., ﬁ → fi, ½ → 1/2).
	s := norm.NFKC.String(title)

	// Step 2: NFD decomposition + strip combining marks.
	// This converts é → e + combining-accent, then we strip the accent.
	s = stripDiacritics(s)

	// Step 3: Lowercase.
	s = strings.ToLower(s)

	// Step 4: Replace any whitespace character(s) with a single hyphen.
	var b strings.Builder
	b.Grow(len(s))
	inSpace := false
	for _, r := range s {
		if unicode.IsSpace(r) {
			if !inSpace {
				b.WriteByte('-')
				inSpace = true
			}
			continue
		}
		inSpace = false
		b.WriteRune(r)
	}
	s = b.String()

	// Step 5: Remove anything that is not [a-z0-9-].
	var cleaned strings.Builder
	cleaned.Grow(len(s))
	for _, r := range s {
		if (r >= 'a' && r <= 'z') || (r >= '0' && r <= '9') || r == '-' {
			cleaned.WriteRune(r)
		}
	}
	s = cleaned.String()

	// Step 6: Collapse consecutive hyphens.
	s = multiHyphenRe.ReplaceAllString(s, "-")

	// Step 7: Trim leading/trailing hyphens.
	s = strings.Trim(s, "-")

	return s
}

// stripDiacritics removes combining marks from NFD-decomposed text.
// This effectively transliterates accented characters to their base form
// (e.g., é → e, ñ → n, ü → u).
func stripDiacritics(s string) string {
	// NFD decompose: é → e + U+0301 (combining acute accent)
	decomposed := norm.NFD.String(s)

	var b strings.Builder
	b.Grow(len(decomposed))
	for _, r := range decomposed {
		// Skip combining marks (Unicode category Mn = Mark, Nonspacing).
		if !unicode.Is(unicode.Mn, r) {
			b.WriteRune(r)
		}
	}
	return b.String()
}

// ---------------------------------------------------------------------------
// Node UUID (id)
// ---------------------------------------------------------------------------

// NodeUUIDPayload builds the canonical payload for computing a tiddler node's
// structural UUID. The payload is deterministic: same key → same UUID.
//
// Payload keys (sorted in canonical JSON):
//
//	key, type, uuid_spec_version
//
// The key is the stable source anchor (title). The id does NOT depend on
// the canonical_slug or version_id, avoiding circular dependencies.
//
// Ref: S34 §14.1 — id computation rule.
// Ref: S30 — UUIDv5 payload pattern.
func NodeUUIDPayload(key string) map[string]interface{} {
	return map[string]interface{}{
		"type":              "tiddler_node",
		"uuid_spec_version": UUIDSpecVersionV1,
		"key":               key,
	}
}

// ComputeNodeUUID computes the deterministic UUIDv5 for a tiddler node.
//
// The UUID is computed as:
//
//	UUIDv5(UUIDNamespaceURL, CanonicalJSON({key, type:"tiddler_node", uuid_spec_version:"v1"}))
//
// The id depends only on the source key (title), not on slug or version_id.
//
// Ref: S34 §14.1 — id computation.
// Ref: S30 — UUIDv5(UUIDNamespaceURL, CanonicalJSON(payload)).
func ComputeNodeUUID(key string) (string, error) {
	payload := NodeUUIDPayload(key)
	name, err := CanonicalJSON(payload)
	if err != nil {
		return "", fmt.Errorf("node uuid: canonical payload: %w", err)
	}
	return UUIDv5(UUIDNamespaceURL, name), nil
}

// ---------------------------------------------------------------------------
// Version ID
// ---------------------------------------------------------------------------

// versionIDNormativeShape builds the normative shape used for version_id
// computation. Only material fields are included; version_id itself is
// excluded (zero-field policy from S30).
//
// Normative shape fields (sorted by canonical JSON):
//
//	created, key, modified, text, title
//
// Excluded fields:
//
//	version_id      — self-referential (zero-field policy)
//	id              — derived from key, not material content
//	canonical_slug  — derived from title, not material content
//	schema_version  — emission metadata, not node content
//	source_position — extraction metadata, not node content
//	source_type     — extraction metadata, not node content
//	source_fields   — extraction metadata, not node content
//	content_type    — S35: derived from source_type + structure
//	modality        — S35: derived from content_type
//	encoding        — S35: derived from content_type
//	is_binary       — S35: derived from content_type + encoding
//	is_reference_only — S35: derived from content_type + structure
//	document_id     — S37: derived from source metadata
//	section_path    — S37: derived from source signals
//	order_in_document — S37: export position metadata
//	relations       — S37: explicit resolvable links, not node material
//
// Ref: S34 §14.5 — version_id normative shape.
// Ref: S35 — reading mode fields are derived, not material.
// Ref: S30 — zero-field checksum policy.
func versionIDNormativeShape(e CanonEntry) map[string]interface{} {
	shape := map[string]interface{}{
		"key":   string(e.Key),
		"title": e.Title,
	}
	if e.Text != nil {
		shape["text"] = *e.Text
	} else {
		shape["text"] = nil
	}
	if e.Created != nil {
		shape["created"] = *e.Created
	} else {
		shape["created"] = nil
	}
	if e.Modified != nil {
		shape["modified"] = *e.Modified
	} else {
		shape["modified"] = nil
	}
	return shape
}

// ComputeVersionID computes the version identifier for a CanonEntry.
//
// The version_id is computed as:
//
//	sha256:<hex> of CanonicalJSON(normative shape)
//
// where the normative shape includes only material fields (key, title,
// text, created, modified) and excludes version_id itself (zero-field
// policy), id, canonical_slug, schema_version, and source_position.
//
// Ref: S34 §14.5 — version_id computation.
// Ref: S30 — Canonical JSON + zero-field policy.
func ComputeVersionID(e CanonEntry) (string, error) {
	shape := versionIDNormativeShape(e)
	canonical, err := CanonicalJSON(shape)
	if err != nil {
		return "", fmt.Errorf("version_id: canonical shape: %w", err)
	}
	h := sha256.Sum256(canonical)
	return fmt.Sprintf("sha256:%x", h[:]), nil
}

// ---------------------------------------------------------------------------
// Slug collision resolution
// ---------------------------------------------------------------------------

// ResolveSlugCollision appends a disambiguating suffix to a base slug
// when two distinct nodes produce the same canonical_slug.
//
// The suffix is derived from the node's id (first 8 characters), which
// is already computed before slug collision resolution and does NOT
// depend on the slug itself, avoiding circular dependencies.
//
// Format: <base_slug>-<first 8 chars of id>
//
// Ref: S34 §14.4 — slug collision policy.
func ResolveSlugCollision(baseSlug string, nodeID string) string {
	suffix := nodeID
	// Strip any prefix like "urn:uuid:" if present, and take first 8 hex chars.
	if idx := strings.LastIndex(suffix, ":"); idx >= 0 {
		suffix = suffix[idx+1:]
	}
	// Remove hyphens from UUID for compact suffix.
	suffix = strings.ReplaceAll(suffix, "-", "")
	if len(suffix) > 8 {
		suffix = suffix[:8]
	}
	if suffix == "" {
		return baseSlug
	}
	return baseSlug + "-" + suffix
}

// ---------------------------------------------------------------------------
// BuildNodeIdentity — single entry point
// ---------------------------------------------------------------------------

// BuildNodeIdentity computes and populates all five structural identity
// fields on a CanonEntry: id, key, title, canonical_slug, version_id.
//
// Preconditions:
//   - e.Title must be non-empty (it is the source anchor for identity).
//   - e.Key should be set by KeyOf(title) before calling; if empty,
//     BuildNodeIdentity derives it from Title.
//
// The function does NOT resolve slug collisions — that requires batch
// context. Use ResolveSlugCollision after detecting collisions across
// a batch.
//
// Ref: S34 §14 — identity computation rules.
func BuildNodeIdentity(e *CanonEntry) error {
	if e.Title == "" {
		return fmt.Errorf("identity: title is empty; cannot derive identity")
	}

	// Key: use existing or derive from title.
	if e.Key == "" {
		e.Key = KeyOf(e.Title)
	}

	// ID: UUIDv5 from key.
	id, err := ComputeNodeUUID(string(e.Key))
	if err != nil {
		return fmt.Errorf("identity: compute id: %w", err)
	}
	e.ID = id

	// Canonical slug: from title.
	e.CanonicalSlug = CanonicalSlugOf(e.Title)

	// Version ID: from normative shape.
	vid, err := ComputeVersionID(*e)
	if err != nil {
		return fmt.Errorf("identity: compute version_id: %w", err)
	}
	e.VersionID = vid

	return nil
}
