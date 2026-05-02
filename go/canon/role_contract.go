package canon

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
)

const rolePrimaryContractPolicyRelPath = "data/sessions/00_contratos/policy/canon_policy_bundle.json"

type rolePolicyBundle struct {
	RolePrimaryContract RolePrimaryContract `json:"role_primary_contract"`
}

// RolePrimaryContract is the S79 machine-readable contract for role_primary.
// The contract is loaded from canon_policy_bundle.json; Go keeps constants as
// ergonomic names, not as the source of truth for the vocabulary.
type RolePrimaryContract struct {
	SchemaVersion              string                         `json:"schema_version"`
	Field                      string                         `json:"field"`
	ContractStatus             string                         `json:"contract_status"`
	CanonicalVocabularyID      string                         `json:"canonical_vocabulary_id"`
	PolicySession              string                         `json:"policy_session"`
	CanonicalRoles             []string                       `json:"canonical_roles"`
	SourceRoleMappings         map[string]string              `json:"source_role_mappings"`
	TagRoleMappings            map[string]string              `json:"tag_role_mappings"`
	AliasesAllowed             map[string]string              `json:"aliases_allowed"`
	LegacyAcceptedTransitional map[string]RoleLegacyMigration `json:"legacy_accepted_transitional"`
	AmbiguousRoles             map[string][]string            `json:"ambiguous_roles"`
	InvalidPolicy              map[string]string              `json:"invalid_policy"`
}

type RoleLegacyMigration struct {
	CanonicalRole *string `json:"canonical_role"`
	MigrationNote string  `json:"migration_note"`
}

type RoleContractVerdict struct {
	InputRole      string   `json:"input_role"`
	CanonicalRole  string   `json:"canonical_role,omitempty"`
	CandidateRoles []string `json:"candidate_roles,omitempty"`
	Verdict        string   `json:"verdict"`
	MigrationClass string   `json:"migration_class"`
}

var (
	defaultRoleContractOnce sync.Once
	defaultRoleContract     RolePrimaryContract
	defaultRoleContractErr  error
)

func LoadDefaultRolePrimaryContract() (RolePrimaryContract, error) {
	defaultRoleContractOnce.Do(func() {
		path, err := FindDefaultRolePrimaryContractPath()
		if err != nil {
			defaultRoleContractErr = err
			return
		}
		defaultRoleContract, defaultRoleContractErr = LoadRolePrimaryContract(path)
	})
	return defaultRoleContract, defaultRoleContractErr
}

func MustDefaultRolePrimaryContract() RolePrimaryContract {
	contract, err := LoadDefaultRolePrimaryContract()
	if err != nil {
		panic(err)
	}
	return contract
}

func FindDefaultRolePrimaryContractPath() (string, error) {
	if cwd, err := os.Getwd(); err == nil {
		if path, ok := findPolicyBundleFrom(cwd); ok {
			return path, nil
		}
	}
	if _, file, _, ok := runtime.Caller(0); ok {
		if path, ok := findPolicyBundleFrom(filepath.Dir(file)); ok {
			return path, nil
		}
	}
	return "", fmt.Errorf("cannot locate %s from current working directory or source path", rolePrimaryContractPolicyRelPath)
}

func findPolicyBundleFrom(start string) (string, bool) {
	dir, err := filepath.Abs(start)
	if err != nil {
		return "", false
	}
	for {
		candidate := filepath.Join(dir, rolePrimaryContractPolicyRelPath)
		if stat, err := os.Stat(candidate); err == nil && !stat.IsDir() {
			return candidate, true
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			return "", false
		}
		dir = parent
	}
}

func LoadRolePrimaryContract(path string) (RolePrimaryContract, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return RolePrimaryContract{}, fmt.Errorf("read role contract %s: %w", path, err)
	}
	var bundle rolePolicyBundle
	if err := json.Unmarshal(data, &bundle); err != nil {
		return RolePrimaryContract{}, fmt.Errorf("parse role contract bundle %s: %w", path, err)
	}
	contract := bundle.RolePrimaryContract
	if err := contract.Validate(); err != nil {
		return RolePrimaryContract{}, fmt.Errorf("invalid role contract %s: %w", path, err)
	}
	return contract, nil
}

func (c RolePrimaryContract) Validate() error {
	if c.SchemaVersion == "" {
		return fmt.Errorf("schema_version is empty")
	}
	if c.Field != "role_primary" {
		return fmt.Errorf("field is %q, want role_primary", c.Field)
	}
	roles := c.CanonicalRoleSet()
	if len(roles) == 0 {
		return fmt.Errorf("canonical_roles is empty")
	}
	if !roles[RoleUnclassified] {
		return fmt.Errorf("canonical_roles must include %q", RoleUnclassified)
	}
	for alias, target := range c.SourceRoleMappings {
		if !roles[target] {
			return fmt.Errorf("source_role_mappings[%q] targets undefined role %q", alias, target)
		}
	}
	for alias, target := range c.TagRoleMappings {
		if !roles[target] {
			return fmt.Errorf("tag_role_mappings[%q] targets undefined role %q", alias, target)
		}
	}
	for alias, target := range c.AliasesAllowed {
		if !roles[target] {
			return fmt.Errorf("aliases_allowed[%q] targets undefined role %q", alias, target)
		}
	}
	for legacy, migration := range c.LegacyAcceptedTransitional {
		if migration.CanonicalRole != nil && !roles[*migration.CanonicalRole] {
			return fmt.Errorf("legacy_accepted_transitional[%q] targets undefined role %q", legacy, *migration.CanonicalRole)
		}
	}
	return nil
}

func (c RolePrimaryContract) CanonicalRoleSet() map[string]bool {
	roles := make(map[string]bool, len(c.CanonicalRoles))
	for _, role := range c.CanonicalRoles {
		role = normalizeRoleKey(role)
		if role != "" {
			roles[role] = true
		}
	}
	return roles
}

func (c RolePrimaryContract) SourceRoleMappingSet() map[string]string {
	return normalizedRoleMap(c.SourceRoleMappings)
}

func (c RolePrimaryContract) TagRoleMappingSet() map[string]string {
	return normalizedRoleMap(c.TagRoleMappings)
}

func (c RolePrimaryContract) ClassifyRole(value string) RoleContractVerdict {
	role := normalizeRoleKey(value)
	roles := c.CanonicalRoleSet()
	if roles[role] {
		return RoleContractVerdict{
			InputRole: role, CanonicalRole: role,
			Verdict: "role_ok", MigrationClass: "canonical",
		}
	}
	if canonical, ok := normalizedRoleMap(c.AliasesAllowed)[role]; ok {
		return RoleContractVerdict{
			InputRole: role, CanonicalRole: canonical,
			Verdict: "role_alias_mapped", MigrationClass: "alias_allowed",
		}
	}
	if migration, ok := c.LegacyAcceptedTransitional[role]; ok {
		if migration.CanonicalRole != nil && *migration.CanonicalRole != "" {
			return RoleContractVerdict{
				InputRole: role, CanonicalRole: normalizeRoleKey(*migration.CanonicalRole),
				Verdict: "role_legacy_detected", MigrationClass: "legacy_accepted_transitional",
			}
		}
		return RoleContractVerdict{
			InputRole: role, CandidateRoles: c.AmbiguousRoles[role],
			Verdict: "role_ambiguous", MigrationClass: "legacy_ambiguous",
		}
	}
	if candidates, ok := c.AmbiguousRoles[role]; ok {
		return RoleContractVerdict{
			InputRole: role, CandidateRoles: candidates,
			Verdict: "role_ambiguous", MigrationClass: "ambiguous",
		}
	}
	verdict := c.InvalidPolicy["default_verdict"]
	if verdict == "" {
		verdict = "role_invalid"
	}
	return RoleContractVerdict{
		InputRole: role, Verdict: verdict, MigrationClass: "invalid",
	}
}

func normalizedRoleMap(input map[string]string) map[string]string {
	out := make(map[string]string, len(input))
	for key, value := range input {
		normalizedKey := normalizeRoleKey(key)
		normalizedValue := normalizeRoleKey(value)
		if normalizedKey != "" && normalizedValue != "" {
			out[normalizedKey] = normalizedValue
		}
	}
	return out
}

func normalizeRoleKey(value string) string {
	return strings.TrimSpace(strings.ToLower(value))
}
