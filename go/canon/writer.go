package canon

import (
	"encoding/json"
	"fmt"
	"io"
)

// WriteResult holds observable counters from a JSONL emission pass.
//
// S19 enrichment: Skipped now counts all entries rejected by the schema v0
// validation gate (ValidateEntryV0), not just empty-key entries.
// ValidationErrors provides contextual messages for each rejected entry.
//
// Ref: S16 §D — evidencia observable de emisión.
// Ref: S19 — compuerta activa de validación antes de emisión.
type WriteResult struct {
	// Written is the number of CanonEntry lines emitted.
	Written int `json:"written"`
	// Skipped is the number of entries rejected by the validation gate.
	// Since S19, this counts all entries failing ValidateEntryV0
	// (empty key, empty title, wrong schema_version).
	Skipped int `json:"skipped"`
	// ValidationErrors contains contextual messages for each rejected entry.
	// Each message identifies the entry and the specific validation failure.
	//
	// Ref: S19 — observabilidad mínima de la compuerta.
	ValidationErrors []string `json:"validation_errors,omitempty"`
}

// Summary returns a one-line human-readable summary of the write pass.
func (r WriteResult) Summary() string {
	if len(r.ValidationErrors) == 0 {
		return fmt.Sprintf("written=%d skipped=%d", r.Written, r.Skipped)
	}
	return fmt.Sprintf("written=%d skipped=%d validation_errors=%d",
		r.Written, r.Skipped, len(r.ValidationErrors))
}

// WriteJSONL serializes a batch of CanonEntry values as JSONL
// (one JSON object per line, no trailing comma, newline-delimited).
//
// Each emitted line carries the schema v0 shape (S18):
//
//	{"schema_version":"v0","key":"…","title":"…","text":"…","source_position":"…","created":"…","modified":"…"}
//
// S19 gate: every entry is validated against ValidateEntryV0 BEFORE emission.
// Entries that fail validation are rejected (never written), counted in
// WriteResult.Skipped, and their validation error is recorded in
// WriteResult.ValidationErrors for observability.
//
// The writer stamps schema_version = SchemaV0 on every emitted line.
//
// The writer does NOT add fields beyond the declared schema v0 shape.
// UUID v5 identity, primary_role, provenance, and meta blocks are deferred.
//
// Ref: S13 §B — CanonEntry shape.
// Ref: S16 §A — writer mínimo de canon.jsonl.
// Ref: S17 — shape enriched with created/modified.
// Ref: S18 — schema v0 explícito; writer stamps schema_version.
// Ref: S19 — compuerta activa de validación antes de emisión.
func WriteJSONL(w io.Writer, entries []CanonEntry) (WriteResult, error) {
	var result WriteResult
	for i, e := range entries {
		// S19 gate: validate against schema v0 before emission.
		if err := ValidateEntryV0(e); err != nil {
			result.Skipped++
			result.ValidationErrors = append(result.ValidationErrors,
				fmt.Sprintf("entry[%d] title=%q: %v", i, e.Title, err))
			continue
		}
		// Stamp schema version on the copy (range var is already a copy).
		e.SchemaVersion = SchemaV0
		line, err := json.Marshal(e)
		if err != nil {
			return result, fmt.Errorf("canon: marshal entry %q: %w", e.Title, err)
		}
		if _, err := w.Write(line); err != nil {
			return result, fmt.Errorf("canon: write entry %q: %w", e.Title, err)
		}
		if _, err := w.Write([]byte("\n")); err != nil {
			return result, fmt.Errorf("canon: write newline after %q: %w", e.Title, err)
		}
		result.Written++
	}
	return result, nil
}
