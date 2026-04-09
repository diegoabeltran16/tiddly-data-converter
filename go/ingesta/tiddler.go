package ingesta

import "time"

// Tiddler is the pre-canonical internal representation produced by
// the Ingesta. This shape is PROVISIONAL — the definitive canonical
// shape will be determined when the Canon JSONL contract exists.
//
// Ref: S05 §5 — Forma del modelo interno común (pre-canónico).
type Tiddler struct {
	// Title is the tiddler title (non-empty after ingestion).
	Title string `json:"title"`

	// Fields is a typed map of all raw_fields after basic semantic
	// interpretation. Fields not explicitly parsed remain as strings.
	Fields map[string]string `json:"fields"`

	// Text is the body content of the tiddler (may be nil).
	Text *string `json:"text,omitempty"`

	// SourcePosition preserves the extraction position from raw.
	SourcePosition *string `json:"source_position,omitempty"`

	// Tags are parsed from the raw "tags" field according to TW5
	// conventions: [[multi word tag]] singleTag.
	// Ref: S05 §9.2.
	Tags []string `json:"tags"`

	// Created is the parsed creation timestamp (nil if absent/malformed).
	// Ref: S05 §9.3.
	Created *time.Time `json:"created,omitempty"`

	// Modified is the parsed modification timestamp (nil if absent/malformed).
	// Ref: S05 §9.3.
	Modified *time.Time `json:"modified,omitempty"`

	// Type is the tiddler MIME type (nil if absent).
	// Ref: S05 §9.4.
	Type *string `json:"type,omitempty"`

	// OriginFormat records whether the source was HTML or JSON.
	OriginFormat OriginFormat `json:"origin_format"`
}
