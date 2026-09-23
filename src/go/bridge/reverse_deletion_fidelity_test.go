package bridge

import (
	"encoding/json"
	"strings"
	"testing"

	"github.com/tiddly-data-converter/canon"
)

// P7-C-R1: STORE MEMBERSHIP fidelity. Under `preserve` the base HTML decides
// membership (a Canon deletion resurrects); under `replace` the output membership is
// CANON_PROJECTED_TITLE_SET UNION STRUCTURAL_KEEP_SET (base titles starting with "$:/").

const (
	staleDeletedTitle = "Deleted Delta" // was in an old base, deleted from Canon
	staleExtraTitle   = "Extra Gamma"   // base-only, non structural
	structuralExtra   = "$:/plugins/tdc/structural-extra"
)

func deletionFidelityBase(t *testing.T) []byte {
	t.Helper()
	base := mustReadReverseFixture(t, "s42", "base.html")
	replaced := strings.Replace(
		string(base),
		"{\"title\":\"$:/SiteTitle\",\"text\":\"s42-base\"}",
		"{\"title\":\""+staleDeletedTitle+"\",\"text\":\"stale\"},"+
			"{\"title\":\""+staleExtraTitle+"\",\"text\":\"g\"},"+
			"{\"title\":\""+structuralExtra+"\",\"text\":\"s\"},"+
			"{\"title\":\"$:/SiteTitle\",\"text\":\"s42-base\"}",
		1,
	)
	if replaced == string(base) {
		t.Fatal("fixture substitution did not apply")
	}
	return []byte(replaced)
}

func canonTitlesOfFixture(t *testing.T, canonJSONL []byte) []string {
	t.Helper()
	var titles []string
	for _, line := range strings.Split(strings.TrimSpace(string(canonJSONL)), "\n") {
		var rec struct {
			Title string `json:"title"`
		}
		if err := json.Unmarshal([]byte(line), &rec); err != nil {
			t.Fatalf("canon fixture line: %v", err)
		}
		titles = append(titles, rec.Title)
	}
	return titles
}

func titlesOf(items []map[string]interface{}) []string {
	out := make([]string, 0, len(items))
	for _, it := range items {
		if s, ok := it["title"].(string); ok {
			out = append(out, s)
		}
	}
	return out
}

func runPolicy(t *testing.T, policy string) (*ReverseResult, []map[string]interface{}) {
	t.Helper()
	canonJSONL := mustReadReverseFixture(t, "s42", "canon_with_new_valid.jsonl")
	result, err := reverseHTMLWithMode(deletionFidelityBase(t), canonJSONL, canon.CanonSourceReport{}, ReverseModeAuthoritativeUpsert, policy)
	if err != nil {
		t.Fatalf("reverse %s: %v", policy, err)
	}
	return result, parseStoreItemsFromHTML(t, result.HTML)
}

func TestStoreMembership_PreserveKeepsBaseOnlyIncludingDeletedCanonTitles(t *testing.T) {
	_, items := runPolicy(t, ReverseStorePolicyPreserve)
	for _, title := range []string{staleDeletedTitle, staleExtraTitle} {
		if !storeContainsTitle(items, title) {
			t.Fatalf("preserve should keep base-only %q (this is the resurrection defect)", title)
		}
	}
}

func TestStoreMembership_ReplaceDropsBaseOnlyNonStructural(t *testing.T) {
	result, items := runPolicy(t, ReverseStorePolicyReplace)
	for _, title := range []string{staleDeletedTitle, staleExtraTitle} {
		if storeContainsTitle(items, title) {
			t.Fatalf("replace must drop non structural base-only %q", title)
		}
	}
	if result.Report.BaseTiddlersDropped != 2 {
		t.Fatalf("BaseTiddlersDropped = %d, want 2", result.Report.BaseTiddlersDropped)
	}
}

func TestStoreMembership_ReplaceKeepsStructuralAndAllCanon(t *testing.T) {
	canonJSONL := mustReadReverseFixture(t, "s42", "canon_with_new_valid.jsonl")
	_, items := runPolicy(t, ReverseStorePolicyReplace)
	for _, title := range []string{"$:/SiteTitle", structuralExtra} {
		if !storeContainsTitle(items, title) {
			t.Fatalf("replace must keep structural %q", title)
		}
	}
	for _, title := range canonTitlesOfFixture(t, canonJSONL) {
		if !storeContainsTitle(items, title) {
			t.Fatalf("replace lost canon title %q", title)
		}
	}
}

func TestStoreMembership_DeletedCanonTitleDoesNotResurrectUnderReplace(t *testing.T) {
	canonJSONL := mustReadReverseFixture(t, "s42", "canon_with_new_valid.jsonl")
	if slicesContains(canonTitlesOfFixture(t, canonJSONL), staleDeletedTitle) {
		t.Fatal("test premise broken: the deleted title is in the canon fixture")
	}
	_, preserved := runPolicy(t, ReverseStorePolicyPreserve)
	_, replaced := runPolicy(t, ReverseStorePolicyReplace)
	if !storeContainsTitle(preserved, staleDeletedTitle) || storeContainsTitle(replaced, staleDeletedTitle) {
		t.Fatal("expected: resurrected under preserve, absent under replace")
	}
}

func TestStoreMembership_ReplaceHasNoDuplicateTitlesAndReportMatchesOutput(t *testing.T) {
	canonJSONL := mustReadReverseFixture(t, "s42", "canon_with_new_valid.jsonl")
	result, items := runPolicy(t, ReverseStorePolicyReplace)
	titles := titlesOf(items)
	seen := map[string]bool{}
	for _, title := range titles {
		if seen[title] {
			t.Fatalf("duplicate title in replace output: %q", title)
		}
		seen[title] = true
	}
	canonSet := map[string]bool{}
	for _, title := range canonTitlesOfFixture(t, canonJSONL) {
		canonSet[title] = true
	}
	structural := 0
	for _, title := range titles {
		if !canonSet[title] {
			if !strings.HasPrefix(title, "$:/") {
				t.Fatalf("non-canon, non-structural title survived: %q", title)
			}
			structural++
		}
	}
	if result.Report.StructuralTiddlersKept != structural {
		t.Fatalf("StructuralTiddlersKept = %d, output structural = %d", result.Report.StructuralTiddlersKept, structural)
	}
	if result.Report.OutputTiddlers != len(titles) {
		t.Fatalf("OutputTiddlers = %d, store has %d", result.Report.OutputTiddlers, len(titles))
	}
}

func slicesContains(list []string, want string) bool {
	for _, v := range list {
		if v == want {
			return true
		}
	}
	return false
}
