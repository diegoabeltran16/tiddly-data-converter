package bridge_test

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/tiddly-data-converter/bridge"
	"github.com/tiddly-data-converter/canon"
	"github.com/tiddly-data-converter/ingesta"
)

// ---------------------------------------------------------------------------
// S20 — E2E smoke test: raw fixture → Ingesta → Bridge → Admit → Writer → Gate
// ---------------------------------------------------------------------------
//
// This file implements the smoke E2E test for the stabilized canonical path:
//   raw fixture / pre-canonical → Ingesta → bridge → admission v0 → writer JSONL → gate v0
//
// The goal is to provide reproducible, minimal evidence that the full path
// produces valid canon.jsonl output accepted by the gate, and that deliberate
// structural corruption is caught with useful diagnostics.
//
// Ref: S20 — canon-gate-e2e-smoke.
// Ref: S14 — bridge mínimo.
// Ref: S16 — writer mínimo.
// Ref: S18 — schema v0.
// Ref: S19 — gate v0.

// gateValidateJSONL reads JSONL content and validates each line against the
// schema v0 gate (ValidateEntryV0). Returns counts and error messages.
//
// This is a test-local helper that simulates a post-emission gate reading
// a canon.jsonl artifact and verifying its structural validity.
//
// Ref: S19 — gate v0 validation.
// Ref: S18 — schema v0 shape.
func gateValidateJSONL(data []byte) (valid, invalid int, errors []string) {
	trimmed := bytes.TrimSpace(data)
	if len(trimmed) == 0 {
		return 0, 0, nil
	}
	lines := bytes.Split(trimmed, []byte("\n"))
	for i, line := range lines {
		if len(bytes.TrimSpace(line)) == 0 {
			continue
		}
		var entry canon.CanonEntry
		if err := json.Unmarshal(line, &entry); err != nil {
			invalid++
			errors = append(errors, fmt.Sprintf("line[%d]: JSON parse error: %v", i, err))
			continue
		}
		if err := canon.ValidateEntryV0(entry); err != nil {
			invalid++
			errors = append(errors, fmt.Sprintf("line[%d] title=%q: %v", i, entry.Title, err))
			continue
		}
		valid++
	}
	return
}

// TestSmokeE2E_CanonGate_PositivePath validates the full canonical path
// produces a structurally valid canon.jsonl artifact that passes the gate.
//
// Steps:
//  1. Load raw fixture (pre-canonical input).
//  2. Run Ingesta to produce []Tiddler.
//  3. Bridge to []CanonEntry via ToCanonEntries.
//  4. Run Admit for collision evidence.
//  5. Write canon.jsonl via WriteJSONL to a temp file.
//  6. Read back and validate every line through the gate (ValidateEntryV0).
//
// Ref: S20 — positive smoke path.
func TestSmokeE2E_CanonGate_PositivePath(t *testing.T) {
	// --- Step 1: Load raw fixture ---
	fixturePath := filepath.Join("..", "..", "tests", "fixtures", "raw_tiddlers_smoke_e2e.json")
	tiddlers, report, err := ingesta.Ingest(fixturePath, ingesta.OriginHTML)
	if err != nil {
		t.Fatalf("Ingest: fatal error: %v", err)
	}
	t.Logf("ingest: count=%d ingested=%d skipped=%d verdict=%s",
		report.TiddlerCount, report.IngestedCount, report.SkippedCount, report.Verdict)

	if len(tiddlers) == 0 {
		t.Fatal("Ingest produced 0 tiddlers; expected at least 1")
	}

	// --- Step 2: Bridge to CanonEntry ---
	entries := bridge.ToCanonEntries(tiddlers)
	if len(entries) != len(tiddlers) {
		t.Fatalf("ToCanonEntries: got %d, want %d", len(entries), len(tiddlers))
	}

	// --- Step 3: Admission ---
	admitReport := bridge.Admit(entries)
	t.Logf("admit: %s", admitReport.Summary())

	// All entries in the smoke fixture are distinct (no collisions expected).
	if admitReport.DistinctCount != len(entries) {
		t.Errorf("DistinctCount: got %d, want %d (fixture has no duplicates)",
			admitReport.DistinctCount, len(entries))
	}

	// --- Step 4: Write canon.jsonl to temp file ---
	outDir := t.TempDir()
	outPath := filepath.Join(outDir, "canon.jsonl")
	f, err := os.Create(outPath)
	if err != nil {
		t.Fatalf("create temp file: %v", err)
	}

	writeResult, err := canon.WriteJSONL(f, entries)
	f.Close()
	if err != nil {
		t.Fatalf("WriteJSONL: %v", err)
	}
	t.Logf("write: %s", writeResult.Summary())

	if writeResult.Written != len(entries) {
		t.Errorf("Written: got %d, want %d", writeResult.Written, len(entries))
	}
	if writeResult.Skipped != 0 {
		t.Errorf("Skipped: got %d, want 0", writeResult.Skipped)
	}

	// --- Step 5: Gate validation — read back and validate ---
	data, err := os.ReadFile(outPath)
	if err != nil {
		t.Fatalf("read canon.jsonl: %v", err)
	}

	valid, invalid, gateErrors := gateValidateJSONL(data)
	if invalid != 0 {
		t.Errorf("gate found %d invalid lines (want 0):", invalid)
		for _, e := range gateErrors {
			t.Errorf("  %s", e)
		}
	}
	if valid != writeResult.Written {
		t.Errorf("gate valid=%d, want %d (all written lines)", valid, writeResult.Written)
	}

	t.Logf("gate: valid=%d invalid=%d — positive path OK", valid, invalid)
}

// TestSmokeE2E_CanonGate_NegativePath validates that deliberate structural
// corruption of the canon.jsonl artifact is caught by the gate with useful
// diagnostic messages.
//
// Strategy: produce a valid canon.jsonl, then corrupt one line by removing
// the "key" field and another by injecting invalid JSON, then run the gate.
//
// Ref: S20 — negative smoke path.
func TestSmokeE2E_CanonGate_NegativePath(t *testing.T) {
	// --- Produce valid canon.jsonl first ---
	fixturePath := filepath.Join("..", "..", "tests", "fixtures", "raw_tiddlers_smoke_e2e.json")
	tiddlers, _, err := ingesta.Ingest(fixturePath, ingesta.OriginHTML)
	if err != nil {
		t.Fatalf("Ingest: fatal error: %v", err)
	}
	if len(tiddlers) < 2 {
		t.Fatalf("Ingest: got %d tiddlers, need at least 2 for negative path", len(tiddlers))
	}

	entries := bridge.ToCanonEntries(tiddlers)

	var buf bytes.Buffer
	writeResult, err := canon.WriteJSONL(&buf, entries)
	if err != nil {
		t.Fatalf("WriteJSONL: %v", err)
	}
	if writeResult.Written < 2 {
		t.Fatalf("need at least 2 written lines, got %d", writeResult.Written)
	}

	// --- Corruption 1: remove "key" field from a valid JSONL line ---
	t.Run("CorruptedKey", func(t *testing.T) {
		lines := strings.Split(strings.TrimSpace(buf.String()), "\n")

		// Take the first line and remove the "key" field.
		var obj map[string]interface{}
		if err := json.Unmarshal([]byte(lines[0]), &obj); err != nil {
			t.Fatalf("parse line[0]: %v", err)
		}
		delete(obj, "key")
		corrupted, err := json.Marshal(obj)
		if err != nil {
			t.Fatalf("re-marshal corrupted line: %v", err)
		}

		// Build a JSONL buffer with the corrupted first line + remaining valid lines.
		var corruptBuf bytes.Buffer
		corruptBuf.Write(corrupted)
		corruptBuf.WriteByte('\n')
		for _, ln := range lines[1:] {
			corruptBuf.WriteString(ln)
			corruptBuf.WriteByte('\n')
		}

		valid, invalid, gateErrors := gateValidateJSONL(corruptBuf.Bytes())
		if invalid != 1 {
			t.Errorf("gate invalid: got %d, want 1 (corrupted key line)", invalid)
		}
		if valid != len(lines)-1 {
			t.Errorf("gate valid: got %d, want %d", valid, len(lines)-1)
		}
		if len(gateErrors) < 1 {
			t.Fatal("expected at least 1 gate error for corrupted key")
		}
		if !strings.Contains(gateErrors[0], "key") {
			t.Errorf("gate error should mention 'key': %s", gateErrors[0])
		}
		t.Logf("gate: valid=%d invalid=%d errors=%v — corrupted key detected", valid, invalid, gateErrors)
	})

	// --- Corruption 2: inject invalid JSON ---
	t.Run("InvalidJSON", func(t *testing.T) {
		lines := strings.Split(strings.TrimSpace(buf.String()), "\n")

		var corruptBuf bytes.Buffer
		corruptBuf.WriteString("{this is not valid json}\n")
		for _, ln := range lines {
			corruptBuf.WriteString(ln)
			corruptBuf.WriteByte('\n')
		}

		valid, invalid, gateErrors := gateValidateJSONL(corruptBuf.Bytes())
		if invalid != 1 {
			t.Errorf("gate invalid: got %d, want 1 (injected bad JSON)", invalid)
		}
		if valid != len(lines) {
			t.Errorf("gate valid: got %d, want %d", valid, len(lines))
		}
		if len(gateErrors) < 1 {
			t.Fatal("expected at least 1 gate error for invalid JSON")
		}
		if !strings.Contains(gateErrors[0], "JSON parse error") {
			t.Errorf("gate error should mention 'JSON parse error': %s", gateErrors[0])
		}
		t.Logf("gate: valid=%d invalid=%d errors=%v — invalid JSON detected", valid, invalid, gateErrors)
	})

	// --- Corruption 3: wrong schema_version ---
	t.Run("WrongSchemaVersion", func(t *testing.T) {
		lines := strings.Split(strings.TrimSpace(buf.String()), "\n")

		var obj map[string]interface{}
		if err := json.Unmarshal([]byte(lines[0]), &obj); err != nil {
			t.Fatalf("parse line[0]: %v", err)
		}
		obj["schema_version"] = "v99"
		corrupted, err := json.Marshal(obj)
		if err != nil {
			t.Fatalf("re-marshal corrupted line: %v", err)
		}

		var corruptBuf bytes.Buffer
		corruptBuf.Write(corrupted)
		corruptBuf.WriteByte('\n')
		for _, ln := range lines[1:] {
			corruptBuf.WriteString(ln)
			corruptBuf.WriteByte('\n')
		}

		valid, invalid, gateErrors := gateValidateJSONL(corruptBuf.Bytes())
		if invalid != 1 {
			t.Errorf("gate invalid: got %d, want 1 (wrong schema_version)", invalid)
		}
		if valid != len(lines)-1 {
			t.Errorf("gate valid: got %d, want %d", valid, len(lines)-1)
		}
		if len(gateErrors) < 1 {
			t.Fatal("expected at least 1 gate error for wrong schema_version")
		}
		if !strings.Contains(gateErrors[0], "schema_version") {
			t.Errorf("gate error should mention 'schema_version': %s", gateErrors[0])
		}
		t.Logf("gate: valid=%d invalid=%d errors=%v — wrong schema_version detected", valid, invalid, gateErrors)
	})

	// --- Corruption 4: empty title ---
	t.Run("EmptyTitle", func(t *testing.T) {
		lines := strings.Split(strings.TrimSpace(buf.String()), "\n")

		var obj map[string]interface{}
		if err := json.Unmarshal([]byte(lines[0]), &obj); err != nil {
			t.Fatalf("parse line[0]: %v", err)
		}
		obj["title"] = ""
		corrupted, err := json.Marshal(obj)
		if err != nil {
			t.Fatalf("re-marshal corrupted line: %v", err)
		}

		var corruptBuf bytes.Buffer
		corruptBuf.Write(corrupted)
		corruptBuf.WriteByte('\n')
		for _, ln := range lines[1:] {
			corruptBuf.WriteString(ln)
			corruptBuf.WriteByte('\n')
		}

		valid, invalid, gateErrors := gateValidateJSONL(corruptBuf.Bytes())
		if invalid != 1 {
			t.Errorf("gate invalid: got %d, want 1 (empty title)", invalid)
		}
		if valid != len(lines)-1 {
			t.Errorf("gate valid: got %d, want %d", valid, len(lines)-1)
		}
		if len(gateErrors) < 1 {
			t.Fatal("expected at least 1 gate error for empty title")
		}
		if !strings.Contains(gateErrors[0], "title") {
			t.Errorf("gate error should mention 'title': %s", gateErrors[0])
		}
		t.Logf("gate: valid=%d invalid=%d errors=%v — empty title detected", valid, invalid, gateErrors)
	})
}
