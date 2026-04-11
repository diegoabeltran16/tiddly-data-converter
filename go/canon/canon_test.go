package canon_test

import (
	"testing"

	"github.com/tiddly-data-converter/canon"
)

// strPtr is a test helper to create a *string from a literal.
func strPtr(s string) *string { return &s }

// ---------------------------------------------------------------------------
// Identity tests
// ---------------------------------------------------------------------------

// TestKeyOf validates that CanonKey is derived from the title.
// Ref: S13 §B — identity key derivation.
func TestKeyOf(t *testing.T) {
	cases := []struct {
		title string
		want  canon.CanonKey
	}{
		{"LICENSE", canon.CanonKey("LICENSE")},
		{"estructura.txt", canon.CanonKey("estructura.txt")},
		{"#### 🌀 Sesión 08 = ingesta-data-triage", canon.CanonKey("#### 🌀 Sesión 08 = ingesta-data-triage")},
		{"", canon.CanonKey("")},
	}
	for _, tc := range cases {
		got := canon.KeyOf(tc.title)
		if got != tc.want {
			t.Errorf("KeyOf(%q) = %q; want %q", tc.title, got, tc.want)
		}
	}
}

// TestCanonEntry_Fields validates that CanonEntry stores all required fields.
// Ref: S13 §B — minimum canonical tiddler identity.
func TestCanonEntry_Fields(t *testing.T) {
	body := "Apache License 2.0"
	pos := "tiddler-store:112"
	e := canon.CanonEntry{
		Key:            canon.KeyOf("LICENSE"),
		Title:          "LICENSE",
		Text:           strPtr(body),
		SourcePosition: strPtr(pos),
	}
	if e.Key != canon.CanonKey("LICENSE") {
		t.Errorf("Key mismatch: %q", e.Key)
	}
	if e.Title != "LICENSE" {
		t.Errorf("Title mismatch: %q", e.Title)
	}
	if e.Text == nil || *e.Text != body {
		t.Errorf("Text mismatch: %v", e.Text)
	}
	if e.SourcePosition == nil || *e.SourcePosition != pos {
		t.Errorf("SourcePosition mismatch: %v", e.SourcePosition)
	}
}

// ---------------------------------------------------------------------------
// Collision classification tests — acceptance cases derived from S11 fixtures
// ---------------------------------------------------------------------------

// TestClassifyCollision_D1_ExactDuplicate validates the D1 classification.
//
// Acceptance case derived from S11 fixture raw_tiddlers_d1_exact_duplicate.json:
// The LICENSE tiddler appeared twice in the corpus with identical title and body.
//
// Expected: CollisionD1, DispositionCollapse.
// Ref: S13 §C — D1: same title + same content → collapse.
// Ref: S11 corpus observation — LICENSE case.
func TestClassifyCollision_D1_ExactDuplicate(t *testing.T) {
	body := "Apache License 2.0 — minimal representative body for duplicate observation."
	a := canon.CanonEntry{
		Key:            canon.KeyOf("LICENSE"),
		Title:          "LICENSE",
		Text:           strPtr(body),
		SourcePosition: strPtr("tiddler-store:112"),
	}
	b := canon.CanonEntry{
		Key:            canon.KeyOf("LICENSE"),
		Title:          "LICENSE",
		Text:           strPtr(body),
		SourcePosition: strPtr("tiddler-store:113"),
	}

	result := canon.ClassifyCollision(a, b)

	if result.Class != canon.CollisionD1 {
		t.Errorf("expected D1, got %q (note: %s)", result.Class, result.Note)
	}
	if result.Disposition != canon.DispositionCollapse {
		t.Errorf("expected collapse disposition, got %q", result.Disposition)
	}
}

// TestClassifyCollision_D2_SameTitleDiffContent validates the D2 classification.
//
// Acceptance case derived from S11 fixture raw_tiddlers_d2_same_title_diff_content.json:
// The estructura.txt tiddler appeared with the same title but different body snapshots.
//
// Expected: CollisionD2, DispositionPendingReview.
// Ref: S13 §C — D2: same title + different content → pending human review.
// Ref: S11 corpus observation — estructura.txt case (3 versions).
func TestClassifyCollision_D2_SameTitleDiffContent(t *testing.T) {
	a := canon.CanonEntry{
		Key:   canon.KeyOf("estructura.txt"),
		Title: "estructura.txt",
		Text: strPtr("├── .gitignore\n├── contratos\n│   ├── contratos.txt\n" +
			"│   └── m01-s01-extractor-contract.md\n├── data\n└── rust"),
		SourcePosition: strPtr("tiddler-store:144"),
	}
	b := canon.CanonEntry{
		Key:   canon.KeyOf("estructura.txt"),
		Title: "estructura.txt",
		Text: strPtr("├── .github\n│   └── workflows\n│       └── ci.yml\n" +
			"├── .gitignore\n├── contratos\n│   ├── contratos.txt\n" +
			"│   ├── m01-s01-extractor-contract.md\n" +
			"│   └── m01-s07-ingesta-bootstrap.md.json\n" +
			"├── data\n├── go\n│   └── ingesta\n└── rust"),
		SourcePosition: strPtr("tiddler-store:146"),
	}

	result := canon.ClassifyCollision(a, b)

	if result.Class != canon.CollisionD2 {
		t.Errorf("expected D2, got %q (note: %s)", result.Class, result.Note)
	}
	if result.Disposition != canon.DispositionPendingReview {
		t.Errorf("expected pending_review disposition, got %q", result.Disposition)
	}
}

// TestClassifyCollision_D4_NearDuplicate validates the D4 classification.
//
// Acceptance case derived from S11 fixture raw_tiddlers_d4_near_duplicate.json:
// "#### 🌀 Sesión 08 = ingesta-data-triage" and its procedencia sibling
// shared almost identical body text (Jaccard ≈ 1.0) but had different titles.
//
// Expected: CollisionD4, DispositionPendingSemantic.
// Ref: S13 §C — D4: different title + high similarity → pending semantic review.
// Ref: S11 corpus observation — Sesión 08 / Procedencia pair.
func TestClassifyCollision_D4_NearDuplicate(t *testing.T) {
	sharedBody := "Sesión 08: ingesta-data-triage. Milestone M01. " +
		"Objetivo: triage semántico del corpus real. " +
		"Resultado: hallazgo I-1 truncamiento de milisegundos."

	a := canon.CanonEntry{
		Key:            canon.KeyOf("#### 🌀 Sesión 08 = ingesta-data-triage"),
		Title:          "#### 🌀 Sesión 08 = ingesta-data-triage",
		Text:           strPtr(sharedBody),
		SourcePosition: strPtr("tiddler-store:41"),
	}
	b := canon.CanonEntry{
		Key:            canon.KeyOf("#### 🌀🧾 Procedencia de sesión 08 = ingesta-data-triage"),
		Title:          "#### 🌀🧾 Procedencia de sesión 08 = ingesta-data-triage",
		Text:           strPtr(sharedBody),
		SourcePosition: strPtr("tiddler-store:61"),
	}

	result := canon.ClassifyCollision(a, b)

	if result.Class != canon.CollisionD4 {
		t.Errorf("expected D4, got %q (note: %s)", result.Class, result.Note)
	}
	if result.Disposition != canon.DispositionPendingSemantic {
		t.Errorf("expected pending_semantic disposition, got %q", result.Disposition)
	}
}

// TestClassifyCollision_NoCollision_DistinctEntries validates that entries
// with different titles and dissimilar content produce NoCollision.
//
// This covers the base case: most tiddlers in the corpus are distinct entities.
func TestClassifyCollision_NoCollision_DistinctEntries(t *testing.T) {
	a := canon.CanonEntry{
		Key:   canon.KeyOf("## 🧭🧱 Protocolo de Sesión"),
		Title: "## 🧭🧱 Protocolo de Sesión",
		Text:  strPtr("Este tiddler contiene el protocolo operativo de sesión del sistema."),
	}
	b := canon.CanonEntry{
		Key:   canon.KeyOf("## 🧠🧱 Política de Memoria Activa"),
		Title: "## 🧠🧱 Política de Memoria Activa",
		Text:  strPtr("Define cómo el agente recupera y prioriza contexto en sesiones largas."),
	}

	result := canon.ClassifyCollision(a, b)

	if result.Class != canon.NoCollision {
		t.Errorf("expected no collision, got %q (note: %s)", result.Class, result.Note)
	}
	if result.Disposition != canon.DispositionDistinct {
		t.Errorf("expected distinct disposition, got %q", result.Disposition)
	}
}

// TestClassifyCollision_Symmetry validates that ClassifyCollision(a,b) == ClassifyCollision(b,a)
// for all collision classes. Collision detection must be symmetric.
func TestClassifyCollision_Symmetry(t *testing.T) {
	body := "Apache License 2.0 — minimal representative body for duplicate observation."

	cases := []struct {
		name string
		a, b canon.CanonEntry
	}{
		{
			name: "D1",
			a:    canon.CanonEntry{Key: canon.KeyOf("LICENSE"), Title: "LICENSE", Text: strPtr(body)},
			b:    canon.CanonEntry{Key: canon.KeyOf("LICENSE"), Title: "LICENSE", Text: strPtr(body)},
		},
		{
			name: "D2",
			a:    canon.CanonEntry{Key: canon.KeyOf("T"), Title: "T", Text: strPtr("content A")},
			b:    canon.CanonEntry{Key: canon.KeyOf("T"), Title: "T", Text: strPtr("content B")},
		},
		{
			name: "NoCollision",
			a:    canon.CanonEntry{Key: canon.KeyOf("Alpha"), Title: "Alpha", Text: strPtr("alpha content here")},
			b:    canon.CanonEntry{Key: canon.KeyOf("Beta"), Title: "Beta", Text: strPtr("completely different words")},
		},
	}
	for _, tc := range cases {
		ab := canon.ClassifyCollision(tc.a, tc.b)
		ba := canon.ClassifyCollision(tc.b, tc.a)
		if ab.Class != ba.Class {
			t.Errorf("%s: ClassifyCollision(a,b).Class=%q != ClassifyCollision(b,a).Class=%q",
				tc.name, ab.Class, ba.Class)
		}
		if ab.Disposition != ba.Disposition {
			t.Errorf("%s: disposition asymmetry: %q vs %q", tc.name, ab.Disposition, ba.Disposition)
		}
	}
}

// ---------------------------------------------------------------------------
// Jaccard similarity metric tests
// ---------------------------------------------------------------------------

// TestJaccardWords_EmptyStrings validates the degenerate case.
// Two empty texts return 0.0 — no positive evidence of similarity.
// Ref: S13 §C — JaccardWords edge case note.
func TestJaccardWords_EmptyStrings(t *testing.T) {
	j := canon.JaccardWords("", "")
	if j != 0.0 {
		t.Errorf("expected 0.0 for empty strings, got %f", j)
	}
}

// TestJaccardWords_IdenticalStrings validates that identical text yields 1.0.
func TestJaccardWords_IdenticalStrings(t *testing.T) {
	s := "Sesión 08 ingesta data triage milestone M01"
	j := canon.JaccardWords(s, s)
	if j != 1.0 {
		t.Errorf("expected 1.0 for identical strings, got %f", j)
	}
}

// TestJaccardWords_DisjointStrings validates that fully disjoint text yields 0.0.
func TestJaccardWords_DisjointStrings(t *testing.T) {
	j := canon.JaccardWords("alpha beta gamma", "delta epsilon zeta")
	if j != 0.0 {
		t.Errorf("expected 0.0 for disjoint strings, got %f", j)
	}
}

// TestJaccardWords_PartialOverlap validates an intermediate similarity score.
// "alpha beta gamma" vs "alpha beta delta": intersection={alpha,beta}, union={alpha,beta,gamma,delta}
// Expected: 2/4 = 0.5
func TestJaccardWords_PartialOverlap(t *testing.T) {
	j := canon.JaccardWords("alpha beta gamma", "alpha beta delta")
	const want = 0.5
	if j != want {
		t.Errorf("expected %f for partial overlap, got %f", want, j)
	}
}

// TestJaccardWords_AboveD4Threshold confirms the D4 fixture pair exceeds the threshold.
//
// S11 observation: the Sesión 08 / Procedencia pair shares identical body text,
// giving Jaccard ≈ 1.0. This test verifies the pair exceeds D4JaccardThreshold.
func TestJaccardWords_AboveD4Threshold(t *testing.T) {
	sharedBody := "Sesión 08: ingesta-data-triage. Milestone M01. " +
		"Objetivo: triage semántico del corpus real. " +
		"Resultado: hallazgo I-1 truncamiento de milisegundos."

	j := canon.JaccardWords(sharedBody, sharedBody)
	if j < canon.D4JaccardThreshold {
		t.Errorf("expected Jaccard >= %f for identical D4 fixture texts, got %f",
			canon.D4JaccardThreshold, j)
	}
}
