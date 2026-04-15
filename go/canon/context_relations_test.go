package canon

import (
	"strings"
	"testing"
)

func sPtr(s string) *string { return &s }

func makeIdentityEntry(t *testing.T, title string, text *string, tags []string, fields map[string]string) CanonEntry {
	t.Helper()
	e := CanonEntry{
		Key:          KeyOf(title),
		Title:        title,
		Text:         text,
		SourceTags:   append([]string(nil), tags...),
		SourceFields: fields,
	}
	if err := BuildNodeIdentity(&e); err != nil {
		t.Fatalf("BuildNodeIdentity(%q): %v", title, err)
	}
	return e
}

func TestComputeDocumentID_Deterministic(t *testing.T) {
	e := CanonEntry{
		SourceFields: map[string]string{"document_key": "docs/topic/wiki.html"},
	}
	id1, err := ComputeDocumentID(e)
	if err != nil {
		t.Fatalf("ComputeDocumentID err1: %v", err)
	}
	id2, err := ComputeDocumentID(e)
	if err != nil {
		t.Fatalf("ComputeDocumentID err2: %v", err)
	}
	if id1 != id2 {
		t.Fatalf("document_id not deterministic: %q != %q", id1, id2)
	}
}

func TestResolveDocumentKey_NoAbsolutePathLeak(t *testing.T) {
	e := CanonEntry{
		SourceFields: map[string]string{"document_key": "/tmp/local/absolute/input.html"},
	}
	key := resolveDocumentKey(e)
	if strings.HasPrefix(key, "/") {
		t.Fatalf("resolveDocumentKey leaked absolute path: %q", key)
	}
	if key != "input.html" {
		t.Fatalf("resolveDocumentKey = %q, want %q", key, "input.html")
	}
}

func TestBuildSectionPath_ExplicitPrecedence(t *testing.T) {
	e := CanonEntry{
		Title:      "### Child",
		SourceTags: []string{"# Root", "## Wrong"},
		SourceFields: map[string]string{
			"section_path": `["# Root","## Right","### Child"]`,
		},
	}
	path := BuildSectionPath(e)
	want := []string{"# Root", "## Right", "### Child"}
	if len(path) != len(want) {
		t.Fatalf("len(path) = %d, want %d (%v)", len(path), len(want), path)
	}
	for i := range want {
		if path[i] != want[i] {
			t.Fatalf("path[%d] = %q, want %q", i, path[i], want[i])
		}
	}
}

func TestBuildSectionPath_DeriveFromStructure(t *testing.T) {
	e := CanonEntry{
		Title:      "### Child",
		SourceTags: []string{"# Root", "## Section"},
	}
	path := BuildSectionPath(e)
	want := []string{"# Root", "## Section", "### Child"}
	if len(path) != len(want) {
		t.Fatalf("len(path) = %d, want %d (%v)", len(path), len(want), path)
	}
	for i := range want {
		if path[i] != want[i] {
			t.Fatalf("path[%d] = %q, want %q", i, path[i], want[i])
		}
	}
}

func TestComputeOrderInDocument_Stable(t *testing.T) {
	if got := ComputeOrderInDocument(0); got != 0 {
		t.Fatalf("ComputeOrderInDocument(0) = %d, want 0", got)
	}
	if got := ComputeOrderInDocument(5); got != 5 {
		t.Fatalf("ComputeOrderInDocument(5) = %d, want 5", got)
	}
}

func TestBuildRelations_ChildOf_Unique(t *testing.T) {
	parent := makeIdentityEntry(t, "## Parent", sPtr("parent"), nil, map[string]string{"document_key": "doc-A"})
	child := makeIdentityEntry(t, "### Child", sPtr("child"), []string{"# Root", "## Parent"}, map[string]string{"document_key": "doc-A"})

	resolver := BuildContextResolver([]CanonEntry{parent, child})
	sectionPath := []string{"# Root", "## Parent", "### Child"}
	rels, status, _ := BuildRelations(child, sectionPath, resolver)
	if status != "resolved" {
		t.Fatalf("status = %q, want %q", status, "resolved")
	}
	if len(rels) != 1 {
		t.Fatalf("len(relations) = %d, want 1 (%v)", len(rels), rels)
	}
	if rels[0].Type != RelationTypeChildOf {
		t.Fatalf("relation type = %q, want %q", rels[0].Type, RelationTypeChildOf)
	}
	if rels[0].TargetID != parent.ID {
		t.Fatalf("target_id = %q, want %q", rels[0].TargetID, parent.ID)
	}
}

func TestBuildRelations_ReferencesFromWikilink(t *testing.T) {
	target := makeIdentityEntry(t, "Alpha", sPtr("alpha"), nil, map[string]string{"document_key": "doc-A"})
	src := makeIdentityEntry(t, "Source", sPtr("link to [[Alpha]]"), nil, map[string]string{"document_key": "doc-A"})

	resolver := BuildContextResolver([]CanonEntry{target, src})
	rels, status, _ := BuildRelations(src, nil, resolver)
	if status != "resolved" {
		t.Fatalf("status = %q, want %q", status, "resolved")
	}
	if len(rels) != 1 {
		t.Fatalf("len(relations) = %d, want 1 (%v)", len(rels), rels)
	}
	if rels[0].Type != RelationTypeReferences {
		t.Fatalf("type = %q, want %q", rels[0].Type, RelationTypeReferences)
	}
	if rels[0].TargetID != target.ID {
		t.Fatalf("target_id = %q, want %q", rels[0].TargetID, target.ID)
	}
}

func TestBuildRelations_AmbiguousWikilink(t *testing.T) {
	a := makeIdentityEntry(t, "Dup", sPtr("a"), nil, map[string]string{"document_key": "doc-A"})
	b := makeIdentityEntry(t, "Dup", sPtr("b"), nil, map[string]string{"document_key": "doc-A"})
	src := makeIdentityEntry(t, "Src", sPtr("see [[Dup]]"), nil, map[string]string{"document_key": "doc-A"})

	resolver := BuildContextResolver([]CanonEntry{a, b, src})
	rels, status, _ := BuildRelations(src, nil, resolver)
	if len(rels) != 0 {
		t.Fatalf("relations should be empty on ambiguity: %v", rels)
	}
	if status != "ambiguous" {
		t.Fatalf("status = %q, want %q", status, "ambiguous")
	}
}

func TestBuildRelations_TargetAbsent(t *testing.T) {
	src := makeIdentityEntry(t, "Src", sPtr("see [[MissingNode]]"), nil, map[string]string{"document_key": "doc-A"})
	resolver := BuildContextResolver([]CanonEntry{src})
	rels, status, _ := BuildRelations(src, nil, resolver)
	if len(rels) != 0 {
		t.Fatalf("relations should be empty when target absent: %v", rels)
	}
	if status != "unresolved" {
		t.Fatalf("status = %q, want %q", status, "unresolved")
	}
}

func TestBuildRelations_DedupeExact(t *testing.T) {
	target := makeIdentityEntry(t, "Alpha", sPtr("alpha"), nil, map[string]string{"document_key": "doc-A"})
	text := `{"relations":[{"type":"references","target":"Alpha"},{"type":"references","target":"Alpha"}]}`
	src := makeIdentityEntry(t, "Src", sPtr(text), nil, map[string]string{"document_key": "doc-A"})

	resolver := BuildContextResolver([]CanonEntry{target, src})
	rels, status, _ := BuildRelations(src, nil, resolver)
	if status != "resolved" {
		t.Fatalf("status = %q, want %q", status, "resolved")
	}
	if len(rels) != 1 {
		t.Fatalf("expected deduped relations length 1, got %d (%v)", len(rels), rels)
	}
}
