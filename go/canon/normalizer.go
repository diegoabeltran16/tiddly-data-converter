// Package canon — normalizer.go
//
// # S39 — canon-executable-policy-and-reverse-readiness-v0
//
// Normalizes a candidate canonical JSONL by:
//   - Recalculating derived fields (id, canonical_slug, version_id).
//   - Applying the S38 semantic_text suppression policy.
//   - Recomputing S41 helper projections (content.plain, normalized_tags).
//   - Emitting deterministic JSONL output.
//   - Producing a normalization report.
//
// The normalizer is deterministic: running it twice on the same input
// produces identical output (idempotency).
//
// Ref: S39 §10.2 — normalizer.
// Ref: S39 §12.3 — normalize mode behavior.
package canon

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"strings"
)

// NormalizationAction describes what the normalizer did to a single line.
type NormalizationAction struct {
	Line    int      `json:"line"`
	Title   string   `json:"title"`
	Actions []string `json:"actions,omitempty"`
	Error   string   `json:"error,omitempty"`
}

// NormalizationReport holds the result of normalizing a canon JSONL file.
type NormalizationReport struct {
	LinesRead       int                   `json:"lines_read"`
	LinesNormalized int                   `json:"lines_normalized"`
	LinesRejected   int                   `json:"lines_rejected"`
	Actions         []NormalizationAction `json:"actions,omitempty"`
}

// OK returns true if no lines were rejected.
func (r NormalizationReport) OK() bool {
	return r.LinesRejected == 0
}

// NormalizeCanonJSONL reads a JSONL stream, normalizes each line by
// recalculating derived fields, and writes the normalized output.
//
// Normalize mode:
//   - Stamps schema_version = "v0".
//   - Recomputes id, canonical_slug, version_id from source fields.
//   - Suppresses semantic_text when it equals text (S38 policy).
//   - Rejects lines with missing required fields (key, title).
//   - Emits normalized JSONL to the writer.
//
// Ref: S39 §12.3 — normalize mode behavior.
func NormalizeCanonJSONL(r io.Reader, w io.Writer) NormalizationReport {
	report := NormalizationReport{}
	scanner := bufio.NewScanner(r)

	// Increase buffer for large lines.
	buf := make([]byte, 0, 1024*1024)
	scanner.Buffer(buf, 10*1024*1024)

	lineNum := 0
	for scanner.Scan() {
		lineNum++
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		report.LinesRead++

		entry, actions, err := normalizeLine([]byte(line))
		if err != "" {
			report.LinesRejected++
			report.Actions = append(report.Actions, NormalizationAction{
				Line:  lineNum,
				Error: err,
			})
			continue
		}

		// Write normalized entry.
		out, marshalErr := json.Marshal(entry)
		if marshalErr != nil {
			report.LinesRejected++
			report.Actions = append(report.Actions, NormalizationAction{
				Line:  lineNum,
				Title: entry.Title,
				Error: fmt.Sprintf("marshal error: %v", marshalErr),
			})
			continue
		}
		fmt.Fprintf(w, "%s\n", out)
		report.LinesNormalized++

		if len(actions) > 0 {
			report.Actions = append(report.Actions, NormalizationAction{
				Line:    lineNum,
				Title:   entry.Title,
				Actions: actions,
			})
		}
	}
	return report
}

// normalizeLine normalizes a single JSONL line. Returns the normalized entry,
// a list of actions taken, and an error string (empty if success).
func normalizeLine(data []byte) (CanonEntry, []string, string) {
	var entry CanonEntry
	if err := json.Unmarshal(data, &entry); err != nil {
		return CanonEntry{}, nil, fmt.Sprintf("invalid JSON: %v", err)
	}

	var actions []string

	// Check required fields.
	if entry.Title == "" {
		return CanonEntry{}, nil, "title is empty; cannot normalize"
	}
	if entry.Key == "" {
		entry.Key = KeyOf(entry.Title)
		actions = append(actions, "derived key from title")
	}

	// Stamp schema version.
	if entry.SchemaVersion != SchemaV0 {
		actions = append(actions, fmt.Sprintf("set schema_version from %q to %q", entry.SchemaVersion, SchemaV0))
		entry.SchemaVersion = SchemaV0
	}

	// Recompute identity fields.
	oldID := entry.ID
	oldSlug := entry.CanonicalSlug
	oldVID := entry.VersionID

	// Temporarily clear derived fields to compute them fresh.
	entry.ID = ""
	entry.CanonicalSlug = ""
	entry.VersionID = ""

	if err := BuildNodeIdentity(&entry); err != nil {
		return CanonEntry{}, nil, fmt.Sprintf("identity computation failed: %v", err)
	}

	if oldID != "" && oldID != entry.ID {
		actions = append(actions, fmt.Sprintf("corrected id from %q to %q", oldID, entry.ID))
	} else if oldID == "" {
		actions = append(actions, "computed id")
	}

	if oldSlug != "" && oldSlug != entry.CanonicalSlug {
		actions = append(actions, fmt.Sprintf("corrected canonical_slug from %q to %q", oldSlug, entry.CanonicalSlug))
	} else if oldSlug == "" {
		actions = append(actions, "computed canonical_slug")
	}

	if oldVID != "" && oldVID != entry.VersionID {
		actions = append(actions, fmt.Sprintf("corrected version_id from %q to %q", oldVID, entry.VersionID))
	} else if oldVID == "" {
		actions = append(actions, "computed version_id")
	}

	// Apply S38 semantic_text suppression: if semantic_text == text, null it.
	if entry.SemanticText != nil && entry.Text != nil && *entry.SemanticText == *entry.Text {
		entry.SemanticText = nil
		actions = append(actions, "suppressed redundant semantic_text (S38)")
	}

	oldPlain := ""
	if entry.Content != nil && entry.Content.Plain != nil {
		oldPlain = *entry.Content.Plain
	}
	oldNormalizedTags := append([]string(nil), entry.NormalizedTags...)

	ApplyDerivedProjections(&entry)

	newPlain := ""
	if entry.Content != nil && entry.Content.Plain != nil {
		newPlain = *entry.Content.Plain
	}
	if oldPlain != newPlain {
		actions = append(actions, "recomputed content.plain")
	}
	if !stringSliceEqual(oldNormalizedTags, entry.NormalizedTags) {
		actions = append(actions, "recomputed normalized_tags")
	}

	return entry, actions, ""
}

func stringSliceEqual(a []string, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}
