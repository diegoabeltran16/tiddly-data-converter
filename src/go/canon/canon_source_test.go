package canon

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestLoadCanonSource_ShardedOrdersNumerically(t *testing.T) {
	tmpDir := t.TempDir()

	writeCanonSourceTestShard(t, tmpDir, "tiddlers_2.jsonl", []CanonEntry{
		canonSourceTestEntry("Shard Two"),
	})
	writeCanonSourceTestShard(t, tmpDir, "tiddlers_1.jsonl", []CanonEntry{
		canonSourceTestEntry("Shard One"),
	})

	data, report, err := LoadCanonSource(tmpDir)
	if err != nil {
		t.Fatalf("LoadCanonSource: %v", err)
	}
	if report.Mode != CanonSourceModeSharded {
		t.Fatalf("Mode = %q, want %q", report.Mode, CanonSourceModeSharded)
	}
	if len(report.Shards) != 2 {
		t.Fatalf("len(Shards) = %d, want 2", len(report.Shards))
	}
	if !strings.HasSuffix(report.InputPaths[0], "tiddlers_1.jsonl") {
		t.Fatalf("first shard path = %q, want tiddlers_1.jsonl first", report.InputPaths[0])
	}

	entries, err := ParseCanonJSONL(strings.NewReader(string(data)))
	if err != nil {
		t.Fatalf("ParseCanonJSONL: %v", err)
	}
	if len(entries) != 2 {
		t.Fatalf("len(entries) = %d, want 2", len(entries))
	}
	if entries[0].Title != "Shard One" || entries[1].Title != "Shard Two" {
		t.Fatalf("unexpected shard order: %q then %q", entries[0].Title, entries[1].Title)
	}
}

func TestLoadCanonSource_ShardedRejectsDuplicateShardContent(t *testing.T) {
	tmpDir := t.TempDir()
	entries := []CanonEntry{canonSourceTestEntry("Duplicate Shard")}

	writeCanonSourceTestShard(t, tmpDir, "tiddlers_1.jsonl", entries)
	writeCanonSourceTestShard(t, tmpDir, "tiddlers_2.jsonl", entries)

	_, report, err := LoadCanonSource(tmpDir)
	if err == nil {
		t.Fatal("expected duplicate shard content error, got nil")
	}
	if report.OK() {
		t.Fatal("report.OK() = true, want false")
	}
	if !canonSourceReportHasRule(report, "duplicate-shard-content") {
		t.Fatalf("expected duplicate-shard-content issue, got %+v", report.Issues)
	}
}

func TestLoadCanonSource_ShardedRejectsDuplicateTitlesAcrossShards(t *testing.T) {
	tmpDir := t.TempDir()

	writeCanonSourceTestShard(t, tmpDir, "tiddlers_1.jsonl", []CanonEntry{
		canonSourceTestEntry("Repeated Title"),
	})
	writeCanonSourceTestShard(t, tmpDir, "tiddlers_2.jsonl", []CanonEntry{
		canonSourceTestEntry("Repeated Title"),
	})

	_, report, err := LoadCanonSource(tmpDir)
	if err == nil {
		t.Fatal("expected duplicate title error, got nil")
	}
	if !canonSourceReportHasRule(report, "duplicate-title") {
		t.Fatalf("expected duplicate-title issue, got %+v", report.Issues)
	}
}

func canonSourceTestEntry(title string) CanonEntry {
	return CanonEntry{
		SchemaVersion: SchemaV0,
		Key:           KeyOf(title),
		Title:         title,
	}
}

func writeCanonSourceTestShard(t *testing.T, dir, name string, entries []CanonEntry) {
	t.Helper()
	data, err := MarshalCanonJSONL(entries)
	if err != nil {
		t.Fatalf("MarshalCanonJSONL(%s): %v", name, err)
	}
	path := filepath.Join(dir, name)
	if err := os.WriteFile(path, data, 0o644); err != nil {
		t.Fatalf("WriteFile(%s): %v", path, err)
	}
}

func canonSourceReportHasRule(report CanonSourceReport, ruleID string) bool {
	for _, issue := range report.Issues {
		if issue.RuleID == ruleID {
			return true
		}
	}
	return false
}
