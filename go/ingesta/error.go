package ingesta

import "fmt"

// IngestErrorCode enumerates the fatal error conditions that prevent
// the Ingesta from producing any IngestReport at all.
//
// Ref: S05 §8 — Fallos bloqueantes.
type IngestErrorCode string

const (
	ErrFileNotFound    IngestErrorCode = "ERR_INGEST_FILE_NOT_FOUND"
	ErrFileNotReadable IngestErrorCode = "ERR_INGEST_FILE_NOT_READABLE"
	ErrNotValidJSON    IngestErrorCode = "ERR_INGEST_NOT_VALID_JSON"
	ErrFatal           IngestErrorCode = "ERR_INGEST_FATAL"
)

// IngestError is a typed error returned when a fatal condition prevents
// the entire ingestion from proceeding. This is distinct from per-tiddler
// semantic errors which are reported inside IngestReport.
type IngestError struct {
	Code    IngestErrorCode
	Message string
	Cause   error
}

func (e *IngestError) Error() string {
	if e.Cause != nil {
		return fmt.Sprintf("%s: %s: %v", e.Code, e.Message, e.Cause)
	}
	return fmt.Sprintf("%s: %s", e.Code, e.Message)
}

func (e *IngestError) Unwrap() error {
	return e.Cause
}
