package ingesta

import (
	"testing"
)

func TestParseTW5Tags_Simple(t *testing.T) {
	tags, err := ParseTW5Tags("alpha beta gamma")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	expected := []string{"alpha", "beta", "gamma"}
	if len(tags) != len(expected) {
		t.Fatalf("expected %d tags, got %d", len(expected), len(tags))
	}
	for i, e := range expected {
		if tags[i] != e {
			t.Errorf("tag[%d]: expected %q, got %q", i, e, tags[i])
		}
	}
}

func TestParseTW5Tags_Bracketed(t *testing.T) {
	tags, err := ParseTW5Tags("[[multi word]] simple [[another one]]")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	expected := []string{"multi word", "simple", "another one"}
	if len(tags) != len(expected) {
		t.Fatalf("expected %d tags, got %d", len(expected), len(tags))
	}
	for i, e := range expected {
		if tags[i] != e {
			t.Errorf("tag[%d]: expected %q, got %q", i, e, tags[i])
		}
	}
}

func TestParseTW5Tags_Empty(t *testing.T) {
	tags, err := ParseTW5Tags("")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(tags) != 0 {
		t.Errorf("expected 0 tags, got %d", len(tags))
	}
}

func TestParseTW5Timestamp_Valid(t *testing.T) {
	ts, err := parseTW5Timestamp("20250531001441132")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if ts == nil {
		t.Fatal("expected non-nil timestamp")
	}
	if ts.Year() != 2025 || ts.Month() != 5 || ts.Day() != 31 {
		t.Errorf("unexpected date: %v", ts)
	}
}

func TestParseTW5Timestamp_Empty(t *testing.T) {
	ts, err := parseTW5Timestamp("")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if ts != nil {
		t.Error("expected nil for empty input")
	}
}

func TestParseTW5Timestamp_Malformed(t *testing.T) {
	ts, err := parseTW5Timestamp("not-a-date")
	if err == nil {
		t.Error("expected error for malformed timestamp")
	}
	if ts != nil {
		t.Error("expected nil for malformed timestamp")
	}
}

// TestParseTW5Timestamp_WithMilliseconds validates S09 policy:
// milliseconds should be preserved when present in TW5 timestamps.
//
// Evidence from S08: 337/338 timestamps in real corpus have non-zero
// milliseconds. Preserving them maintains temporal precision without
// semantic loss.
func TestParseTW5Timestamp_WithMilliseconds(t *testing.T) {
	// Real case from S08 fixture: created=20260409180825708
	ts, err := parseTW5Timestamp("20260409180825708")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if ts == nil {
		t.Fatal("expected non-nil timestamp")
	}

	// Verify base timestamp
	if ts.Year() != 2026 || ts.Month() != 4 || ts.Day() != 9 {
		t.Errorf("unexpected date: %v", ts)
	}
	if ts.Hour() != 18 || ts.Minute() != 8 || ts.Second() != 25 {
		t.Errorf("unexpected time: %v", ts)
	}

	// Verify milliseconds are preserved (708ms = 708,000,000 nanoseconds)
	expectedNanos := 708 * 1000000
	actualNanos := ts.Nanosecond()
	if actualNanos != expectedNanos {
		t.Errorf("milliseconds not preserved: expected %dns, got %dns", expectedNanos, actualNanos)
	}

	// Additional case: timestamp with 0 milliseconds
	ts2, err := parseTW5Timestamp("20250531001441000")
	if err != nil {
		t.Fatalf("unexpected error for 000 ms: %v", err)
	}
	if ts2.Nanosecond() != 0 {
		t.Errorf("expected 0 nanoseconds, got %d", ts2.Nanosecond())
	}

	// Edge case: 999 milliseconds
	ts3, err := parseTW5Timestamp("20250531001441999")
	if err != nil {
		t.Fatalf("unexpected error for 999 ms: %v", err)
	}
	expectedNanos3 := 999 * 1000000
	if ts3.Nanosecond() != expectedNanos3 {
		t.Errorf("999ms not preserved: expected %dns, got %dns", expectedNanos3, ts3.Nanosecond())
	}
}

// TestParseTW5Timestamp_14DigitsOnly validates backward compatibility:
// timestamps with only 14 digits (no milliseconds) still work.
func TestParseTW5Timestamp_14DigitsOnly(t *testing.T) {
	ts, err := parseTW5Timestamp("20250531001441")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if ts == nil {
		t.Fatal("expected non-nil timestamp")
	}
	// Should have 0 milliseconds
	if ts.Nanosecond() != 0 {
		t.Errorf("expected 0 nanoseconds for 14-digit timestamp, got %d", ts.Nanosecond())
	}
}
