package canon

// ---------------------------------------------------------------------------
// S25 — canon-gate-batch-contract-v1
//
// Formal contract that freezes the interfaces, ownership boundaries,
// field provenance and cross-layer invariants of the Canon gate batch
// pipeline stabilised in S22–S24.
//
// This file does NOT introduce new behaviour. It declares, documents and
// exposes compile-time-verifiable constants that downstream consumers and
// parallel sessions can depend on without risking semantic collision.
//
// Pipeline shape (frozen):
//
//   []CanonEntry
//     → AuditBatch        (S22)  → BatchAuditResult
//     → BuildBatchReport  (S23)  → BatchReport
//     → DeriveVerdict     (S24)  → GateVerdict
//     → EmitBatchV0       (S24)  → EmitBatchResult   (orchestrator)
//
// Ownership summary:
//
//   Audit  — evaluates each entry against ValidateEntryV0; OWNS
//            ItemVerdict, BatchAuditItem, RejectTally, BatchAuditSummary,
//            BatchAuditResult. Source of truth for per-item verdicts and
//            aggregate counters (Total, Accepted, Rejected).
//
//   Report — projects audit result into a human-inspectable view; OWNS
//            BatchReport, RejectedEntry, AcceptedTitles list.
//            Does NOT re-evaluate entries.
//
//   Verdict — derives a single global verdict from audit counters; OWNS
//             BatchVerdict enum, GateVerdict struct.
//             Does NOT re-evaluate entries.
//
//   Emit   — orchestrates audit → report → filter → write; OWNS
//            EmitBatchResult (which embeds Audit, Report, Write results
//            plus convenience counters). Does NOT re-evaluate entries.
//
// Ref: S22 — batch audit contract.
// Ref: S23 — batch report contract.
// Ref: S24 — batch emit and verdict contracts.
// Ref: S25 — this contract freeze.
// ---------------------------------------------------------------------------

// BatchContractVersion is the version of the gate batch contract.
// Consumers that depend on the frozen interface shape should assert this
// constant to detect breaking changes at compile/test time.
//
// Ref: S25 — contract version declaration.
const BatchContractVersion = "v1"

// ---------------------------------------------------------------------------
// Field provenance — source vs derived
// ---------------------------------------------------------------------------
//
// SOURCE (authoritative):
//   - BatchAuditResult.Summary.Total      — count of entries submitted
//   - BatchAuditResult.Summary.Accepted   — count passing ValidateEntryV0
//   - BatchAuditResult.Summary.Rejected   — count failing ValidateEntryV0
//   - BatchAuditResult.Items[i].Verdict   — per-entry accept/reject
//   - BatchAuditResult.Items[i].Reason    — rejection cause
//
// DERIVED (must be consistent with source):
//   - BatchReport.Total / .Accepted / .Rejected  — copied from audit
//   - BatchReport.AcceptedTitles                  — from audit Items
//   - BatchReport.RejectedEntries                 — from audit Items
//   - BatchReport.RejectsByReason                 — from audit summary
//   - GateVerdict.Total / .Accepted / .Rejected   — from audit summary
//   - GateVerdict.Verdict                         — from audit counters
//   - EmitBatchResult.Total / .Accepted / .Rejected — from audit summary
//   - EmitBatchResult.Written                     — from WriteResult
//
// ---------------------------------------------------------------------------
// Cross-layer invariants (tested in batch_contract_test.go)
// ---------------------------------------------------------------------------
//
// INV-1  Total == Accepted + Rejected            (all layers)
// INV-2  len(Items) == Total                     (audit)
// INV-3  Items preserve input order              (audit)
// INV-4  Written == Accepted                     (emit, absent I/O error)
// INV-5  len(AcceptedTitles) == Accepted         (report)
// INV-6  len(RejectedEntries) == Rejected        (report)
// INV-7  sum(RejectsByReason[].Count) == Rejected (audit/report)
// INV-8  Report counters == Audit counters       (report)
// INV-9  Verdict counters == Audit counters      (verdict)
// INV-10 Emit counters == Audit counters         (emit)
// INV-11 No re-evaluation in Report              (structural)
// INV-12 No re-evaluation in Emit                (structural)
// INV-13 No re-evaluation in Verdict             (structural)
// ---------------------------------------------------------------------------
