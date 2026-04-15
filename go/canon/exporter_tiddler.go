// Package canon — exporter_tiddler.go
//
// S33 per-tiddler JSONL exporter. Writes one CanonEntry per line to the
// export JSONL file and produces an export log with per-tiddler decisions.
//
// This exporter uses the existing WriteJSONL gate (S19) and adds:
//   - Per-tiddler export log entries for auditability
//   - SHA-256 hash of the final JSONL file
//   - Manifest with conteos and metadata
//
// Contract reference: contratos/m01-s33-single-jsonl-functional-tiddlers-from-real-html-v0.md.json
// Ref: S16 — writer mínimo
// Ref: S18 — schema v0
// Ref: S19 — validation gate
package canon

import (
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"time"
)

// ExportLogEntry records the export decision for a single tiddler.
//
// S34 enrichment: ExportIdentity captures the computed identity fields
// for included tiddlers; nil for excluded tiddlers.
// S35 enrichment: ReadingMode captures the computed reading mode fields
// for included tiddlers; nil for excluded tiddlers.
// S36 enrichment: SemanticInfo captures the semantic function and
// traceability fields for included tiddlers; nil for excluded tiddlers.
type ExportLogEntry struct {
	TiddlerID      string              `json:"tiddler_id"`
	Action         string              `json:"action"` // "included" or "excluded"
	RuleID         string              `json:"rule_id"`
	Reason         string              `json:"reason"`
	RunID          string              `json:"run_id"`
	ExportIdentity *ExportIdentityRef  `json:"export_identity,omitempty"`
	ReadingMode    *ReadingMode        `json:"reading_mode,omitempty"`
	SemanticInfo   *ExportSemanticRef  `json:"semantic_info,omitempty"`
}

// ExportIdentityRef holds the identity fields emitted for an included tiddler.
// Ref: S34 §17.1 — export log shape.
type ExportIdentityRef struct {
	ID            string `json:"id"`
	CanonicalSlug string `json:"canonical_slug"`
	VersionID     string `json:"version_id"`
}

// ExportSemanticRef holds the semantic function traceability fields for
// an included tiddler in the export log.
// Ref: S36 §16 — export log enrichment.
type ExportSemanticRef struct {
	RolePrimary      string `json:"role_primary"`
	RoleSource       string `json:"role_source"`
	TaxonomySource   string `json:"taxonomy_source"`
	SemanticTextMode string `json:"semantic_text_mode"`
	MimeSource       string `json:"mime_source"`
	AssetMode        string `json:"asset_mode"`
}

// ExportManifest contains metadata about the export run.
//
// S35 enrichment: adds conteos by content_type, modality, is_binary,
// and is_reference_only for observability.
// S36 enrichment: adds conteos by role_primary and has_asset for
// semantic observability.
type ExportManifest struct {
	RunID          string            `json:"run_id"`
	Timestamp      time.Time         `json:"timestamp"`
	InputCount     int               `json:"input_count"`
	FilteredCount  int               `json:"filtered_count"`
	ExportedCount  int               `json:"exported_count"`
	SkippedByGate  int               `json:"skipped_by_gate"`
	SHA256         string            `json:"sha256"`
	OutputPath     string            `json:"output_path"`
	SchemaVersion  string            `json:"schema_version"`
	// S35 conteos
	ContentTypeCounts    map[string]int `json:"content_type_counts,omitempty"`
	ModalityCounts       map[string]int `json:"modality_counts,omitempty"`
	BinaryCount          int            `json:"binary_count"`
	ReferenceOnlyCount   int            `json:"reference_only_count"`
	// S36 conteos
	RolePrimaryCounts    map[string]int `json:"role_primary_counts,omitempty"`
	AssetCount           int            `json:"asset_count"`
	SemanticTextCount    int            `json:"semantic_text_count"`
}

// ExportTiddlersResult holds the complete result of an S33 export.
type ExportTiddlersResult struct {
	Manifest  ExportManifest   `json:"manifest"`
	LogEntries []ExportLogEntry `json:"log_entries"`
}

// ExportTiddlersJSONL writes a slice of CanonEntry values as JSONL to w,
// producing an export log and computing the SHA-256 hash of the output.
//
// Each entry is validated by the S19 gate (ValidateEntryV0) before emission.
// Entries that fail the gate are logged as "excluded" with reason "gate_rejected".
//
// Parameters:
//   - w: the writer for the JSONL output
//   - entries: the CanonEntry values to export
//   - runID: a unique identifier for this export run
//
// Returns an ExportTiddlersResult with the manifest and per-tiddler log.
func ExportTiddlersJSONL(w io.Writer, entries []CanonEntry, runID string) (*ExportTiddlersResult, error) {
	result := &ExportTiddlersResult{
		Manifest: ExportManifest{
			RunID:             runID,
			Timestamp:         time.Now().UTC(),
			InputCount:        len(entries),
			SchemaVersion:     SchemaV0,
			ContentTypeCounts: make(map[string]int),
			ModalityCounts:    make(map[string]int),
			RolePrimaryCounts: make(map[string]int),
		},
	}

	// Use a hash writer to compute SHA-256 as we write.
	h := sha256.New()
	multi := io.MultiWriter(w, h)

	var exported int
	var skipped int

	for i, e := range entries {
		// S19 gate: validate before emission.
		if err := ValidateEntryV0(e); err != nil {
			skipped++
			result.LogEntries = append(result.LogEntries, ExportLogEntry{
				TiddlerID: e.Title,
				Action:    "excluded",
				RuleID:    "gate-v0",
				Reason:    fmt.Sprintf("gate_rejected: %v", err),
				RunID:     runID,
			})
			continue
		}

		// Stamp schema version.
		e.SchemaVersion = SchemaV0

		// S34: compute structural identity (id, canonical_slug, version_id).
		if err := BuildNodeIdentity(&e); err != nil {
			skipped++
			result.LogEntries = append(result.LogEntries, ExportLogEntry{
				TiddlerID: e.Title,
				Action:    "excluded",
				RuleID:    "identity-s34",
				Reason:    fmt.Sprintf("identity_failed: %v", err),
				RunID:     runID,
			})
			continue
		}

		// S35: compute reading mode (content_type, modality, encoding, is_binary, is_reference_only).
		rm := BuildNodeReadingMode(e)
		e.ContentType = rm.ContentType
		e.Modality = rm.Modality
		e.Encoding = rm.Encoding
		e.IsBinary = rm.IsBinary
		e.IsReferenceOnly = rm.IsReferenceOnly

		// S36: compute semantic function and asset separation.
		sem := BuildNodeSemantics(e)
		e.RolePrimary = sem.RolePrimary
		e.RolesSecondary = sem.RolesSecondary
		e.Tags = sem.Tags
		e.TaxonomyPath = sem.TaxonomyPath
		e.SemanticText = sem.SemanticText
		e.RawPayloadRef = sem.RawPayloadRef
		e.AssetID = sem.AssetID
		e.MimeType = sem.MimeType

		line, err := json.Marshal(e)
		if err != nil {
			return nil, fmt.Errorf("exporter: marshal entry[%d] %q: %w", i, e.Title, err)
		}
		if _, err := multi.Write(line); err != nil {
			return nil, fmt.Errorf("exporter: write entry[%d] %q: %w", i, e.Title, err)
		}
		if _, err := multi.Write([]byte("\n")); err != nil {
			return nil, fmt.Errorf("exporter: write newline after entry[%d]: %w", i, err)
		}

		exported++
		// S35: track conteos for manifest.
		result.Manifest.ContentTypeCounts[rm.ContentType]++
		result.Manifest.ModalityCounts[rm.Modality]++
		if rm.IsBinary {
			result.Manifest.BinaryCount++
		}
		if rm.IsReferenceOnly {
			result.Manifest.ReferenceOnlyCount++
		}
		// S36: track semantic conteos for manifest.
		result.Manifest.RolePrimaryCounts[sem.RolePrimary]++
		if sem.AssetID != "" {
			result.Manifest.AssetCount++
		}
		if sem.SemanticText != "" {
			result.Manifest.SemanticTextCount++
		}
		result.LogEntries = append(result.LogEntries, ExportLogEntry{
			TiddlerID: e.Title,
			Action:    "included",
			RuleID:    "gate-v0-pass",
			Reason:    "validated and emitted",
			RunID:     runID,
			ExportIdentity: &ExportIdentityRef{
				ID:            e.ID,
				CanonicalSlug: e.CanonicalSlug,
				VersionID:     e.VersionID,
			},
			ReadingMode: &rm,
			SemanticInfo: &ExportSemanticRef{
				RolePrimary:      sem.RolePrimary,
				RoleSource:       sem.RoleSource,
				TaxonomySource:   sem.TaxonomySource,
				SemanticTextMode: sem.SemanticTextMode,
				MimeSource:       sem.MimeSource,
				AssetMode:        sem.AssetMode,
			},
		})
	}

	result.Manifest.ExportedCount = exported
	result.Manifest.SkippedByGate = skipped
	result.Manifest.SHA256 = fmt.Sprintf("sha256:%x", h.Sum(nil))

	return result, nil
}

// WriteExportLog writes the export log entries as JSONL to the given path.
func WriteExportLog(path string, entries []ExportLogEntry) error {
	f, err := os.Create(path)
	if err != nil {
		return fmt.Errorf("exporter: create log %s: %w", path, err)
	}
	defer f.Close()

	for _, e := range entries {
		line, err := json.Marshal(e)
		if err != nil {
			return fmt.Errorf("exporter: marshal log entry: %w", err)
		}
		if _, err := f.Write(line); err != nil {
			return err
		}
		if _, err := f.Write([]byte("\n")); err != nil {
			return err
		}
	}
	return nil
}

// WriteExportManifest writes the manifest as JSON to the given path.
func WriteExportManifest(path string, manifest ExportManifest) error {
	f, err := os.Create(path)
	if err != nil {
		return fmt.Errorf("exporter: create manifest %s: %w", path, err)
	}
	defer f.Close()

	enc := json.NewEncoder(f)
	enc.SetIndent("", "  ")
	return enc.Encode(manifest)
}
