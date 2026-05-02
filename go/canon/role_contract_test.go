package canon

import "testing"

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
