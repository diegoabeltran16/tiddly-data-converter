package canon

import (
	"encoding/json"
	"fmt"
	"io"
)

// WriteResult holds observable counters from a JSONL emission pass.
//
// This shape is PROVISIONAL for S16. It reports the minimum auditable
// evidence that a canon.jsonl emission occurred.
//
// Ref: S16 §D — evidencia observable de emisión.
type WriteResult struct {
	// Written is the number of CanonEntry lines emitted.
	Written int `json:"written"`
	// Skipped is the number of entries skipped (e.g. empty key).
	Skipped int `json:"skipped"`
}

// Summary returns a one-line human-readable summary of the write pass.
func (r WriteResult) Summary() string {
	return fmt.Sprintf("written=%d skipped=%d", r.Written, r.Skipped)
}

// WriteJSONL serializes a batch of CanonEntry values as JSONL
// (one JSON object per line, no trailing comma, newline-delimited).
//
// Each line has the CanonEntry shape including optional timestamps:
//
//	{"key":"…","title":"…","text":"…","source_position":"…","created":"…","modified":"…"}
//
// Entries with an empty Key are skipped and counted in WriteResult.Skipped.
// The writer does NOT add fields beyond the current CanonEntry shape.
//
// PROVISIONAL: This is the bootstrap emission. The shape will evolve when
// UUID v5 identity, primary_role, provenance, and meta blocks are formalized
// in the Canon JSONL contract.
//
// Ref: S13 §B — CanonEntry shape.
// Ref: S16 §A — writer mínimo de canon.jsonl.
// Ref: S17 — shape enriched with created/modified.
func WriteJSONL(w io.Writer, entries []CanonEntry) (WriteResult, error) {
	var result WriteResult
	for _, e := range entries {
		if e.Key == "" {
			result.Skipped++
			continue
		}
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
