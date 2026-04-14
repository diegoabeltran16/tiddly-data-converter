package canon

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
)

// ---------------------------------------------------------------------------
// S26 — canon-gate-batch-report-persist-v0
//
// Minimal, auditable persistence seam for BatchReport as a JSON artifact.
// Provides two functions:
//
//   WriteBatchReportJSON  — serializes a BatchReport to any io.Writer.
//   WriteBatchReportFile  — thin wrapper that persists to a file path.
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
// ---------------------------------------------------------------------------

// WriteBatchReportJSON serializes a BatchReport as indented JSON to w.
//
// The output is valid JSON followed by a single trailing newline ('\n').
// The function does not modify the report; it is a pure read-only
// serialization.
//
// Returns an error if JSON marshaling fails (should not happen for
// well-formed BatchReport values) or if writing to w fails.
//
// Ref: S26 — batch report persist base function.
func WriteBatchReportJSON(w io.Writer, report BatchReport) error {
	data, err := json.MarshalIndent(report, "", "  ")
	if err != nil {
		return fmt.Errorf("batch_report_persist: marshal: %w", err)
	}
	// Append trailing newline for POSIX convention and diff-friendliness.
	data = append(data, '\n')
	if _, err := w.Write(data); err != nil {
		return fmt.Errorf("batch_report_persist: write: %w", err)
	}
	return nil
}

// WriteBatchReportFile persists a BatchReport as a JSON file at path.
//
// This is a thin wrapper over WriteBatchReportJSON. It creates or
// truncates the file at the given path, writes the JSON content, and
// closes the file. The caller is responsible for ensuring the parent
// directory exists.
//
// Returns an error if the file cannot be created or if serialization /
// writing fails. On write failure, a partial file may remain on disk.
//
// Ref: S26 — batch report persist file wrapper.
func WriteBatchReportFile(path string, report BatchReport) error {
	f, err := os.Create(path)
	if err != nil {
		return fmt.Errorf("batch_report_persist: create %q: %w", path, err)
	}
	defer f.Close()

	if err := WriteBatchReportJSON(f, report); err != nil {
		return err
	}
	return nil
}
