package canon

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func readFixtureJSONL(t *testing.T, name string) []CanonEntry {
	t.Helper()
	path := filepath.Join("..", "..", "tests", "fixtures", "s40", name)
	f, err := os.Open(path)
	if err != nil {
		t.Fatalf("open fixture %s: %v", name, err)
	}
	defer f.Close()
	entries, err := ParseCanonJSONL(f)
	if err != nil {
		t.Fatalf("parse fixture %s: %v", name, err)
	}
	return entries
}

func readFixtureText(t *testing.T, name string) string {
	t.Helper()
	path := filepath.Join("..", "..", "tests", "fixtures", "s40", name)
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read fixture %s: %v", name, err)
	}
	return strings.TrimSpace(string(raw))
}

func TestGuardedMergeIntegration_ValidBatchMatchesExpectedMergedCanon(t *testing.T) {
	base := readFixtureJSONL(t, "base_canon.jsonl")
	candidates := readFixtureJSONL(t, "candidate_batch_valid.jsonl")

	validation := ValidateCandidateBatch(base, candidates)
	if len(validation.Accepted) != 2 || len(validation.Rejected) != 0 {
		t.Fatalf("unexpected validation result: accepted=%d rejected=%d issues=%v", len(validation.Accepted), len(validation.Rejected), validation.Issues)
	}

	merged := MergeAcceptedNodes(base, validation.Accepted)
	mergedJSONL, err := MarshalCanonJSONL(merged)
	if err != nil {
		t.Fatalf("MarshalCanonJSONL: %v", err)
	}

	expected := readFixtureText(t, "expected_merged_canon.jsonl")
	if strings.TrimSpace(string(mergedJSONL)) != expected {
		t.Fatalf("merged canon mismatch\nexpected:\n%s\n\ngot:\n%s", expected, strings.TrimSpace(string(mergedJSONL)))
	}
}

func TestGuardedMergeIntegration_MixedBatchMatchesExpectedEvidence(t *testing.T) {
	base := readFixtureJSONL(t, "base_canon.jsonl")
	candidates := readFixtureJSONL(t, "candidate_batch_mixed.jsonl")

	validation := ValidateCandidateBatch(base, candidates)
	evidence, _, err := BuildMergeEvidence("s40-fixture-run", base, validation)
	if err != nil {
		t.Fatalf("BuildMergeEvidence: %v", err)
	}

	expectedReportJSON := readFixtureText(t, "expected_rejection_report.json")
	var expectedReport struct {
		Decisions []CandidateDecision `json:"decisions"`
		Issues    []CandidateIssue    `json:"issues"`
	}
	if err := json.Unmarshal([]byte(expectedReportJSON), &expectedReport); err != nil {
		t.Fatalf("unmarshal expected rejection report: %v", err)
	}

	gotReport := struct {
		Decisions []CandidateDecision `json:"decisions"`
		Issues    []CandidateIssue    `json:"issues"`
	}{
		Decisions: validation.Decisions,
		Issues:    validation.Issues,
	}
	if !reflectJSONEqual(t, expectedReport, gotReport) {
		t.Fatalf("rejection report mismatch")
	}

	expectedEvidenceJSON := readFixtureText(t, "expected_manifest_summary.json")
	var expectedEvidence GuardedMergeEvidence
	if err := json.Unmarshal([]byte(expectedEvidenceJSON), &expectedEvidence); err != nil {
		t.Fatalf("unmarshal expected evidence: %v", err)
	}
	if !reflectJSONEqual(t, expectedEvidence, evidence) {
		t.Fatalf("manifest summary mismatch")
	}
}

func reflectJSONEqual(t *testing.T, want, got any) bool {
	t.Helper()
	wantJSON, err := json.Marshal(want)
	if err != nil {
		t.Fatalf("marshal want: %v", err)
	}
	gotJSON, err := json.Marshal(got)
	if err != nil {
		t.Fatalf("marshal got: %v", err)
	}
	return string(wantJSON) == string(gotJSON)
}
