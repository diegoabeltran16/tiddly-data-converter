package ingesta

import (
	"encoding/json"
	"fmt"
	"os"
)

// Ingest reads the raw validated artifact at rawPath and transforms it
// into a collection of pre-canonical Tiddlers plus an IngestReport.
//
// Parameters:
//   - rawPath: filesystem path to raw.tiddlers.json (validated by the Doctor).
//   - origin: indicates whether the source was HTML or JSON.
//
// Returns:
//   - []Tiddler: the pre-canonical tiddler collection (nil on fatal error).
//   - *IngestReport: always present when ingestion can start.
//   - error: an *IngestError only when a fatal condition prevents all ingestion.
//
// Contract invariants (S05 §7):
//   - The raw file is never modified.
//   - An IngestReport is always produced when ingestion starts.
//   - Deterministic: same input + same rules = same output.
//
// Ref: S05 §3 — Objetivo del componente.
func Ingest(rawPath string, origin OriginFormat) ([]Tiddler, *IngestReport, error) {
	data, err := os.ReadFile(rawPath)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil, &IngestError{
				Code:    ErrFileNotFound,
				Message: fmt.Sprintf("raw file not found: %s", rawPath),
				Cause:   err,
			}
		}
		return nil, nil, &IngestError{
			Code:    ErrFileNotReadable,
			Message: fmt.Sprintf("cannot read raw file: %s", rawPath),
			Cause:   err,
		}
	}

	var raws []RawTiddler
	if err := json.Unmarshal(data, &raws); err != nil {
		return nil, nil, &IngestError{
			Code:    ErrNotValidJSON,
			Message: "raw file is not valid JSON",
			Cause:   err,
		}
	}

	report := &IngestReport{
		TiddlerCount: len(raws),
		Warnings:     []string{},
		Errors:       []string{},
	}

	tiddlers := make([]Tiddler, 0, len(raws))

	for i, raw := range raws {
		t, warns, errs := transformOne(raw, origin, i)

		report.Warnings = append(report.Warnings, warns...)
		report.Errors = append(report.Errors, errs...)

		if len(errs) > 0 {
			report.SkippedCount++
			continue
		}

		tiddlers = append(tiddlers, t)
		report.IngestedCount++
	}

	// Determine verdict (S05 §5).
	switch {
	case len(report.Errors) > 0:
		report.Verdict = VerdictError
	case len(report.Warnings) > 0:
		report.Verdict = VerdictWarning
	default:
		report.Verdict = VerdictOk
	}

	return tiddlers, report, nil
}

// TransformOne converts a single RawTiddler into a pre-canonical Tiddler.
// It returns per-tiddler warnings and errors (semantic, not fatal).
//
// Exported for use by the S33 export_tiddlers CLI, which performs in-memory
// ingestion of RawTiddler values extracted directly from HTML.
// The index parameter is used only for error/warning messages.
//
// Ref: S05 §9 — per-tiddler transformation rules.
// Ref: S33 — adapter_real_html requires direct access to transformation.
func TransformOne(raw RawTiddler, origin OriginFormat) (Tiddler, []string, []string) {
	return transformOne(raw, origin, 0)
}

// transformOne converts a single RawTiddler into a pre-canonical Tiddler.
// It returns per-tiddler warnings and errors (semantic, not fatal).
func transformOne(raw RawTiddler, origin OriginFormat, index int) (Tiddler, []string, []string) {
	var warns []string
	var errs []string

	// S05 §9.6: title starting with $:/ is ingested normally.
	if raw.Title == "" {
		errs = append(errs, fmt.Sprintf("tiddler[%d]: empty title", index))
		return Tiddler{}, warns, errs
	}

	// Copy fields (S05 §9.5, §9.7: extra fields preserved as strings).
	fields := make(map[string]string, len(raw.RawFields))
	for k, v := range raw.RawFields {
		fields[k] = v
	}

	// Parse tags (S05 §9.2).
	var tags []string
	if rawTags, ok := raw.RawFields["tags"]; ok && rawTags != "" {
		var parseErr error
		tags, parseErr = ParseTW5Tags(rawTags)
		if parseErr != nil {
			warns = append(warns, fmt.Sprintf("tiddler[%d] %q: tag parse failed: %v", index, raw.Title, parseErr))
			tags = []string{}
		}
	} else {
		tags = []string{}
	}

	// Parse timestamps (S05 §9.3).
	created, err := parseTW5Timestamp(raw.RawFields["created"])
	if err != nil && raw.RawFields["created"] != "" {
		warns = append(warns, fmt.Sprintf("tiddler[%d] %q: created timestamp malformed: %v", index, raw.Title, err))
	}
	modified, err := parseTW5Timestamp(raw.RawFields["modified"])
	if err != nil && raw.RawFields["modified"] != "" {
		warns = append(warns, fmt.Sprintf("tiddler[%d] %q: modified timestamp malformed: %v", index, raw.Title, err))
	}

	// Type (S05 §9.4).
	var typ *string
	if t, ok := raw.RawFields["type"]; ok && t != "" {
		typ = &t
	}

	return Tiddler{
		Title:          raw.Title,
		Fields:         fields,
		Text:           raw.RawText,
		SourcePosition: raw.SourcePosition,
		Tags:           tags,
		Created:        created,
		Modified:       modified,
		Type:           typ,
		OriginFormat:   origin,
	}, warns, errs
}
