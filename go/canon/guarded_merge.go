package canon

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"sort"
	"slices"
	"strings"
)

const (
	GuardedDecisionAccepted = "accepted"
	GuardedDecisionRejected = "rejected"
)

var (
	guardedAllowedRelationEvidence = map[string]bool{
		RelationEvidenceExplicitField: true,
		RelationEvidenceStructuralTag: true,
		RelationEvidenceWikilink:      true,
	}
	guardedPlaceholderTokens = []string{
		"pendiente",
		"todo",
		"resolver luego",
		"[pendiente",
		"[todo",
	}
)

type CandidateIssue struct {
	Line     int    `json:"line"`
	Title    string `json:"title,omitempty"`
	Field    string `json:"field,omitempty"`
	RuleID   string `json:"rule_id"`
	Message  string `json:"message"`
	Severity string `json:"severity"`
}

type CandidateDecision struct {
	Line     int      `json:"line"`
	Title    string   `json:"title,omitempty"`
	ID       string   `json:"id,omitempty"`
	Decision string   `json:"decision"`
	RuleIDs  []string `json:"rule_ids,omitempty"`
}

type GuardedMergeManifest struct {
	RunID          string `json:"run_id"`
	SchemaVersion  string `json:"schema_version"`
	BaseCount      int    `json:"base_count"`
	CandidateCount int    `json:"candidate_count"`
	AcceptedCount  int    `json:"accepted_count"`
	RejectedCount  int    `json:"rejected_count"`
	MergedCount    int    `json:"merged_count"`
	ReverseReady   bool   `json:"reverse_ready"`
}

type GuardedMergeEvidence struct {
	Manifest         GuardedMergeManifest  `json:"manifest"`
	DecisionLog      []CandidateDecision   `json:"decision_log"`
	ValidationReport ValidationReport      `json:"validation_report"`
	ReversePreflight ReversePreflightReport `json:"reverse_preflight"`
}

type CandidateBatchValidation struct {
	Accepted  []CanonEntry        `json:"-"`
	Rejected  []CanonEntry        `json:"-"`
	Issues    []CandidateIssue    `json:"issues,omitempty"`
	Decisions []CandidateDecision `json:"decisions,omitempty"`
}

type candidateLine struct {
	Line  int
	Entry CanonEntry
}

type candidateIndexes struct {
	baseByID    map[string]CanonEntry
	baseByKey   map[CanonKey]CanonEntry
	baseByTitle map[string]CanonEntry
}

// ValidateCandidateNode validates a single candidate node against S40 guarded
// admission rules. The candidate must already be a canonical line; this
// function rejects incomplete, ambiguous, or policy-violating nodes.
func ValidateCandidateNode(candidate CanonEntry, lineNum int, resolver contextResolver, indexes candidateIndexes) []CandidateIssue {
	var issues []CandidateIssue
	title := candidate.Title

	addIssue := func(field, ruleID, message string) {
		issues = append(issues, CandidateIssue{
			Line:     lineNum,
			Title:    title,
			Field:    field,
			RuleID:   ruleID,
			Message:  message,
			Severity: "error",
		})
	}

	if candidate.SchemaVersion != SchemaV0 {
		addIssue("schema_version", "wrong-schema-version", fmt.Sprintf("schema_version must be %q", SchemaV0))
	}
	if candidate.Key == "" {
		addIssue("key", "missing-required-field", "key is empty")
	}
	if candidate.Title == "" {
		addIssue("title", "missing-required-field", "title is empty")
	}
	if candidate.ID == "" {
		addIssue("id", "missing-required-field", "id is empty")
	}
	if candidate.CanonicalSlug == "" {
		addIssue("canonical_slug", "missing-required-field", "canonical_slug is empty")
	}
	if candidate.VersionID == "" {
		addIssue("version_id", "missing-required-field", "version_id is empty")
	}

	if candidate.Key != "" && candidate.Title != "" && string(candidate.Key) != candidate.Title {
		addIssue("key", "key-title-mismatch", "key must be identical to title under the S34 identity rule")
	}
	if candidate.Title != "" {
		expectedID, err := ComputeNodeUUID(string(KeyOf(candidate.Title)))
		if err == nil && candidate.ID != "" && candidate.ID != expectedID {
			addIssue("id", "inconsistent-derived-id", fmt.Sprintf("id %q does not match recomputed %q", candidate.ID, expectedID))
		}
		expectedSlug := CanonicalSlugOf(candidate.Title)
		if candidate.CanonicalSlug != "" && candidate.CanonicalSlug != expectedSlug {
			addIssue("canonical_slug", "inconsistent-derived-slug", fmt.Sprintf("canonical_slug %q does not match recomputed %q", candidate.CanonicalSlug, expectedSlug))
		}
	}
	if candidate.VersionID != "" {
		expectedVersionID, err := ComputeVersionID(candidate)
		if err == nil && candidate.VersionID != expectedVersionID {
			addIssue("version_id", "inconsistent-derived-version-id", fmt.Sprintf("version_id %q does not match recomputed %q", candidate.VersionID, expectedVersionID))
		}
	}

	if candidate.ID != "" {
		if base, ok := indexes.baseByID[candidate.ID]; ok {
			addIssue("id", "existing-node-collision", fmt.Sprintf("candidate id collides with existing node %q", base.Title))
		}
	}
	if candidate.Key != "" {
		if base, ok := indexes.baseByKey[candidate.Key]; ok {
			addIssue("key", "existing-node-collision", fmt.Sprintf("candidate key collides with existing node %q", base.Title))
		}
	}
	if candidate.Title != "" {
		if base, ok := indexes.baseByTitle[candidate.Title]; ok {
			addIssue("title", "existing-node-collision", fmt.Sprintf("candidate title collides with existing node %q", base.Title))
		}
	}

	validatePlaceholderStrings(candidate, lineNum, &issues)

	validateReadingMode(candidate, lineNum, &issues)
	validateSemantics(candidate, lineNum, &issues)
	validateContextRelations(candidate, lineNum, resolver, &issues)

	return issues
}

// ValidateCandidateBatch validates a candidate batch against a canonical base.
// The result separates accepted and rejected nodes and produces deterministic
// decision logs suitable for evidence artifacts.
func ValidateCandidateBatch(base []CanonEntry, candidates []CanonEntry) CandidateBatchValidation {
	indexes := buildCandidateIndexes(base)
	prevalidated := make([]candidateLine, 0, len(candidates))
	var result CandidateBatchValidation

	for i, candidate := range candidates {
		lineNum := i + 1
		lineIssues := validateBatchLocalCollisions(candidates, lineNum)
		if len(lineIssues) > 0 {
			result.Issues = append(result.Issues, lineIssues...)
			result.Rejected = append(result.Rejected, candidate)
			result.Decisions = append(result.Decisions, buildDecision(candidate, lineNum, lineIssues))
			continue
		}
		prevalidated = append(prevalidated, candidateLine{Line: lineNum, Entry: candidate})
	}

	validIdentityLines := make([]candidateLine, 0, len(prevalidated))
	for _, line := range prevalidated {
		lineIssues := validateCandidateIdentityAndFields(line.Entry, line.Line, indexes)
		if len(lineIssues) > 0 {
			result.Issues = append(result.Issues, lineIssues...)
			result.Rejected = append(result.Rejected, line.Entry)
			result.Decisions = append(result.Decisions, buildDecision(line.Entry, line.Line, lineIssues))
			continue
		}
		validIdentityLines = append(validIdentityLines, line)
	}

	resolverEntries := append(slices.Clone(base), extractEntries(validIdentityLines)...)
	resolver := BuildContextResolver(resolverEntries)

	for _, line := range validIdentityLines {
		lineIssues := ValidateCandidateNode(line.Entry, line.Line, resolver, indexes)
		if len(lineIssues) > 0 {
			result.Issues = append(result.Issues, lineIssues...)
			result.Rejected = append(result.Rejected, line.Entry)
			result.Decisions = append(result.Decisions, buildDecision(line.Entry, line.Line, lineIssues))
			continue
		}
		result.Accepted = append(result.Accepted, line.Entry)
		result.Decisions = append(result.Decisions, CandidateDecision{
			Line:     line.Line,
			Title:    line.Entry.Title,
			ID:       line.Entry.ID,
			Decision: GuardedDecisionAccepted,
		})
	}

	sort.Slice(result.Decisions, func(i, j int) bool {
		if result.Decisions[i].Line != result.Decisions[j].Line {
			return result.Decisions[i].Line < result.Decisions[j].Line
		}
		return result.Decisions[i].Decision < result.Decisions[j].Decision
	})
	sort.Slice(result.Issues, func(i, j int) bool {
		if result.Issues[i].Line != result.Issues[j].Line {
			return result.Issues[i].Line < result.Issues[j].Line
		}
		if result.Issues[i].Field != result.Issues[j].Field {
			return result.Issues[i].Field < result.Issues[j].Field
		}
		return result.Issues[i].RuleID < result.Issues[j].RuleID
	})

	return result
}

// MergeAcceptedNodes merges accepted nodes onto a canonical base without
// mutating or rewriting existing nodes. Base order is preserved and accepted
// nodes are appended in candidate order.
func MergeAcceptedNodes(base []CanonEntry, accepted []CanonEntry) []CanonEntry {
	merged := append(slices.Clone(base), accepted...)
	return merged
}

// BuildMergeEvidence derives a reproducible evidence bundle for an S40 merge.
func BuildMergeEvidence(runID string, base []CanonEntry, validation CandidateBatchValidation) (GuardedMergeEvidence, []CanonEntry, error) {
	merged := MergeAcceptedNodes(base, validation.Accepted)
	jsonl, err := MarshalCanonJSONL(merged)
	if err != nil {
		return GuardedMergeEvidence{}, nil, err
	}

	validationReport := ValidateCanonJSONL(bytes.NewReader(jsonl), DefaultCanonPolicy())
	reverseReport := ReversePreflightCanonJSONL(bytes.NewReader(jsonl))

	evidence := GuardedMergeEvidence{
		Manifest: GuardedMergeManifest{
			RunID:          runID,
			SchemaVersion:  SchemaV0,
			BaseCount:      len(base),
			CandidateCount: len(validation.Accepted) + len(validation.Rejected),
			AcceptedCount:  len(validation.Accepted),
			RejectedCount:  len(validation.Rejected),
			MergedCount:    len(merged),
			ReverseReady:   validationReport.OK() && reverseReport.OK(),
		},
		DecisionLog:      validation.Decisions,
		ValidationReport: validationReport,
		ReversePreflight: reverseReport,
	}

	return evidence, merged, nil
}

func ParseCanonJSONL(r io.Reader) ([]CanonEntry, error) {
	scanner := bufio.NewScanner(r)
	buf := make([]byte, 0, 1024*1024)
	scanner.Buffer(buf, 10*1024*1024)

	var entries []CanonEntry
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		var entry CanonEntry
		if err := json.Unmarshal([]byte(line), &entry); err != nil {
			return nil, err
		}
		entries = append(entries, entry)
	}
	if err := scanner.Err(); err != nil {
		return nil, err
	}
	return entries, nil
}

func MarshalCanonJSONL(entries []CanonEntry) ([]byte, error) {
	var buf bytes.Buffer
	for _, entry := range entries {
		line, err := json.Marshal(entry)
		if err != nil {
			return nil, err
		}
		buf.Write(line)
		buf.WriteByte('\n')
	}
	return buf.Bytes(), nil
}

func validateCandidateIdentityAndFields(candidate CanonEntry, lineNum int, indexes candidateIndexes) []CandidateIssue {
	var issues []CandidateIssue
	title := candidate.Title

	addIssue := func(field, ruleID, message string) {
		issues = append(issues, CandidateIssue{
			Line:     lineNum,
			Title:    title,
			Field:    field,
			RuleID:   ruleID,
			Message:  message,
			Severity: "error",
		})
	}

	if candidate.SchemaVersion != SchemaV0 {
		addIssue("schema_version", "wrong-schema-version", fmt.Sprintf("schema_version must be %q", SchemaV0))
	}
	if candidate.Key == "" {
		addIssue("key", "missing-required-field", "key is empty")
	}
	if candidate.Title == "" {
		addIssue("title", "missing-required-field", "title is empty")
	}
	if candidate.ID == "" {
		addIssue("id", "missing-required-field", "id is empty")
	}
	if candidate.CanonicalSlug == "" {
		addIssue("canonical_slug", "missing-required-field", "canonical_slug is empty")
	}
	if candidate.VersionID == "" {
		addIssue("version_id", "missing-required-field", "version_id is empty")
	}

	if candidate.Key != "" && candidate.Title != "" && string(candidate.Key) != candidate.Title {
		addIssue("key", "key-title-mismatch", "key must be identical to title under the S34 identity rule")
	}
	if candidate.Title != "" {
		expectedID, err := ComputeNodeUUID(string(KeyOf(candidate.Title)))
		if err == nil && candidate.ID != "" && candidate.ID != expectedID {
			addIssue("id", "inconsistent-derived-id", fmt.Sprintf("id %q does not match recomputed %q", candidate.ID, expectedID))
		}
		expectedSlug := CanonicalSlugOf(candidate.Title)
		if candidate.CanonicalSlug != "" && candidate.CanonicalSlug != expectedSlug {
			addIssue("canonical_slug", "inconsistent-derived-slug", fmt.Sprintf("canonical_slug %q does not match recomputed %q", candidate.CanonicalSlug, expectedSlug))
		}
	}
	if candidate.VersionID != "" {
		expectedVersionID, err := ComputeVersionID(candidate)
		if err == nil && candidate.VersionID != expectedVersionID {
			addIssue("version_id", "inconsistent-derived-version-id", fmt.Sprintf("version_id %q does not match recomputed %q", candidate.VersionID, expectedVersionID))
		}
	}

	if candidate.ID != "" {
		if base, ok := indexes.baseByID[candidate.ID]; ok {
			addIssue("id", "existing-node-collision", fmt.Sprintf("candidate id collides with existing node %q", base.Title))
		}
	}
	if candidate.Key != "" {
		if base, ok := indexes.baseByKey[candidate.Key]; ok {
			addIssue("key", "existing-node-collision", fmt.Sprintf("candidate key collides with existing node %q", base.Title))
		}
	}
	if candidate.Title != "" {
		if base, ok := indexes.baseByTitle[candidate.Title]; ok {
			addIssue("title", "existing-node-collision", fmt.Sprintf("candidate title collides with existing node %q", base.Title))
		}
	}

	validatePlaceholderStrings(candidate, lineNum, &issues)
	validateReadingMode(candidate, lineNum, &issues)
	validateSemantics(candidate, lineNum, &issues)

	return issues
}

func buildCandidateIndexes(base []CanonEntry) candidateIndexes {
	idx := candidateIndexes{
		baseByID:    make(map[string]CanonEntry, len(base)),
		baseByKey:   make(map[CanonKey]CanonEntry, len(base)),
		baseByTitle: make(map[string]CanonEntry, len(base)),
	}
	for _, entry := range base {
		if entry.ID != "" {
			idx.baseByID[entry.ID] = entry
		}
		if entry.Key != "" {
			idx.baseByKey[entry.Key] = entry
		}
		if entry.Title != "" {
			idx.baseByTitle[entry.Title] = entry
		}
	}
	return idx
}

func validateBatchLocalCollisions(candidates []CanonEntry, lineNum int) []CandidateIssue {
	current := candidates[lineNum-1]
	var issues []CandidateIssue
	addIssue := func(field, ruleID, message string) {
		issues = append(issues, CandidateIssue{
			Line:     lineNum,
			Title:    current.Title,
			Field:    field,
			RuleID:   ruleID,
			Message:  message,
			Severity: "error",
		})
	}

	for i, other := range candidates {
		if i == lineNum-1 {
			continue
		}
		if current.ID != "" && current.ID == other.ID {
			addIssue("id", "batch-duplicate-id", fmt.Sprintf("candidate id collides with batch line %d", i+1))
		}
		if current.Key != "" && current.Key == other.Key {
			addIssue("key", "batch-duplicate-key", fmt.Sprintf("candidate key collides with batch line %d", i+1))
		}
		if current.Title != "" && current.Title == other.Title {
			addIssue("title", "batch-duplicate-title", fmt.Sprintf("candidate title collides with batch line %d", i+1))
		}
	}
	return dedupeCandidateIssues(issues)
}

func validateReadingMode(candidate CanonEntry, lineNum int, issues *[]CandidateIssue) {
	addIssue := func(field, ruleID, message string) {
		*issues = append(*issues, CandidateIssue{
			Line:     lineNum,
			Title:    candidate.Title,
			Field:    field,
			RuleID:   ruleID,
			Message:  message,
			Severity: "error",
		})
	}

	validContentTypes := map[string]bool{
		ContentTypePlain: true, ContentTypeMarkdown: true, ContentTypeHTML: true,
		ContentTypeTiddlyWiki: true, ContentTypeJSON: true, ContentTypeCSV: true,
		ContentTypePNG: true, ContentTypeJPEG: true, ContentTypeSVG: true,
		ContentTypeOctetStream: true, ContentTypeTiddler: true, ContentTypeUnknown: true,
	}
	validModalities := map[string]bool{
		ModalityText: true, ModalityCode: true, ModalityTable: true, ModalityImage: true,
		ModalityMetadata: true, ModalityBinary: true, ModalityEquation: true,
		ModalityMixed: true, ModalityUnknown: true,
	}
	validEncodings := map[string]bool{
		EncodingUTF8: true, EncodingBase64: true, EncodingBinary: true, EncodingUnknown: true,
	}

	if candidate.ContentType == "" {
		addIssue("content_type", "missing-required-field", "content_type is empty")
	} else if !validContentTypes[candidate.ContentType] {
		addIssue("content_type", "invalid-content-type", fmt.Sprintf("content_type %q is not in the S35 catalogue", candidate.ContentType))
	}
	if candidate.Modality == "" {
		addIssue("modality", "missing-required-field", "modality is empty")
	} else if !validModalities[candidate.Modality] {
		addIssue("modality", "invalid-modality", fmt.Sprintf("modality %q is not in the S35 catalogue", candidate.Modality))
	}
	if candidate.Encoding == "" {
		addIssue("encoding", "missing-required-field", "encoding is empty")
	} else if !validEncodings[candidate.Encoding] {
		addIssue("encoding", "invalid-encoding", fmt.Sprintf("encoding %q is not in the S35 catalogue", candidate.Encoding))
	}

	if candidate.IsBinary && candidate.Encoding == EncodingUTF8 &&
		candidate.ContentType != ContentTypeSVG {
		addIssue("is_binary", "binary-encoding-mismatch", "binary nodes must not advertise utf-8 encoding except SVG text assets")
	}

	if candidate.IsReferenceOnly && candidate.Text != nil && strings.TrimSpace(*candidate.Text) != "" &&
		candidate.ContentType != ContentTypeTiddler {
		addIssue("is_reference_only", "reference-only-has-payload", "reference-only nodes must not carry substantive payload")
	}
}

func validateSemantics(candidate CanonEntry, lineNum int, issues *[]CandidateIssue) {
	addIssue := func(field, ruleID, message string) {
		*issues = append(*issues, CandidateIssue{
			Line:     lineNum,
			Title:    candidate.Title,
			Field:    field,
			RuleID:   ruleID,
			Message:  message,
			Severity: "error",
		})
	}

	if candidate.RolePrimary == "" {
		addIssue("role_primary", "missing-required-field", "role_primary is empty")
	} else if !validRolePrimary[candidate.RolePrimary] {
		addIssue("role_primary", "invalid-role-primary", fmt.Sprintf("role_primary %q is not in the S36 catalogue", candidate.RolePrimary))
	}

	if candidate.SourceRole != nil && strings.TrimSpace(*candidate.SourceRole) != "" {
		normalized := strings.TrimSpace(strings.ToLower(*candidate.SourceRole))
		if mapped, ok := explicitRoleMapping[normalized]; ok {
			if candidate.RolePrimary != mapped {
				addIssue("role_primary", "explicit-role-overridden", fmt.Sprintf("role_primary %q contradicts explicit source role %q mapped to %q", candidate.RolePrimary, normalized, mapped))
			}
		} else if validRolePrimary[normalized] && candidate.RolePrimary != normalized {
			addIssue("role_primary", "explicit-role-overridden", fmt.Sprintf("role_primary %q contradicts explicit source role %q", candidate.RolePrimary, normalized))
		}
	}

	for _, secondary := range candidate.RolesSecondary {
		if secondary == candidate.RolePrimary {
			addIssue("roles_secondary", "secondary-role-duplicates-primary", "roles_secondary must not repeat role_primary")
			break
		}
	}

	if len(candidate.Tags) == 0 {
		addIssue("tags", "missing-required-field", "tags is empty")
	}
	if len(candidate.SourceTags) > 0 {
		expectedTags := MergeSemanticTags(candidate.SourceTags)
		if !slices.Equal(candidate.Tags, expectedTags) {
			addIssue("tags", "non-deterministic-tags", "tags do not match deterministic merge of source_tags")
		}
	}

	expectedTaxonomy := BuildTaxonomyPath(candidate.Tags)
	if !slices.Equal(candidate.TaxonomyPath, expectedTaxonomy) {
		addIssue("taxonomy_path", "non-deterministic-taxonomy-path", "taxonomy_path does not match deterministic derivation from tags")
	}

	expectedPayloadRef := BuildRawPayloadRef(candidate)
	if candidate.RawPayloadRef == "" {
		addIssue("raw_payload_ref", "missing-required-field", "raw_payload_ref is empty")
	} else if candidate.RawPayloadRef != expectedPayloadRef {
		addIssue("raw_payload_ref", "inconsistent-raw-payload-ref", fmt.Sprintf("raw_payload_ref %q does not match recomputed %q", candidate.RawPayloadRef, expectedPayloadRef))
	}

	expectedMimeType, _ := ResolveMimeType(candidate)
	if candidate.MimeType == "" {
		addIssue("mime_type", "missing-required-field", "mime_type is empty")
	} else if candidate.MimeType != expectedMimeType {
		addIssue("mime_type", "inconsistent-mime-type", fmt.Sprintf("mime_type %q does not match recomputed %q", candidate.MimeType, expectedMimeType))
	}

	expectedAssetID, _ := BuildAssetID(candidate)
	if candidate.AssetID != expectedAssetID {
		addIssue("asset_id", "inconsistent-asset-id", fmt.Sprintf("asset_id %q does not match recomputed %q", candidate.AssetID, expectedAssetID))
	}

	if candidate.SemanticText != nil && candidate.Text != nil && *candidate.SemanticText == *candidate.Text {
		addIssue("semantic_text", "semantic-text-redundant", "semantic_text equals text; canonical nodes must suppress it")
	}
}

func validateContextRelations(candidate CanonEntry, lineNum int, resolver contextResolver, issues *[]CandidateIssue) {
	addIssue := func(field, ruleID, message string) {
		*issues = append(*issues, CandidateIssue{
			Line:     lineNum,
			Title:    candidate.Title,
			Field:    field,
			RuleID:   ruleID,
			Message:  message,
			Severity: "error",
		})
	}

	if candidate.DocumentID == "" {
		addIssue("document_id", "missing-required-field", "document_id is empty")
	} else {
		expectedDocumentID, err := ComputeDocumentID(candidate)
		if err == nil && candidate.DocumentID != expectedDocumentID {
			addIssue("document_id", "inconsistent-document-id", fmt.Sprintf("document_id %q does not match recomputed %q", candidate.DocumentID, expectedDocumentID))
		}
	}

	expectedSectionPath := BuildSectionPath(candidate)
	if !slices.Equal(candidate.SectionPath, expectedSectionPath) {
		addIssue("section_path", "non-deterministic-section-path", "section_path does not match conservative derivation")
	}
	if candidate.OrderInDocument < 0 {
		addIssue("order_in_document", "invalid-order-in-document", "order_in_document must be >= 0")
	}

	expectedRelations := dedupeSortRelations(candidate.Relations)
	if !slices.Equal(candidate.Relations, expectedRelations) {
		addIssue("relations", "non-deterministic-relations-order", "relations must be deduplicated and sorted deterministically")
	}
	for _, relation := range candidate.Relations {
		if relation.Type == "" || normalizeRelationType(relation.Type) == "" {
			addIssue("relations", "invalid-relation-type", fmt.Sprintf("relation type %q is not allowed", relation.Type))
			continue
		}
		if !guardedAllowedRelationEvidence[relation.Evidence] {
			addIssue("relations", "invalid-relation-evidence", fmt.Sprintf("relation evidence %q is not allowed", relation.Evidence))
		}
		if strings.TrimSpace(relation.TargetID) == "" {
			addIssue("relations", "missing-relation-target", "relation target_id is empty")
			continue
		}
		if relation.TargetID == candidate.ID {
			addIssue("relations", "self-relation-forbidden", "candidate relations must not target the candidate itself")
			continue
		}
		if _, status := ResolveRelationTargets(relation.TargetID, resolver); status != "resolved" {
			addIssue("relations", "unresolved-relation-target", fmt.Sprintf("relation target %q is not resolvable against canon base + accepted candidates", relation.TargetID))
		}
	}
}

func validatePlaceholderStrings(candidate CanonEntry, lineNum int, issues *[]CandidateIssue) {
	check := func(field, value string) {
		if stringLooksLikePlaceholder(value) {
			*issues = append(*issues, CandidateIssue{
				Line:     lineNum,
				Title:    candidate.Title,
				Field:    field,
				RuleID:   "placeholder-not-allowed",
				Message:  fmt.Sprintf("field %q contains a non-admissible placeholder", field),
				Severity: "error",
			})
		}
	}

	check("title", candidate.Title)
	check("key", string(candidate.Key))
	check("canonical_slug", candidate.CanonicalSlug)
	check("role_primary", candidate.RolePrimary)
	check("document_id", candidate.DocumentID)
	if candidate.SourceRole != nil {
		check("source_role", *candidate.SourceRole)
	}
	for _, value := range candidate.RolesSecondary {
		check("roles_secondary", value)
	}
	for _, value := range candidate.Tags {
		check("tags", value)
	}
	for _, value := range candidate.TaxonomyPath {
		check("taxonomy_path", value)
	}
	for _, value := range candidate.SectionPath {
		check("section_path", value)
	}
}

func stringLooksLikePlaceholder(value string) bool {
	normalized := strings.ToLower(strings.TrimSpace(value))
	if normalized == "" {
		return false
	}
	for _, token := range guardedPlaceholderTokens {
		if normalized == token || strings.Contains(normalized, token+"]") {
			return true
		}
	}
	return false
}

func buildDecision(candidate CanonEntry, lineNum int, issues []CandidateIssue) CandidateDecision {
	ruleIDs := make([]string, 0, len(issues))
	seen := make(map[string]bool, len(issues))
	for _, issue := range issues {
		if seen[issue.RuleID] {
			continue
		}
		seen[issue.RuleID] = true
		ruleIDs = append(ruleIDs, issue.RuleID)
	}
	return CandidateDecision{
		Line:     lineNum,
		Title:    candidate.Title,
		ID:       candidate.ID,
		Decision: GuardedDecisionRejected,
		RuleIDs:  ruleIDs,
	}
}

func extractEntries(lines []candidateLine) []CanonEntry {
	entries := make([]CanonEntry, 0, len(lines))
	for _, line := range lines {
		entries = append(entries, line.Entry)
	}
	return entries
}

func dedupeCandidateIssues(in []CandidateIssue) []CandidateIssue {
	if len(in) == 0 {
		return nil
	}
	seen := make(map[string]bool, len(in))
	out := make([]CandidateIssue, 0, len(in))
	for _, issue := range in {
		key := fmt.Sprintf("%d|%s|%s|%s", issue.Line, issue.Field, issue.RuleID, issue.Message)
		if seen[key] {
			continue
		}
		seen[key] = true
		out = append(out, issue)
	}
	return out
}
