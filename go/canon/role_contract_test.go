package canon

import (
	"path/filepath"
	"sync"
	"testing"
)

// resetDefaultRoleContract resets the package-level once-loaded contract so
// tests that change CANON_POLICY_BUNDLE_PATH or cwd can re-trigger loading.
func resetDefaultRoleContract() {
	defaultRoleContractOnce = sync.Once{}
	defaultRoleContract = RolePrimaryContract{}
	defaultRoleContractErr = nil
}

func TestRolePrimaryContractLoadsFromPolicyBundle(t *testing.T) {
	contract, err := LoadDefaultRolePrimaryContract()
	if err != nil {
		t.Fatalf("LoadDefaultRolePrimaryContract() error = %v", err)
	}
	if contract.Field != "role_primary" {
		t.Fatalf("contract field = %q, want role_primary", contract.Field)
	}

	roles := contract.CanonicalRoleSet()
	for _, role := range []string{
		RoleConcept,
		RoleProcedure,
		RoleEvidence,
		RoleDefinition,
		RoleGlossary,
		RolePolicy,
		RoleLog,
		RoleAsset,
		RoleConfig,
		RoleCode,
		RoleNarrative,
		RoleNote,
		RoleWarning,
		RoleUnclassified,
	} {
		if !roles[role] {
			t.Fatalf("role contract missing canonical role %q", role)
		}
	}
}

func TestRolePrimaryContractMappingsDriveSemanticResolution(t *testing.T) {
	contract := MustDefaultRolePrimaryContract()

	sourceMappings := contract.SourceRoleMappingSet()
	if got := sourceMappings["procedencia"]; got != RoleEvidence {
		t.Fatalf("source_role procedencia maps to %q, want %q", got, RoleEvidence)
	}
	if got := sourceMappings["reporte"]; got != RoleLog {
		t.Fatalf("source_role reporte maps to %q, want %q", got, RoleLog)
	}

	tagMappings := contract.TagRoleMappingSet()
	if got := tagMappings["procedimiento"]; got != RoleProcedure {
		t.Fatalf("tag procedimiento maps to %q, want %q", got, RoleProcedure)
	}
	if got := tagMappings["código"]; got != RoleCode {
		t.Fatalf("tag código maps to %q, want %q", got, RoleCode)
	}

	// S80 — unclassified-residual-mapping: verify new tag mappings resolve
	// the three main unclassified subfamilies (Fam A, B, C).
	if got := tagMappings["--- codigo"]; got != RoleCode {
		t.Fatalf("tag '--- codigo' maps to %q, want %q (Fam B: codigo/build nodes)", got, RoleCode)
	}
	if got := tagMappings["layer:session"]; got != RoleLog {
		t.Fatalf("tag 'layer:session' maps to %q, want %q (Fam A: session artifacts)", got, RoleLog)
	}
	if got := tagMappings["#### referencias especificas 🌀"]; got != RoleEvidence {
		t.Fatalf("tag '#### referencias especificas 🌀' maps to %q, want %q (Fam C: references)", got, RoleEvidence)
	}
	if got := tagMappings["## 📚🧱 glosario y convenciones"]; got != RoleGlossary {
		t.Fatalf("tag '## 📚🧱 glosario y convenciones' maps to %q, want %q (glossary nodes)", got, RoleGlossary)
	}
}

func TestRolePrimaryContractClassifiesMigrationStates(t *testing.T) {
	contract := MustDefaultRolePrimaryContract()

	ok := contract.ClassifyRole(RoleLog)
	if ok.Verdict != "role_ok" || ok.CanonicalRole != RoleLog {
		t.Fatalf("ClassifyRole(log) = %+v", ok)
	}

	alias := contract.ClassifyRole("concepto")
	if alias.Verdict != "role_alias_mapped" || alias.CanonicalRole != RoleConcept {
		t.Fatalf("ClassifyRole(concepto) = %+v", alias)
	}

	legacy := contract.ClassifyRole("session")
	if legacy.Verdict != "role_legacy_detected" || legacy.CanonicalRole != RoleLog {
		t.Fatalf("ClassifyRole(session) = %+v", legacy)
	}

	ambiguous := contract.ClassifyRole("hypothesis")
	if ambiguous.Verdict != "role_ambiguous" || len(ambiguous.CandidateRoles) == 0 {
		t.Fatalf("ClassifyRole(hypothesis) = %+v", ambiguous)
	}

	invalid := contract.ClassifyRole("not-a-role")
	if invalid.Verdict != "role_invalid" {
		t.Fatalf("ClassifyRole(not-a-role) = %+v", invalid)
	}
}

// TestFindContractPath_EnvVarOverride verifies that CANON_POLICY_BUNDLE_PATH
// takes precedence over cwd-based discovery (S82 — explicit env override).
func TestFindContractPath_EnvVarOverride(t *testing.T) {
	realPath, err := FindDefaultRolePrimaryContractPath()
	if err != nil {
		t.Skipf("cannot locate policy bundle to run env-var test: %v", err)
	}

	t.Setenv(EnvCanonPolicyBundlePath, realPath)

	// Move to an unrelated temp directory so cwd-walk cannot find the file.
	t.Chdir(t.TempDir())

	got, err := FindDefaultRolePrimaryContractPath()
	if err != nil {
		t.Fatalf("FindDefaultRolePrimaryContractPath with env var set: %v", err)
	}
	if got != realPath {
		t.Fatalf("expected path %q, got %q", realPath, got)
	}
}

// TestFindContractPath_EnvVarInvalid verifies that setting CANON_POLICY_BUNDLE_PATH
// to a non-existent path returns an explicit error, not a silent fallback.
func TestFindContractPath_EnvVarInvalid(t *testing.T) {
	t.Setenv(EnvCanonPolicyBundlePath, filepath.Join(t.TempDir(), "does_not_exist.json"))

	_, err := FindDefaultRolePrimaryContractPath()
	if err == nil {
		t.Fatal("expected error for invalid CANON_POLICY_BUNDLE_PATH, got nil")
	}
}

// TestFindContractPath_CwdIndependent verifies that policy discovery succeeds
// even when the process working directory is an unrelated temp directory,
// as long as the source-file walk-up fallback is functional (S82).
func TestFindContractPath_CwdIndependent(t *testing.T) {
	// Ensure no env override is active.
	t.Setenv(EnvCanonPolicyBundlePath, "")

	// Change to a temp dir that has no relation to the repo.
	t.Chdir(t.TempDir())

	path, err := FindDefaultRolePrimaryContractPath()
	if err != nil {
		t.Fatalf("FindDefaultRolePrimaryContractPath from unrelated cwd: %v\n"+
			"Hint: source-file walk-up should have found the bundle; "+
			"check that the source tree is accessible at compile-time path", err)
	}

	// Verify the resolved path actually contains a loadable contract.
	contract, err := LoadRolePrimaryContract(path)
	if err != nil {
		t.Fatalf("LoadRolePrimaryContract(%q): %v", path, err)
	}
	if contract.Field != "role_primary" {
		t.Fatalf("loaded contract field = %q, want role_primary", contract.Field)
	}
}

// TestLoadDefaultRolePrimaryContract_UsesEnvVar verifies end-to-end that the
// default loader honours CANON_POLICY_BUNDLE_PATH from an unrelated cwd.
func TestLoadDefaultRolePrimaryContract_UsesEnvVar(t *testing.T) {
	realPath, err := FindDefaultRolePrimaryContractPath()
	if err != nil {
		t.Skipf("cannot locate policy bundle: %v", err)
	}

	t.Setenv(EnvCanonPolicyBundlePath, realPath)
	t.Chdir(t.TempDir())

	// Reset the once so the env override takes effect.
	resetDefaultRoleContract()
	t.Cleanup(resetDefaultRoleContract)

	contract, err := LoadDefaultRolePrimaryContract()
	if err != nil {
		t.Fatalf("LoadDefaultRolePrimaryContract with env var: %v", err)
	}
	if contract.Field != "role_primary" {
		t.Fatalf("contract.Field = %q, want role_primary", contract.Field)
	}
}
