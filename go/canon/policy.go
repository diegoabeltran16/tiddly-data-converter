// Package canon — policy.go
//
// S39 — canon-executable-policy-and-reverse-readiness-v0
//
// Defines the machine-readable policy for the canonical JSONL export.
// The policy declares which fields are required, editable, derived,
// allowed at top level, and required for reverse readiness.
//
// The policy is the single source of governance rules for any automated
// validation, normalization, or reverse-preflight check on canon JSONL.
//
// Ref: S39 §10.1 — executable policy bundle.
// Ref: S38 — export contract hardening.
// Ref: contratos/policy/canon_policy_bundle.json — machine-readable policy.
package canon

// CanonPolicy holds the machine-readable governance rules for canon JSONL.
type CanonPolicy struct {
	RequiredFields       []string `json:"required_fields"`
	DerivedFields        []string `json:"derived_fields"`
	EditableFields       []string `json:"editable_fields"`
	AllowedTopLevel      []string `json:"allowed_top_level_fields"`
	ReverseRequired      []string `json:"reverse_required_fields"`
	ReverseOptional      []string `json:"reverse_optional_fields"`
	ReverseExcluded      []string `json:"reverse_excluded_fields"`
	SchemaVersion        string   `json:"schema_version"`
	CanonArtifactRole    string   `json:"canon_artifact_role"`
}

// DefaultCanonPolicy returns the canonical policy for schema v0.
//
// This policy is the Go-native equivalent of the JSON bundle at
// contratos/policy/canon_policy_bundle.json. It must stay in sync
// with that artifact.
//
// Ref: S39 §10.1 — policy bundle.
// Ref: S34–S38 — field provenance.
func DefaultCanonPolicy() CanonPolicy {
	return CanonPolicy{
		SchemaVersion:     SchemaV0,
		CanonArtifactRole: "canon_export",
		RequiredFields:    []string{"schema_version", "key", "title"},
		DerivedFields: []string{
			"id", "canonical_slug", "version_id",
			"content_type", "modality", "encoding", "is_binary", "is_reference_only",
			"role_primary", "roles_secondary", "tags", "taxonomy_path",
			"semantic_text", "raw_payload_ref", "asset_id", "mime_type",
			"document_id", "section_path", "order_in_document", "relations",
		},
		EditableFields: []string{
			"key", "title", "text", "created", "modified",
			"source_type", "source_position", "source_tags", "source_fields", "source_role",
		},
		AllowedTopLevel: []string{
			"schema_version", "id", "key", "title", "canonical_slug", "version_id",
			"content_type", "modality", "encoding", "is_binary", "is_reference_only",
			"role_primary", "roles_secondary", "tags", "taxonomy_path",
			"semantic_text", "raw_payload_ref", "asset_id", "mime_type",
			"document_id", "section_path", "order_in_document", "relations",
			"source_tags", "source_fields", "source_type", "source_position", "source_role",
			"text", "created", "modified",
		},
		ReverseRequired: []string{"title", "text", "created", "modified"},
		ReverseOptional: []string{"source_type", "source_tags"},
		ReverseExcluded: []string{
			"id", "canonical_slug", "version_id",
			"content_type", "modality", "encoding", "is_binary", "is_reference_only",
			"role_primary", "roles_secondary", "taxonomy_path",
			"semantic_text", "raw_payload_ref", "asset_id", "mime_type",
			"document_id", "section_path", "order_in_document", "relations",
			"source_fields", "source_role",
		},
	}
}

// IsAllowedField checks whether a JSON field name is permitted at the top level.
func (p CanonPolicy) IsAllowedField(field string) bool {
	for _, f := range p.AllowedTopLevel {
		if f == field {
			return true
		}
	}
	return false
}

// IsDerivedField checks whether a JSON field name is a derived field.
func (p CanonPolicy) IsDerivedField(field string) bool {
	for _, f := range p.DerivedFields {
		if f == field {
			return true
		}
	}
	return false
}
