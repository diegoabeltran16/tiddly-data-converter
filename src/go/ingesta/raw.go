// Package ingesta implements the semantic transformation bridge between
// the raw validated artifact (produced by the Doctor) and a pre-canonical
// internal model suitable for later canonization.
//
// Contract reference: contratos/m01-s05-ingesta-contract.md
package ingesta

// RawTiddler represents a single tiddler as extracted and validated by
// the Rust pipeline (Extractor + Doctor). This is the input shape that
// the Ingesta receives via raw.tiddlers.json.
//
// Ref: S05 §4 — Entrada recibida.
type RawTiddler struct {
	Title          string            `json:"title"`
	RawFields      map[string]string `json:"raw_fields"`
	RawText        *string           `json:"raw_text"`
	SourcePosition *string           `json:"source_position"`
}

// OriginFormat indicates the source format from which the tiddlers were
// extracted. This metadata is provided at invocation time, not inferred.
type OriginFormat string

const (
	OriginHTML OriginFormat = "html"
	OriginJSON OriginFormat = "json"
)
