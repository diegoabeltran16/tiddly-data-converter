package canon

import "fmt"

// ---------------------------------------------------------------------------
// S23 — canon-gate-batch-report-v0
//
// Aggregate report layer over the batch audit result (S22). Transforms the
// per-item audit detail into a human-inspectable, structured report with
// accepted/rejected entry lists, reason distribution, and one-line summary.
//
// This layer REUSES the BatchAuditResult contract from S22 without modifying
// or re-evaluating entries. It is a pure projection: audit result → report.
//
// Ref: S22 — batch audit result structure.
// Ref: S19 — ValidateEntryV0 contract (used by AuditBatch).
// ---------------------------------------------------------------------------

// BatchReport is the aggregate, human-inspectable report built from a
// BatchAuditResult. It preserves the counters and adds structured lists
// of accepted/rejected entries for observability and post-hoc inspection.
//
// Ref: S23 — batch report over audit result.
type BatchReport struct {
	// Total entries in the audited batch.
	Total int `json:"total"`
	// Accepted count.
	Accepted int `json:"accepted"`
	// Rejected count.
	Rejected int `json:"rejected"`
	// AcceptedTitles lists the titles of accepted entries, in input order.
	AcceptedTitles []string `json:"accepted_titles"`
	// RejectedEntries lists rejected items with index, title and reason.
	RejectedEntries []RejectedEntry `json:"rejected_entries,omitempty"`
	// RejectsByReason groups rejection counts by distinct reason string.
	RejectsByReason []RejectTally `json:"rejects_by_reason,omitempty"`
}

// RejectedEntry is a summary of a single rejected entry in the report.
type RejectedEntry struct {
	Index  int    `json:"index"`
	Title  string `json:"title"`
	Reason string `json:"reason"`
}

// BuildBatchReport constructs a BatchReport from a BatchAuditResult.
//
// The function is a pure projection — it does not re-evaluate entries,
// modify audit data, or access external state. It extracts accepted
// titles and rejected entries from the audit items in input order.
//
// An audit result with Total=0 produces a valid report with empty lists.
//
// Ref: S23 — batch report over Canon gate batch audit.
// Ref: S22 — BatchAuditResult contract.
func BuildBatchReport(audit BatchAuditResult) BatchReport {
	report := BatchReport{
		Total:           audit.Summary.Total,
		Accepted:        audit.Summary.Accepted,
		Rejected:        audit.Summary.Rejected,
		AcceptedTitles:  make([]string, 0, audit.Summary.Accepted),
		RejectsByReason: audit.Summary.RejectsByReason,
	}

	for _, item := range audit.Items {
		switch item.Verdict {
		case VerdictAccepted:
			report.AcceptedTitles = append(report.AcceptedTitles, item.Title)
		case VerdictRejected:
			report.RejectedEntries = append(report.RejectedEntries, RejectedEntry{
				Index:  item.Index,
				Title:  item.Title,
				Reason: item.Reason,
			})
		}
	}

	return report
}

// FormatBatchReport returns a one-line human-readable summary of a batch
// report, suitable for logging.
//
// Ref: S23 — observability mínima del batch report.
func FormatBatchReport(r BatchReport) string {
	if r.Rejected == 0 {
		return fmt.Sprintf("batch_report: total=%d accepted=%d rejected=%d",
			r.Total, r.Accepted, r.Rejected)
	}
	return fmt.Sprintf("batch_report: total=%d accepted=%d rejected=%d reject_reasons=%d",
		r.Total, r.Accepted, r.Rejected,
		len(r.RejectsByReason))
}
