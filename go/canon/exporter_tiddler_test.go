package canon

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"
)

// TestExportTiddlersJSONL_Basic verifies basic per-tiddler export with
// SHA-256 computation and export log generation.
func TestExportTiddlersJSONL_Basic(t *testing.T) {
	text1 := "Content of Alpha"
	text2 := "Content of Beta"
	entries := []CanonEntry{
		{Key: "alpha", Title: "Alpha", Text: &text1},
		{Key: "beta", Title: "Beta", Text: &text2},
	}

	var buf bytes.Buffer
	result, err := ExportTiddlersJSONL(&buf, entries, "test-run-001")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	// Verify manifest
	if result.Manifest.ExportedCount != 2 {
		t.Errorf("ExportedCount = %d, want 2", result.Manifest.ExportedCount)
	}
	if result.Manifest.SkippedByGate != 0 {
		t.Errorf("SkippedByGate = %d, want 0", result.Manifest.SkippedByGate)
	}
	if result.Manifest.InputCount != 2 {
		t.Errorf("InputCount = %d, want 2", result.Manifest.InputCount)
	}
	if !strings.HasPrefix(result.Manifest.SHA256, "sha256:") {
		t.Errorf("SHA256 = %q, want sha256: prefix", result.Manifest.SHA256)
	}
	if result.Manifest.SchemaVersion != SchemaV0 {
		t.Errorf("SchemaVersion = %q, want %q", result.Manifest.SchemaVersion, SchemaV0)
	}

	// Verify JSONL output: 2 lines
	lines := strings.Split(strings.TrimSpace(buf.String()), "\n")
	if len(lines) != 2 {
		t.Fatalf("JSONL lines = %d, want 2", len(lines))
	}

	// Each line should be valid JSON and have schema_version stamped
	for i, line := range lines {
		var entry CanonEntry
		if err := json.Unmarshal([]byte(line), &entry); err != nil {
			t.Errorf("line[%d] invalid JSON: %v", i, err)
			continue
		}
		if entry.SchemaVersion != SchemaV0 {
			t.Errorf("line[%d] schema_version = %q, want %q", i, entry.SchemaVersion, SchemaV0)
		}
	}

	// Verify export log
	if len(result.LogEntries) != 2 {
		t.Fatalf("LogEntries = %d, want 2", len(result.LogEntries))
	}
	for _, entry := range result.LogEntries {
		if entry.Action != "included" {
			t.Errorf("log entry %q action = %q, want %q", entry.TiddlerID, entry.Action, "included")
		}
		if entry.RunID != "test-run-001" {
			t.Errorf("log entry run_id = %q, want %q", entry.RunID, "test-run-001")
		}
	}
}

// TestExportTiddlersJSONL_GateRejection verifies that entries failing
// the S19 gate are excluded and logged.
func TestExportTiddlersJSONL_GateRejection(t *testing.T) {
	text := "valid content"
	entries := []CanonEntry{
		{Key: "valid", Title: "Valid", Text: &text},
		{Key: "", Title: "EmptyKey", Text: &text},      // will be rejected
		{Key: "notitle", Title: "", Text: &text},        // will be rejected
	}

	var buf bytes.Buffer
	result, err := ExportTiddlersJSONL(&buf, entries, "test-run-002")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if result.Manifest.ExportedCount != 1 {
		t.Errorf("ExportedCount = %d, want 1", result.Manifest.ExportedCount)
	}
	if result.Manifest.SkippedByGate != 2 {
		t.Errorf("SkippedByGate = %d, want 2", result.Manifest.SkippedByGate)
	}

	// Verify JSONL output: only 1 line
	lines := strings.Split(strings.TrimSpace(buf.String()), "\n")
	if len(lines) != 1 {
		t.Fatalf("JSONL lines = %d, want 1", len(lines))
	}

	// Verify log has 3 entries (1 included + 2 excluded)
	if len(result.LogEntries) != 3 {
		t.Fatalf("LogEntries = %d, want 3", len(result.LogEntries))
	}

	excludedCount := 0
	for _, entry := range result.LogEntries {
		if entry.Action == "excluded" {
			excludedCount++
			if entry.RuleID != "gate-v0" {
				t.Errorf("excluded entry rule_id = %q, want %q", entry.RuleID, "gate-v0")
			}
		}
	}
	if excludedCount != 2 {
		t.Errorf("excluded count = %d, want 2", excludedCount)
	}
}

// TestExportTiddlersJSONL_EmptyInput verifies export with no entries.
func TestExportTiddlersJSONL_EmptyInput(t *testing.T) {
	var buf bytes.Buffer
	result, err := ExportTiddlersJSONL(&buf, nil, "test-run-empty")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.Manifest.ExportedCount != 0 {
		t.Errorf("ExportedCount = %d, want 0", result.Manifest.ExportedCount)
	}
	if buf.Len() != 0 {
		t.Errorf("output should be empty, got %d bytes", buf.Len())
	}
}

// TestExportTiddlersJSONL_NoDuplication verifies that each tiddler
// appears exactly once in the output (no silent duplication).
func TestExportTiddlersJSONL_NoDuplication(t *testing.T) {
	text := "content"
	entries := []CanonEntry{
		{Key: "a", Title: "A", Text: &text},
		{Key: "b", Title: "B", Text: &text},
		{Key: "c", Title: "C", Text: &text},
	}

	var buf bytes.Buffer
	result, err := ExportTiddlersJSONL(&buf, entries, "test-run-dedup")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	lines := strings.Split(strings.TrimSpace(buf.String()), "\n")
	if len(lines) != 3 {
		t.Fatalf("JSONL lines = %d, want 3", len(lines))
	}

	// Check unique keys
	seen := make(map[string]bool)
	for i, line := range lines {
		var entry CanonEntry
		if err := json.Unmarshal([]byte(line), &entry); err != nil {
			t.Errorf("line[%d] invalid JSON: %v", i, err)
			continue
		}
		if seen[string(entry.Key)] {
			t.Errorf("duplicate key %q at line %d", entry.Key, i)
		}
		seen[string(entry.Key)] = true
	}

	if result.Manifest.ExportedCount != 3 {
		t.Errorf("ExportedCount = %d, want 3", result.Manifest.ExportedCount)
	}
}
