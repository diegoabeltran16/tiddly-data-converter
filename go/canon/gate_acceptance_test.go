package canon_test

import (
	"bufio"
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/tiddly-data-converter/canon"
)

// ---------------------------------------------------------------------------
// S21 — canon-jsonl-gate-v0 acceptance matrix
//
// This file materializes the explicit accept/reject matrix for the
// canon-jsonl-gate-v0 (ValidateEntryV0 + WriteJSONL gate).
//
// The matrix makes observable which CanonEntry combinations MUST pass
// and which MUST be rejected by the current gate, without reopening
// the schema v0 definition, without redesigning CanonEntry, and without
// invading Ingesta, Doctor or Extractor boundaries.
//
// Ref: S18 — schema v0 declaration.
// Ref: S19 — active validation gate in WriteJSONL.
// Ref: S20 — E2E smoke evidence.
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// A. ValidateEntryV0 acceptance matrix — table-driven
// ---------------------------------------------------------------------------

// TestGateAcceptanceMatrix_ValidateEntryV0 is the canonical table-driven
// acceptance matrix for ValidateEntryV0. Each row declares a named case,
// the input CanonEntry, and whether it MUST pass (wantErr=false) or
// MUST be rejected (wantErr=true) with an expected substring in the error.
//
// Ref: S21 — acceptance matrix for canon-jsonl-gate-v0.
func TestGateAcceptanceMatrix_ValidateEntryV0(t *testing.T) {
	cases := []struct {
		name       string
		entry      canon.CanonEntry
		wantErr    bool
		errContain string // substring expected in error message (when wantErr=true)
	}{
		// ---- ACCEPT cases ----
		{
			name: "Accept/MinimalValid_KeyAndTitle",
			entry: canon.CanonEntry{
				Key:   canon.KeyOf("Test"),
				Title: "Test",
			},
			wantErr: false,
		},
		{
			name: "Accept/WithSchemaV0",
			entry: canon.CanonEntry{
				SchemaVersion: canon.SchemaV0,
				Key:           canon.KeyOf("Test"),
				Title:         "Test",
			},
			wantErr: false,
		},
		{
			name: "Accept/WithoutSchemaVersion_PreWriterStamping",
			entry: canon.CanonEntry{
				Key:   canon.KeyOf("PreStamp"),
				Title: "PreStamp",
			},
			wantErr: false,
		},
		{
			name: "Accept/AllOptionalFieldsPresent",
			entry: canon.CanonEntry{
				SchemaVersion:  canon.SchemaV0,
				Key:            canon.KeyOf("Full"),
				Title:          "Full",
				Text:           strPtr("body content"),
				SourcePosition: strPtr("tiddler-store:42"),
				Created:        strPtr("20230615143052123"),
				Modified:       strPtr("20230615150000456"),
			},
			wantErr: false,
		},
		{
			name: "Accept/NilText",
			entry: canon.CanonEntry{
				Key:   canon.KeyOf("NoBody"),
				Title: "NoBody",
			},
			wantErr: false,
		},
		{
			name: "Accept/EmptyStringText",
			entry: canon.CanonEntry{
				Key:   canon.KeyOf("EmptyBody"),
				Title: "EmptyBody",
				Text:  strPtr(""),
			},
			wantErr: false,
		},
		{
			name: "Accept/UnicodeTitle",
			entry: canon.CanonEntry{
				Key:   canon.KeyOf("#### 🌀 Sesión 08 = ingesta-data-triage"),
				Title: "#### 🌀 Sesión 08 = ingesta-data-triage",
			},
			wantErr: false,
		},
		{
			name: "Accept/OnlyCreatedTimestamp",
			entry: canon.CanonEntry{
				Key:     canon.KeyOf("WithCreated"),
				Title:   "WithCreated",
				Created: strPtr("20260101000000000"),
			},
			wantErr: false,
		},
		{
			name: "Accept/OnlyModifiedTimestamp",
			entry: canon.CanonEntry{
				Key:      canon.KeyOf("WithModified"),
				Title:    "WithModified",
				Modified: strPtr("20260101120000000"),
			},
			wantErr: false,
		},
		{
			name: "Accept/SingleCharTitle",
			entry: canon.CanonEntry{
				Key:   canon.KeyOf("X"),
				Title: "X",
			},
			wantErr: false,
		},

		// ---- REJECT cases ----
		{
			name: "Reject/EmptyKey",
			entry: canon.CanonEntry{
				Key:   "",
				Title: "HasTitle",
			},
			wantErr:    true,
			errContain: "key",
		},
		{
			name: "Reject/EmptyTitle",
			entry: canon.CanonEntry{
				Key:   canon.KeyOf("HasKey"),
				Title: "",
			},
			wantErr:    true,
			errContain: "title",
		},
		{
			name: "Reject/BothKeyAndTitleEmpty",
			entry: canon.CanonEntry{
				Key:   "",
				Title: "",
			},
			wantErr:    true,
			errContain: "key", // key is checked first
		},
		{
			name: "Reject/WrongSchemaVersion_v99",
			entry: canon.CanonEntry{
				SchemaVersion: "v99",
				Key:           canon.KeyOf("Bad"),
				Title:         "Bad",
			},
			wantErr:    true,
			errContain: "schema_version",
		},
		{
			name: "Reject/WrongSchemaVersion_v1",
			entry: canon.CanonEntry{
				SchemaVersion: "v1",
				Key:           canon.KeyOf("V1"),
				Title:         "V1",
			},
			wantErr:    true,
			errContain: "schema_version",
		},
		{
			name: "Reject/CaseSensitiveSchemaVersion_V0",
			entry: canon.CanonEntry{
				SchemaVersion: "V0", // uppercase V — must be rejected
				Key:           canon.KeyOf("CaseBad"),
				Title:         "CaseBad",
			},
			wantErr:    true,
			errContain: "schema_version",
		},
		{
			name: "Reject/EmptyKeyWithText",
			entry: canon.CanonEntry{
				Key:   "",
				Title: "HasTitle",
				Text:  strPtr("has body but no key"),
			},
			wantErr:    true,
			errContain: "key",
		},
		{
			name: "Reject/EmptyTitleWithAllOptionals",
			entry: canon.CanonEntry{
				SchemaVersion:  canon.SchemaV0,
				Key:            canon.KeyOf("NoTitle"),
				Title:          "",
				Text:           strPtr("body"),
				SourcePosition: strPtr("pos:0"),
				Created:        strPtr("20230615143052123"),
				Modified:       strPtr("20230615150000456"),
			},
			wantErr:    true,
			errContain: "title",
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			err := canon.ValidateEntryV0(tc.entry)
			if tc.wantErr {
				if err == nil {
					t.Errorf("expected error containing %q, got nil", tc.errContain)
				} else if !strings.Contains(err.Error(), tc.errContain) {
					t.Errorf("error %q does not contain %q", err.Error(), tc.errContain)
				}
			} else {
				if err != nil {
					t.Errorf("expected no error, got: %v", err)
				}
			}
		})
	}
}

// ---------------------------------------------------------------------------
// B. WriteJSONL gate acceptance matrix — table-driven
// ---------------------------------------------------------------------------

// TestGateAcceptanceMatrix_WriteJSONL is the canonical table-driven
// acceptance matrix for the WriteJSONL emission gate. Each row declares
// a named batch of entries, and the expected counters (written, skipped)
// after passing through the gate.
//
// This verifies that the gate integrated into WriteJSONL produces the
// correct accept/reject behavior observable in the output.
//
// Ref: S21 — acceptance matrix for canon-jsonl-gate-v0.
func TestGateAcceptanceMatrix_WriteJSONL(t *testing.T) {
	cases := []struct {
		name        string
		entries     []canon.CanonEntry
		wantWritten int
		wantSkipped int
		wantErrors  int
	}{
		{
			name: "AllValid_SingleEntry",
			entries: []canon.CanonEntry{
				{Key: canon.KeyOf("A"), Title: "A", Text: strPtr("body")},
			},
			wantWritten: 1,
			wantSkipped: 0,
			wantErrors:  0,
		},
		{
			name: "AllValid_MultipleEntries",
			entries: []canon.CanonEntry{
				{Key: canon.KeyOf("A"), Title: "A", Text: strPtr("body A")},
				{Key: canon.KeyOf("B"), Title: "B"},
				{Key: canon.KeyOf("C"), Title: "C", Text: strPtr("body C"), SourcePosition: strPtr("pos:2")},
			},
			wantWritten: 3,
			wantSkipped: 0,
			wantErrors:  0,
		},
		{
			name:        "EmptyBatch",
			entries:     []canon.CanonEntry{},
			wantWritten: 0,
			wantSkipped: 0,
			wantErrors:  0,
		},
		{
			name: "AllInvalid",
			entries: []canon.CanonEntry{
				{Key: "", Title: ""},
				{Key: "", Title: "NoKey"},
				{Key: canon.KeyOf("NoTitle"), Title: ""},
			},
			wantWritten: 0,
			wantSkipped: 3,
			wantErrors:  3,
		},
		{
			name: "MixedBatch_ValidAndInvalid",
			entries: []canon.CanonEntry{
				{Key: canon.KeyOf("Good1"), Title: "Good1", Text: strPtr("ok")},
				{Key: "", Title: ""},                                                 // invalid
				{Key: canon.KeyOf("Good2"), Title: "Good2"},                          // valid
				{Key: canon.KeyOf("BadTitle"), Title: ""},                            // invalid
				{SchemaVersion: "v99", Key: canon.KeyOf("BadVer"), Title: "BadVer"},  // invalid
				{Key: canon.KeyOf("Good3"), Title: "Good3", Text: strPtr("also ok")}, // valid
			},
			wantWritten: 3,
			wantSkipped: 3,
			wantErrors:  3,
		},
		{
			name: "ValidWithTimestamps",
			entries: []canon.CanonEntry{
				{
					Key:      canon.KeyOf("WithTS"),
					Title:    "WithTS",
					Text:     strPtr("body"),
					Created:  strPtr("20230615143052123"),
					Modified: strPtr("20230615150000456"),
				},
			},
			wantWritten: 1,
			wantSkipped: 0,
			wantErrors:  0,
		},
		{
			name: "InvalidSurroundedByValid",
			entries: []canon.CanonEntry{
				{Key: canon.KeyOf("First"), Title: "First"},
				{Key: "", Title: "NoKey"},
				{Key: canon.KeyOf("Last"), Title: "Last"},
			},
			wantWritten: 2,
			wantSkipped: 1,
			wantErrors:  1,
		},
		{
			name: "SingleInvalid_EmptyKey",
			entries: []canon.CanonEntry{
				{Key: "", Title: "OnlyTitle"},
			},
			wantWritten: 0,
			wantSkipped: 1,
			wantErrors:  1,
		},
		{
			name: "SingleInvalid_WrongVersion",
			entries: []canon.CanonEntry{
				{SchemaVersion: "v2", Key: canon.KeyOf("E"), Title: "E"},
			},
			wantWritten: 0,
			wantSkipped: 1,
			wantErrors:  1,
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			var buf bytes.Buffer
			result, err := canon.WriteJSONL(&buf, tc.entries)
			if err != nil {
				t.Fatalf("WriteJSONL returned unexpected I/O error: %v", err)
			}
			if result.Written != tc.wantWritten {
				t.Errorf("Written: got %d, want %d", result.Written, tc.wantWritten)
			}
			if result.Skipped != tc.wantSkipped {
				t.Errorf("Skipped: got %d, want %d", result.Skipped, tc.wantSkipped)
			}
			if len(result.ValidationErrors) != tc.wantErrors {
				t.Errorf("ValidationErrors: got %d, want %d", len(result.ValidationErrors), tc.wantErrors)
			}

			// Verify every emitted line is valid JSON with schema_version stamped.
			if result.Written > 0 {
				lines := strings.Split(strings.TrimSpace(buf.String()), "\n")
				if len(lines) != tc.wantWritten {
					t.Fatalf("expected %d JSONL lines, got %d", tc.wantWritten, len(lines))
				}
				for i, line := range lines {
					var parsed canon.CanonEntry
					if err := json.Unmarshal([]byte(line), &parsed); err != nil {
						t.Errorf("line %d: invalid JSON: %v", i, err)
						continue
					}
					if parsed.SchemaVersion != canon.SchemaV0 {
						t.Errorf("line %d: schema_version = %q, want %q", i, parsed.SchemaVersion, canon.SchemaV0)
					}
					if err := canon.ValidateEntryV0(parsed); err != nil {
						t.Errorf("line %d: emitted entry fails ValidateEntryV0: %v", i, err)
					}
				}
			}

			// Verify empty output when nothing was written.
			if tc.wantWritten == 0 && buf.Len() != 0 {
				t.Errorf("expected empty output, got %q", buf.String())
			}
		})
	}
}

// ---------------------------------------------------------------------------
// C. JSONL fixture-based acceptance matrix
// ---------------------------------------------------------------------------

// TestGateAcceptanceMatrix_Fixture_Accept validates that every line in the
// canon_gate_accept.jsonl fixture parses to a CanonEntry that passes
// ValidateEntryV0.
//
// This fixture provides external, file-based evidence of valid canon.jsonl
// lines that the gate MUST accept.
//
// Ref: S21 — fixture-backed acceptance evidence.
func TestGateAcceptanceMatrix_Fixture_Accept(t *testing.T) {
	path := filepath.Join("..", "..", "tests", "fixtures", "canon_gate_accept.jsonl")
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("failed to read fixture %q: %v", path, err)
	}

	scanner := bufio.NewScanner(bytes.NewReader(data))
	lineNum := 0
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		lineNum++

		var entry canon.CanonEntry
		if err := json.Unmarshal([]byte(line), &entry); err != nil {
			t.Errorf("line %d: JSON parse error: %v", lineNum, err)
			continue
		}
		if err := canon.ValidateEntryV0(entry); err != nil {
			t.Errorf("line %d (title=%q): expected ACCEPT, got reject: %v", lineNum, entry.Title, err)
		}
	}
	if err := scanner.Err(); err != nil {
		t.Fatalf("scanner error: %v", err)
	}
	if lineNum == 0 {
		t.Fatal("fixture is empty — no lines tested")
	}
	t.Logf("Verified %d accept lines from fixture", lineNum)
}

// TestGateAcceptanceMatrix_Fixture_Reject validates that every line in the
// canon_gate_reject.jsonl fixture either fails JSON parsing or fails
// ValidateEntryV0.
//
// This fixture provides external, file-based evidence of invalid canon.jsonl
// lines that the gate MUST reject.
//
// Ref: S21 — fixture-backed rejection evidence.
func TestGateAcceptanceMatrix_Fixture_Reject(t *testing.T) {
	path := filepath.Join("..", "..", "tests", "fixtures", "canon_gate_reject.jsonl")
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("failed to read fixture %q: %v", path, err)
	}

	scanner := bufio.NewScanner(bytes.NewReader(data))
	lineNum := 0
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		lineNum++

		var entry canon.CanonEntry
		parseErr := json.Unmarshal([]byte(line), &entry)
		if parseErr != nil {
			// Malformed JSON is a valid rejection reason.
			continue
		}
		if err := canon.ValidateEntryV0(entry); err == nil {
			t.Errorf("line %d (title=%q): expected REJECT, but passed validation", lineNum, entry.Title)
		}
	}
	if err := scanner.Err(); err != nil {
		t.Fatalf("scanner error: %v", err)
	}
	if lineNum == 0 {
		t.Fatal("fixture is empty — no lines tested")
	}
	t.Logf("Verified %d reject lines from fixture", lineNum)
}

// ---------------------------------------------------------------------------
// D. WriteJSONL accept fixture round-trip
// ---------------------------------------------------------------------------

// TestGateAcceptanceMatrix_Fixture_AcceptRoundTrip validates that every line
// in the accept fixture can be deserialized into a CanonEntry, passed through
// WriteJSONL, and the output re-validates successfully.
//
// This closes the loop: fixture → parse → WriteJSONL → re-parse → validate.
//
// Ref: S21 — round-trip evidence for acceptance matrix.
func TestGateAcceptanceMatrix_Fixture_AcceptRoundTrip(t *testing.T) {
	path := filepath.Join("..", "..", "tests", "fixtures", "canon_gate_accept.jsonl")
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("failed to read fixture %q: %v", path, err)
	}

	// Parse all entries from the fixture.
	var entries []canon.CanonEntry
	scanner := bufio.NewScanner(bytes.NewReader(data))
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		var entry canon.CanonEntry
		if err := json.Unmarshal([]byte(line), &entry); err != nil {
			t.Fatalf("fixture parse error: %v", err)
		}
		// Clear SchemaVersion to simulate pre-writer state (writer stamps it).
		entry.SchemaVersion = ""
		entries = append(entries, entry)
	}
	if err := scanner.Err(); err != nil {
		t.Fatalf("scanner error: %v", err)
	}
	if len(entries) == 0 {
		t.Fatal("no entries parsed from fixture")
	}

	// Write all entries through WriteJSONL.
	var buf bytes.Buffer
	result, err := canon.WriteJSONL(&buf, entries)
	if err != nil {
		t.Fatalf("WriteJSONL: unexpected error: %v", err)
	}
	if result.Written != len(entries) {
		t.Errorf("Written: got %d, want %d", result.Written, len(entries))
	}
	if result.Skipped != 0 {
		t.Errorf("Skipped: got %d, want 0; errors: %v", result.Skipped, result.ValidationErrors)
	}

	// Re-parse and re-validate every emitted line.
	lines := strings.Split(strings.TrimSpace(buf.String()), "\n")
	if len(lines) != len(entries) {
		t.Fatalf("expected %d output lines, got %d", len(entries), len(lines))
	}
	for i, line := range lines {
		var restored canon.CanonEntry
		if err := json.Unmarshal([]byte(line), &restored); err != nil {
			t.Errorf("line %d: re-parse error: %v", i, err)
			continue
		}
		if restored.SchemaVersion != canon.SchemaV0 {
			t.Errorf("line %d: schema_version = %q, want %q", i, restored.SchemaVersion, canon.SchemaV0)
		}
		if err := canon.ValidateEntryV0(restored); err != nil {
			t.Errorf("line %d: round-trip entry fails validation: %v", i, err)
		}
	}
	t.Logf("Round-trip verified for %d entries", len(entries))
}

// ---------------------------------------------------------------------------
// E. Schema v0 shape strict-fields check on emitted output
// ---------------------------------------------------------------------------

// TestGateAcceptanceMatrix_EmittedShape_NoExtraFields verifies that the
// gate + writer never emit fields outside the declared schema v0 set.
//
// This is a structural invariant: if a field not in SchemaV0RequiredFields
// or SchemaV0OptionalFields appears in the output, the shape contract is
// violated.
//
// Ref: S21 — shape strictness acceptance.
// Ref: S18 — declared schema v0 fields.
func TestGateAcceptanceMatrix_EmittedShape_NoExtraFields(t *testing.T) {
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
		{Key: canon.KeyOf("Minimal"), Title: "Minimal"},
	}

	declared := make(map[string]bool)
	for _, f := range canon.SchemaV0RequiredFields {
		declared[f] = true
	}
	for _, f := range canon.SchemaV0OptionalFields {
		declared[f] = true
	}

	var buf bytes.Buffer
	result, err := canon.WriteJSONL(&buf, entries)
	if err != nil {
		t.Fatalf("WriteJSONL: unexpected error: %v", err)
	}
	if result.Written != 2 {
		t.Fatalf("Written: got %d, want 2", result.Written)
	}

	lines := strings.Split(strings.TrimSpace(buf.String()), "\n")
	for i, line := range lines {
		var parsed map[string]interface{}
		if err := json.Unmarshal([]byte(line), &parsed); err != nil {
			t.Fatalf("line %d: invalid JSON: %v", i, err)
		}
		for k := range parsed {
			if !declared[k] {
				t.Errorf("line %d: unexpected field %q (not in schema v0)", i, k)
			}
		}
	}
}

// ---------------------------------------------------------------------------
// F. Validation error context quality
// ---------------------------------------------------------------------------

// TestGateAcceptanceMatrix_ErrorContextQuality validates that every
// rejection error produced by the gate contains enough context to
// identify the failing entry (index) and the specific violation (field name).
//
// Ref: S21 — observability of gate rejections.
// Ref: S19 — contextual validation errors.
func TestGateAcceptanceMatrix_ErrorContextQuality(t *testing.T) {
	entries := []canon.CanonEntry{
		{Key: canon.KeyOf("Good"), Title: "Good"},
		{Key: "", Title: "NoKey"},                                             // entry[1], key
		{Key: canon.KeyOf("NoTitle"), Title: ""},                              // entry[2], title
		{SchemaVersion: "v99", Key: canon.KeyOf("BadVer"), Title: "BadVer"},   // entry[3], schema_version
	}

	var buf bytes.Buffer
	result, _ := canon.WriteJSONL(&buf, entries)

	if len(result.ValidationErrors) != 3 {
		t.Fatalf("ValidationErrors: got %d, want 3", len(result.ValidationErrors))
	}

	expectations := []struct {
		indexStr string
		field    string
	}{
		{"entry[1]", "key"},
		{"entry[2]", "title"},
		{"entry[3]", "schema_version"},
	}

	for i, exp := range expectations {
		ve := result.ValidationErrors[i]
		if !strings.Contains(ve, exp.indexStr) {
			t.Errorf("ValidationErrors[%d] should contain %q: %s", i, exp.indexStr, ve)
		}
		if !strings.Contains(ve, exp.field) {
			t.Errorf("ValidationErrors[%d] should contain %q: %s", i, exp.field, ve)
		}
	}
}
