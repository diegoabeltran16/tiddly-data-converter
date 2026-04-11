package canon

// CanonKey is the stable canonical identity key for a tiddler.
//
// In the S13 bootstrap the key is derived directly from the normalized title,
// which is the primary stable identifier available from the pre-canonical
// Ingesta output. A deterministic UUID v5 (urn:uuid:<hex>) derived from
// (title, schema_version) will replace this in the full Canon JSONL contract.
//
// Invariant: two CanonEntries with the same CanonKey represent the same
// canonical entity and MUST be examined for collision before admission.
//
// Ref: S13 §B — Identidad canónica mínima.
// Ref: docs/Technical_Report_Tiddler_Sys_(Eng).md — id block (UUID v5 rule).
type CanonKey string

// CanonEntry is the minimal canonical representation of a tiddler at the
// Canon boundary, as it arrives from the pre-canonical Ingesta layer.
//
// This shape is PROVISIONAL for S13. The definitive Canon JSONL schema
// (including UUID v5, primary_role, relations, provenance, meta blocks)
// is defined when the Canon JSONL contract is formalized.
//
// Ref: S13 §B — Identidad canónica mínima.
// Ref: docs/Informe_Tecnico_de_Tiddler (Esp).md — estructura mínima del nodo.
type CanonEntry struct {
	// Key is the canonical identity key (derived from Title via KeyOf).
	Key CanonKey `json:"key"`

	// Title is the human-readable identifier, preserved from the raw tiddler.
	Title string `json:"title"`

	// Text is the body content of the tiddler (nil if absent).
	Text *string `json:"text,omitempty"`

	// SourcePosition traces back to the extraction origin for auditability.
	SourcePosition *string `json:"source_position,omitempty"`
}

// KeyOf derives the canonical key from a tiddler title.
//
// In S13 this is a direct mapping: the title is used as-is.
// No normalization (case folding, whitespace collapse) is applied yet —
// that policy is deferred to the Canon JSONL contract formalization.
//
// Provisional: exact normalization rules depend on the full Canon schema.
// Ref: S13 §B — identity key derivation.
func KeyOf(title string) CanonKey {
	return CanonKey(title)
}
