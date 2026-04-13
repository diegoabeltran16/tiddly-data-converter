package canon

import "fmt"

// SchemaV0 is the declared schema version for the bootstrap canon.jsonl shape.
//
// This constant identifies the first explicit schema of the Canon JSONL output.
// Every line emitted by WriteJSONL carries this version in the "schema_version"
// field, making the shape self-describing and traceable.
//
// The schema v0 shape is:
//
//	schema_version  string   required  always "v0"
//	key             string   required  non-empty canonical identity key
//	title           string   required  human-readable tiddler identifier
//	text            *string  optional  body content (omitted when nil)
//	source_position *string  optional  extraction origin (omitted when nil)
//	created         *string  optional  TW5 17-digit timestamp (omitted when nil)
//	modified        *string  optional  TW5 17-digit timestamp (omitted when nil)
//
// Fields deliberately absent from v0:
//   - UUID v5 stable identity (deferred)
//   - primary_role, relations, provenance, meta blocks (deferred)
//   - deduplication resolution (deferred)
//
// PROVISIONAL: This is NOT the definitive Canon schema. It formalizes the
// current bootstrap shape so it is declared, tested and observable — not
// merely "whatever the code happens to emit today."
//
// Ref: S18 — schema v0 explícito para canon.jsonl.
// Ref: S13 §B — CanonEntry shape.
// Ref: S16 §A — writer mínimo.
// Ref: S17 — created/modified enrichment.
const SchemaV0 = "v0"

// SchemaV0RequiredFields lists the JSON field names that MUST be present
// in every emitted canon.jsonl line under schema v0.
var SchemaV0RequiredFields = []string{"schema_version", "key", "title"}

// SchemaV0OptionalFields lists the JSON field names that MAY be present
// (omitted when the underlying value is nil/zero).
var SchemaV0OptionalFields = []string{"text", "source_position", "created", "modified"}

// ValidateEntryV0 checks that a CanonEntry satisfies the schema v0 invariants.
//
// It validates:
//   - SchemaVersion is SchemaV0 (when set; callers that validate before writer
//     stamping may pass entries without schema_version).
//   - Key is non-empty.
//   - Title is non-empty.
//
// It does NOT validate timestamp format — that responsibility belongs to
// Ingesta (S09) and the bridge (S17). Canon schema v0 only asserts structural
// presence/absence of required fields.
//
// Returns nil if the entry conforms to v0, or an error describing the violation.
//
// Ref: S18 — schema v0 validation.
func ValidateEntryV0(e CanonEntry) error {
	if e.SchemaVersion != "" && e.SchemaVersion != SchemaV0 {
		return fmt.Errorf("schema_version: got %q, want %q", e.SchemaVersion, SchemaV0)
	}
	if e.Key == "" {
		return fmt.Errorf("key: required field is empty")
	}
	if e.Title == "" {
		return fmt.Errorf("title: required field is empty")
	}
	return nil
}
