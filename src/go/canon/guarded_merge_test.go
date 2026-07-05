package canon

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"
)

func makeS40CanonEntry(t *testing.T, title string, text string, sourceTags []string, sourceRole string, sourceFields map[string]string, sourceType string, order int) CanonEntry {
	t.Helper()

	entry := CanonEntry{
		SchemaVersion:  SchemaV0,
		Key:            KeyOf(title),
		Title:          title,
		Text:           ptr(text),
		SourceTags:     append([]string(nil), sourceTags...),
		SourceFields:   cloneMap(sourceFields),
		OrderInDocument: order,
	}
	if sourceRole != "" {
		entry.SourceRole = ptr(sourceRole)
	}
	if sourceType != "" {
		entry.SourceType = ptr(sourceType)
	}

	if err := BuildNodeIdentity(&entry); err != nil {
		t.Fatalf("BuildNodeIdentity: %v", err)
	}
	reading := BuildNodeReadingMode(entry)
	entry.ContentType = reading.ContentType
	entry.Modality = reading.Modality
	entry.Encoding = reading.Encoding
	entry.IsBinary = reading.IsBinary
	entry.IsReferenceOnly = reading.IsReferenceOnly

	semantics := BuildNodeSemantics(entry)
	entry.RolePrimary = semantics.RolePrimary
	entry.RolesSecondary = semantics.RolesSecondary
	entry.Tags = semantics.Tags
	entry.TaxonomyPath = semantics.TaxonomyPath
	entry.SemanticText = semantics.SemanticText
	entry.RawPayloadRef = semantics.RawPayloadRef
	entry.AssetID = semantics.AssetID
	entry.MimeType = semantics.MimeType

	documentID, err := ComputeDocumentID(entry)
	if err != nil {
		t.Fatalf("ComputeDocumentID: %v", err)
	}
	entry.DocumentID = documentID
	entry.SectionPath = BuildSectionPath(entry)
	entry.Relations = dedupeSortRelations(entry.Relations)
	return entry
}

func cloneMap(in map[string]string) map[string]string {
	if in == nil {
		return nil
	}
	out := make(map[string]string, len(in))
	for k, v := range in {
		out[k] = v
	}
	return out
}

func ptr[T any](v T) *T {
	return &v
}

func TestValidateCandidateBatch_AcceptsValidNode(t *testing.T) {
	base := makeS40CanonEntry(t, "## Base Root", "Base content", []string{"## 🧭🧱 Protocolo de Sesión"}, "", map[string]string{
		"document_key": "s40-test-doc",
		"section_path": `["## Base Root"]`,
	}, "text/markdown", 0)

	candidate := makeS40CanonEntry(t, "Guarded Valid Node", "Valid candidate body", []string{"## 🧭🧱 Protocolo de Sesión", "policy"}, "policy", map[string]string{
		"document_key": "s40-test-doc",
		"section_path": `["## Base Root","Guarded Valid Node"]`,
	}, "text/markdown", 1)
	candidate.Relations = []NodeRelation{{
		Type: RelationTypeReferences, TargetID: base.ID, Evidence: RelationEvidenceExplicitField,
	}}

	result := ValidateCandidateBatch([]CanonEntry{base}, []CanonEntry{candidate})
	if len(result.Accepted) != 1 {
		t.Fatalf("accepted = %d, want 1; issues=%v", len(result.Accepted), result.Issues)
	}
	if len(result.Rejected) != 0 {
		t.Fatalf("rejected = %d, want 0", len(result.Rejected))
	}
	if len(result.Decisions) != 1 || result.Decisions[0].Decision != GuardedDecisionAccepted {
		t.Fatalf("unexpected decisions: %+v", result.Decisions)
	}
}

func TestValidateCandidateBatch_RejectsInvalidIdentity(t *testing.T) {
	base := makeS40CanonEntry(t, "## Base Root", "Base content", []string{"## 🧭🧱 Protocolo de Sesión"}, "", map[string]string{
		"document_key": "s40-test-doc",
	}, "text/markdown", 0)
	candidate := makeS40CanonEntry(t, "Broken Identity Node", "Valid candidate body", []string{"policy"}, "policy", map[string]string{
		"document_key": "s40-test-doc",
	}, "text/markdown", 1)
	candidate.ID = "not-the-canonical-id"

	result := ValidateCandidateBatch([]CanonEntry{base}, []CanonEntry{candidate})
	if len(result.Accepted) != 0 {
		t.Fatalf("accepted = %d, want 0", len(result.Accepted))
	}
	if len(result.Rejected) != 1 {
		t.Fatalf("rejected = %d, want 1", len(result.Rejected))
	}
	if !hasRule(result.Issues, "inconsistent-derived-id") {
		t.Fatalf("expected inconsistent-derived-id, got %+v", result.Issues)
	}
}

func TestValidateCandidateBatch_RejectsExplicitRoleOverride(t *testing.T) {
	base := makeS40CanonEntry(t, "## Base Root", "Base content", []string{"## 🧭🧱 Protocolo de Sesión"}, "", map[string]string{
		"document_key": "s40-test-doc",
	}, "text/markdown", 0)
	candidate := makeS40CanonEntry(t, "Invented Role Node", "Body", []string{"policy"}, "policy", map[string]string{
		"document_key": "s40-test-doc",
	}, "text/markdown", 1)
	candidate.RolePrimary = RoleWarning

	result := ValidateCandidateBatch([]CanonEntry{base}, []CanonEntry{candidate})
	if !hasRule(result.Issues, "explicit-role-overridden") {
		t.Fatalf("expected explicit-role-overridden, got %+v", result.Issues)
	}
}

func TestValidateCandidateBatch_RejectsInvalidRelationTarget(t *testing.T) {
	base := makeS40CanonEntry(t, "## Base Root", "Base content", []string{"## 🧭🧱 Protocolo de Sesión"}, "", map[string]string{
		"document_key": "s40-test-doc",
	}, "text/markdown", 0)
	candidate := makeS40CanonEntry(t, "Broken Relation Node", "Body", []string{"policy"}, "policy", map[string]string{
		"document_key": "s40-test-doc",
	}, "text/markdown", 1)
	candidate.Relations = []NodeRelation{{
		Type: RelationTypeReferences, TargetID: "missing-target", Evidence: RelationEvidenceExplicitField,
	}}

	result := ValidateCandidateBatch([]CanonEntry{base}, []CanonEntry{candidate})
	if !hasRule(result.Issues, "unresolved-relation-target") {
		t.Fatalf("expected unresolved-relation-target, got %+v", result.Issues)
	}
}

func TestValidateCandidateBatch_MixedBatchAndImmutableBase(t *testing.T) {
	base := makeS40CanonEntry(t, "## Base Root", "Base content", []string{"## 🧭🧱 Protocolo de Sesión"}, "", map[string]string{
		"document_key": "s40-test-doc",
	}, "text/markdown", 0)
	valid := makeS40CanonEntry(t, "Mixed Valid Node", "Valid body", []string{"policy"}, "policy", map[string]string{
		"document_key": "s40-test-doc",
	}, "text/markdown", 1)
	valid.Relations = []NodeRelation{{
		Type: RelationTypeReferences, TargetID: base.ID, Evidence: RelationEvidenceExplicitField,
	}}

	invalid := makeS40CanonEntry(t, "Mixed Invalid Node", "Body", []string{"policy"}, "policy", map[string]string{
		"document_key": "s40-test-doc",
	}, "text/markdown", 2)
	invalid.CanonicalSlug = "tampered-slug"

	baseJSON, _ := json.Marshal(base)
	result := ValidateCandidateBatch([]CanonEntry{base}, []CanonEntry{valid, invalid})
	if len(result.Accepted) != 1 || result.Accepted[0].Title != valid.Title {
		t.Fatalf("unexpected accepted set: %+v", result.Accepted)
	}
	if len(result.Rejected) != 1 || result.Rejected[0].Title != invalid.Title {
		t.Fatalf("unexpected rejected set: %+v", result.Rejected)
	}

	merged := MergeAcceptedNodes([]CanonEntry{base}, result.Accepted)
	if len(merged) != 2 {
		t.Fatalf("merged length = %d, want 2", len(merged))
	}
	afterJSON, _ := json.Marshal(merged[0])
	if !bytes.Equal(baseJSON, afterJSON) {
		t.Fatalf("base node mutated during merge")
	}
}

func TestBuildMergeEvidence_Reproducible(t *testing.T) {
	base := makeS40CanonEntry(t, "## Base Root", "Base content", []string{"## 🧭🧱 Protocolo de Sesión"}, "", map[string]string{
		"document_key": "s40-test-doc",
	}, "text/markdown", 0)
	valid := makeS40CanonEntry(t, "Stable Candidate", "Valid body", []string{"policy"}, "policy", map[string]string{
		"document_key": "s40-test-doc",
	}, "text/markdown", 1)
	valid.Relations = []NodeRelation{{
		Type: RelationTypeReferences, TargetID: base.ID, Evidence: RelationEvidenceExplicitField,
	}}

	resultA := ValidateCandidateBatch([]CanonEntry{base}, []CanonEntry{valid})
	evidenceA, mergedA, err := BuildMergeEvidence("s40-repro", []CanonEntry{base}, resultA)
	if err != nil {
		t.Fatalf("BuildMergeEvidence A: %v", err)
	}
	resultB := ValidateCandidateBatch([]CanonEntry{base}, []CanonEntry{valid})
	evidenceB, mergedB, err := BuildMergeEvidence("s40-repro", []CanonEntry{base}, resultB)
	if err != nil {
		t.Fatalf("BuildMergeEvidence B: %v", err)
	}

	jsonA, _ := json.Marshal(evidenceA)
	jsonB, _ := json.Marshal(evidenceB)
	if !bytes.Equal(jsonA, jsonB) {
		t.Fatalf("evidence is not reproducible\nA=%s\nB=%s", jsonA, jsonB)
	}
	linesA, _ := MarshalCanonJSONL(mergedA)
	linesB, _ := MarshalCanonJSONL(mergedB)
	if !bytes.Equal(linesA, linesB) {
		t.Fatalf("merged canon is not reproducible")
	}
}

func TestParseAndMarshalCanonJSONL_RoundTrip(t *testing.T) {
	entry := makeS40CanonEntry(t, "Round Trip Node", "Body", []string{"policy"}, "policy", map[string]string{
		"document_key": "s40-test-doc",
	}, "text/markdown", 0)

	jsonl, err := MarshalCanonJSONL([]CanonEntry{entry})
	if err != nil {
		t.Fatalf("MarshalCanonJSONL: %v", err)
	}
	parsed, err := ParseCanonJSONL(strings.NewReader(string(jsonl)))
	if err != nil {
		t.Fatalf("ParseCanonJSONL: %v", err)
	}
	if len(parsed) != 1 || parsed[0].Title != entry.Title {
		t.Fatalf("unexpected parsed entries: %+v", parsed)
	}
}

func hasRule(issues []CandidateIssue, ruleID string) bool {
	for _, issue := range issues {
		if issue.RuleID == ruleID {
			return true
		}
	}
	return false
}
