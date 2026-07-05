package canon

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestShardCanonJSONL_SequentialDefaultMaxLines(t *testing.T) {
	input := shardTestInput(205)

	shards, report, err := ShardCanonJSONL(strings.NewReader(input))
	if err != nil {
		t.Fatalf("ShardCanonJSONL() error = %v", err)
	}

	if report.PolicyID != "sequential-max-lines-v0" {
		t.Fatalf("policy_id = %q, want sequential-max-lines-v0", report.PolicyID)
	}
	if report.ShardMaxLines != DefaultCanonShardMaxLines {
		t.Fatalf("shard max lines = %d, want %d", report.ShardMaxLines, DefaultCanonShardMaxLines)
	}
	wantOrder := []string{"tiddlers_1.jsonl", "tiddlers_2.jsonl", "tiddlers_3.jsonl"}
	if !stringSliceEqual(report.ShardOrder, wantOrder) {
		t.Fatalf("shard order = %v, want %v", report.ShardOrder, wantOrder)
	}
	if report.ShardLineCounts["tiddlers_1.jsonl"] != 100 {
		t.Fatalf("tiddlers_1.jsonl count = %d, want 100", report.ShardLineCounts["tiddlers_1.jsonl"])
	}
	if report.ShardLineCounts["tiddlers_2.jsonl"] != 100 {
		t.Fatalf("tiddlers_2.jsonl count = %d, want 100", report.ShardLineCounts["tiddlers_2.jsonl"])
	}
	if report.ShardLineCounts["tiddlers_3.jsonl"] != 5 {
		t.Fatalf("tiddlers_3.jsonl count = %d, want 5", report.ShardLineCounts["tiddlers_3.jsonl"])
	}
	if _, exists := shards["tiddlers_4.jsonl"]; exists {
		t.Fatal("unexpected empty tiddlers_4.jsonl shard")
	}
	if !strings.Contains(shards["tiddlers_1.jsonl"][0], `"title":"node-000"`) {
		t.Fatalf("first line not preserved: %q", shards["tiddlers_1.jsonl"][0])
	}
	if !strings.Contains(shards["tiddlers_3.jsonl"][4], `"title":"node-204"`) {
		t.Fatalf("last line not preserved: %q", shards["tiddlers_3.jsonl"][4])
	}
}

func TestShardCanonJSONLWithMaxLines_PreservesOrder(t *testing.T) {
	input := shardTestInput(5)

	shards, report, err := ShardCanonJSONLWithMaxLines(strings.NewReader(input), 3)
	if err != nil {
		t.Fatalf("ShardCanonJSONLWithMaxLines() error = %v", err)
	}

	wantOrder := []string{"tiddlers_1.jsonl", "tiddlers_2.jsonl"}
	if !stringSliceEqual(report.ShardOrder, wantOrder) {
		t.Fatalf("shard order = %v, want %v", report.ShardOrder, wantOrder)
	}
	if report.ShardLineCounts["tiddlers_1.jsonl"] != 3 {
		t.Fatalf("tiddlers_1.jsonl count = %d, want 3", report.ShardLineCounts["tiddlers_1.jsonl"])
	}
	if report.ShardLineCounts["tiddlers_2.jsonl"] != 2 {
		t.Fatalf("tiddlers_2.jsonl count = %d, want 2", report.ShardLineCounts["tiddlers_2.jsonl"])
	}
	if !strings.Contains(shards["tiddlers_2.jsonl"][0], `"title":"node-003"`) {
		t.Fatalf("first second-shard line not preserved: %q", shards["tiddlers_2.jsonl"][0])
	}
}

func TestShardCanonJSONL_FailsOnInvalidJSON(t *testing.T) {
	_, _, err := ShardCanonJSONL(strings.NewReader("{not-json}\n"))
	if err == nil {
		t.Fatal("expected parse error")
	}
}

func TestShardCanonJSONLWithMaxLines_FailsOnInvalidLimit(t *testing.T) {
	_, _, err := ShardCanonJSONLWithMaxLines(strings.NewReader(shardTestInput(1)), 0)
	if err == nil {
		t.Fatal("expected invalid limit error")
	}
}

func TestWriteShardSetWithMaxLines_ReplacesOnlyCanonShards(t *testing.T) {
	tmpDir := t.TempDir()
	inputPath := filepath.Join(tmpDir, "tiddlers.export.jsonl")
	outDir := filepath.Join(tmpDir, "canon")
	if err := os.WriteFile(inputPath, []byte(shardTestInput(3)), 0o644); err != nil {
		t.Fatalf("write input: %v", err)
	}
	if err := os.MkdirAll(outDir, 0o755); err != nil {
		t.Fatalf("mkdir out: %v", err)
	}
	if err := os.WriteFile(filepath.Join(outDir, "tiddlers_99.jsonl"), []byte(`{"title":"stale"}`+"\n"), 0o644); err != nil {
		t.Fatalf("write stale shard: %v", err)
	}
	if err := os.WriteFile(filepath.Join(outDir, "notes.txt"), []byte("keep me\n"), 0o644); err != nil {
		t.Fatalf("write non-shard file: %v", err)
	}

	report, err := WriteShardSetWithMaxLines(inputPath, outDir, 2)
	if err != nil {
		t.Fatalf("WriteShardSetWithMaxLines() error = %v", err)
	}

	if _, err := os.Stat(filepath.Join(outDir, "tiddlers_99.jsonl")); !os.IsNotExist(err) {
		t.Fatalf("stale shard should be removed, stat err = %v", err)
	}
	if _, err := os.Stat(filepath.Join(outDir, "notes.txt")); err != nil {
		t.Fatalf("non-shard file should remain: %v", err)
	}
	if report.ShardLineCounts["tiddlers_1.jsonl"] != 2 || report.ShardLineCounts["tiddlers_2.jsonl"] != 1 {
		t.Fatalf("unexpected shard line counts: %v", report.ShardLineCounts)
	}
	if got := countShardTestLines(t, filepath.Join(outDir, "tiddlers_1.jsonl")); got != 2 {
		t.Fatalf("tiddlers_1.jsonl lines = %d, want 2", got)
	}
	if got := countShardTestLines(t, filepath.Join(outDir, "tiddlers_2.jsonl")); got != 1 {
		t.Fatalf("tiddlers_2.jsonl lines = %d, want 1", got)
	}
}

func shardTestInput(count int) string {
	var lines []string
	for i := 0; i < count; i++ {
		lines = append(lines, fmt.Sprintf(`{"title":"node-%03d"}`, i))
	}
	return strings.Join(lines, "\n") + "\n"
}

func countShardTestLines(t *testing.T, path string) int {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read %s: %v", path, err)
	}
	return len(strings.Split(strings.TrimSpace(string(data)), "\n"))
}
