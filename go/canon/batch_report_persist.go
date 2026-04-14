package canon

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
)

// ---------------------------------------------------------------------------
// S26 — canon-gate-batch-report-persist-v0  (base implementation)
// S27 — canon-gate-batch-report-persist-v0  (observability result type)
//
// Minimal, auditable persistence seam for BatchReport as a JSON artifact.
// Provides two functions:
//
//   WriteBatchReportJSON  — serializes a BatchReport to any io.Writer.
//   WriteBatchReportFile  — thin wrapper that persists to a file path.
//
// S27 adds WriteBatchReportResult to provide observable byte-count
// feedback on every write, following the pattern established by
// WriteResult in writer.go.
//
// This layer does NOT:
//   - modify the BatchReport shape (frozen in S23/S25);
//   - re-evaluate entries or audit data;
//   - introduce new dependencies;
//   - define naming policies, directories, or multi-format support.
//
// The serialization produces indented JSON with a trailing newline for
// human inspectability and diff-friendliness.
//
// Ref: S23 — BatchReport contract.
// Ref: S25 — batch contract freeze v1.
// Ref: S26 — base persistence functions.
// Ref: S27 — observability result type.
// ---------------------------------------------------------------------------

// WriteBatchReportResult holds observable counters from a batch report
// persistence operation. Provides verifiable feedback on the write.
//
// Ref: S27 — observability for batch report persistence.
type WriteBatchReportResult struct {
	// BytesWritten is the number of bytes written to the output.
	BytesWritten int `json:"bytes_written"`
}

// WriteBatchReportJSON serializes a BatchReport as indented JSON to w.
//
// The output is valid JSON followed by a single trailing newline ('\n').
// The function does not modify the report; it is a pure read-only
// serialization.
//
// Returns a WriteBatchReportResult with the byte count of the written
// payload, and an error if JSON marshaling fails (should not happen for
// well-formed BatchReport values) or if writing to w fails.
//
// Ref: S26 — batch report persist base function.
// Ref: S27 — observability result type.
func WriteBatchReportJSON(w io.Writer, report BatchReport) (WriteBatchReportResult, error) {
	var result WriteBatchReportResult

	data, err := json.MarshalIndent(report, "", "  ")
	if err != nil {
		return result, fmt.Errorf("batch_report_persist: marshal: %w", err)
	}
	// Append trailing newline for POSIX convention and diff-friendliness.
	data = append(data, '\n')
	n, err := w.Write(data)
	if err != nil {
		return result, fmt.Errorf("batch_report_persist: write: %w", err)
	}
	result.BytesWritten = n
	return result, nil
}

// WriteBatchReportFile persists a BatchReport as a JSON file at path.
//
// This is a thin wrapper over WriteBatchReportJSON. It creates or
// truncates the file at the given path, writes the JSON content, and
// closes the file. The caller is responsible for ensuring the parent
// directory exists.
//
// Returns a WriteBatchReportResult with byte count and an error if the
// file cannot be created or if serialization / writing fails. On write
// failure, a partial file may remain on disk.
//
// Ref: S26 — batch report persist file wrapper.
// Ref: S27 — observability result type.
func WriteBatchReportFile(path string, report BatchReport) (WriteBatchReportResult, error) {
	f, err := os.Create(path)
	if err != nil {
		return WriteBatchReportResult{}, fmt.Errorf("batch_report_persist: create %q: %w", path, err)
	}
	defer f.Close()

	return WriteBatchReportJSON(f, report)
}
