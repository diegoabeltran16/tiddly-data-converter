package canon_test

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"

	"github.com/tiddly-data-converter/canon"
)

// ---------------------------------------------------------------------------
// WriteJSONL tests — S16 canon.jsonl emission
// ---------------------------------------------------------------------------

// TestWriteJSONL_MinimalBatch validates that a small batch of CanonEntries
// is serialized as valid JSONL (one JSON object per line).
//
// Ref: S16 §A — writer mínimo de canon.jsonl.
func TestWriteJSONL_MinimalBatch(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("Alpha"), Title: "Alpha", Text: strPtr("body A"), SourcePosition: strPtr("pos:0")},
		{Key: canon.KeyOf("Beta"), Title: "Beta", Text: strPtr("body B")},
	}

	var buf bytes.Buffer
	result, err := canon.WriteJSONL(&buf, entries)
	if err != nil {
		t.Fatalf("WriteJSONL: unexpected error: %v", err)
	}
	if result.Written != 2 {
		t.Errorf("Written: got %d, want 2", result.Written)
	}
	if result.Skipped != 0 {
		t.Errorf("Skipped: got %d, want 0", result.Skipped)
	}

	// Each line must be a valid JSON object.
	lines := strings.Split(strings.TrimSpace(buf.String()), "\n")
	if len(lines) != 2 {
		t.Fatalf("expected 2 JSONL lines, got %d", len(lines))
	}
	for i, line := range lines {
		var ce canon.CanonEntry
		if err := json.Unmarshal([]byte(line), &ce); err != nil {
			t.Errorf("line %d: invalid JSON: %v\nraw: %s", i, err, line)
		}
	}
}

// TestWriteJSONL_EmptyBatch validates that an empty slice produces no output
// and WriteResult reflects zero written.
func TestWriteJSONL_EmptyBatch(t *testing.T) {
	var buf bytes.Buffer
	result, err := canon.WriteJSONL(&buf, []canon.CanonEntry{})
	if err != nil {
		t.Fatalf("WriteJSONL: unexpected error: %v", err)
	}
	if result.Written != 0 {
		t.Errorf("Written: got %d, want 0", result.Written)
	}
	if buf.Len() != 0 {
		t.Errorf("expected empty output, got %q", buf.String())
	}
}

// TestWriteJSONL_SkipsEmptyKey validates that entries with empty Key are
// skipped and counted correctly.
//
// This safeguard protects canon.jsonl from entries that lack canonical identity.
func TestWriteJSONL_SkipsEmptyKey(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("Valid"), Title: "Valid", Text: strPtr("ok")},
		{Key: "", Title: "", Text: strPtr("no key")},
		{Key: canon.KeyOf("AlsoValid"), Title: "AlsoValid", Text: strPtr("ok2")},
	}

	var buf bytes.Buffer
	result, err := canon.WriteJSONL(&buf, entries)
	if err != nil {
		t.Fatalf("WriteJSONL: unexpected error: %v", err)
	}
	if result.Written != 2 {
		t.Errorf("Written: got %d, want 2", result.Written)
	}
	if result.Skipped != 1 {
		t.Errorf("Skipped: got %d, want 1", result.Skipped)
	}

	lines := strings.Split(strings.TrimSpace(buf.String()), "\n")
	if len(lines) != 2 {
		t.Fatalf("expected 2 JSONL lines, got %d", len(lines))
	}
}

// TestWriteJSONL_ShapeConsistency validates that each emitted line contains
// the CanonEntry core fields: schema_version, key, title, text (omitempty),
// source_position (omitempty). Optional fields created/modified are omitted
// when nil.
//
// Ref: S16 §B — shape mínimo explícito.
// Ref: S17 — shape enriched with optional created/modified.
// Ref: S18 — schema v0 with schema_version field.
func TestWriteJSONL_ShapeConsistency(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("WithText"), Title: "WithText", Text: strPtr("body"), SourcePosition: strPtr("pos:1")},
		{Key: canon.KeyOf("NoText"), Title: "NoText"},
	}

	var buf bytes.Buffer
	_, err := canon.WriteJSONL(&buf, entries)
	if err != nil {
		t.Fatalf("WriteJSONL: unexpected error: %v", err)
	}

	lines := strings.Split(strings.TrimSpace(buf.String()), "\n")
	if len(lines) != 2 {
		t.Fatalf("expected 2 lines, got %d", len(lines))
	}

	// Line 0: all fields present.
	var full map[string]interface{}
	if err := json.Unmarshal([]byte(lines[0]), &full); err != nil {
		t.Fatalf("line 0: invalid JSON: %v", err)
	}
	for _, required := range []string{"schema_version", "key", "title", "text", "source_position"} {
		if _, ok := full[required]; !ok {
			t.Errorf("line 0: missing field %q", required)
		}
	}

	// Line 1: text and source_position should be omitted (omitempty).
	var sparse map[string]interface{}
	if err := json.Unmarshal([]byte(lines[1]), &sparse); err != nil {
		t.Fatalf("line 1: invalid JSON: %v", err)
	}
	for _, required := range []string{"schema_version", "key", "title"} {
		if _, ok := sparse[required]; !ok {
			t.Errorf("line 1: missing field %q", required)
		}
	}
	for _, absent := range []string{"text", "source_position", "created", "modified"} {
		if _, ok := sparse[absent]; ok {
			t.Errorf("line 1: field %q should be omitted (omitempty)", absent)
		}
	}
}

// TestWriteJSONL_NilTextOmitted validates that nil Text is correctly
// omitted from the JSONL output, preserving the S13 shape contract.
func TestWriteJSONL_NilTextOmitted(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("NoBody"), Title: "NoBody"},
	}

	var buf bytes.Buffer
	_, err := canon.WriteJSONL(&buf, entries)
	if err != nil {
		t.Fatalf("WriteJSONL: unexpected error: %v", err)
	}

	line := strings.TrimSpace(buf.String())
	if strings.Contains(line, `"text"`) {
		t.Errorf("nil text should be omitted; got: %s", line)
	}
}

// TestWriteResult_Summary validates the human-readable summary.
func TestWriteResult_Summary(t *testing.T) {
	r := canon.WriteResult{Written: 5, Skipped: 1}
	want := "written=5 skipped=1"
	if got := r.Summary(); got != want {
		t.Errorf("Summary: got %q, want %q", got, want)
	}
}

// TestWriteJSONL_RoundTrip validates that entries survive a write-read cycle
// via JSONL serialization. This is the minimal round-trip evidence for S16.
//
// Ref: S16 §D — evidencia observable de emisión.
func TestWriteJSONL_RoundTrip(t *testing.T) {
	original := []canon.CanonEntry{
		{Key: canon.KeyOf("LICENSE"), Title: "LICENSE", Text: strPtr("Apache License 2.0"), SourcePosition: strPtr("pos:0")},
		{Key: canon.KeyOf("README"), Title: "README", Text: strPtr("project readme")},
		{Key: canon.KeyOf("NoText"), Title: "NoText"},
	}

	// Write
	var buf bytes.Buffer
	result, err := canon.WriteJSONL(&buf, original)
	if err != nil {
		t.Fatalf("WriteJSONL: unexpected error: %v", err)
	}
	if result.Written != 3 {
		t.Errorf("Written: got %d, want 3", result.Written)
	}

	// Read back
	lines := strings.Split(strings.TrimSpace(buf.String()), "\n")
	if len(lines) != 3 {
		t.Fatalf("expected 3 JSONL lines, got %d", len(lines))
	}

	for i, line := range lines {
		var restored canon.CanonEntry
		if err := json.Unmarshal([]byte(line), &restored); err != nil {
			t.Errorf("line %d: unmarshal error: %v", i, err)
			continue
		}
		if restored.Key != original[i].Key {
			t.Errorf("line %d Key: got %q, want %q", i, restored.Key, original[i].Key)
		}
		if restored.Title != original[i].Title {
			t.Errorf("line %d Title: got %q, want %q", i, restored.Title, original[i].Title)
		}
	}
}

// ---------------------------------------------------------------------------
// S17 — WriteJSONL tests with timestamps (created/modified)
// ---------------------------------------------------------------------------

// TestWriteJSONL_WithTimestamps validates that created and modified fields
// appear in the JSONL output when present, and are omitted when nil.
//
// Ref: S17 — shape enrichment with created/modified.
func TestWriteJSONL_WithTimestamps(t *testing.T) {
	created := "20230615143052123"
	modified := "20230615150000456"
	entries := []canon.CanonEntry{
		{
			Key:      canon.KeyOf("WithTS"),
			Title:    "WithTS",
			Text:     strPtr("body"),
			Created:  &created,
			Modified: &modified,
		},
		{
			Key:   canon.KeyOf("NoTS"),
			Title: "NoTS",
			Text:  strPtr("body"),
		},
	}

	var buf bytes.Buffer
	result, err := canon.WriteJSONL(&buf, entries)
	if err != nil {
		t.Fatalf("WriteJSONL: unexpected error: %v", err)
	}
	if result.Written != 2 {
		t.Errorf("Written: got %d, want 2", result.Written)
	}

	lines := strings.Split(strings.TrimSpace(buf.String()), "\n")
	if len(lines) != 2 {
		t.Fatalf("expected 2 lines, got %d", len(lines))
	}

	// Line 0: timestamps should be present.
	var withTS map[string]interface{}
	if err := json.Unmarshal([]byte(lines[0]), &withTS); err != nil {
		t.Fatalf("line 0: invalid JSON: %v", err)
	}
	if v, ok := withTS["created"]; !ok || v != created {
		t.Errorf("line 0: created = %v, want %q", v, created)
	}
	if v, ok := withTS["modified"]; !ok || v != modified {
		t.Errorf("line 0: modified = %v, want %q", v, modified)
	}

	// Line 1: timestamps should be omitted (omitempty).
	var noTS map[string]interface{}
	if err := json.Unmarshal([]byte(lines[1]), &noTS); err != nil {
		t.Fatalf("line 1: invalid JSON: %v", err)
	}
	if _, ok := noTS["created"]; ok {
		t.Error("line 1: created should be omitted (omitempty)")
	}
	if _, ok := noTS["modified"]; ok {
		t.Error("line 1: modified should be omitted (omitempty)")
	}
}

// ---------------------------------------------------------------------------
// S19 — WriteJSONL validation gate tests
// ---------------------------------------------------------------------------

// TestWriteJSONL_Gate_RejectsEmptyTitle validates that the S19 gate blocks
// entries with a non-empty Key but empty Title from being emitted.
//
// Before S19, an entry with Key="x" and Title="" would pass the simple
// empty-key check and be emitted as a structurally invalid line.
// The gate now invokes ValidateEntryV0, which rejects empty Title.
//
// Ref: S19 — compuerta activa de validación antes de emisión.
func TestWriteJSONL_Gate_RejectsEmptyTitle(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("Valid"), Title: "Valid", Text: strPtr("ok")},
		{Key: canon.KeyOf("NoTitle"), Title: ""},
		{Key: canon.KeyOf("AlsoValid"), Title: "AlsoValid"},
	}

	var buf bytes.Buffer
	result, err := canon.WriteJSONL(&buf, entries)
	if err != nil {
		t.Fatalf("WriteJSONL: unexpected error: %v", err)
	}
	if result.Written != 2 {
		t.Errorf("Written: got %d, want 2", result.Written)
	}
	if result.Skipped != 1 {
		t.Errorf("Skipped: got %d, want 1", result.Skipped)
	}
	if len(result.ValidationErrors) != 1 {
		t.Fatalf("ValidationErrors: got %d, want 1", len(result.ValidationErrors))
	}
	if !strings.Contains(result.ValidationErrors[0], "title") {
		t.Errorf("ValidationErrors[0] should mention 'title': %s", result.ValidationErrors[0])
	}

	lines := strings.Split(strings.TrimSpace(buf.String()), "\n")
	if len(lines) != 2 {
		t.Fatalf("expected 2 JSONL lines, got %d", len(lines))
	}
}

// TestWriteJSONL_Gate_RejectsWrongSchemaVersion validates that the gate
// blocks entries with an explicitly wrong schema_version from being emitted.
//
// Ref: S19 — compuerta activa: wrong schema_version is a gate violation.
func TestWriteJSONL_Gate_RejectsWrongSchemaVersion(t *testing.T) {
	entries := []canon.CanonEntry{
		{SchemaVersion: "v99", Key: canon.KeyOf("Bad"), Title: "Bad", Text: strPtr("body")},
		{Key: canon.KeyOf("Good"), Title: "Good", Text: strPtr("ok")},
	}

	var buf bytes.Buffer
	result, err := canon.WriteJSONL(&buf, entries)
	if err != nil {
		t.Fatalf("WriteJSONL: unexpected error: %v", err)
	}
	if result.Written != 1 {
		t.Errorf("Written: got %d, want 1", result.Written)
	}
	if result.Skipped != 1 {
		t.Errorf("Skipped: got %d, want 1", result.Skipped)
	}
	if len(result.ValidationErrors) != 1 {
		t.Fatalf("ValidationErrors: got %d, want 1", len(result.ValidationErrors))
	}
	if !strings.Contains(result.ValidationErrors[0], "schema_version") {
		t.Errorf("ValidationErrors[0] should mention 'schema_version': %s", result.ValidationErrors[0])
	}

	line := strings.TrimSpace(buf.String())
	var parsed map[string]interface{}
	if err := json.Unmarshal([]byte(line), &parsed); err != nil {
		t.Fatalf("invalid JSON: %v", err)
	}
	if parsed["title"] != "Good" {
		t.Errorf("emitted entry should be 'Good', got %v", parsed["title"])
	}
}

// TestWriteJSONL_Gate_RejectsAllInvalid validates that a batch where every
// entry is invalid produces zero output and all entries are rejected.
//
// Ref: S19 — gate blocks all structurally invalid entries.
func TestWriteJSONL_Gate_RejectsAllInvalid(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: "", Title: ""},
		{Key: "", Title: "OnlyTitle"},
		{Key: canon.KeyOf("OnlyKey"), Title: ""},
	}

	var buf bytes.Buffer
	result, err := canon.WriteJSONL(&buf, entries)
	if err != nil {
		t.Fatalf("WriteJSONL: unexpected error: %v", err)
	}
	if result.Written != 0 {
		t.Errorf("Written: got %d, want 0", result.Written)
	}
	if result.Skipped != 3 {
		t.Errorf("Skipped: got %d, want 3", result.Skipped)
	}
	if len(result.ValidationErrors) != 3 {
		t.Errorf("ValidationErrors: got %d, want 3", len(result.ValidationErrors))
	}
	if buf.Len() != 0 {
		t.Errorf("expected empty output for all-invalid batch, got %q", buf.String())
	}
}

// TestWriteJSONL_Gate_MixedBatch validates the gate with a realistic mixed
// batch containing valid, empty-key, empty-title and wrong-version entries.
//
// Ref: S19 — compuerta activa observable en batch mixto.
func TestWriteJSONL_Gate_MixedBatch(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("A"), Title: "A", Text: strPtr("ok")},     // valid
		{Key: "", Title: ""},                                          // invalid: empty key+title
		{Key: canon.KeyOf("C"), Title: "C"},                          // valid
		{Key: canon.KeyOf("D"), Title: ""},                           // invalid: empty title
		{SchemaVersion: "v2", Key: canon.KeyOf("E"), Title: "E"},     // invalid: wrong version
		{Key: canon.KeyOf("F"), Title: "F", Text: strPtr("also ok")}, // valid
	}

	var buf bytes.Buffer
	result, err := canon.WriteJSONL(&buf, entries)
	if err != nil {
		t.Fatalf("WriteJSONL: unexpected error: %v", err)
	}
	if result.Written != 3 {
		t.Errorf("Written: got %d, want 3", result.Written)
	}
	if result.Skipped != 3 {
		t.Errorf("Skipped: got %d, want 3", result.Skipped)
	}
	if len(result.ValidationErrors) != 3 {
		t.Errorf("ValidationErrors: got %d, want 3", len(result.ValidationErrors))
	}

	lines := strings.Split(strings.TrimSpace(buf.String()), "\n")
	if len(lines) != 3 {
		t.Fatalf("expected 3 JSONL lines, got %d", len(lines))
	}

	// Verify only valid entries were emitted, in order.
	wantTitles := []string{"A", "C", "F"}
	for i, line := range lines {
		var ce canon.CanonEntry
		if err := json.Unmarshal([]byte(line), &ce); err != nil {
			t.Errorf("line %d: invalid JSON: %v", i, err)
			continue
		}
		if ce.Title != wantTitles[i] {
			t.Errorf("line %d: title = %q, want %q", i, ce.Title, wantTitles[i])
		}
		if ce.SchemaVersion != canon.SchemaV0 {
			t.Errorf("line %d: schema_version = %q, want %q", i, ce.SchemaVersion, canon.SchemaV0)
		}
	}
}

// TestWriteJSONL_Gate_ValidationErrorsHaveContext validates that each
// validation error message contains enough context to identify the failing
// entry: its index and the specific field violation.
//
// Ref: S19 — observabilidad mínima de errores de validación.
func TestWriteJSONL_Gate_ValidationErrorsHaveContext(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("Ok"), Title: "Ok"},
		{Key: "", Title: "NoKey"},
		{Key: canon.KeyOf("NoTitle"), Title: ""},
	}

	var buf bytes.Buffer
	result, err := canon.WriteJSONL(&buf, entries)
	if err != nil {
		t.Fatalf("WriteJSONL: unexpected error: %v", err)
	}
	if len(result.ValidationErrors) != 2 {
		t.Fatalf("ValidationErrors: got %d, want 2", len(result.ValidationErrors))
	}

	// Error for entry[1] should mention index and "key".
	if !strings.Contains(result.ValidationErrors[0], "entry[1]") {
		t.Errorf("error[0] should contain 'entry[1]': %s", result.ValidationErrors[0])
	}
	if !strings.Contains(result.ValidationErrors[0], "key") {
		t.Errorf("error[0] should mention 'key': %s", result.ValidationErrors[0])
	}

	// Error for entry[2] should mention index and "title".
	if !strings.Contains(result.ValidationErrors[1], "entry[2]") {
		t.Errorf("error[1] should contain 'entry[2]': %s", result.ValidationErrors[1])
	}
	if !strings.Contains(result.ValidationErrors[1], "title") {
		t.Errorf("error[1] should mention 'title': %s", result.ValidationErrors[1])
	}
}

// TestWriteResult_Summary_WithErrors validates the summary format when
// validation errors are present.
//
// Ref: S19 — observabilidad mínima.
func TestWriteResult_Summary_WithErrors(t *testing.T) {
	r := canon.WriteResult{
		Written:          3,
		Skipped:          2,
		ValidationErrors: []string{"err1", "err2"},
	}
	got := r.Summary()
	want := "written=3 skipped=2 validation_errors=2"
	if got != want {
		t.Errorf("Summary: got %q, want %q", got, want)
	}
}

// TestWriteJSONL_RoundTrip_WithTimestamps validates that timestamps survive
// a write-read cycle via JSONL serialization.
//
// Ref: S17 — round-trip evidence for enriched shape.
func TestWriteJSONL_RoundTrip_WithTimestamps(t *testing.T) {
	created := "20230615143052123"
	modified := "20230615150000456"
	original := []canon.CanonEntry{
		{
			Key:      canon.KeyOf("WithTS"),
			Title:    "WithTS",
			Text:     strPtr("body"),
			Created:  &created,
			Modified: &modified,
		},
	}

	var buf bytes.Buffer
	_, err := canon.WriteJSONL(&buf, original)
	if err != nil {
		t.Fatalf("WriteJSONL: unexpected error: %v", err)
	}

	line := strings.TrimSpace(buf.String())
	var restored canon.CanonEntry
	if err := json.Unmarshal([]byte(line), &restored); err != nil {
		t.Fatalf("unmarshal error: %v", err)
	}

	if restored.Created == nil || *restored.Created != created {
		t.Errorf("Created: got %v, want %q", restored.Created, created)
	}
	if restored.Modified == nil || *restored.Modified != modified {
		t.Errorf("Modified: got %v, want %q", restored.Modified, modified)
	}
}
