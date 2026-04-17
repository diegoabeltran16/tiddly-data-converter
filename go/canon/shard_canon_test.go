package canon

import (
	"fmt"
	"strings"
	"testing"
)

func TestShardCanonJSONL_ClassifiesSessionFamilies(t *testing.T) {
	input := strings.Join([]string{
		`{"title":"_README.md"}`,
		`{"title":"#### 🌀📦 Política de dependencias"}`,
		`{"title":"#### 🌀 Sesión 44 = canon-sharded-homogeneous-records-and-robust-reverse-v0"}`,
		`{"title":"#### 🌀🧪 Hipótesis de sesión 44 = canon-sharded-homogeneous-records-and-robust-reverse-v0"}`,
		`{"title":"#### 🌀🧾 Procedencia de sesión 44"}`,
		`{"title":"#### referencias especificas 🌀"}`,
		`{"title":"01. Reference title"}`,
		`{"title":"go/canon/example.go"}`,
	}, "\n") + "\n"

	shards, report, err := ShardCanonJSONL(strings.NewReader(input))
	if err != nil {
		t.Fatalf("ShardCanonJSONL() error = %v", err)
	}

	if report.SessionCount != 1 || len(shards["tiddlers_2.jsonl"]) != 1 {
		t.Fatalf("session shard mismatch: report=%d shard=%d", report.SessionCount, len(shards["tiddlers_2.jsonl"]))
	}
	if report.HypothesisCount != 2 || len(shards["tiddlers_3.jsonl"]) != 2 {
		t.Fatalf("hypothesis shard mismatch: report=%d shard=%d", report.HypothesisCount, len(shards["tiddlers_3.jsonl"]))
	}
	if report.ProvenanceCount != 3 || len(shards["tiddlers_4.jsonl"]) != 3 {
		t.Fatalf("provenance shard mismatch: report=%d shard=%d", report.ProvenanceCount, len(shards["tiddlers_4.jsonl"]))
	}
	if got := len(shards["tiddlers_1.jsonl"]); got != 2 {
		t.Fatalf("tiddlers_1.jsonl count = %d, want 2", got)
	}
	if !strings.Contains(shards["tiddlers_3.jsonl"][0], `"title":"#### 🌀📦 Política de dependencias"`) {
		t.Fatalf("shard 3 pinned block order mismatch: %q", shards["tiddlers_3.jsonl"][0])
	}
	if !strings.Contains(shards["tiddlers_4.jsonl"][0], `"title":"#### 🌀🧾 Procedencia de sesión 44"`) {
		t.Fatalf("shard 4 provenance-first order mismatch: %q", shards["tiddlers_4.jsonl"][0])
	}
}

func TestShardCanonJSONL_PreservesRemainingOrderAcrossAuxShards(t *testing.T) {
	var lines []string
	for i := 0; i < 290; i++ {
		lines = append(lines, fmt.Sprintf(`{"title":"node-%03d"}`, i))
	}
	input := strings.Join(lines, "\n") + "\n"

	shards, report, err := ShardCanonJSONL(strings.NewReader(input))
	if err != nil {
		t.Fatalf("ShardCanonJSONL() error = %v", err)
	}

	if report.ShardLineCounts["tiddlers_1.jsonl"] != 2 {
		t.Fatalf("tiddlers_1.jsonl count = %d, want 2", report.ShardLineCounts["tiddlers_1.jsonl"])
	}
	if report.ShardLineCounts["tiddlers_5.jsonl"] != 144 {
		t.Fatalf("tiddlers_5.jsonl count = %d, want 144", report.ShardLineCounts["tiddlers_5.jsonl"])
	}
	if report.ShardLineCounts["tiddlers_6.jsonl"] != 144 {
		t.Fatalf("tiddlers_6.jsonl count = %d, want 144", report.ShardLineCounts["tiddlers_6.jsonl"])
	}
	if report.ShardLineCounts["tiddlers_7.jsonl"] != 0 {
		t.Fatalf("tiddlers_7.jsonl count = %d, want 0", report.ShardLineCounts["tiddlers_7.jsonl"])
	}

	if !strings.Contains(shards["tiddlers_1.jsonl"][0], `"title":"node-000"`) {
		t.Fatalf("first auxiliary line not preserved: %q", shards["tiddlers_1.jsonl"][0])
	}
	if !strings.Contains(shards["tiddlers_6.jsonl"][143], `"title":"node-289"`) {
		t.Fatalf("last filled auxiliary line not preserved: %q", shards["tiddlers_6.jsonl"][143])
	}
}

func TestShardCanonJSONL_FailsOnInvalidJSON(t *testing.T) {
	_, _, err := ShardCanonJSONL(strings.NewReader("{not-json}\n"))
	if err == nil {
		t.Fatal("expected parse error")
	}
}

func TestShardCanonJSONL_FailsWhenAuxCapacityExceeded(t *testing.T) {
	var builder strings.Builder
	for i := 0; i < (auxShardMaxLines*len(auxShardOrder))+1; i++ {
		builder.WriteString(`{"title":"node-overflow"}` + "\n")
	}

	_, _, err := ShardCanonJSONL(strings.NewReader(builder.String()))
	if err == nil {
		t.Fatal("expected overflow error")
	}
}
