package bridge

import (
	"fmt"

	"github.com/tiddly-data-converter/canon"
)

// AdmitReport summarises the result of running Canon admission on a batch
// of CanonEntries. It provides observable counters for auditing the bridge.
//
// This report is PROVISIONAL for S14. A definitive CanonReport may replace
// or extend it when the full Canon admission logic is formalized.
//
// Ref: S13 §12 — "Admisión de corpus completo (pendiente etapa posterior)".
type AdmitReport struct {
	// InputCount is the number of CanonEntries submitted for admission.
	InputCount int `json:"input_count"`

	// DistinctCount is the number of entries admitted as distinct (no collision).
	DistinctCount int `json:"distinct_count"`

	// D1Count is the number of D1 collisions (exact duplicates) detected.
	D1Count int `json:"d1_count"`

	// D2Count is the number of D2 collisions (same key, different content) detected.
	D2Count int `json:"d2_count"`

	// D4Count is the number of D4 collisions (near-duplicates) detected.
	D4Count int `json:"d4_count"`

	// Collisions contains every collision detected between pairs of entries.
	Collisions []CollisionRecord `json:"collisions,omitempty"`
}

// CollisionRecord is a single collision observation between two entries.
type CollisionRecord struct {
	IndexA int                    `json:"index_a"`
	IndexB int                    `json:"index_b"`
	TitleA string                 `json:"title_a"`
	TitleB string                 `json:"title_b"`
	Result canon.CollisionResult  `json:"result"`
}

// Admit runs the existing Canon collision classification over a batch of
// CanonEntries and produces an AdmitReport with observable counters.
//
// This function does NOT resolve collisions. It classifies them using
// canon.ClassifyCollision and records the results for human review.
//
// The algorithm is O(n²) pairwise comparison, which is acceptable for the
// current corpus size (< 500 tiddlers). Future optimization is deferred.
//
// Ref: S13 §C — ClassifyCollision.
// Ref: S14 §A — bridge mínimo.
func Admit(entries []canon.CanonEntry) *AdmitReport {
	report := &AdmitReport{
		InputCount: len(entries),
		Collisions: []CollisionRecord{},
	}

	// Track which entries have been involved in a collision.
	involved := make(map[int]bool)

	for i := 0; i < len(entries); i++ {
		for j := i + 1; j < len(entries); j++ {
			result := canon.ClassifyCollision(entries[i], entries[j])
			if result.Class == canon.NoCollision {
				continue
			}

			involved[i] = true
			involved[j] = true

			record := CollisionRecord{
				IndexA: i,
				IndexB: j,
				TitleA: entries[i].Title,
				TitleB: entries[j].Title,
				Result: result,
			}
			report.Collisions = append(report.Collisions, record)

			switch result.Class {
			case canon.CollisionD1:
				report.D1Count++
			case canon.CollisionD2:
				report.D2Count++
			case canon.CollisionD4:
				report.D4Count++
			}
		}
	}

	// Distinct entries: those not involved in any collision.
	report.DistinctCount = len(entries) - len(involved)

	return report
}

// Summary returns a human-readable one-line summary of the AdmitReport.
func (r *AdmitReport) Summary() string {
	return fmt.Sprintf(
		"input=%d distinct=%d d1=%d d2=%d d4=%d collisions=%d",
		r.InputCount,
		r.DistinctCount,
		r.D1Count,
		r.D2Count,
		r.D4Count,
		len(r.Collisions),
	)
}
