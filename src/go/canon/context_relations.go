package canon

import (
	"encoding/json"
	"fmt"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

const (
	RelationTypeChildOf    = "child_of"
	RelationTypeReferences = "references"

	// Capa-2 semantic relation types (S84) — human-authored inside content payloads.
	RelationTypeUsa        = "usa"
	RelationTypeDefine     = "define"
	RelationTypeRequiere   = "requiere"
	RelationTypeParteDe    = "parte_de"
	RelationTypePerteneceA = "pertenece_a"
	RelationTypeContiene   = "contiene"
	RelationTypePruebaDe   = "prueba_de"

	RelationEvidenceExplicitField   = "explicit_field"
	RelationEvidenceStructuralTag   = "structural_tag"
	RelationEvidenceWikilink        = "wikilink"
	RelationEvidenceEmbeddedContent = "content_embedded" // S84: capa-2 semantic relations

	CanonicalRelationArtifactFamily = "canonical_relation"
	CanonicalRelationSchemaV1       = "canonical-relation/v1"
	CanonicalRelationLifecycleState = "admitted_to_canon"
)

// embeddedRelationTypes is the set of semantic relation types recognised
// exclusively from content-embedded (capa-2) JSON payloads. Canonical
// structural types (child_of, references) are intentionally excluded because
// they are handled by extractExplicitRelationTargets.
var embeddedRelationTypes = map[string]bool{
	RelationTypeUsa:        true,
	RelationTypeDefine:     true,
	RelationTypeRequiere:   true,
	RelationTypeParteDe:    true,
	RelationTypePerteneceA: true,
	RelationTypeContiene:   true,
	RelationTypePruebaDe:   true,
}

var (
	absWindowsPathRe = regexp.MustCompile(`^[A-Za-z]:[\\/].*`)
	wikilinkRe       = regexp.MustCompile(`\[\[([^\]]+)\]\]`)
)

// CanonicalRelationEvidence is the structured evidence written by the
// canonical-relation/v1 producer. Both fields are required on read; an empty
// reviewed_evidence_paths list is valid and remains distinguishable from an
// absent or null field.
type CanonicalRelationEvidence struct {
	CandidateID           string   `json:"candidate_id"`
	ReviewedEvidencePaths []string `json:"reviewed_evidence_paths"`
}

// CanonicalRelationAuthority preserves the governed human authority carried
// by canonical-relation/v1. Optional producer values use pointers so JSON null
// is preserved as null instead of becoming a synthetic empty string.
type CanonicalRelationAuthority struct {
	AdmittedBy             string  `json:"admitted_by"`
	AdmissionSession       string  `json:"admission_session"`
	HumanReviewDecision    string  `json:"human_review_decision"`
	HumanReviewReasonCode  string  `json:"human_review_reason_code"`
	HumanReviewNote        *string `json:"human_review_note"`
	DecisionBatchID        *string `json:"decision_batch_id"`
	MultiReviewOperationID *string `json:"multi_review_operation_id"`
	ReviewPolicyID         *string `json:"review_policy_id"`
}

// NodeRelation is the relation union observed in canonical JSONL. Legacy S37
// relations keep Evidence as a string. canonical-relation/v1 values keep their
// evidence and authority in explicit typed fields. MarshalJSON and
// UnmarshalJSON preserve the original JSON shape and reject every uncontracted
// evidence form.
type NodeRelation struct {
	Type     string `json:"-"`
	TargetID string `json:"-"`
	Evidence string `json:"-"`

	ArtifactFamily        string                      `json:"-"`
	RelationSchemaVersion string                      `json:"-"`
	RelationID            string                      `json:"-"`
	RelationType          string                      `json:"-"`
	SourceID              string                      `json:"-"`
	StructuredEvidence    *CanonicalRelationEvidence  `json:"-"`
	Authority             *CanonicalRelationAuthority `json:"-"`
	LifecycleState        string                      `json:"-"`
}

type legacyNodeRelationJSON struct {
	Type     string `json:"type"`
	TargetID string `json:"target_id"`
	Evidence string `json:"evidence"`
}

type canonicalNodeRelationV1JSON struct {
	Type                  string                     `json:"type"`
	ArtifactFamily        string                     `json:"artifact_family"`
	RelationSchemaVersion string                     `json:"relation_schema_version"`
	RelationID            string                     `json:"relation_id"`
	RelationType          string                     `json:"relation_type"`
	SourceID              string                     `json:"source_id"`
	TargetID              string                     `json:"target_id"`
	Evidence              CanonicalRelationEvidence  `json:"evidence"`
	Authority             CanonicalRelationAuthority `json:"authority"`
	LifecycleState        string                     `json:"lifecycle_state"`
}

var (
	legacyNodeRelationKeys = map[string]bool{
		"type": true, "target_id": true, "evidence": true,
	}
	canonicalNodeRelationV1Keys = map[string]bool{
		"type": true, "artifact_family": true, "relation_schema_version": true,
		"relation_id": true, "relation_type": true, "source_id": true,
		"target_id": true, "evidence": true, "authority": true,
		"lifecycle_state": true,
	}
	canonicalRelationEvidenceKeys = map[string]bool{
		"candidate_id": true, "reviewed_evidence_paths": true,
	}
	canonicalRelationAuthorityKeys = map[string]bool{
		"admitted_by": true, "admission_session": true,
		"human_review_decision": true, "human_review_reason_code": true,
		"human_review_note": true, "decision_batch_id": true,
		"multi_review_operation_id": true, "review_policy_id": true,
	}
)

// MarshalJSON emits exactly the relation shape represented in memory. It does
// not normalize legacy strings into objects or stringify structured evidence.
func (r NodeRelation) MarshalJSON() ([]byte, error) {
	if r.StructuredEvidence == nil {
		if r.hasCanonicalRelationFields() {
			return nil, fmt.Errorf("relations.evidence: canonical-relation/v1 requires an evidence object")
		}
		return json.Marshal(legacyNodeRelationJSON{
			Type: r.Type, TargetID: r.TargetID, Evidence: r.Evidence,
		})
	}
	if r.Evidence != "" {
		return nil, fmt.Errorf("relations.evidence: relation cannot contain both string and object evidence")
	}
	if err := validateCanonicalNodeRelationV1(r); err != nil {
		return nil, err
	}
	return json.Marshal(canonicalNodeRelationV1JSON{
		Type:                  r.Type,
		ArtifactFamily:        r.ArtifactFamily,
		RelationSchemaVersion: r.RelationSchemaVersion,
		RelationID:            r.RelationID,
		RelationType:          r.RelationType,
		SourceID:              r.SourceID,
		TargetID:              r.TargetID,
		Evidence:              *r.StructuredEvidence,
		Authority:             *r.Authority,
		LifecycleState:        r.LifecycleState,
	})
}

// UnmarshalJSON accepts only the two shapes observed and authorized by S0184:
// the three-field legacy relation with string evidence, and the complete
// canonical-relation/v1 object with structured evidence.
func (r *NodeRelation) UnmarshalJSON(data []byte) error {
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(data, &fields); err != nil {
		return fmt.Errorf("relation must be a JSON object: %w", err)
	}
	if fields == nil {
		return fmt.Errorf("relation must be a JSON object")
	}
	evidenceRaw, ok := fields["evidence"]
	if !ok {
		return fmt.Errorf("relations.evidence: required field is missing")
	}
	trimmedEvidence := strings.TrimSpace(string(evidenceRaw))
	if trimmedEvidence == "" {
		return fmt.Errorf("relations.evidence: empty JSON value")
	}

	*r = NodeRelation{}
	switch trimmedEvidence[0] {
	case '"':
		if err := requireExactJSONKeys(fields, legacyNodeRelationKeys, "legacy relation"); err != nil {
			return err
		}
		var legacy legacyNodeRelationJSON
		if err := json.Unmarshal(data, &legacy); err != nil {
			return fmt.Errorf("relations.evidence: legacy string relation: %w", err)
		}
		r.Type = legacy.Type
		r.TargetID = legacy.TargetID
		r.Evidence = legacy.Evidence
		return nil
	case '{':
		if err := requireExactJSONKeys(fields, canonicalNodeRelationV1Keys, "canonical-relation/v1"); err != nil {
			return err
		}
		if err := requireNestedExactJSONKeys(evidenceRaw, canonicalRelationEvidenceKeys, "relations.evidence"); err != nil {
			return err
		}
		if err := requireNestedExactJSONKeys(fields["authority"], canonicalRelationAuthorityKeys, "relations.authority"); err != nil {
			return err
		}
		var canonical canonicalNodeRelationV1JSON
		if err := json.Unmarshal(data, &canonical); err != nil {
			return fmt.Errorf("canonical-relation/v1: %w", err)
		}
		r.Type = canonical.Type
		r.ArtifactFamily = canonical.ArtifactFamily
		r.RelationSchemaVersion = canonical.RelationSchemaVersion
		r.RelationID = canonical.RelationID
		r.RelationType = canonical.RelationType
		r.SourceID = canonical.SourceID
		r.TargetID = canonical.TargetID
		r.StructuredEvidence = &canonical.Evidence
		r.Authority = &canonical.Authority
		r.LifecycleState = canonical.LifecycleState
		return validateCanonicalNodeRelationV1(*r)
	default:
		return fmt.Errorf("relations.evidence: expected string or canonical-relation/v1 object, got %s", jsonValueKind(evidenceRaw))
	}
}

func (r NodeRelation) hasCanonicalRelationFields() bool {
	return r.ArtifactFamily != "" || r.RelationSchemaVersion != "" || r.RelationID != "" ||
		r.RelationType != "" || r.SourceID != "" || r.Authority != nil || r.LifecycleState != ""
}

func validateCanonicalNodeRelationV1(r NodeRelation) error {
	switch {
	case r.Type != "application/json":
		return fmt.Errorf("canonical-relation/v1: type must be application/json")
	case r.ArtifactFamily != CanonicalRelationArtifactFamily:
		return fmt.Errorf("canonical-relation/v1: artifact_family must be %s", CanonicalRelationArtifactFamily)
	case r.RelationSchemaVersion != CanonicalRelationSchemaV1:
		return fmt.Errorf("canonical-relation/v1: relation_schema_version must be %s", CanonicalRelationSchemaV1)
	case strings.TrimSpace(r.RelationID) == "":
		return fmt.Errorf("canonical-relation/v1: relation_id is required")
	case strings.TrimSpace(r.RelationType) == "":
		return fmt.Errorf("canonical-relation/v1: relation_type is required")
	case strings.TrimSpace(r.SourceID) == "":
		return fmt.Errorf("canonical-relation/v1: source_id is required")
	case strings.TrimSpace(r.TargetID) == "":
		return fmt.Errorf("canonical-relation/v1: target_id is required")
	case r.StructuredEvidence == nil:
		return fmt.Errorf("relations.evidence: object is required")
	case strings.TrimSpace(r.StructuredEvidence.CandidateID) == "":
		return fmt.Errorf("relations.evidence.candidate_id: non-empty string is required")
	case r.StructuredEvidence.ReviewedEvidencePaths == nil:
		return fmt.Errorf("relations.evidence.reviewed_evidence_paths: array is required")
	case r.Authority == nil:
		return fmt.Errorf("canonical-relation/v1: authority object is required")
	case strings.TrimSpace(r.Authority.HumanReviewDecision) == "":
		return fmt.Errorf("canonical-relation/v1: authority.human_review_decision is required")
	case strings.TrimSpace(r.Authority.HumanReviewReasonCode) == "":
		return fmt.Errorf("canonical-relation/v1: authority.human_review_reason_code is required")
	case r.LifecycleState != CanonicalRelationLifecycleState:
		return fmt.Errorf("canonical-relation/v1: lifecycle_state must be %s", CanonicalRelationLifecycleState)
	default:
		return nil
	}
}

func requireNestedExactJSONKeys(data json.RawMessage, expected map[string]bool, label string) error {
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(data, &fields); err != nil {
		return fmt.Errorf("%s: expected object: %w", label, err)
	}
	if fields == nil {
		return fmt.Errorf("%s: expected object", label)
	}
	return requireExactJSONKeys(fields, expected, label)
}

func requireExactJSONKeys(fields map[string]json.RawMessage, expected map[string]bool, label string) error {
	for key := range fields {
		if !expected[key] {
			return fmt.Errorf("%s: unsupported field %q", label, key)
		}
	}
	for key := range expected {
		if _, ok := fields[key]; !ok {
			return fmt.Errorf("%s: required field %q is missing", label, key)
		}
	}
	return nil
}

func jsonValueKind(data json.RawMessage) string {
	trimmed := strings.TrimSpace(string(data))
	if trimmed == "" {
		return "empty"
	}
	switch trimmed[0] {
	case 'n':
		return "null"
	case '[':
		return "array"
	case 't', 'f':
		return "boolean"
	case '0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '-':
		return "number"
	default:
		return "unsupported JSON value"
	}
}

// ContextRelations is the computed S37 context + relations bundle for one node.
type ContextRelations struct {
	DocumentID      string
	SectionPath     []string
	OrderInDocument int
	Relations       []NodeRelation

	RelationResolutionStatus string
	RelationCandidates       int
}

type relationTarget struct {
	Type     string
	Target   string
	Evidence string
}

type contextResolver struct {
	byID    map[string]bool
	byTitle map[string][]string
	byKey   map[string][]string
	bySlug  map[string][]string
}

func BuildContextResolver(entries []CanonEntry) contextResolver {
	r := contextResolver{
		byID:    make(map[string]bool, len(entries)),
		byTitle: make(map[string][]string, len(entries)),
		byKey:   make(map[string][]string, len(entries)),
		bySlug:  make(map[string][]string, len(entries)),
	}

	for _, e := range entries {
		if e.ID == "" {
			continue
		}
		r.byID[e.ID] = true
		r.byTitle[e.Title] = append(r.byTitle[e.Title], e.ID)
		r.byKey[string(e.Key)] = append(r.byKey[string(e.Key)], e.ID)
		if e.CanonicalSlug != "" {
			r.bySlug[e.CanonicalSlug] = append(r.bySlug[e.CanonicalSlug], e.ID)
		}
	}
	for k := range r.byTitle {
		sort.Strings(r.byTitle[k])
	}
	for k := range r.byKey {
		sort.Strings(r.byKey[k])
	}
	for k := range r.bySlug {
		sort.Strings(r.bySlug[k])
	}
	return r
}

// BuildNodeContextAndRelations computes S37 fields for one node.
func BuildNodeContextAndRelations(srcNode CanonEntry, exportIndex int, resolver contextResolver) (ContextRelations, error) {
	documentID, err := ComputeDocumentID(srcNode)
	if err != nil {
		return ContextRelations{}, err
	}

	sectionPath := BuildSectionPath(srcNode)
	relations, relationStatus, relationCandidates := BuildRelations(srcNode, sectionPath, resolver)

	return ContextRelations{
		DocumentID:               documentID,
		SectionPath:              sectionPath,
		OrderInDocument:          ComputeOrderInDocument(exportIndex),
		Relations:                relations,
		RelationResolutionStatus: relationStatus,
		RelationCandidates:       relationCandidates,
	}, nil
}

// ComputeDocumentID computes the deterministic document UUIDv5 per S37.
func ComputeDocumentID(e CanonEntry) (string, error) {
	documentKey := resolveDocumentKey(e)
	payload := map[string]interface{}{
		"type":              "document",
		"uuid_spec_version": UUIDSpecVersionV1,
		"document_key":      documentKey,
	}
	name, err := CanonicalJSON(payload)
	if err != nil {
		return "", fmt.Errorf("context_s37: canonical document payload: %w", err)
	}
	return UUIDv5(UUIDNamespaceURL, name), nil
}

func resolveDocumentKey(e CanonEntry) string {
	if e.SourceFields != nil {
		for _, k := range []string{"document_key", "document.id", "document_id"} {
			if v := strings.TrimSpace(e.SourceFields[k]); v != "" {
				return normalizeDocumentKey(v)
			}
		}
	}
	if e.SourcePosition != nil {
		pos := strings.TrimSpace(*e.SourcePosition)
		if pos != "" {
			// Prefer logical extractor prefix as document source hint.
			if idx := strings.Index(pos, ":"); idx > 0 {
				return normalizeDocumentKey(pos[:idx])
			}
			return normalizeDocumentKey(pos)
		}
	}
	return "source:unknown"
}

func normalizeDocumentKey(raw string) string {
	s := strings.TrimSpace(strings.ReplaceAll(raw, `\`, "/"))
	if s == "" {
		return "source:unknown"
	}
	if strings.HasPrefix(s, "/") || absWindowsPathRe.MatchString(s) {
		// S37 anti-leak policy: never keep host absolute paths.
		s = filepath.Base(s)
	}
	s = strings.TrimPrefix(s, "./")
	if s == "" {
		return "source:unknown"
	}
	return s
}

// BuildSectionPath builds the conservative section path per S37 precedence.
func BuildSectionPath(e CanonEntry) []string {
	if e.SourceFields != nil {
		if raw := strings.TrimSpace(e.SourceFields["section_path"]); raw != "" {
			if explicit, ok := parseSectionPathArray(raw); ok && len(explicit) > 0 {
				return explicit
			}
		}
	}
	if explicit := extractSectionPathFromTextJSON(e.Text); len(explicit) > 0 {
		return explicit
	}
	return deriveSectionPathFromStructure(e.Title, e.SourceTags)
}

func parseSectionPathArray(raw string) ([]string, bool) {
	var arr []string
	if err := json.Unmarshal([]byte(raw), &arr); err != nil {
		return nil, false
	}
	out := make([]string, 0, len(arr))
	for _, item := range arr {
		s := strings.TrimSpace(item)
		if s != "" {
			out = append(out, s)
		}
	}
	return out, len(out) > 0
}

func extractSectionPathFromTextJSON(text *string) []string {
	if text == nil || strings.TrimSpace(*text) == "" {
		return nil
	}
	var obj map[string]interface{}
	if err := json.Unmarshal([]byte(*text), &obj); err != nil {
		return nil
	}
	raw, ok := obj["section_path"]
	if !ok {
		return nil
	}
	items, ok := raw.([]interface{})
	if !ok {
		return nil
	}
	out := make([]string, 0, len(items))
	for _, it := range items {
		s, ok := it.(string)
		if !ok {
			continue
		}
		s = strings.TrimSpace(s)
		if s != "" {
			out = append(out, s)
		}
	}
	return out
}

func deriveSectionPathFromStructure(title string, tags []string) []string {
	levels := make(map[int][]string)
	for _, tag := range tags {
		tag = strings.TrimSpace(tag)
		lvl := headingLevel(tag)
		if lvl == 0 {
			continue
		}
		levels[lvl] = appendUnique(levels[lvl], tag)
	}

	title = strings.TrimSpace(title)
	selfLevel := headingLevel(title)
	var path []string

	if selfLevel > 0 {
		for lvl := 1; lvl < selfLevel; lvl++ {
			candidates := levels[lvl]
			if len(candidates) == 1 {
				path = append(path, candidates[0])
				continue
			}
			if len(candidates) > 1 {
				break
			}
		}
		path = append(path, title)
	} else {
		for lvl := 1; lvl <= 6; lvl++ {
			candidates := levels[lvl]
			if len(candidates) == 1 {
				path = append(path, candidates[0])
				continue
			}
			if len(candidates) > 1 {
				break
			}
		}
		// CMU-1 (S81): if the path is empty but exactly one #### tag exists, use it
		// as a categorical fallback. Covers nodes with unambiguous #### membership
		// blocked by multi-tagging ambiguity at higher levels (e.g. evidence nodes).
		// This yields a depth-1 categorical path, not a structural hierarchy.
		if len(path) == 0 && len(levels[4]) == 1 {
			path = append(path, levels[4][0])
		}
	}

	return dedupePath(path)
}

func appendUnique(items []string, v string) []string {
	for _, it := range items {
		if it == v {
			return items
		}
	}
	return append(items, v)
}

func dedupePath(path []string) []string {
	if len(path) == 0 {
		return nil
	}
	out := make([]string, 0, len(path))
	seen := make(map[string]bool, len(path))
	for _, p := range path {
		if strings.TrimSpace(p) == "" {
			continue
		}
		if seen[p] {
			continue
		}
		seen[p] = true
		out = append(out, p)
	}
	if len(out) == 0 {
		return nil
	}
	return out
}

func headingLevel(s string) int {
	s = strings.TrimSpace(s)
	if s == "" || s[0] != '#' {
		return 0
	}
	n := 0
	for n < len(s) && s[n] == '#' {
		n++
	}
	if n == 0 || n > 6 || len(s) <= n || s[n] != ' ' {
		return 0
	}
	return n
}

func ComputeOrderInDocument(exportIndex int) int {
	return exportIndex
}

// BuildRelations emits explicit and resolvable S37 relations.
// CMU-DT05-1: self-references (targetID == e.ID) are silently discarded.
func BuildRelations(e CanonEntry, sectionPath []string, resolver contextResolver) ([]NodeRelation, string, int) {
	var relations []NodeRelation
	candidates := 0
	resolved := 0
	ambiguous := 0
	unresolved := 0
	selfRefs := 0

	if parent := ResolveStructuralParent(e, sectionPath); parent != "" {
		candidates++
		if targetID, status := ResolveRelationTargets(parent, resolver); status == "resolved" {
			if targetID != e.ID {
				relations = append(relations, NodeRelation{
					Type: RelationTypeChildOf, TargetID: targetID, Evidence: RelationEvidenceStructuralTag,
				})
				resolved++
			} else {
				selfRefs++
			}
		} else if status == "ambiguous" {
			ambiguous++
		} else {
			unresolved++
		}
	}

	for _, explicit := range extractExplicitRelationTargets(e.Text) {
		candidates++
		targetID, status := ResolveRelationTargets(explicit.Target, resolver)
		if status == "resolved" {
			if targetID != e.ID {
				relations = append(relations, NodeRelation{
					Type: explicit.Type, TargetID: targetID, Evidence: explicit.Evidence,
				})
				resolved++
			} else {
				selfRefs++
			}
		} else if status == "ambiguous" {
			ambiguous++
		} else {
			unresolved++
		}
	}

	for _, link := range extractWikilinks(e.Text) {
		candidates++
		targetID, status := ResolveRelationTargets(link, resolver)
		if status == "resolved" {
			if targetID != e.ID {
				relations = append(relations, NodeRelation{
					Type: RelationTypeReferences, TargetID: targetID, Evidence: RelationEvidenceWikilink,
				})
				resolved++
			} else {
				selfRefs++
			}
		} else if status == "ambiguous" {
			ambiguous++
		} else {
			unresolved++
		}
	}

	// S84: extract capa-2 semantic relations embedded in content payloads.
	for _, embedded := range extractEmbeddedContentRelations(e.Text) {
		candidates++
		targetID, status := ResolveRelationTargets(embedded.Target, resolver)
		if status == "resolved" {
			if targetID != e.ID {
				relations = append(relations, NodeRelation{
					Type: embedded.Type, TargetID: targetID, Evidence: RelationEvidenceEmbeddedContent,
				})
				resolved++
			} else {
				selfRefs++
			}
		} else if status == "ambiguous" {
			ambiguous++
		} else {
			unresolved++
		}
	}

	relations = dedupeSortRelations(relations)

	// effectiveCandidates excludes self-references: they are structurally resolved
	// but carry no discriminating signal for external graph analysis.
	effectiveCandidates := candidates - selfRefs
	switch {
	case effectiveCandidates == 0:
		return relations, "none", candidates
	case ambiguous > 0 && resolved == 0:
		return relations, "ambiguous", candidates
	case unresolved > 0 && resolved == 0:
		return relations, "unresolved", candidates
	case ambiguous > 0 || unresolved > 0:
		return relations, "partial", candidates
	default:
		return relations, "resolved", candidates
	}
}

// ResolveStructuralParent resolves the immediate structural parent title.
func ResolveStructuralParent(e CanonEntry, sectionPath []string) string {
	if len(sectionPath) == 0 {
		return ""
	}
	title := strings.TrimSpace(e.Title)
	for i := len(sectionPath) - 1; i >= 0; i-- {
		candidate := strings.TrimSpace(sectionPath[i])
		if candidate == "" || candidate == title {
			continue
		}
		return candidate
	}
	return ""
}

// ResolveRelationTargets resolves a target using the S37 precedence:
// title exact, key exact, canonical_slug exact.
func ResolveRelationTargets(target string, resolver contextResolver) (string, string) {
	target = strings.TrimSpace(target)
	if target == "" {
		return "", "unresolved"
	}

	// Direct ID resolution.
	if strings.HasPrefix(target, "urn:uuid:") {
		target = strings.TrimPrefix(target, "urn:uuid:")
	}
	if resolver.byID[target] {
		return target, "resolved"
	}

	check := func(candidates []string) (string, string) {
		switch len(candidates) {
		case 0:
			return "", "unresolved"
		case 1:
			return candidates[0], "resolved"
		default:
			return "", "ambiguous"
		}
	}

	if id, status := check(resolver.byTitle[target]); status != "unresolved" {
		return id, status
	}
	if id, status := check(resolver.byKey[target]); status != "unresolved" {
		return id, status
	}
	if id, status := check(resolver.bySlug[target]); status != "unresolved" {
		return id, status
	}
	return "", "unresolved"
}

// extractEmbeddedContentRelations reads the JSON-encoded text and extracts
// semantic relations stored in the embedded "relations" array whose types
// belong to embeddedRelationTypes (S84 capa-2). Canonical structural types
// (child_of, references) are intentionally excluded — they are handled by
// extractExplicitRelationTargets. Evidence is tagged as content_embedded
// to allow downstream consumers to distinguish these from authoritative
// top-level relations.
func extractEmbeddedContentRelations(text *string) []relationTarget {
	if text == nil || strings.TrimSpace(*text) == "" {
		return nil
	}
	var obj map[string]interface{}
	if err := json.Unmarshal([]byte(*text), &obj); err != nil {
		return nil
	}
	rawRelations, ok := obj["relations"].([]interface{})
	if !ok {
		return nil
	}
	out := make([]relationTarget, 0, len(rawRelations))
	for _, item := range rawRelations {
		m, ok := item.(map[string]interface{})
		if !ok {
			continue
		}
		rawType := strings.TrimSpace(strings.ToLower(fmt.Sprintf("%v", m["type"])))
		if !embeddedRelationTypes[rawType] {
			continue
		}
		rawTarget, _ := m["target"].(string)
		if rawTarget == "" {
			rawTarget, _ = m["target_id"].(string)
		}
		if strings.TrimSpace(rawTarget) == "" {
			continue
		}
		out = append(out, relationTarget{
			Type: rawType, Target: strings.TrimSpace(rawTarget), Evidence: RelationEvidenceEmbeddedContent,
		})
	}
	return out
}

func extractExplicitRelationTargets(text *string) []relationTarget {
	if text == nil || strings.TrimSpace(*text) == "" {
		return nil
	}
	var obj map[string]interface{}
	if err := json.Unmarshal([]byte(*text), &obj); err != nil {
		return nil
	}
	rawRelations, ok := obj["relations"].([]interface{})
	if !ok {
		return nil
	}
	out := make([]relationTarget, 0, len(rawRelations))
	for _, item := range rawRelations {
		m, ok := item.(map[string]interface{})
		if !ok {
			continue
		}
		rawType, _ := m["type"].(string)
		rawTarget, _ := m["target"].(string)
		if rawTarget == "" {
			rawTarget, _ = m["target_id"].(string)
		}
		t := normalizeRelationType(rawType)
		if t == "" || strings.TrimSpace(rawTarget) == "" {
			continue
		}
		out = append(out, relationTarget{
			Type: t, Target: strings.TrimSpace(rawTarget), Evidence: RelationEvidenceExplicitField,
		})
	}
	return out
}

func normalizeRelationType(raw string) string {
	switch strings.TrimSpace(strings.ToLower(raw)) {
	case RelationTypeChildOf:
		return RelationTypeChildOf
	case RelationTypeReferences:
		return RelationTypeReferences
	default:
		return ""
	}
}

func extractWikilinks(text *string) []string {
	if text == nil || *text == "" {
		return nil
	}
	matches := wikilinkRe.FindAllStringSubmatch(*text, -1)
	if len(matches) == 0 {
		return nil
	}
	seen := make(map[string]bool, len(matches))
	var out []string
	for _, m := range matches {
		if len(m) < 2 {
			continue
		}
		target := strings.TrimSpace(m[1])
		if target == "" || seen[target] {
			continue
		}
		seen[target] = true
		out = append(out, target)
	}
	sort.Strings(out)
	return out
}

// UnresolvedTargetClass categorises a capa-2 target that failed resolution so
// that auditing surfaces can distinguish actionable stale links from structural
// non-promotables. Classes (S85):
//
//	non_promotable_template  — placeholder pattern, e.g. "#### 🌀 Sesión = m##"
//	non_promotable_concept   — dot/slash notation referencing a concept, not a node
//	non_promotable_path      — file-system path, not a canon title
//	urn_missing              — urn:uuid: or bare UUID not present in the canon
//	stale                    — resolvable-looking title that simply does not exist
type UnresolvedTargetClass string

const (
	UnresolvedTemplate UnresolvedTargetClass = "non_promotable_template"
	UnresolvedConcept  UnresolvedTargetClass = "non_promotable_concept"
	UnresolvedPath     UnresolvedTargetClass = "non_promotable_path"
	UnresolvedURN      UnresolvedTargetClass = "urn_missing"
	UnresolvedStale    UnresolvedTargetClass = "stale"
)

var (
	uuidBareRe    = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)
	headingPrefRe = regexp.MustCompile(`^#{1,6} `)
)

// ClassifyUnresolvedTarget returns the S85 class for a target string that
// failed all resolution strategies. It does NOT attempt resolution itself;
// call ResolveRelationTargets first and only invoke this on "unresolved" results.
func ClassifyUnresolvedTarget(target string) UnresolvedTargetClass {
	t := strings.TrimSpace(target)
	if t == "" {
		return UnresolvedStale
	}

	// URN or bare UUID reference not in canon.
	if strings.HasPrefix(t, "urn:uuid:") {
		return UnresolvedURN
	}
	bare := strings.ToLower(t)
	if uuidBareRe.MatchString(bare) {
		return UnresolvedURN
	}

	// Template placeholder: "##" appearing as a variable placeholder, NOT as
	// the leading markdown heading prefix (e.g. "## Heading" is a heading; "m##"
	// or "#### Node = m##" are template patterns).
	isHeadingPrefix := headingPrefRe.MatchString(t)
	stripped := t
	if isHeadingPrefix {
		// Remove the heading prefix (e.g. "## ") before checking for ## placeholders.
		stripped = headingPrefRe.ReplaceAllString(t, "")
	}
	if strings.Contains(stripped, "##") || strings.Contains(t, "<") || strings.Contains(t, ">") {
		return UnresolvedTemplate
	}

	// Concept notation: dot-delimited identifier (e.g. "relations.type") or
	// slash-delimited path segment that is not a recognisable file path.
	if strings.Contains(t, ".") && !strings.Contains(t, " ") && !strings.Contains(t, "/") {
		return UnresolvedConcept
	}

	// File-system path reference (markdown or common doc extension).
	lower := strings.ToLower(t)
	if strings.HasSuffix(lower, ".md") || strings.HasSuffix(lower, ".html") ||
		strings.HasSuffix(lower, ".json") || strings.Contains(t, "/") {
		return UnresolvedPath
	}

	return UnresolvedStale
}

func dedupeSortRelations(relations []NodeRelation) []NodeRelation {
	if len(relations) == 0 {
		return nil
	}
	sort.Slice(relations, func(i, j int) bool {
		if relations[i].Type != relations[j].Type {
			return relations[i].Type < relations[j].Type
		}
		if relations[i].TargetID != relations[j].TargetID {
			return relations[i].TargetID < relations[j].TargetID
		}
		if relations[i].Evidence != relations[j].Evidence {
			return relations[i].Evidence < relations[j].Evidence
		}
		return nodeRelationJSONKey(relations[i]) < nodeRelationJSONKey(relations[j])
	})

	out := make([]NodeRelation, 0, len(relations))
	prevKey := ""
	for i, rel := range relations {
		key := nodeRelationJSONKey(rel)
		if i > 0 && key == prevKey {
			continue
		}
		out = append(out, rel)
		prevKey = key
	}
	return out
}

func nodeRelationJSONKey(relation NodeRelation) string {
	data, err := json.Marshal(relation)
	if err != nil {
		return fmt.Sprintf("invalid:%#v", relation)
	}
	return string(data)
}
