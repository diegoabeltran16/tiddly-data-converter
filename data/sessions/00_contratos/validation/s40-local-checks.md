# S40 Local Checks — canon-guarded-local-session-test-v0

## Date

2026-04-16

## Environment

- Go 1.25.0
- Modules: `github.com/tiddly-data-converter/canon`, `github.com/tiddly-data-converter/bridge`
- Platform: local Linux workspace
- `GOCACHE`: redirected to `/tmp/go-build` inside the sandbox

## Commands Executed

### 1. Canon tests

```bash
cd go/canon
env GOCACHE=/tmp/go-build go test ./... -count=1
```

Result: PASS

- `go/canon` passed all pre-existing tests.
- New S40 tests passed, including:
  - valid node admission
  - invalid identity rejection
  - explicit role override rejection
  - invalid relation rejection
  - mixed batch with immutable base
  - reproducibility of evidence and merged canon
  - fixture-backed integration against expected merged canon and expected evidence

### 2. Bridge regression

```bash
cd go/bridge
env GOCACHE=/tmp/go-build go test ./... -count=1
```

Result: PASS

### 3. Real canon guarded check

Command: temporary local Go probe against `out/tiddly-data-converter.jsonl`

Observed result:

- base canon lines read: `576`
- strict validation on real canon: `OK`
- reverse preflight on real canon: `OK`
- candidate batch against real canon: `1 accepted`, `1 rejected`
- rejection reason: `unresolved-relation-target`
- merged count after accepting the valid candidate: `577`

### 4. Fixture integrity

Fixtures created and consumed by integration tests:

- `tests/fixtures/s40/base_canon.jsonl`
- `tests/fixtures/s40/candidate_batch_valid.jsonl`
- `tests/fixtures/s40/candidate_batch_invalid.jsonl`
- `tests/fixtures/s40/candidate_batch_mixed.jsonl`
- `tests/fixtures/s40/expected_merged_canon.jsonl`
- `tests/fixtures/s40/expected_rejection_report.json`
- `tests/fixtures/s40/expected_manifest_summary.json`

## Coverage of S40 Minimum Cases

| Case | Coverage | Result |
|------|----------|--------|
| A — Alta válida de nodo nuevo | `TestValidateCandidateBatch_AcceptsValidNode`, fixture valid batch | PASS |
| B — Nodo con identidad inválida | `TestValidateCandidateBatch_RejectsInvalidIdentity` | PASS |
| C — Rol inventado con rol explícito previo | `TestValidateCandidateBatch_RejectsExplicitRoleOverride` | PASS |
| D — Relaciones ambiguas o inválidas | `TestValidateCandidateBatch_RejectsInvalidRelationTarget`, real canon guarded check | PASS |
| E — Batch mixto | `TestValidateCandidateBatch_MixedBatchAndImmutableBase`, fixture mixed batch | PASS |
| F — Inmutabilidad de nodos existentes | `TestValidateCandidateBatch_MixedBatchAndImmutableBase` | PASS |
| G — Reproducibilidad | `TestBuildMergeEvidence_Reproducible` | PASS |

## Summary

S40 leaves a reproducible guarded circuit in `go/canon` and verifies it both on a minimal fixture corpus and on the real exported canon currently present in `out/tiddly-data-converter.jsonl`.
