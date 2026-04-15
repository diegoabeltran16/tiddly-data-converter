package canon_test

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"

	"github.com/tiddly-data-converter/canon"
)

// ---------------------------------------------------------------------------
// Schema v0 tests — S18 canon.jsonl schema declaration and validation
// ---------------------------------------------------------------------------

// TestSchemaV0_Constant validates that the schema version constant is "v0".
func TestSchemaV0_Constant(t *testing.T) {
	if canon.SchemaV0 != "v0" {
		t.Errorf("SchemaV0: got %q, want %q", canon.SchemaV0, "v0")
	}
}

// TestSchemaV0RequiredFields validates the declared required field list.
func TestSchemaV0RequiredFields(t *testing.T) {
	want := []string{"schema_version", "key", "title"}
	got := canon.SchemaV0RequiredFields
	if len(got) != len(want) {
		t.Fatalf("SchemaV0RequiredFields: got %d fields, want %d", len(got), len(want))
	}
	for i := range want {
		if got[i] != want[i] {
			t.Errorf("SchemaV0RequiredFields[%d]: got %q, want %q", i, got[i], want[i])
		}
	}
}

// TestSchemaV0OptionalFields validates the declared optional field list.
func TestSchemaV0OptionalFields(t *testing.T) {
	want := []string{"text", "source_type", "source_position", "created", "modified", "source_fields"}
	got := canon.SchemaV0OptionalFields
	if len(got) != len(want) {
		t.Fatalf("SchemaV0OptionalFields: got %d fields, want %d", len(got), len(want))
	}
	for i := range want {
		if got[i] != want[i] {
			t.Errorf("SchemaV0OptionalFields[%d]: got %q, want %q", i, got[i], want[i])
		}
	}
}

// TestValidateEntryV0_Valid validates that a well-formed entry passes.
func TestValidateEntryV0_Valid(t *testing.T) {
	e := canon.CanonEntry{
		SchemaVersion: canon.SchemaV0,
		Key:           canon.KeyOf("Test"),
		Title:         "Test",
		Text:          strPtr("body"),
	}
	if err := canon.ValidateEntryV0(e); err != nil {
		t.Errorf("ValidateEntryV0: unexpected error: %v", err)
	}
}

// TestValidateEntryV0_ValidWithoutSchemaVersion validates that an entry
// without schema_version set (pre-writer stamping) also passes.
func TestValidateEntryV0_ValidWithoutSchemaVersion(t *testing.T) {
	e := canon.CanonEntry{
		Key:   canon.KeyOf("Test"),
		Title: "Test",
	}
	if err := canon.ValidateEntryV0(e); err != nil {
		t.Errorf("ValidateEntryV0: unexpected error for entry without schema_version: %v", err)
	}
}

// TestValidateEntryV0_EmptyKey validates that empty Key is rejected.
func TestValidateEntryV0_EmptyKey(t *testing.T) {
	e := canon.CanonEntry{
		Key:   "",
		Title: "Test",
	}
	if err := canon.ValidateEntryV0(e); err == nil {
		t.Error("ValidateEntryV0: expected error for empty key, got nil")
	}
}

// TestValidateEntryV0_EmptyTitle validates that empty Title is rejected.
func TestValidateEntryV0_EmptyTitle(t *testing.T) {
	e := canon.CanonEntry{
		Key:   canon.KeyOf("Test"),
		Title: "",
	}
	if err := canon.ValidateEntryV0(e); err == nil {
		t.Error("ValidateEntryV0: expected error for empty title, got nil")
	}
}

// TestValidateEntryV0_WrongSchemaVersion validates that a wrong version is rejected.
func TestValidateEntryV0_WrongSchemaVersion(t *testing.T) {
	e := canon.CanonEntry{
		SchemaVersion: "v99",
		Key:           canon.KeyOf("Test"),
		Title:         "Test",
	}
	if err := canon.ValidateEntryV0(e); err == nil {
		t.Error("ValidateEntryV0: expected error for wrong schema_version, got nil")
	}
}

// TestValidateEntryV0_MinimalValid validates the absolute minimum valid entry.
func TestValidateEntryV0_MinimalValid(t *testing.T) {
	e := canon.CanonEntry{
		Key:   canon.KeyOf("X"),
		Title: "X",
	}
	if err := canon.ValidateEntryV0(e); err != nil {
		t.Errorf("ValidateEntryV0: unexpected error for minimal entry: %v", err)
	}
}

// ---------------------------------------------------------------------------
// Schema v0 emission tests — validates writer stamps schema_version
// ---------------------------------------------------------------------------

// TestWriteJSONL_SchemaVersionStamped validates that every emitted JSONL line
// contains schema_version = "v0", even when the input entry has no schema_version set.
//
// Ref: S18 — writer stamps schema_version.
func TestWriteJSONL_SchemaVersionStamped(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("Alpha"), Title: "Alpha", Text: strPtr("body A")},
		{Key: canon.KeyOf("Beta"), Title: "Beta"},
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
		t.Fatalf("expected 2 JSONL lines, got %d", len(lines))
	}

	for i, line := range lines {
		var parsed map[string]interface{}
		if err := json.Unmarshal([]byte(line), &parsed); err != nil {
			t.Fatalf("line %d: invalid JSON: %v", i, err)
		}
		v, ok := parsed["schema_version"]
		if !ok {
			t.Errorf("line %d: missing schema_version field", i)
			continue
		}
		if v != canon.SchemaV0 {
			t.Errorf("line %d: schema_version = %v, want %q", i, v, canon.SchemaV0)
		}
	}
}

// TestWriteJSONL_SchemaVersionDoesNotMutateInput validates that the writer
// does not modify the original entries slice when stamping schema_version.
//
// Ref: S18 — writer uses range copy for stamping.
func TestWriteJSONL_SchemaVersionDoesNotMutateInput(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("A"), Title: "A"},
	}

	var buf bytes.Buffer
	_, err := canon.WriteJSONL(&buf, entries)
	if err != nil {
		t.Fatalf("WriteJSONL: unexpected error: %v", err)
	}

	// The original entry should still have empty SchemaVersion.
	if entries[0].SchemaVersion != "" {
		t.Errorf("original entry mutated: SchemaVersion = %q, want empty", entries[0].SchemaVersion)
	}
}

// TestWriteJSONL_SchemaV0ShapeComplete validates that the basic WriteJSONL
// writer produces the correct shape: required + optional fields only.
// Identity (S34) and reading mode (S35) fields are computed by
// ExportTiddlersJSONL, not by the basic WriteJSONL writer. The boolean
// reading mode fields (is_binary, is_reference_only) always appear because
// Go serializes bool zero values.
//
// Ref: S18 — schema v0 shape validation.
func TestWriteJSONL_SchemaV0ShapeComplete(t *testing.T) {
	created := "20230615143052123"
	modified := "20230615150000456"
	entries := []canon.CanonEntry{
		{
			Key:            canon.KeyOf("Full"),
			Title:          "Full",
			Text:           strPtr("body"),
			SourcePosition: strPtr("pos:0"),
			Created:        &created,
			Modified:       &modified,
		},
	}

	var buf bytes.Buffer
	_, err := canon.WriteJSONL(&buf, entries)
	if err != nil {
		t.Fatalf("WriteJSONL: unexpected error: %v", err)
	}

	line := strings.TrimSpace(buf.String())
	var parsed map[string]interface{}
	if err := json.Unmarshal([]byte(line), &parsed); err != nil {
		t.Fatalf("invalid JSON: %v", err)
	}

	// Basic required fields must be present.
	for _, f := range canon.SchemaV0RequiredFields {
		if _, ok := parsed[f]; !ok {
			t.Errorf("missing required field %q in basic writer output", f)
		}
	}

	// Boolean reading mode fields are always present (Go zero values).
	for _, f := range []string{"is_binary", "is_reference_only"} {
		if _, ok := parsed[f]; !ok {
			t.Errorf("missing boolean field %q in basic writer output", f)
		}
	}

	// No extra fields beyond the full declared schema should be present.
	allDeclared := make(map[string]bool)
	for _, f := range canon.SchemaV0RequiredFields {
		allDeclared[f] = true
	}
	for _, f := range canon.SchemaV0IdentityFields {
		allDeclared[f] = true
	}
	for _, f := range canon.SchemaV0ReadingModeFields {
		allDeclared[f] = true
	}
	for _, f := range canon.SchemaV0SemanticFields {
		allDeclared[f] = true
	}
	for _, f := range canon.SchemaV0ContextRelationFields {
		allDeclared[f] = true
	}
	for _, f := range canon.SchemaV0OptionalFields {
		allDeclared[f] = true
	}
	for k := range parsed {
		if !allDeclared[k] {
			t.Errorf("unexpected field %q in output (not in schema v0)", k)
		}
	}
}

// TestWriteJSONL_RoundTrip_WithSchemaVersion validates that schema_version
// survives a write-read cycle via JSONL serialization.
//
// Ref: S18 — round-trip evidence for schema v0.
func TestWriteJSONL_RoundTrip_WithSchemaVersion(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("RT"), Title: "RT", Text: strPtr("round trip")},
	}

	var buf bytes.Buffer
	_, err := canon.WriteJSONL(&buf, entries)
	if err != nil {
		t.Fatalf("WriteJSONL: unexpected error: %v", err)
	}

	line := strings.TrimSpace(buf.String())
	var restored canon.CanonEntry
	if err := json.Unmarshal([]byte(line), &restored); err != nil {
		t.Fatalf("unmarshal error: %v", err)
	}

	if restored.SchemaVersion != canon.SchemaV0 {
		t.Errorf("SchemaVersion: got %q, want %q", restored.SchemaVersion, canon.SchemaV0)
	}

	// Validate the restored entry passes schema v0 validation.
	if err := canon.ValidateEntryV0(restored); err != nil {
		t.Errorf("ValidateEntryV0 on restored entry: %v", err)
	}
}
