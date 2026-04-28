# S39 Local Checks — canon-executable-policy-and-reverse-readiness-v0

## Date

2026-04-16

## Environment

- Go 1.25.0
- Module: `github.com/tiddly-data-converter/canon`
- Platform: Linux (CI runner)

## Tests Executed

### Unit tests — `go/canon`

```
go test ./... -count=1 -v
```

All tests pass. Key S39-specific tests:

| Test | Description | Result |
|------|-------------|--------|
| `TestDefaultCanonPolicy` | Policy returns correct schema version, artifact role, field counts | PASS |
| `TestPolicyIsAllowedField` | Known fields allowed, invented fields rejected | PASS |
| `TestPolicyIsDerivedField` | Derived fields correctly identified | PASS |
| `TestValidateStrict_ValidLine` | Case A: valid canon line passes strict | PASS |
| `TestValidateStrict_MissingKey` | Case B: missing key rejected | PASS |
| `TestValidateStrict_InconsistentID` | Case C: tampered id detected | PASS |
| `TestValidateStrict_UnknownField` | Case D: unknown field rejected | PASS |
| `TestValidateStrict_SemanticTextRedundant` | Case E: redundant semantic_text reported as warning | PASS |
| `TestValidateStrict_WrongSchemaVersion` | Wrong schema version rejected | PASS |
| `TestValidateStrict_InvalidJSON` | Invalid JSON rejected | PASS |
| `TestNormalize_NewTiddlerNoDeriveds` | Case B: new tiddler gets derived fields computed | PASS |
| `TestNormalize_Idempotent` | Normalizer is idempotent (double run = same output) | PASS |
| `TestNormalize_SemanticTextSuppressed` | Case E: redundant semantic_text suppressed to null | PASS |
| `TestNormalize_RejectsEmptyTitle` | Empty title rejected by normalizer | PASS |
| `TestNormalize_CorrectedVersionID` | Case C: tampered version_id corrected | PASS |
| `TestNormalize_NoDrift` | Case A: valid canon passes through without drift | PASS |
| `TestReversePreflight_Ready` | Case A: valid node is reverse-ready | PASS |
| `TestReversePreflight_MissingTitle` | Case F: missing title fails preflight | PASS |
| `TestReversePreflight_MissingKey` | Case F: missing key fails preflight | PASS |
| `TestReversePreflight_WrongSchema` | Case F: wrong schema fails preflight | PASS |
| `TestReversePreflight_NullText` | Null text is still reverse-ready | PASS |
| `TestReversePreflight_InvalidJSON` | Invalid JSON fails preflight | PASS |
| `TestDerivedLayersRegistryNotCanonical` | Case G: no derived layer marked canonical | PASS |
| `TestFullFlow_NewTiddlerAdded` | Integration: normalize → strict → reverse-preflight | PASS |
| `TestValidate_MultipleLines` | Mixed valid/invalid lines in same file | PASS |

### Build verification

```
go build ./cmd/canon_preflight/
```

CLI binary builds without errors.

### Pre-existing tests

All pre-existing tests in `go/canon` continue to pass (no regressions from S34–S38).

## Coverage of S39 §14 Cases

| Case | Description | Covered By |
|------|-------------|------------|
| A | Canon actual intacto | TestValidateStrict_ValidLine, TestNormalize_NoDrift |
| B | Nuevo tiddler con campos fuente válidos | TestNormalize_NewTiddlerNoDeriveds |
| C | Derivado adulterado | TestValidateStrict_InconsistentID, TestNormalize_CorrectedVersionID |
| D | Campo no permitido | TestValidateStrict_UnknownField |
| E | semantic_text redundante | TestValidateStrict_SemanticTextRedundant, TestNormalize_SemanticTextSuppressed |
| F | Nodo no reverse-ready | TestReversePreflight_MissingTitle, TestReversePreflight_MissingKey |
| G | Registro de capas derivadas | TestDerivedLayersRegistryNotCanonical |

## Determinism Verification

`TestNormalize_Idempotent` confirms that running the normalizer twice on the same input produces identical output.

## JSON Validity of Contract Artifacts

All `.json` artifacts under `contratos/` parse correctly as JSON.
