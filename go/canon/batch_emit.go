package canon

import (
	"fmt"
	"io"
)

// ---------------------------------------------------------------------------
// S24 — canon-gate-batch-emit-v0
//
// Minimal batch emission seam that stitches together the capabilities
// already stabilised in S16 (WriteJSONL), S19 (gate), S22 (AuditBatch)
// and S23 (BuildBatchReport) to produce a single, observable, reproducible
// emission pass over a batch of CanonEntry candidates.
//
// The pipeline is:
//   batch of CanonEntry → AuditBatch → BuildBatchReport
//     → filter accepted → WriteJSONL (accepted only) → EmitBatchResult
//
// This layer does NOT:
//   - redefine validation rules (S18/S19 gate is reused);
//   - redefine audit semantics (S22 AuditBatch is reused);
//   - persist the report to disk (report is returned in-memory);
//   - modify rejected entries or attempt recovery;
//   - introduce new dependencies.
//
// Ref: S16 — writer mínimo de canon.jsonl.
// Ref: S19 — compuerta activa de validación.
// Ref: S22 — batch audit over Canon gate v0.
// Ref: S23 — batch report over audit result.
// ---------------------------------------------------------------------------

// EmitBatchResult is the structured outcome of a batch emission pass.
//
// It provides full observability: the audit result, the aggregate report,
// the writer result, and convenience counters for quick inspection.
//
// Ref: S24 — structured emission result.
type EmitBatchResult struct {
	// Audit is the full per-item audit result from AuditBatch.
	Audit BatchAuditResult `json:"audit"`
	// Report is the aggregate report built from the audit.
	Report BatchReport `json:"report"`
	// Write is the result from WriteJSONL for the accepted entries.
	Write WriteResult `json:"write"`
	// Total is the number of entries submitted to the emission.
	Total int `json:"total"`
	// Accepted is the count of entries that passed the gate.
	Accepted int `json:"accepted"`
	// Rejected is the count of entries that failed the gate.
	Rejected int `json:"rejected"`
	// Written is the count of entries actually written to the output.
	Written int `json:"written"`
}

// EmitBatchV0 executes a complete batch emission pass:
//
//  1. Audits the full batch via AuditBatch (S22).
//  2. Builds the aggregate BatchReport (S23).
//  3. Selects only the accepted entries, preserving input order.
//  4. Writes the accepted entries to the output via WriteJSONL (S16/S19).
//  5. Returns a structured EmitBatchResult with full observability.
//
// The function guarantees:
//   - rejected entries are never written to the output;
//   - accepted entries are written in the same relative order as in the input;
//   - Written count in the result equals the number of accepted entries
//     (unless a fatal I/O error interrupts writing);
//   - the audit, report and write results are internally consistent.
//
// An empty or nil batch produces a valid result with all counters at zero.
//
// The function returns an error only for fatal I/O failures during writing.
// Validation rejections are NOT errors — they are recorded in the audit
// and report structures.
//
// Ref: S24 — costura mínima de emisión por lote.
// Ref: S22 — AuditBatch.
// Ref: S23 — BuildBatchReport.
// Ref: S16 — WriteJSONL.
func EmitBatchV0(w io.Writer, entries []CanonEntry) (EmitBatchResult, error) {
	var result EmitBatchResult

	// Step 1: Audit the full batch.
	result.Audit = AuditBatch(entries)

	// Step 2: Build aggregate report.
	result.Report = BuildBatchReport(result.Audit)

	// Step 3: Select accepted entries in input order.
	accepted := make([]CanonEntry, 0, result.Audit.Summary.Accepted)
	for _, item := range result.Audit.Items {
		if item.Verdict == VerdictAccepted {
			accepted = append(accepted, entries[item.Index])
		}
	}

	// Step 4: Write accepted entries only.
	writeResult, err := WriteJSONL(w, accepted)
	if err != nil {
		return result, fmt.Errorf("emit_batch: write error: %w", err)
	}
	result.Write = writeResult

	// Step 5: Populate convenience counters.
	result.Total = result.Audit.Summary.Total
	result.Accepted = result.Audit.Summary.Accepted
	result.Rejected = result.Audit.Summary.Rejected
	result.Written = writeResult.Written

	return result, nil
}

// FormatEmitBatchResult returns a one-line human-readable summary of a
// batch emission result, suitable for logging.
//
// Ref: S24 — observability mínima de la emisión por lote.
func FormatEmitBatchResult(r EmitBatchResult) string {
	return fmt.Sprintf("emit_batch: total=%d accepted=%d rejected=%d written=%d",
		r.Total, r.Accepted, r.Rejected, r.Written)
}
