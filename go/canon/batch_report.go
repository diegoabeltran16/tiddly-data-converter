package canon

import (
	"fmt"
	"strings"
)

// ---------------------------------------------------------------------------
// S23 — canon-gate-batch-report-v0
//
// Structured batch report layer over the Canon gate audit (S22).
// Takes a BatchAuditResult and produces a self-describing, reproducible
// report with metadata, the full audit output, and derived observations.
//
// This layer REUSES the audit contract already stabilised in S22.
// It does NOT redefine validation rules, schema shape, collision logic,
// or audit semantics. It adds report-level metadata and observations
// that make the audit result inspectable as a standalone artefact.
//
// Ref: S22 — AuditBatch, BatchAuditResult.
// Ref: S21 — acceptance matrix (determines what accepted/rejected means).
// Ref: S19 — ValidateEntryV0 (gate contract).
// Ref: S18 — schema v0 declaration.
// ---------------------------------------------------------------------------

// BatchReportMeta holds report-level metadata for a batch report artefact.
//
// All fields are informational and do not affect the audit logic.
//
// Ref: S23 — report metadata.
type BatchReportMeta struct {
	// Session identifies the processing session that produced this report.
	Session string `json:"session"`

	// SchemaVersion identifies the Canon schema version used by the gate.
	SchemaVersion string `json:"schema_version"`

	// GateVersion identifies the gate contract version.
	GateVersion string `json:"gate_version"`

	// Timestamp is the ISO-8601 or TW5-format timestamp of report generation.
	Timestamp string `json:"timestamp"`
}

// ReportObservation is a structured note or warning derived from the
// audit result during report assembly.
//
// Observations are informational — they do not alter the audit data.
// They highlight edge cases, distribution patterns, and notable conditions
// that aid human inspection.
//
// Ref: S23 — observability mínima del reporte batch.
type ReportObservation struct {
	// Code is a machine-readable observation identifier (e.g. "empty_batch").
	Code string `json:"code"`
	// Message is a human-readable description.
	Message string `json:"message"`
}

// Observation codes emitted by GenerateBatchReport.
const (
	ObsEmptyBatch        = "empty_batch"
	ObsAllAccepted       = "all_accepted"
	ObsAllRejected       = "all_rejected"
	ObsHighRejectionRate = "high_rejection_rate"
)

// BatchReport is the structured batch report for Canon Gate processing.
//
// It wraps a BatchAuditResult (S22) with report-level metadata and
// derived observations, producing a self-describing, inspectable artefact.
//
// The report does NOT modify the audit data. It adds context.
//
// Ref: S23 — batch report v0 over Canon gate.
type BatchReport struct {
	// Meta holds report-level metadata.
	Meta BatchReportMeta `json:"meta"`

	// Summary is the aggregate audit summary (total, accepted, rejected,
	// rejects_by_reason). Copied from BatchAuditResult.Summary.
	Summary BatchAuditSummary `json:"summary"`

	// Items contains per-entry audit details in input order.
	// Copied from BatchAuditResult.Items.
	Items []BatchAuditItem `json:"items"`

	// Observations are derived notes/warnings about the batch.
	Observations []ReportObservation `json:"observations,omitempty"`
}

// GenerateBatchReport creates a BatchReport from a BatchAuditResult,
// enriching it with report-level metadata and derived observations.
//
// Parameters:
//   - audit: the BatchAuditResult produced by AuditBatch (S22).
//   - timestamp: the report generation timestamp (ISO-8601 or TW5 format).
//     The caller is responsible for providing the timestamp — the report
//     function does not call time.Now() to preserve determinism in tests.
//
// The function:
//   - copies the audit summary and items into the report;
//   - stamps metadata (session, schema_version, gate_version, timestamp);
//   - derives observations from the audit result.
//
// Ref: S23 — batch report generation.
func GenerateBatchReport(audit BatchAuditResult, timestamp string) BatchReport {
	report := BatchReport{
		Meta: BatchReportMeta{
			Session:       "m02-s23-canon-gate-batch-report-v0",
			SchemaVersion: SchemaV0,
			GateVersion:   "gate-v0",
			Timestamp:     timestamp,
		},
		Summary: audit.Summary,
		Items:   audit.Items,
	}

	report.Observations = deriveObservations(audit)

	return report
}

// deriveObservations produces structured observations from the audit result.
//
// Rules (conservative — only emit observations justified by S19–S22 data):
//
//   - empty_batch: Total == 0
//   - all_accepted: Total > 0 && Rejected == 0
//   - all_rejected: Total > 0 && Accepted == 0
//   - high_rejection_rate: Total > 0 && Rejected > Accepted
//
// Observations are NOT errors. They are informational.
func deriveObservations(audit BatchAuditResult) []ReportObservation {
	var obs []ReportObservation

	s := audit.Summary

	if s.Total == 0 {
		obs = append(obs, ReportObservation{
			Code:    ObsEmptyBatch,
			Message: "No entries were submitted for processing.",
		})
		return obs
	}

	if s.Rejected == 0 {
		obs = append(obs, ReportObservation{
			Code:    ObsAllAccepted,
			Message: fmt.Sprintf("All %d entries passed the gate.", s.Total),
		})
	}

	if s.Accepted == 0 {
		obs = append(obs, ReportObservation{
			Code:    ObsAllRejected,
			Message: fmt.Sprintf("No entries passed the gate (%d rejected).", s.Rejected),
		})
	}

	if s.Total > 0 && s.Rejected > 0 && s.Accepted > 0 && s.Rejected > s.Accepted {
		obs = append(obs, ReportObservation{
			Code: ObsHighRejectionRate,
			Message: fmt.Sprintf("High rejection rate: %d of %d entries rejected (%.0f%%).",
				s.Rejected, s.Total, float64(s.Rejected)/float64(s.Total)*100),
		})
	}

	return obs
}

// FormatBatchReport returns a multi-line, human-readable rendering of a
// BatchReport, suitable for logging, CLI output, or human inspection.
//
// The format is structured but not machine-parseable (use JSON serialization
// for that). It is designed for readability and auditability.
//
// Ref: S23 — human-readable batch report.
func FormatBatchReport(r BatchReport) string {
	var b strings.Builder

	// Header
	b.WriteString("=== Canon Gate Batch Report ===\n")
	b.WriteString(fmt.Sprintf("Session:        %s\n", r.Meta.Session))
	b.WriteString(fmt.Sprintf("SchemaVersion:  %s\n", r.Meta.SchemaVersion))
	b.WriteString(fmt.Sprintf("GateVersion:    %s\n", r.Meta.GateVersion))
	b.WriteString(fmt.Sprintf("Timestamp:      %s\n", r.Meta.Timestamp))
	b.WriteString("\n")

	// Summary
	b.WriteString("--- Summary ---\n")
	b.WriteString(fmt.Sprintf("Total:    %d\n", r.Summary.Total))
	b.WriteString(fmt.Sprintf("Accepted: %d\n", r.Summary.Accepted))
	b.WriteString(fmt.Sprintf("Rejected: %d\n", r.Summary.Rejected))

	if len(r.Summary.RejectsByReason) > 0 {
		b.WriteString("\n--- Rejections by Reason ---\n")
		for _, rt := range r.Summary.RejectsByReason {
			b.WriteString(fmt.Sprintf("  [%d] %s\n", rt.Count, rt.Reason))
		}
	}

	// Items
	if len(r.Items) > 0 {
		b.WriteString("\n--- Items ---\n")
		for _, item := range r.Items {
			if item.Verdict == VerdictAccepted {
				b.WriteString(fmt.Sprintf("  [%d] %-10s %s\n", item.Index, item.Verdict, item.Title))
			} else {
				b.WriteString(fmt.Sprintf("  [%d] %-10s %s — %s\n", item.Index, item.Verdict, item.Title, item.Reason))
			}
		}
	}

	// Observations
	if len(r.Observations) > 0 {
		b.WriteString("\n--- Observations ---\n")
		for _, obs := range r.Observations {
			b.WriteString(fmt.Sprintf("  [%s] %s\n", obs.Code, obs.Message))
		}
	}

	return b.String()
}
