package canon

import (
	"strings"
	"unicode"
)

// CollisionClass categorizes the type of overlap between two CanonEntries.
//
// Ref: S11 — D1/D2/D3/D4 classification from corpus observation.
// Ref: S13 §C — Initial collision matrix for D1/D2/D4.
type CollisionClass string

const (
	// CollisionD1: same CanonKey AND same text content.
	// Observation: both entries are semantically identical.
	// Disposition: collapse — only one needs to be retained in Canon.
	//
	// S11 corpus case: LICENSE tiddler appeared twice with identical content.
	CollisionD1 CollisionClass = "D1"

	// CollisionD2: same CanonKey AND different text content.
	// Observation: two versions of the "same" node with conflicting content.
	// Disposition: pending_review — Canon cannot auto-resolve; human authority required.
	//
	// S11 corpus case: estructura.txt appeared with 3 snapshots at different timestamps.
	CollisionD2 CollisionClass = "D2"

	// CollisionD3: different CanonKey AND same text content.
	// Observation: exact textual equality across distinct titles/keys.
	// Disposition: pending_semantic — exact text alone does not guarantee the
	// same canonical entity; role/path/artifact context may differ.
	//
	// S15 refinement: explicit operational class for exact-content siblings.
	CollisionD3 CollisionClass = "D3"

	// CollisionD4: different CanonKey AND content similarity >= D4JaccardThreshold.
	// Observation: distinct nodes whose text is textually near-identical.
	// Disposition: pending_semantic — Jaccard alone does not imply semantic equivalence;
	// semantic review is required before any merge.
	//
	// S11 corpus case: "#### 🌀 Sesión 08 = ingesta-data-triage" and its
	// "#### 🌀🧾 Procedencia de sesión 08" sibling shared almost identical body text.
	//
	// Important invariant: high Jaccard does NOT automatically imply duplicate.
	// Ref: S13 §C note on Jaccard.
	CollisionD4 CollisionClass = "D4"

	// NoCollision: entries are distinct with no collision detected.
	// Disposition: distinct — both entries are admitted independently.
	NoCollision CollisionClass = "none"
)

// Disposition is the initial Canon action for a detected collision.
type Disposition string

const (
	// DispositionCollapse: entries are equivalent; one can be dropped.
	// Applies to D1 exact duplicates.
	DispositionCollapse Disposition = "collapse"

	// DispositionPendingReview: version conflict; human review required.
	// Applies to D2 (same title, different content).
	DispositionPendingReview Disposition = "pending_review"

	// DispositionPendingSemantic: near-duplicate; semantic review required.
	// Applies to D4 (different title, high content similarity).
	DispositionPendingSemantic Disposition = "pending_semantic"

	// DispositionDistinct: no collision; entries are independent.
	// Applies to NoCollision.
	DispositionDistinct Disposition = "distinct"
)

// CollisionResult describes the Canon initial disposition for a pair of entries.
type CollisionResult struct {
	Class       CollisionClass `json:"class"`
	Disposition Disposition    `json:"disposition"`
	// Note is a human-readable explanation of the collision decision.
	Note string `json:"note,omitempty"`
}

// D4JaccardThreshold is the minimum word-level Jaccard similarity required
// to classify two entries as D4 (near-duplicate).
//
// Provisional for S13 bootstrap. The value 0.85 is derived from the S11
// observation that the Sesión 08 / Procedencia pair showed Jaccard ≈ 1.0.
// The threshold may be tuned once more corpus observations accumulate.
//
// Ref: S11 — near-duplicate Jaccard ≈ 1.0 observation.
const D4JaccardThreshold = 0.85

// ClassifyCollision determines the initial collision class between two CanonEntries.
//
// The function applies the D1/D2/D3/D4 matrix for bootstrap acceptance.
//   - D1: same key + same text
//   - D2: same key + different text
//   - D3: different key + same text
//   - D4: different key + high text similarity (Jaccard >= threshold)
//
// It classifies collisions — it does NOT resolve them.
// Resolution (collapse, merge, discard) requires human authority or a future
// Canon policy that goes beyond the S13 bootstrap scope.
//
// Parameters:
//   - a, b: two CanonEntries arriving from the pre-canonical Ingesta output.
//
// Returns: CollisionResult with Class, Disposition and a short explanatory note.
//
// Ref: S13 §C — Initial collision matrix D1/D2/D4.
// Ref: S15 — explicit D3 acceptance class.
// Ref: S05 §9.8 — deduplication deferred to Canon.
func ClassifyCollision(a, b CanonEntry) CollisionResult {
	sameKey := a.Key == b.Key

	textA := ""
	if a.Text != nil {
		textA = *a.Text
	}
	textB := ""
	if b.Text != nil {
		textB = *b.Text
	}
	sameText := textA == textB

	switch {
	case sameKey && sameText:
		return CollisionResult{
			Class:       CollisionD1,
			Disposition: DispositionCollapse,
			Note:        "identical key and content; safe to collapse",
		}
	case sameKey && !sameText:
		return CollisionResult{
			Class:       CollisionD2,
			Disposition: DispositionPendingReview,
			Note:        "same key with conflicting content; human review required",
		}
	case !sameKey && sameText:
		return CollisionResult{
			Class:       CollisionD3,
			Disposition: DispositionPendingSemantic,
			Note:        "different keys with exact same content; semantic review required",
		}
	default:
		j := JaccardWords(textA, textB)
		if j >= D4JaccardThreshold {
			return CollisionResult{
				Class:       CollisionD4,
				Disposition: DispositionPendingSemantic,
				Note:        "different keys but high content similarity; semantic review required",
			}
		}
		return CollisionResult{
			Class:       NoCollision,
			Disposition: DispositionDistinct,
		}
	}
}

// JaccardWords computes the word-level Jaccard similarity between two strings.
//
//	Jaccard(A, B) = |A ∩ B| / |A ∪ B|
//
// Words are tokenized by splitting on non-letter, non-digit runes and
// folding to lowercase. This handles ASCII and Unicode (including Spanish
// and emoji-heavy tiddler titles observed in the real corpus).
//
// Edge case: two empty strings return 0.0 (no positive evidence of similarity).
//
// Exported so tests can verify the metric directly.
// Ref: S11 — near-duplicate detection; S13 §C — D4 threshold.
func JaccardWords(a, b string) float64 {
	setA := wordSet(a)
	setB := wordSet(b)

	// Degenerate case: empty texts provide no evidence of similarity.
	if len(setA) == 0 && len(setB) == 0 {
		return 0.0
	}

	intersection := 0
	for w := range setA {
		if setB[w] {
			intersection++
		}
	}
	union := len(setA) + len(setB) - intersection
	if union == 0 {
		return 0.0
	}
	return float64(intersection) / float64(union)
}

// wordSet tokenizes s into a set of lowercase words.
// Words are sequences of letters and digits (Unicode-aware).
func wordSet(s string) map[string]bool {
	set := make(map[string]bool)
	words := strings.FieldsFunc(strings.ToLower(s), func(r rune) bool {
		return !unicode.IsLetter(r) && !unicode.IsDigit(r)
	})
	for _, w := range words {
		if w != "" {
			set[w] = true
		}
	}
	return set
}
