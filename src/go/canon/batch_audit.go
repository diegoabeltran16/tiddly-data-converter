package canon

import "fmt"

// ---------------------------------------------------------------------------
// S22 — canon-gate-batch-audit-v0
//
// Batch audit layer over the Canon gate (ValidateEntryV0). Evaluates a
// batch of CanonEntry candidates, produces per-item audit detail and an
// aggregate summary suitable for deterministic, reproducible auditing.
//
// This layer REUSES the gate contract already stabilised in S18–S21.
// It does NOT redefine validation rules, schema shape, or collision logic.
//
// Ref: S18 — schema v0 declaration.
// Ref: S19 — active validation gate (ValidateEntryV0).
// Ref: S20 — E2E smoke evidence.
// Ref: S21 — acceptance matrix.
// ---------------------------------------------------------------------------

// ItemVerdict is the audit verdict for a single entry in a batch.
type ItemVerdict string

const (
	// VerdictAccepted means the entry passed ValidateEntryV0.
	VerdictAccepted ItemVerdict = "accepted"
	// VerdictRejected means the entry failed ValidateEntryV0.
	VerdictRejected ItemVerdict = "rejected"
)

// BatchAuditItem holds the audit result for a single entry in a batch.
//
// Each item records the original index (for deterministic traceability),
// the verdict, and the rejection reason when applicable.
//
// Ref: S22 — per-item audit detail.
type BatchAuditItem struct {
	// Index is the zero-based position of the entry in the input batch.
	Index int `json:"index"`
	// Title is the title of the audited entry (for human readability in logs).
	Title string `json:"title"`
	// Verdict is "accepted" or "rejected".
	Verdict ItemVerdict `json:"verdict"`
	// Reason is the rejection cause (empty for accepted entries).
	Reason string `json:"reason,omitempty"`
}

// RejectTally counts occurrences of each distinct rejection reason.
//
// Ref: S22 — aggregated view by rejection motive.
type RejectTally struct {
	Reason string `json:"reason"`
	Count  int    `json:"count"`
}

// BatchAuditSummary holds aggregate counters for a batch audit pass.
//
// Ref: S22 — batch-level summary.
type BatchAuditSummary struct {
	// Total is the number of entries submitted to the audit.
	Total int `json:"total"`
	// Accepted is the count of entries that passed the gate.
	Accepted int `json:"accepted"`
	// Rejected is the count of entries that failed the gate.
	Rejected int `json:"rejected"`
	// RejectsByReason groups rejection counts by distinct reason string.
	RejectsByReason []RejectTally `json:"rejects_by_reason,omitempty"`
}

// BatchAuditResult is the complete audit output for a batch of CanonEntry
// candidates evaluated against the Canon gate v0.
//
// It preserves input order in Items and provides a deterministic Summary.
//
// Ref: S22 — batch audit result structure.
type BatchAuditResult struct {
	// Summary provides aggregate counters for the batch.
	Summary BatchAuditSummary `json:"summary"`
	// Items contains per-entry audit details, in input order.
	Items []BatchAuditItem `json:"items"`
}

// AuditBatch evaluates a batch of CanonEntry candidates against the
// Canon gate v0 (ValidateEntryV0) and returns a deterministic, auditable
// result with per-item detail and aggregate summary.
//
// The function:
//   - processes each entry in order, preserving the input index;
//   - applies ValidateEntryV0 to each entry WITHOUT modifying it;
//   - records accept/reject verdict and rejection reason per item;
//   - computes aggregate counters (total, accepted, rejected);
//   - groups rejections by reason for observability.
//
// An empty batch produces a valid result with Total=0 and no items.
//
// The function does NOT write JSONL, stamp schema_version, or modify
// entries. It is a pure audit/evaluation pass.
//
// Ref: S22 — batch audit over Canon gate v0.
// Ref: S19 — ValidateEntryV0 contract.
func AuditBatch(entries []CanonEntry) BatchAuditResult {
	result := BatchAuditResult{
		Items: make([]BatchAuditItem, 0, len(entries)),
	}
	result.Summary.Total = len(entries)

	reasonCounts := make(map[string]int)

	for i, e := range entries {
		item := BatchAuditItem{
			Index: i,
			Title: e.Title,
		}
		if err := ValidateEntryV0(e); err != nil {
			item.Verdict = VerdictRejected
			item.Reason = err.Error()
			result.Summary.Rejected++
			reasonCounts[item.Reason]++
		} else {
			item.Verdict = VerdictAccepted
			result.Summary.Accepted++
		}
		result.Items = append(result.Items, item)
	}

	// Build sorted-by-first-occurrence tally for deterministic output.
	if len(reasonCounts) > 0 {
		seen := make(map[string]bool)
		for _, item := range result.Items {
			if item.Verdict == VerdictRejected && !seen[item.Reason] {
				seen[item.Reason] = true
				result.Summary.RejectsByReason = append(result.Summary.RejectsByReason,
					RejectTally{Reason: item.Reason, Count: reasonCounts[item.Reason]})
			}
		}
	}

	return result
}

// FormatBatchSummary returns a one-line human-readable summary of a batch
// audit result, suitable for logging.
//
// Ref: S22 — observability mínima del batch audit.
func FormatBatchSummary(r BatchAuditResult) string {
	if r.Summary.Rejected == 0 {
		return fmt.Sprintf("batch_audit: total=%d accepted=%d rejected=%d",
			r.Summary.Total, r.Summary.Accepted, r.Summary.Rejected)
	}
	return fmt.Sprintf("batch_audit: total=%d accepted=%d rejected=%d reject_reasons=%d",
		r.Summary.Total, r.Summary.Accepted, r.Summary.Rejected,
		len(r.Summary.RejectsByReason))
}
