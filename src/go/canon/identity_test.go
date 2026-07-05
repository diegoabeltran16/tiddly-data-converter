package canon

import (
	"encoding/json"
	"strings"
	"testing"
)

// ---------------------------------------------------------------------------
// Test: CanonicalSlugOf
// ---------------------------------------------------------------------------

func TestCanonicalSlugOf_Basic(t *testing.T) {
	tests := []struct {
		name  string
		title string
		want  string
	}{
		{"simple ascii", "Hello World", "hello-world"},
		{"already lowercase", "simple title", "simple-title"},
		{"mixed case", "MyTiddler", "mytiddler"},
		{"numbers", "Item 42 Final", "item-42-final"},
		{"leading trailing spaces", "  padded  ", "padded"},
		{"multiple spaces", "a   b   c", "a-b-c"},
		{"empty string", "", ""},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := CanonicalSlugOf(tt.title)
			if got != tt.want {
				t.Errorf("CanonicalSlugOf(%q) = %q, want %q", tt.title, got, tt.want)
			}
		})
	}
}

// Case D: Special characters — diacritics, emojis, symbols, punctuation.
func TestCanonicalSlugOf_SpecialCharacters(t *testing.T) {
	tests := []struct {
		name  string
		title string
		want  string
	}{
		{"spanish diacritics", "Introducción al Español", "introduccion-al-espanol"},
		{"french accents", "Résumé Café", "resume-cafe"},
		// ß does not decompose via NFD; NFKC maps it to "ss" in some
		// normalization forms. In practice, our pipeline strips it because
		// after NFD, ß remains a single codepoint that is not in [a-z0-9-].
		// Policy: ß → stripped. Documented in contract.
		{"german umlaut", "Über Straße", "uber-strae"},
		{"tilde n", "Señor Año", "senor-ano"},
		{"emojis stripped", "🌀 Sesión 08 = data-triage", "sesion-08-data-triage"},
		{"emoji heavy", "#### 🌀🧾 Procedencia", "procedencia"},
		{"symbols stripped", "## 🧰🧱 Elementos específicos", "elementos-especificos"},
		{"hash prefix", "### Section Title", "section-title"},
		{"punctuation", "Hello, World! (test)", "hello-world-test"},
		{"underscore", "_🧱README.md", "readmemd"},
		{"mixed emoji and text", "🧪 Hipótesis de sesión 34", "hipotesis-de-sesion-34"},
		{"ligature fi", "\uFB01nal", "final"},                          // ﬁ → fi via NFKC
		{"fraction half", "\u00BD cup", "12-cup"},                      // ½ → 12 via NFKC (/ stripped)
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := CanonicalSlugOf(tt.title)
			if got != tt.want {
				t.Errorf("CanonicalSlugOf(%q) = %q, want %q", tt.title, got, tt.want)
			}
		})
	}
}

func TestCanonicalSlugOf_Deterministic(t *testing.T) {
	title := "#### 🌀 Sesión 08 = ingesta-data-triage"
	slug1 := CanonicalSlugOf(title)
	slug2 := CanonicalSlugOf(title)
	if slug1 != slug2 {
		t.Errorf("non-deterministic: %q != %q", slug1, slug2)
	}
}

// ---------------------------------------------------------------------------
// Test: ComputeNodeUUID
// ---------------------------------------------------------------------------

func TestComputeNodeUUID_Deterministic(t *testing.T) {
	key := "Hello World"
	id1, err := ComputeNodeUUID(key)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	id2, err := ComputeNodeUUID(key)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if id1 != id2 {
		t.Errorf("non-deterministic: %q != %q", id1, id2)
	}
}

func TestComputeNodeUUID_DifferentKeys(t *testing.T) {
	id1, _ := ComputeNodeUUID("Alpha")
	id2, _ := ComputeNodeUUID("Beta")
	if id1 == id2 {
		t.Errorf("different keys produce same UUID: %q", id1)
	}
}

func TestComputeNodeUUID_Format(t *testing.T) {
	id, err := ComputeNodeUUID("test")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	// UUIDv5 format: 8-4-4-4-12 hex chars
	parts := strings.Split(id, "-")
	if len(parts) != 5 {
		t.Errorf("UUID format invalid: %q, expected 5 parts", id)
	}
	// Check version nibble (byte 6 high nibble = 5)
	if len(parts) >= 3 && len(parts[2]) >= 1 && parts[2][0] != '5' {
		t.Errorf("UUID version nibble: got %c, want 5", parts[2][0])
	}
}

// ---------------------------------------------------------------------------
// Test: ComputeVersionID
// ---------------------------------------------------------------------------

func TestComputeVersionID_Deterministic(t *testing.T) {
	text := "body content"
	e := CanonEntry{Key: "k1", Title: "Title One", Text: &text}
	v1, err := ComputeVersionID(e)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	v2, err := ComputeVersionID(e)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if v1 != v2 {
		t.Errorf("non-deterministic: %q != %q", v1, v2)
	}
}

func TestComputeVersionID_Format(t *testing.T) {
	e := CanonEntry{Key: "k1", Title: "T1"}
	vid, err := ComputeVersionID(e)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !strings.HasPrefix(vid, "sha256:") {
		t.Errorf("VersionID = %q, want sha256: prefix", vid)
	}
	// sha256 hex = 64 chars
	hex := strings.TrimPrefix(vid, "sha256:")
	if len(hex) != 64 {
		t.Errorf("sha256 hex length = %d, want 64", len(hex))
	}
}

// Case C: Material content change → version_id changes.
func TestComputeVersionID_ContentChangeChangesVersion(t *testing.T) {
	text1 := "original content"
	text2 := "modified content"
	e1 := CanonEntry{Key: "k1", Title: "T1", Text: &text1}
	e2 := CanonEntry{Key: "k1", Title: "T1", Text: &text2}
	v1, _ := ComputeVersionID(e1)
	v2, _ := ComputeVersionID(e2)
	if v1 == v2 {
		t.Error("material content change did not change version_id")
	}
}

// version_id must exclude id, canonical_slug, schema_version, source_position.
func TestComputeVersionID_ExcludesDerivedFields(t *testing.T) {
	text := "content"
	e1 := CanonEntry{Key: "k1", Title: "T1", Text: &text}
	e2 := CanonEntry{
		Key: "k1", Title: "T1", Text: &text,
		ID: "some-uuid", CanonicalSlug: "t1", VersionID: "sha256:old",
		SchemaVersion: "v0", SourcePosition: strPtr("pos1"),
	}
	v1, _ := ComputeVersionID(e1)
	v2, _ := ComputeVersionID(e2)
	if v1 != v2 {
		t.Errorf("derived fields affected version_id: %q != %q", v1, v2)
	}
}

// ---------------------------------------------------------------------------
// Test: ResolveSlugCollision
// ---------------------------------------------------------------------------

func TestResolveSlugCollision(t *testing.T) {
	resolved := ResolveSlugCollision("my-slug", "a1b2c3d4-e5f6-5789-abcd-ef0123456789")
	// Should append first 8 hex chars (without hyphens) of UUID
	if !strings.HasPrefix(resolved, "my-slug-") {
		t.Errorf("expected prefix 'my-slug-', got %q", resolved)
	}
	if resolved == "my-slug" {
		t.Error("collision resolution did not modify slug")
	}
	// The suffix should be 8 hex chars from the UUID
	suffix := strings.TrimPrefix(resolved, "my-slug-")
	if len(suffix) != 8 {
		t.Errorf("suffix length = %d, want 8, got %q", len(suffix), suffix)
	}
}

func TestResolveSlugCollision_DifferentIDs(t *testing.T) {
	r1 := ResolveSlugCollision("slug", "aaaabbbb-cccc-5ddd-eeee-ffffffffffff")
	r2 := ResolveSlugCollision("slug", "11112222-3333-5444-5555-666677778888")
	if r1 == r2 {
		t.Errorf("different IDs produced same collision resolution: %q", r1)
	}
}

// ---------------------------------------------------------------------------
// Test: BuildNodeIdentity
// ---------------------------------------------------------------------------

// Case A: Stable node without changes — same inputs → same outputs.
func TestBuildNodeIdentity_CaseA_StableNode(t *testing.T) {
	text := "content body"
	e1 := CanonEntry{Key: "Alpha", Title: "Alpha", Text: &text}
	e2 := CanonEntry{Key: "Alpha", Title: "Alpha", Text: &text}

	if err := BuildNodeIdentity(&e1); err != nil {
		t.Fatalf("e1: %v", err)
	}
	if err := BuildNodeIdentity(&e2); err != nil {
		t.Fatalf("e2: %v", err)
	}

	if e1.ID != e2.ID {
		t.Errorf("id mismatch: %q != %q", e1.ID, e2.ID)
	}
	if e1.Key != e2.Key {
		t.Errorf("key mismatch: %q != %q", e1.Key, e2.Key)
	}
	if e1.Title != e2.Title {
		t.Errorf("title mismatch: %q != %q", e1.Title, e2.Title)
	}
	if e1.CanonicalSlug != e2.CanonicalSlug {
		t.Errorf("canonical_slug mismatch: %q != %q", e1.CanonicalSlug, e2.CanonicalSlug)
	}
	if e1.VersionID != e2.VersionID {
		t.Errorf("version_id mismatch: %q != %q", e1.VersionID, e2.VersionID)
	}
}

// Case B: Cosmetic title change with stable key → id remains stable.
func TestBuildNodeIdentity_CaseB_CosmeticTitleChange(t *testing.T) {
	text := "content"
	e1 := CanonEntry{Key: "MyKey", Title: "My Title v1", Text: &text}
	e2 := CanonEntry{Key: "MyKey", Title: "My Title v2", Text: &text}

	if err := BuildNodeIdentity(&e1); err != nil {
		t.Fatalf("e1: %v", err)
	}
	if err := BuildNodeIdentity(&e2); err != nil {
		t.Fatalf("e2: %v", err)
	}

	// ID depends on key, not title, so it should remain stable.
	if e1.ID != e2.ID {
		t.Errorf("id changed on cosmetic title change: %q != %q", e1.ID, e2.ID)
	}

	// canonical_slug changes because title changed.
	if e1.CanonicalSlug == e2.CanonicalSlug {
		t.Log("note: canonical_slug did not change — titles may produce the same slug")
	}

	// version_id changes because title is in the normative shape.
	if e1.VersionID == e2.VersionID {
		t.Error("version_id should change when title changes")
	}
}

// Case C: Material content change → version_id changes, id stable.
func TestBuildNodeIdentity_CaseC_MaterialContentChange(t *testing.T) {
	text1 := "original content"
	text2 := "modified content"
	e1 := CanonEntry{Key: "K", Title: "T", Text: &text1}
	e2 := CanonEntry{Key: "K", Title: "T", Text: &text2}

	if err := BuildNodeIdentity(&e1); err != nil {
		t.Fatalf("e1: %v", err)
	}
	if err := BuildNodeIdentity(&e2); err != nil {
		t.Fatalf("e2: %v", err)
	}

	if e1.ID != e2.ID {
		t.Errorf("id changed on content change: %q != %q", e1.ID, e2.ID)
	}
	if e1.VersionID == e2.VersionID {
		t.Error("version_id should change when content changes")
	}
}

// Case E: Slug collision — two distinct nodes with the same base slug.
func TestBuildNodeIdentity_CaseE_SlugCollision(t *testing.T) {
	text1 := "content alpha"
	text2 := "content beta"
	// These will produce the same base slug "hello-world"
	e1 := CanonEntry{Key: "Hello World", Title: "Hello World", Text: &text1}
	e2 := CanonEntry{Key: "hello world", Title: "hello world", Text: &text2}

	if err := BuildNodeIdentity(&e1); err != nil {
		t.Fatalf("e1: %v", err)
	}
	if err := BuildNodeIdentity(&e2); err != nil {
		t.Fatalf("e2: %v", err)
	}

	// Same base slug
	if e1.CanonicalSlug != e2.CanonicalSlug {
		t.Logf("slugs differ: %q vs %q (no collision to resolve)", e1.CanonicalSlug, e2.CanonicalSlug)
		return
	}

	// But different IDs (different keys → different UUIDs)
	if e1.ID == e2.ID {
		t.Error("different keys should produce different IDs")
	}

	// Resolve collision
	resolved1 := ResolveSlugCollision(e1.CanonicalSlug, e1.ID)
	resolved2 := ResolveSlugCollision(e2.CanonicalSlug, e2.ID)
	if resolved1 == resolved2 {
		t.Errorf("collision resolution failed: both resolved to %q", resolved1)
	}
	t.Logf("collision resolved: %q, %q", resolved1, resolved2)
}

// BuildNodeIdentity fails on empty title.
func TestBuildNodeIdentity_EmptyTitleError(t *testing.T) {
	e := CanonEntry{Key: "k"}
	err := BuildNodeIdentity(&e)
	if err == nil {
		t.Error("expected error for empty title")
	}
}

// BuildNodeIdentity derives key from title if not set.
func TestBuildNodeIdentity_DerivesKeyFromTitle(t *testing.T) {
	e := CanonEntry{Title: "My Title"}
	if err := BuildNodeIdentity(&e); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if e.Key != "My Title" {
		t.Errorf("key = %q, want %q", e.Key, "My Title")
	}
}

// All five fields populated after BuildNodeIdentity.
func TestBuildNodeIdentity_AllFieldsPopulated(t *testing.T) {
	text := "some text"
	e := CanonEntry{Key: "K", Title: "My Title", Text: &text}
	if err := BuildNodeIdentity(&e); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if e.ID == "" {
		t.Error("id is empty")
	}
	if e.Key == "" {
		t.Error("key is empty")
	}
	if e.Title == "" {
		t.Error("title is empty")
	}
	if e.CanonicalSlug == "" {
		t.Error("canonical_slug is empty")
	}
	if e.VersionID == "" {
		t.Error("version_id is empty")
	}
}

// JSONL line should contain all 5 identity fields.
func TestBuildNodeIdentity_JSONContainsAllFields(t *testing.T) {
	text := "content"
	e := CanonEntry{Key: "K", Title: "Title", Text: &text, SchemaVersion: SchemaV0}
	if err := BuildNodeIdentity(&e); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	data, err := json.Marshal(e)
	if err != nil {
		t.Fatalf("marshal error: %v", err)
	}
	line := string(data)
	for _, field := range []string{"\"id\":", "\"key\":", "\"title\":", "\"canonical_slug\":", "\"version_id\":"} {
		if !strings.Contains(line, field) {
			t.Errorf("JSON missing field %s in: %s", field, line)
		}
	}
}

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

func strPtr(s string) *string {
	return &s
}
