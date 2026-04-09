package ingesta

// Verdict represents the outcome of an ingestion run.
//
// Ref: S05 §5 — Semántica del veredicto.
type Verdict string

const (
	VerdictOk      Verdict = "ok"
	VerdictWarning Verdict = "warning"
	VerdictError   Verdict = "error"
)

// IngestReport captures the outcome of an ingestion run including
// counts, warnings and errors. An IngestReport is always produced
// when the ingestion can start (i.e. no IngestError occurred).
//
// Ref: S05 §5 — Forma de IngestReport.
type IngestReport struct {
	Verdict       Verdict  `json:"verdict"`
	TiddlerCount  int      `json:"tiddler_count"`
	IngestedCount int      `json:"ingested_count"`
	SkippedCount  int      `json:"skipped_count"`
	Warnings      []string `json:"warnings"`
	Errors        []string `json:"errors"`
}
