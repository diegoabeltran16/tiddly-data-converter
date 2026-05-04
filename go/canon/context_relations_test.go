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

// TestDeriveSectionPath_CMU1_CategoricalFallback verifies that a non-heading
// node with a unique #### tag and ambiguous ## tags gets a categorical
// depth-1 section_path (CMU-1, S81).
func TestDeriveSectionPath_CMU1_CategoricalFallback(t *testing.T) {
	e := CanonEntry{
		Title: "Some Evidence Node",
		SourceTags: []string{
			"## 🧰🧱 Elementos específicos",
			"## 🧾🧱 Procedencia epistemológica",
			"## 🧪🧱 Hipótesis",
			"#### referencias especificas 🌀",
		},
	}
	path := BuildSectionPath(e)
	want := []string{"#### referencias especificas 🌀"}
	if len(path) != len(want) {
		t.Fatalf("CMU-1: len(path) = %d, want %d (%v)", len(path), len(want), path)
	}
	if path[0] != want[0] {
		t.Fatalf("CMU-1: path[0] = %q, want %q", path[0], want[0])
	}
}

// TestDeriveSectionPath_CMU1_NoFallback_MultipleH4 verifies that ambiguous ####
// tags do NOT trigger the CMU-1 fallback — only a single #### is accepted.
func TestDeriveSectionPath_CMU1_NoFallback_MultipleH4(t *testing.T) {
	e := CanonEntry{
		Title: "Ambiguous Node",
		SourceTags: []string{
			"## 🧰🧱 Elementos específicos",
			"## 🧾🧱 Procedencia",
			"#### tag-A 🌀",
			"#### tag-B 🌀",
		},
	}
	path := BuildSectionPath(e)
	if len(path) != 0 {
		t.Fatalf("CMU-1 must not fire for multiple #### tags: got %v", path)
	}
}

// TestDeriveSectionPath_CMU1_NoFallback_NoHeadingTags verifies that nodes
// without any heading-level tags get no section_path (code nodes).
func TestDeriveSectionPath_CMU1_NoFallback_NoHeadingTags(t *testing.T) {
	e := CanonEntry{
		Title:      "data/some/file.txt",
		SourceTags: []string{"⚙️ Text", "⚙️ Markdown"},
	}
	path := BuildSectionPath(e)
	if len(path) != 0 {
		t.Fatalf("no-heading-tags node must have no section_path: got %v", path)
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

// TestBuildRelations_NoSelfReference_Wikilink verifies CMU-DT05-1:
// a node whose text contains a wikilink to itself must not emit a relation.
func TestBuildRelations_NoSelfReference_Wikilink(t *testing.T) {
	self := makeIdentityEntry(t, "go/bridge/bridge.go", sPtr("see [[go/bridge/bridge.go]] for details"), nil, nil)
	resolver := BuildContextResolver([]CanonEntry{self})
	rels, status, _ := BuildRelations(self, nil, resolver)
	if len(rels) != 0 {
		t.Fatalf("self-reference via wikilink must be suppressed; got %d relations: %v", len(rels), rels)
	}
	if status != "none" {
		t.Fatalf("status = %q, want %q (all candidates were self-references)", status, "none")
	}
}

// TestBuildRelations_NoSelfReference_Mixed verifies that self-references are
// filtered while external relations in the same node are preserved.
func TestBuildRelations_NoSelfReference_Mixed(t *testing.T) {
	other := makeIdentityEntry(t, "Other Node", sPtr("other"), nil, nil)
	self := makeIdentityEntry(t, "Source", sPtr("see [[Source]] and [[Other Node]]"), nil, nil)
	resolver := BuildContextResolver([]CanonEntry{other, self})
	rels, status, _ := BuildRelations(self, nil, resolver)
	if len(rels) != 1 {
		t.Fatalf("expected 1 relation (external only), got %d: %v", len(rels), rels)
	}
	if rels[0].TargetID != other.ID {
		t.Fatalf("expected relation to other node %q, got %q", other.ID, rels[0].TargetID)
	}
	if status != "resolved" {
		t.Fatalf("status = %q, want %q", status, "resolved")
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

// ── S84: embedded content relations (capa-2) ─────────────────────────────────

// TestExtractEmbeddedContentRelations_BasicTypes verifies that capa-2 semantic
// types (usa, define, requiere, parte_de, pertenece_a, contiene, prueba_de)
// are extracted with evidence content_embedded.
func TestExtractEmbeddedContentRelations_BasicTypes(t *testing.T) {
	text := `{"relations":[
		{"type":"usa","target":"## 🧭🧱 Protocolo de Sesión"},
		{"type":"define","target":"### 🎯 1. Objetivos 🧱"},
		{"type":"requiere","target":"## 🗂🧱 Principios de Gestion"},
		{"type":"parte_de","target":"# 1_tiddly-data-converter"},
		{"type":"pertenece_a","target":"## 🌀🧱 Desarrollo y Evolución"},
		{"type":"contiene","target":"## 🧪🧱 Hipótesis"},
		{"type":"prueba_de","target":"## 🧾🧱 Procedencia epistemológica"}
	]}`
	got := extractEmbeddedContentRelations(sPtr(text))
	if len(got) != 7 {
		t.Fatalf("expected 7 embedded relations, got %d: %v", len(got), got)
	}
	for _, r := range got {
		if r.Evidence != RelationEvidenceEmbeddedContent {
			t.Errorf("relation %q/%q: evidence = %q, want %q", r.Type, r.Target, r.Evidence, RelationEvidenceEmbeddedContent)
		}
		if !embeddedRelationTypes[r.Type] {
			t.Errorf("relation has unexpected type %q", r.Type)
		}
	}
}

// TestExtractEmbeddedContentRelations_CanonicalTypesExcluded verifies that
// child_of and references are NOT extracted by the embedded extractor
// (they are handled by extractExplicitRelationTargets).
func TestExtractEmbeddedContentRelations_CanonicalTypesExcluded(t *testing.T) {
	text := `{"relations":[
		{"type":"child_of","target":"# Root"},
		{"type":"references","target":"## Section"},
		{"type":"usa","target":"## 🧭🧱 Protocolo de Sesión"}
	]}`
	got := extractEmbeddedContentRelations(sPtr(text))
	if len(got) != 1 {
		t.Fatalf("expected 1 (only usa), got %d: %v", len(got), got)
	}
	if got[0].Type != RelationTypeUsa {
		t.Errorf("expected type %q, got %q", RelationTypeUsa, got[0].Type)
	}
}

// TestExtractEmbeddedContentRelations_NoDoubleCountCanonical verifies that
// a node with both canonical and embedded relations does not double-count
// the canonical ones.
func TestExtractEmbeddedContentRelations_NoDoubleCountCanonical(t *testing.T) {
	target := makeIdentityEntry(t, "## Proto", sPtr("x"), nil, nil)
	root := makeIdentityEntry(t, "# Root", sPtr("x"), nil, nil)
	text := `{"relations":[
		{"type":"references","target":"## Proto"},
		{"type":"usa","target":"## Proto"}
	]}`
	src := makeIdentityEntry(t, "Src", sPtr(text), nil, nil)
	resolver := BuildContextResolver([]CanonEntry{target, root, src})
	rels, _, _ := BuildRelations(src, nil, resolver)

	var refRels, usaRels []NodeRelation
	for _, r := range rels {
		switch r.Type {
		case RelationTypeReferences:
			refRels = append(refRels, r)
		case RelationTypeUsa:
			usaRels = append(usaRels, r)
		}
	}
	// references comes from extractExplicitRelationTargets
	if len(refRels) != 1 {
		t.Errorf("expected 1 references relation, got %d", len(refRels))
	}
	// usa comes from extractEmbeddedContentRelations
	if len(usaRels) != 1 {
		t.Errorf("expected 1 usa relation, got %d", len(usaRels))
	}
	if len(refRels) > 0 && refRels[0].Evidence != RelationEvidenceExplicitField {
		t.Errorf("references evidence = %q, want %q", refRels[0].Evidence, RelationEvidenceExplicitField)
	}
	if len(usaRels) > 0 && usaRels[0].Evidence != RelationEvidenceEmbeddedContent {
		t.Errorf("usa evidence = %q, want %q", usaRels[0].Evidence, RelationEvidenceEmbeddedContent)
	}
}

// TestBuildRelations_EmbeddedContent_Resolved verifies the full path: an
// embedded usa relation pointing to an existing node produces a resolved
// NodeRelation with content_embedded evidence.
func TestBuildRelations_EmbeddedContent_Resolved(t *testing.T) {
	target := makeIdentityEntry(t, "## 🧭🧱 Protocolo de Sesión", sPtr("proto"), nil, nil)
	text := `{"relations":[{"type":"usa","target":"## 🧭🧱 Protocolo de Sesión"}]}`
	src := makeIdentityEntry(t, "#### 🌀 Sesión 84 = test", sPtr(text), nil, nil)
	resolver := BuildContextResolver([]CanonEntry{target, src})
	rels, status, _ := BuildRelations(src, nil, resolver)
	if status != "resolved" {
		t.Fatalf("status = %q, want resolved", status)
	}
	if len(rels) != 1 {
		t.Fatalf("expected 1 relation, got %d: %v", len(rels), rels)
	}
	if rels[0].Type != RelationTypeUsa {
		t.Errorf("type = %q, want %q", rels[0].Type, RelationTypeUsa)
	}
	if rels[0].TargetID != target.ID {
		t.Errorf("target_id = %q, want %q", rels[0].TargetID, target.ID)
	}
	if rels[0].Evidence != RelationEvidenceEmbeddedContent {
		t.Errorf("evidence = %q, want %q", rels[0].Evidence, RelationEvidenceEmbeddedContent)
	}
}

// TestBuildRelations_EmbeddedContent_Stale verifies that a stale embedded
// relation (target not in corpus) increments unresolved but emits no relation.
func TestBuildRelations_EmbeddedContent_Stale(t *testing.T) {
	text := `{"relations":[{"type":"usa","target":"m01-s13-canon-bootstrap"}]}`
	src := makeIdentityEntry(t, "#### 🌀 Sesión 84 = test", sPtr(text), nil, nil)
	resolver := BuildContextResolver([]CanonEntry{src})
	rels, status, candidates := BuildRelations(src, nil, resolver)
	if len(rels) != 0 {
		t.Errorf("stale embedded relation must not emit: got %v", rels)
	}
	if status != "unresolved" {
		t.Errorf("status = %q, want unresolved", status)
	}
	if candidates != 1 {
		t.Errorf("candidates = %d, want 1", candidates)
	}
}

// TestBuildRelations_EmbeddedContent_NoSelfRef verifies that a self-referential
// embedded relation is silently suppressed.
func TestBuildRelations_EmbeddedContent_NoSelfRef(t *testing.T) {
	title := "#### 🌀 Sesión 84 = self-ref-test"
	text := `{"relations":[{"type":"usa","target":"#### 🌀 Sesión 84 = self-ref-test"}]}`
	src := makeIdentityEntry(t, title, sPtr(text), nil, nil)
	resolver := BuildContextResolver([]CanonEntry{src})
	rels, status, _ := BuildRelations(src, nil, resolver)
	if len(rels) != 0 {
		t.Errorf("self-ref embedded relation must be suppressed: got %v", rels)
	}
	if status != "none" {
		t.Errorf("status = %q, want none (self-ref excluded)", status)
	}
}
