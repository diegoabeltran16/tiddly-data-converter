package bridge

import (
	"strings"
	"testing"
)

// TestExtractRawTiddlersFromHTML_MinimalFixture verifies extraction from
// a minimal TiddlyWiki HTML fixture with known tiddlers.
func TestExtractRawTiddlersFromHTML_MinimalFixture(t *testing.T) {
	html := `<!DOCTYPE html>
<html>
<head><title>Test</title></head>
<body>
<script class="tiddlywiki-tiddler-store" type="application/json">[
{"title":"Alpha","created":"20260101120000000","modified":"20260101130000000","tags":"tag1 tag2","type":"text/vnd.tiddlywiki","text":"Content of Alpha"},
{"title":"Beta","created":"20260102120000000","tags":"tag3","text":"Content of Beta"},
{"title":"No Text Tiddler","created":"20260103120000000"},
{"title":"$:/SiteTitle","text":"my-wiki"}
]</script>
</body>
</html>`

	raws, result, err := ExtractRawTiddlersFromHTML(strings.NewReader(html))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if result.BlocksFound != 1 {
		t.Errorf("BlocksFound = %d, want 1", result.BlocksFound)
	}
	if result.TotalExtracted != 4 {
		t.Errorf("TotalExtracted = %d, want 4", result.TotalExtracted)
	}
	if len(raws) != 4 {
		t.Fatalf("len(raws) = %d, want 4", len(raws))
	}

	// Check Alpha
	alpha := raws[0]
	if alpha.Title != "Alpha" {
		t.Errorf("raws[0].Title = %q, want %q", alpha.Title, "Alpha")
	}
	if alpha.RawText == nil || *alpha.RawText != "Content of Alpha" {
		t.Errorf("raws[0].RawText = %v, want %q", alpha.RawText, "Content of Alpha")
	}
	if alpha.RawFields["created"] != "20260101120000000" {
		t.Errorf("raws[0].created = %q", alpha.RawFields["created"])
	}
	if alpha.RawFields["tags"] != "tag1 tag2" {
		t.Errorf("raws[0].tags = %q", alpha.RawFields["tags"])
	}

	// Check No Text Tiddler (RawText should be nil)
	noText := raws[2]
	if noText.RawText != nil {
		t.Errorf("raws[2].RawText = %v, want nil", noText.RawText)
	}

	// Check SourcePosition
	if alpha.SourcePosition == nil || *alpha.SourcePosition != "html:block0:tiddler0" {
		t.Errorf("raws[0].SourcePosition = %v, want %q", alpha.SourcePosition, "html:block0:tiddler0")
	}
}

// TestExtractRawTiddlersFromHTML_NoBlocks verifies error on missing blocks.
func TestExtractRawTiddlersFromHTML_NoBlocks(t *testing.T) {
	html := `<!DOCTYPE html><html><body>No tiddler stores here</body></html>`
	_, result, err := ExtractRawTiddlersFromHTML(strings.NewReader(html))
	if err == nil {
		t.Fatal("expected error for missing blocks")
	}
	if result.BlocksFound != 0 {
		t.Errorf("BlocksFound = %d, want 0", result.BlocksFound)
	}
}

// TestExtractRawTiddlersFromHTML_MultipleBlocks verifies extraction from
// multiple tiddler-store blocks in a single HTML file.
func TestExtractRawTiddlersFromHTML_MultipleBlocks(t *testing.T) {
	html := `<!DOCTYPE html>
<html><body>
<script class="tiddlywiki-tiddler-store" type="application/json">[
{"title":"A","text":"a"}
]</script>
<script class="tiddlywiki-tiddler-store" type="application/json">[
{"title":"B","text":"b"},
{"title":"C","text":"c"}
]</script>
</body></html>`

	raws, result, err := ExtractRawTiddlersFromHTML(strings.NewReader(html))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.BlocksFound != 2 {
		t.Errorf("BlocksFound = %d, want 2", result.BlocksFound)
	}
	if result.TotalExtracted != 3 {
		t.Errorf("TotalExtracted = %d, want 3", result.TotalExtracted)
	}
	if len(raws) != 3 {
		t.Fatalf("len(raws) = %d, want 3", len(raws))
	}
	// Verify SourcePosition tracks block index
	if sp := *raws[1].SourcePosition; sp != "html:block1:tiddler0" {
		t.Errorf("raws[1].SourcePosition = %q, want %q", sp, "html:block1:tiddler0")
	}
}

// TestApplyFilterRules_DefaultRules verifies the S33 default filtering
// rules: system tiddlers excluded, user tiddlers included.
func TestApplyFilterRules_DefaultRules(t *testing.T) {
	html := `<html><body>
<script class="tiddlywiki-tiddler-store" type="application/json">[
{"title":"User Tiddler","text":"user content"},
{"title":"$:/SiteTitle","text":"my-wiki"},
{"title":"$:/plugins/tiddlywiki/markdown","text":"plugin"},
{"title":"Another User","text":"more content"}
]</script>
</body></html>`

	raws, _, err := ExtractRawTiddlersFromHTML(strings.NewReader(html))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	rules := DefaultFunctionalTiddlerRules()
	included, logEntries := ApplyFilterRules(raws, rules, "test-run-001")

	// Expect 2 user tiddlers included, 2 system excluded
	if len(included) != 2 {
		t.Errorf("len(included) = %d, want 2", len(included))
	}
	if len(logEntries) != 4 {
		t.Errorf("len(logEntries) = %d, want 4", len(logEntries))
	}

	// Verify included are user tiddlers
	for _, inc := range included {
		if strings.HasPrefix(inc.Title, "$:/") {
			t.Errorf("system tiddler %q should not be included", inc.Title)
		}
	}

	// Verify log entries
	excludedCount := 0
	includedCount := 0
	for _, entry := range logEntries {
		switch entry.Action {
		case "excluded":
			excludedCount++
			if entry.RuleID != "R1-exclude-system" {
				t.Errorf("excluded entry rule_id = %q, want %q", entry.RuleID, "R1-exclude-system")
			}
		case "included":
			includedCount++
		}
		if entry.RunID != "test-run-001" {
			t.Errorf("run_id = %q, want %q", entry.RunID, "test-run-001")
		}
	}
	if excludedCount != 2 {
		t.Errorf("excludedCount = %d, want 2", excludedCount)
	}
	if includedCount != 2 {
		t.Errorf("includedCount = %d, want 2", includedCount)
	}
}

// TestFilterRule_Reversibility verifies that the filtering rules are
// reversible: all tiddlers can be included by using an empty rule set.
func TestFilterRule_Reversibility(t *testing.T) {
	html := `<html><body>
<script class="tiddlywiki-tiddler-store" type="application/json">[
{"title":"User","text":"u"},
{"title":"$:/System","text":"s"}
]</script>
</body></html>`

	raws, _, err := ExtractRawTiddlersFromHTML(strings.NewReader(html))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	// Empty rules = include all
	included, _ := ApplyFilterRules(raws, nil, "test-run")
	if len(included) != 2 {
		t.Errorf("with no rules, len(included) = %d, want 2", len(included))
	}
}
