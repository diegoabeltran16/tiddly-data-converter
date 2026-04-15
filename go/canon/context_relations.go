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

	RelationEvidenceExplicitField = "explicit_field"
	RelationEvidenceStructuralTag = "structural_tag"
	RelationEvidenceWikilink      = "wikilink"
)

var (
	absWindowsPathRe = regexp.MustCompile(`^[A-Za-z]:[\\/].*`)
	wikilinkRe       = regexp.MustCompile(`\[\[([^\]]+)\]\]`)
)

// NodeRelation is the minimal S37 relation shape emitted in canonical JSONL.
type NodeRelation struct {
	Type     string `json:"type"`
	TargetID string `json:"target_id"`
	Evidence string `json:"evidence"`
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
func BuildRelations(e CanonEntry, sectionPath []string, resolver contextResolver) ([]NodeRelation, string, int) {
	var relations []NodeRelation
	candidates := 0
	resolved := 0
	ambiguous := 0
	unresolved := 0

	if parent := ResolveStructuralParent(e, sectionPath); parent != "" {
		candidates++
		if targetID, status := ResolveRelationTargets(parent, resolver); status == "resolved" {
			relations = append(relations, NodeRelation{
				Type: RelationTypeChildOf, TargetID: targetID, Evidence: RelationEvidenceStructuralTag,
			})
			resolved++
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
			relations = append(relations, NodeRelation{
				Type: explicit.Type, TargetID: targetID, Evidence: explicit.Evidence,
			})
			resolved++
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
			relations = append(relations, NodeRelation{
				Type: RelationTypeReferences, TargetID: targetID, Evidence: RelationEvidenceWikilink,
			})
			resolved++
		} else if status == "ambiguous" {
			ambiguous++
		} else {
			unresolved++
		}
	}

	relations = dedupeSortRelations(relations)

	switch {
	case candidates == 0:
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
		return relations[i].Evidence < relations[j].Evidence
	})

	out := make([]NodeRelation, 0, len(relations))
	var prev NodeRelation
	for i, rel := range relations {
		if i > 0 && rel == prev {
			continue
		}
		out = append(out, rel)
		prev = rel
	}
	return out
}
