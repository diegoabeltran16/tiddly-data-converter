package canon

import "fmt"

// ---------------------------------------------------------------------------
// S24 — canon-gate-verdict-v0
//
// Batch verdict layer over the Canon gate audit (S22) and report (S23).
// Derives a single, deterministic, global verdict for a processed batch
// from the aggregate counters already stabilised in BatchAuditSummary.
//
// The verdict is a pure function of (Total, Accepted, Rejected) — it does
// NOT re-evaluate individual entries, access external state, or introduce
// new validation logic.
//
// This layer completes the minimal decision surface of the Canon gate v0:
//
//   ValidateEntryV0 (S19) → per-entry gate
//   AuditBatch      (S22) → batch audit with counters
//   BuildBatchReport(S23) → human-inspectable report
//   DeriveVerdict   (S24) → global batch verdict  ← this file
//
// Ref: S19 — ValidateEntryV0 contract.
// Ref: S22 — BatchAuditResult / BatchAuditSummary.
// Ref: S23 — BatchReport.
// ---------------------------------------------------------------------------

// BatchVerdict is the global verdict for a processed batch.
type BatchVerdict string

const (
	// VerdictEmpty means the batch contained no entries (Total == 0).
	VerdictEmpty BatchVerdict = "empty"
	// VerdictAccept means all entries were accepted (Rejected == 0, Accepted > 0).
	VerdictAccept BatchVerdict = "accept"
	// VerdictReject means all entries were rejected (Accepted == 0, Rejected > 0).
	VerdictReject BatchVerdict = "reject"
	// VerdictMixed means both accepted and rejected entries exist.
	VerdictMixed BatchVerdict = "mixed"
)

// GateVerdict holds the deterministic global verdict for a batch,
// together with the counters from which it was derived for traceability.
//
// Ref: S24 — gate verdict structure.
type GateVerdict struct {
	// Verdict is the global batch verdict.
	Verdict BatchVerdict `json:"verdict"`
	// Total entries evaluated.
	Total int `json:"total"`
	// Accepted entries count.
	Accepted int `json:"accepted"`
	// Rejected entries count.
	Rejected int `json:"rejected"`
}

// DeriveVerdict computes the global batch verdict from a BatchAuditResult.
//
// The derivation is deterministic and based exclusively on the aggregate
// counters in the audit summary:
//
//   - empty  : Total == 0
//   - accept : Rejected == 0 && Accepted > 0
//   - reject : Accepted == 0 && Rejected > 0
//   - mixed  : Accepted > 0 && Rejected > 0
//
// The function does NOT re-evaluate entries, modify the audit result, or
// access external state. It is a pure projection: summary counters → verdict.
//
// Ref: S24 — deterministic verdict derivation.
// Ref: S22 — BatchAuditResult contract.
func DeriveVerdict(audit BatchAuditResult) GateVerdict {
	s := audit.Summary
	v := GateVerdict{
		Total:    s.Total,
		Accepted: s.Accepted,
		Rejected: s.Rejected,
	}

	switch {
	case s.Total == 0:
		v.Verdict = VerdictEmpty
	case s.Rejected == 0 && s.Accepted > 0:
		v.Verdict = VerdictAccept
	case s.Accepted == 0 && s.Rejected > 0:
		v.Verdict = VerdictReject
	default:
		// Both accepted > 0 and rejected > 0.
		v.Verdict = VerdictMixed
	}

	return v
}

// FormatVerdict returns a one-line human-readable summary of a gate verdict,
// suitable for logging.
//
// Ref: S24 — observability mínima del verdict.
func FormatVerdict(v GateVerdict) string {
	return fmt.Sprintf("gate_verdict: verdict=%s total=%d accepted=%d rejected=%d",
		v.Verdict, v.Total, v.Accepted, v.Rejected)
}
