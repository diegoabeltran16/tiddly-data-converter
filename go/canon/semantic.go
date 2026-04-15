// Package canon — semantic.go
//
// S36 — canon-semantic-function-and-asset-separation-v0
//
// Defines the semantic function layer and asset separation for each node
// in the canonical JSONL export. Every exported line may expose up to
// eight semantic fields:
//
//   role_primary     — canonical semantic function of the node
//   roles_secondary  — preserved additional roles and labels
//   tags             — merged, deduplicated union of internal + native tags
//   taxonomy_path    — conservative taxonomy path from declared tags
//   semantic_text    — text useful for AI reading / retrieval
//   raw_payload_ref  — traceable reference to the raw payload
//   asset_id         — emitted only when a real asset exists
//   mime_type        — MIME type from content_type or conservative mapping
//
// Design principles (S36 §9 — anti-invention policy):
//   - Extraction and preservation over inference
//   - Explicit roles take precedence over inferred roles
//   - Tags merge without loss: internal first, then native
//   - semantic_text never invents content
//   - asset_id not emitted for purely textual nodes
//   - Equations in text stay in semantic_text, not treated as assets
//
// Precedence hierarchy for semantic derivation (S36 §9):
//   1. Explicit roles/signals declared within the tiddler
//   2. Internal declared tags within the content or metadata
//   3. Native TiddlyWiki tags
//   4. Known structural patterns (documented)
//   5. Conservative fallback
//
// Dependencies on prior sessions (not reopened here):
//   S34 — structural identity (id, key, title, canonical_slug, version_id)
//   S35 — reading mode (content_type, modality, encoding, is_binary, is_reference_only)
//   S30 — UUIDv5, Canonical JSON, zero-field checksum
//
// Ref: S36 — canon-semantic-function-and-asset-separation-v0.
package canon

import (
	"sort"
	"strings"
)

// ---------------------------------------------------------------------------
// Constants — controlled vocabulary for role_primary (S36 §10)
// ---------------------------------------------------------------------------

const (
	RoleConcept      = "concept"
	RoleProcedure    = "procedure"
	RoleEvidence     = "evidence"
	RoleDefinition   = "definition"
	RoleGlossary     = "glossary"
	RolePolicy       = "policy"
	RoleLog          = "log"
	RoleAsset        = "asset"
	RoleConfig       = "config"
	RoleCode         = "code"
	RoleNarrative    = "narrative"
	RoleNote         = "note"
	RoleWarning      = "warning"
	RoleUnclassified = "unclassified"
)

// validRolePrimary is the set of allowed role_primary values.
var validRolePrimary = map[string]bool{
	RoleConcept:      true,
	RoleProcedure:    true,
	RoleEvidence:     true,
	RoleDefinition:   true,
	RoleGlossary:     true,
	RolePolicy:       true,
	RoleLog:          true,
	RoleAsset:        true,
	RoleConfig:       true,
	RoleCode:         true,
	RoleNarrative:    true,
	RoleNote:         true,
	RoleWarning:      true,
	RoleUnclassified: true,
}

// ---------------------------------------------------------------------------
// Role mapping from explicit source roles to controlled vocabulary
// ---------------------------------------------------------------------------

// explicitRoleMapping maps known explicit role strings (lowercase) from
// tiddler metadata to the controlled vocabulary role_primary.
//
// This mapping preserves the semantic intent while normalizing to the
// canonical vocabulary. Roles not in this map are preserved in
// roles_secondary without mapping to role_primary.
//
// Ref: S36 §10 — normalization without loss.
var explicitRoleMapping = map[string]string{
	// Direct matches
	"concept":     RoleConcept,
	"procedure":   RoleProcedure,
	"evidence":    RoleEvidence,
	"definition":  RoleDefinition,
	"glossary":    RoleGlossary,
	"policy":      RolePolicy,
	"log":         RoleLog,
	"asset":       RoleAsset,
	"config":      RoleConfig,
	"code":        RoleCode,
	"narrative":   RoleNarrative,
	"note":        RoleNote,
	"warning":     RoleWarning,

	// Domain-specific mappings (S36 §10 — normalization)
	"sesión":        RoleLog,
	"sesion":        RoleLog,
	"hipótesis":     RoleEvidence,
	"hipotesis":     RoleEvidence,
	"procedencia":   RoleEvidence,
	"arquitectura":  RoleConcept,
	"documentación": RoleNarrative,
	"documentacion": RoleNarrative,
	"reporte":       RoleLog,
	"dato":          RoleEvidence,
	"evento":        RoleLog,
}

// ---------------------------------------------------------------------------
// Tag-based role inference (level 2–3 in precedence)
// ---------------------------------------------------------------------------

// tagRoleMapping maps specific tag patterns (lowercase) to role_primary.
// Used when no explicit role is present. Tags are checked in order of
// specificity.
//
// Ref: S36 §9 — precedence level 2 (internal tags) and level 3 (native tags).
var tagRoleMapping = map[string]string{
	"hipótesis":    RoleEvidence,
	"hipotesis":    RoleEvidence,
	"procedencia":  RoleEvidence,
	"sesión":       RoleLog,
	"sesion":       RoleLog,
	"glosario":     RoleGlossary,
	"glossary":     RoleGlossary,
	"definición":   RoleDefinition,
	"definicion":   RoleDefinition,
	"definition":   RoleDefinition,
	"política":     RolePolicy,
	"politica":     RolePolicy,
	"policy":       RolePolicy,
	"arquitectura": RoleConcept,
	"concepto":     RoleConcept,
	"concept":      RoleConcept,
	"código":       RoleCode,
	"codigo":       RoleCode,
	"code":         RoleCode,
	"config":       RoleConfig,
	"warning":      RoleWarning,
	"narrative":    RoleNarrative,
	"nota":         RoleNote,
	"note":         RoleNote,
	"asset":        RoleAsset,
	"procedure":    RoleProcedure,
	"procedimiento": RoleProcedure,
	"evidence":     RoleEvidence,
	"evidencia":    RoleEvidence,
	"log":          RoleLog,
}

// ---------------------------------------------------------------------------
// Semantics — the output struct
// ---------------------------------------------------------------------------

// Semantics holds all semantic function and asset separation fields
// for a canonical node.
//
// Ref: S36 §1 — semantic layer output.
type Semantics struct {
	RolePrimary   string   `json:"role_primary"`
	RolesSecondary []string `json:"roles_secondary"`
	Tags          []string `json:"tags"`
	TaxonomyPath  []string `json:"taxonomy_path"`
	SemanticText  string   `json:"semantic_text"`
	RawPayloadRef string   `json:"raw_payload_ref"`
	AssetID       string   `json:"asset_id"`
	MimeType      string   `json:"mime_type"`

	// Traceability fields for the export log (not emitted in JSONL).
	RoleSource       string `json:"role_source"`
	TaxonomySource   string `json:"taxonomy_source"`
	SemanticTextMode string `json:"semantic_text_mode"`
	MimeSource       string `json:"mime_source"`
	AssetMode        string `json:"asset_mode"`
}

// ---------------------------------------------------------------------------
// ResolvePrimaryRole — S36 §9 precedence hierarchy
// ---------------------------------------------------------------------------

// ResolvePrimaryRole determines the canonical role_primary for a node
// following the strict precedence hierarchy:
//   1. Explicit role declared in source (SourceRole field)
//   2. Internal declared tags
//   3. Native TiddlyWiki tags (SourceTags)
//   4. Structural patterns (content_type, modality)
//   5. Fallback: "unclassified"
//
// Returns the role and its source for traceability.
//
// Ref: S36 §9 — anti-invention policy and precedence.
// Ref: S36 §10 — role_primary vocabulary.
func ResolvePrimaryRole(e CanonEntry) (role string, source string) {
	// Level 1: explicit role from source.
	if e.SourceRole != nil && *e.SourceRole != "" {
		normalized := strings.TrimSpace(strings.ToLower(*e.SourceRole))
		if mapped, ok := explicitRoleMapping[normalized]; ok {
			return mapped, "explicit_role"
		}
		// If the explicit role is already in the controlled vocabulary, use it directly.
		if validRolePrimary[normalized] {
			return normalized, "explicit_role"
		}
		// Explicit role not in vocabulary — will be preserved in roles_secondary.
		// Fall through to tag-based inference.
	}

	// Level 2: internal declared tags (from SourceTags — first entries are internal).
	// Note: SourceTags carries native TiddlyWiki tags. For internal tags, we
	// look at tag patterns that map to roles.
	for _, tag := range e.SourceTags {
		normalized := strings.TrimSpace(strings.ToLower(tag))
		if mapped, ok := tagRoleMapping[normalized]; ok {
			return mapped, "declared_tags"
		}
	}

	// Level 3: native TiddlyWiki tags (same source, lower specificity).
	// Already checked in level 2 since SourceTags contains all native tags.

	// Level 4: structural patterns based on content_type and modality.
	if e.ContentType != "" {
		switch e.ContentType {
		case ContentTypeJSON:
			return RoleConfig, "structural_rule"
		case ContentTypePNG, ContentTypeJPEG, ContentTypeSVG:
			return RoleAsset, "structural_rule"
		case ContentTypeOctetStream:
			return RoleAsset, "structural_rule"
		}
	}
	if e.Modality == ModalityCode {
		return RoleCode, "structural_rule"
	}
	if e.Modality == ModalityImage {
		return RoleAsset, "structural_rule"
	}

	// Level 5: fallback.
	return RoleUnclassified, "fallback"
}

// ---------------------------------------------------------------------------
// ResolveSecondaryRoles — S36 §10
// ---------------------------------------------------------------------------

// ResolveSecondaryRoles preserves additional explicit roles and semantic
// terms that do not fit as role_primary.
//
// It collects:
//   - The original explicit role if it was not used as role_primary
//   - Any mapped role from tags that differs from role_primary
//
// The result is deduplicated and sorted for determinism.
//
// Ref: S36 §10 — roles_secondary preservation rule.
func ResolveSecondaryRoles(e CanonEntry, primaryRole string) []string {
	seen := make(map[string]bool)
	seen[primaryRole] = true // exclude primary from secondary
	var secondary []string

	// Preserve the original explicit role if it wasn't used as primary.
	if e.SourceRole != nil && *e.SourceRole != "" {
		normalized := strings.TrimSpace(strings.ToLower(*e.SourceRole))
		mapped, hasMapped := explicitRoleMapping[normalized]
		if hasMapped && mapped != primaryRole && !seen[mapped] {
			seen[mapped] = true
			secondary = append(secondary, mapped)
		}
		// Also preserve the original term if it differs from both primary and mapped.
		if normalized != primaryRole && !seen[normalized] {
			seen[normalized] = true
			secondary = append(secondary, normalized)
		}
	}

	// Collect role signals from tags that differ from primary.
	for _, tag := range e.SourceTags {
		normalized := strings.TrimSpace(strings.ToLower(tag))
		if mapped, ok := tagRoleMapping[normalized]; ok {
			if !seen[mapped] {
				seen[mapped] = true
				secondary = append(secondary, mapped)
			}
		}
	}

	sort.Strings(secondary)
	return secondary
}

// ---------------------------------------------------------------------------
// MergeSemanticTags — S36 §11
// ---------------------------------------------------------------------------

// MergeSemanticTags produces the normalized, deduplicated union of
// internal declared tags and native TiddlyWiki tags.
//
// Order: internal tags first (deterministic), then native tags that
// are not already present.
//
// The distinction between internal and native is preserved via ordering.
// Deduplication is case-insensitive for comparison but preserves the
// first occurrence's casing.
//
// Ref: S36 §11 — tag merge policy.
func MergeSemanticTags(sourceTags []string) []string {
	if len(sourceTags) == 0 {
		return nil
	}

	seen := make(map[string]bool)
	var merged []string

	for _, tag := range sourceTags {
		trimmed := strings.TrimSpace(tag)
		if trimmed == "" {
			continue
		}
		lower := strings.ToLower(trimmed)
		if !seen[lower] {
			seen[lower] = true
			merged = append(merged, trimmed)
		}
	}

	if len(merged) == 0 {
		return nil
	}
	return merged
}

// ---------------------------------------------------------------------------
// BuildTaxonomyPath — S36 §12
// ---------------------------------------------------------------------------

// BuildTaxonomyPath derives a conservative, stable taxonomy path from
// declared tags. Only tags that have a documented mapping are used.
//
// Returns an empty slice when evidence is insufficient.
//
// Ref: S36 §12 — taxonomy_path conservative derivation.
func BuildTaxonomyPath(tags []string) []string {
	if len(tags) == 0 {
		return nil
	}

	// Taxonomy segments are derived from tags that contain hierarchical
	// markers (🧱, 🌀, ##, ###, ####) or known structural prefixes.
	var segments []string
	seen := make(map[string]bool)

	for _, tag := range tags {
		trimmed := strings.TrimSpace(tag)
		if trimmed == "" {
			continue
		}

		// Extract meaningful taxonomy segment.
		segment := extractTaxonomySegment(trimmed)
		if segment != "" && !seen[segment] {
			seen[segment] = true
			segments = append(segments, segment)
		}
	}

	if len(segments) == 0 {
		return nil
	}
	return segments
}

// extractTaxonomySegment extracts a taxonomy segment from a tag.
// Returns empty string if the tag is not a taxonomy-relevant tag.
func extractTaxonomySegment(tag string) string {
	// Tags with markdown heading markers (##, ###, ####) are structural.
	if strings.HasPrefix(tag, "####") || strings.HasPrefix(tag, "###") || strings.HasPrefix(tag, "##") {
		// Strip the heading marker and emoji prefixes for a clean segment.
		segment := tag
		// Remove leading # characters
		segment = strings.TrimLeft(segment, "#")
		segment = strings.TrimSpace(segment)
		if segment != "" {
			return segment
		}
	}

	// Tags containing 🧱 are structural taxonomy markers.
	if strings.Contains(tag, "🧱") {
		return tag
	}

	// Tags containing 🌀 are session/evolution markers.
	if strings.Contains(tag, "🌀") {
		return tag
	}

	return ""
}

// ---------------------------------------------------------------------------
// ExtractSemanticText — S36 §13
// ---------------------------------------------------------------------------

// ExtractSemanticText extracts the text content useful for semantic
// reading, retrieval, or reasoning.
//
// Rules:
//   - For textual nodes (text/plain, text/markdown, text/vnd.tiddlywiki,
//     text/html, text/csv): return the full text content.
//   - For binary/reference-only nodes: return empty string.
//   - For JSON metadata: return the text if it's readable JSON.
//   - Equations embedded in text are preserved (S36 §14).
//   - Never invents content or produces summaries.
//
// Ref: S36 §13 — semantic_text policy.
// Ref: S36 §14 — equation preservation rule.
func ExtractSemanticText(e CanonEntry) (text string, mode string) {
	// Binary or reference-only nodes have no semantic text.
	if e.IsBinary {
		return "", "empty_for_binary"
	}
	if e.IsReferenceOnly {
		return "", "reference_only"
	}

	if e.Text == nil || *e.Text == "" {
		return "", "empty_for_binary"
	}

	// For textual content types, preserve the full text including equations.
	switch e.ContentType {
	case ContentTypePlain, ContentTypeMarkdown, ContentTypeTiddlyWiki,
		ContentTypeHTML, ContentTypeCSV, ContentTypeJSON, ContentTypeTiddler:
		return *e.Text, "direct_text"
	default:
		// If content_type is unknown but we have text and it's not binary,
		// preserve it conservatively.
		if e.ContentType == ContentTypeUnknown && e.Text != nil && *e.Text != "" {
			return *e.Text, "direct_text"
		}
		return "", "empty_for_binary"
	}
}

// ---------------------------------------------------------------------------
// BuildRawPayloadRef — S36 §13
// ---------------------------------------------------------------------------

// BuildRawPayloadRef builds a deterministic, auditable reference to the
// raw payload of the node.
//
// The reference format is: "node:<id>" where id is the structural UUID
// of the node (S34). This provides a stable, non-interpretive pointer
// back to the source payload.
//
// Ref: S36 §13 — raw_payload_ref definition.
func BuildRawPayloadRef(e CanonEntry) string {
	if e.ID == "" {
		return ""
	}
	return "node:" + e.ID
}

// ---------------------------------------------------------------------------
// ResolveMimeType — S36 §13
// ---------------------------------------------------------------------------

// ResolveMimeType determines the MIME type of the node following the
// priority:
//   1. content_type from S35 (already derived from explicit source)
//   2. Conservative mapping from structural signals
//   3. Empty string when evidence is insufficient
//
// Explicitly supports text/vnd.tiddlywiki as a valid MIME type.
//
// Ref: S36 §13 — mime_type policy.
func ResolveMimeType(e CanonEntry) (mimeType string, source string) {
	// Priority 1: content_type from S35.
	if e.ContentType != "" && e.ContentType != ContentTypeUnknown {
		return e.ContentType, "content_type"
	}

	// Priority 2: source_type if available.
	if e.SourceType != nil && *e.SourceType != "" {
		return *e.SourceType, "metadata"
	}

	// Priority 3: conservative mapping from modality.
	switch e.Modality {
	case ModalityText:
		return ContentTypePlain, "mapping"
	case ModalityImage:
		return ContentTypeOctetStream, "mapping"
	case ModalityBinary:
		return ContentTypeOctetStream, "mapping"
	}

	return "", "fallback"
}

// ---------------------------------------------------------------------------
// BuildAssetID — S36 §13
// ---------------------------------------------------------------------------

// BuildAssetID emits an asset identifier only when there is a real
// distinguishable asset separate from the semantic text.
//
// Asset conditions:
//   - Binary content (images, opaque data)
//   - Reference-only nodes that point to external resources
//   - Nodes where content_type indicates a non-textual asset
//
// Purely textual nodes do NOT receive an asset_id.
// Equations embedded in text are NOT treated as assets (S36 §14).
//
// The asset_id is derived from the node's structural UUID: "asset:<id>".
//
// Ref: S36 §13 — asset_id policy.
// Ref: S36 §14 — equation rule.
func BuildAssetID(e CanonEntry) (assetID string, mode string) {
	// Purely textual nodes: no asset_id.
	if !e.IsBinary && !e.IsReferenceOnly {
		switch e.ContentType {
		case ContentTypePlain, ContentTypeMarkdown, ContentTypeTiddlyWiki,
			ContentTypeHTML, ContentTypeCSV, ContentTypeJSON, ContentTypeTiddler,
			ContentTypeUnknown, "":
			return "", "none"
		}
	}

	// Binary or reference-only or non-textual content type: emit asset_id.
	if e.ID == "" {
		return "", "none"
	}

	if e.IsBinary {
		return "asset:" + e.ID, "derived"
	}
	if e.IsReferenceOnly {
		return "asset:" + e.ID, "reference_only"
	}

	// Non-textual content types (images as SVG, etc.)
	switch e.ContentType {
	case ContentTypePNG, ContentTypeJPEG, ContentTypeSVG, ContentTypeOctetStream:
		return "asset:" + e.ID, "derived"
	}

	return "", "none"
}

// ---------------------------------------------------------------------------
// BuildNodeSemantics — single entry point (S36 §15)
// ---------------------------------------------------------------------------

// BuildNodeSemantics computes all semantic function and asset separation
// fields for a CanonEntry. This is the central function that orchestrates
// all semantic resolution.
//
// Preconditions:
//   - Identity (S34) must be computed (e.ID non-empty).
//   - Reading mode (S35) must be computed (e.ContentType non-empty).
//
// The function does NOT modify the CanonEntry; it returns a Semantics struct.
// The caller is responsible for applying the semantics to the entry.
//
// Ref: S36 §15 — centralisation requirement.
func BuildNodeSemantics(e CanonEntry) Semantics {
	role, roleSource := ResolvePrimaryRole(e)
	secondary := ResolveSecondaryRoles(e, role)
	tags := MergeSemanticTags(e.SourceTags)
	taxonomy := BuildTaxonomyPath(tags)
	semText, semTextMode := ExtractSemanticText(e)
	payloadRef := BuildRawPayloadRef(e)
	mime, mimeSource := ResolveMimeType(e)
	assetID, assetMode := BuildAssetID(e)

	return Semantics{
		RolePrimary:    role,
		RolesSecondary: secondary,
		Tags:           tags,
		TaxonomyPath:   taxonomy,
		SemanticText:   semText,
		RawPayloadRef:  payloadRef,
		AssetID:        assetID,
		MimeType:       mime,

		// Traceability
		RoleSource:       roleSource,
		TaxonomySource:   deriveTaxonomySource(taxonomy, tags),
		SemanticTextMode: semTextMode,
		MimeSource:       mimeSource,
		AssetMode:        assetMode,
	}
}

// deriveTaxonomySource determines the source of the taxonomy path.
func deriveTaxonomySource(taxonomy []string, tags []string) string {
	if len(taxonomy) == 0 {
		if len(tags) > 0 {
			return "fallback"
		}
		return "fallback"
	}
	return "declared_tags"
}
