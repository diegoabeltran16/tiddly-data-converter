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
