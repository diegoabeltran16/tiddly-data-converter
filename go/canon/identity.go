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
// Schema v0 (S18): the shape is now explicitly declared and validated.
// See SchemaV0 constant and ValidateEntryV0 for the formal contract.
//
// The definitive Canon JSONL schema (including UUID v5, primary_role,
// relations, provenance, meta blocks) is deferred to future sessions.
//
// S17 enrichment: Created and Modified are now carried from Ingesta when
// available, as optional timestamp strings in TW5 format (YYYYMMDDHHmmssSSS).
//
// Ref: S13 §B — Identidad canónica mínima.
// Ref: S17 — admisión canónica mínima v0 (created/modified enrichment).
// Ref: S18 — schema v0 explícito para canon.jsonl.
// Ref: docs/Informe_Tecnico_de_Tiddler (Esp).md — estructura mínima del nodo.
type CanonEntry struct {
	// SchemaVersion identifies the schema that governs this entry's shape.
	// Set by the writer at emission time; not populated by upstream stages.
	//
	// Ref: S18 — schema v0 explícito.
	SchemaVersion string `json:"schema_version,omitempty"`

	// Key is the canonical identity key (derived from Title via KeyOf).
	Key CanonKey `json:"key"`

	// Title is the human-readable identifier, preserved from the raw tiddler.
	Title string `json:"title"`

	// Text is the body content of the tiddler (nil if absent).
	Text *string `json:"text,omitempty"`

	// SourcePosition traces back to the extraction origin for auditability.
	SourcePosition *string `json:"source_position,omitempty"`

	// Created is the tiddler creation timestamp in TW5 format (YYYYMMDDHHmmssSSS).
	// Nil when absent in the source. Carried from Ingesta without transformation.
	//
	// PROVISIONAL (S17): enriches the minimal shape without defining canonical
	// timestamp policy. The timestamp remains pre-canonical metadata.
	// Ref: S09 — ingesta timestamp preservation policy.
	// Ref: S17 — shape enrichment with created/modified.
	Created *string `json:"created,omitempty"`

	// Modified is the tiddler modification timestamp in TW5 format (YYYYMMDDHHmmssSSS).
	// Nil when absent in the source. Carried from Ingesta without transformation.
	//
	// PROVISIONAL (S17): enriches the minimal shape without defining canonical
	// timestamp policy. The timestamp remains pre-canonical metadata.
	// Ref: S09 — ingesta timestamp preservation policy.
	// Ref: S17 — shape enrichment with created/modified.
	Modified *string `json:"modified,omitempty"`
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
