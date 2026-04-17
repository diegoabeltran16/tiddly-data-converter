# S38 Local Checks

- Fecha: 2026-04-16
- Sesión: `m02-s38-canon-export-contract-hardening-v0`
- Estado: completado en entorno local

## Archivos tocados (resumen)

### Código
- `go/canon/identity.go` — SemanticText changed to *string
- `go/canon/semantic.go` — ExtractSemanticText returns *string; suppression logic
- `go/canon/exporter_tiddler.go` — ExportManifest and ExportLogEntry hardened
- `go/bridge/cmd/export_tiddlers/main.go` — adapted to new fields

### Tests
- `go/canon/semantic_test.go` — updated for *string semantic_text
- `go/canon/exporter_tiddler_test.go` — adapted to new manifest/log fields
- `go/canon/export_identity_integration_test.go` — Decision instead of Action
- `go/canon/export_semantic_integration_test.go` — semantic counters updated
- `go/canon/export_context_relations_integration_test.go` — Decision instead of Action
- `go/canon/export_contract_integration_test.go` — **new** (7 tests)
- `go/bridge/s33_e2e_test.go` — adapted to ExcludedCount

### Fixtures
- `tests/fixtures/s38/export_contract/contract_hardening_fixture.json` — **new**

### Documentation
- `contratos/export_contract/export_contract_rules.md` — **new**
- `contratos/m02-s38-canon-export-contract-hardening-v0.md.json` — **new**

## Comandos ejecutados y resultado

1. Build canon package
```bash
cd go/canon && go build ./...
```
Resultado: OK.

2. Build bridge package
```bash
cd go/bridge && go build ./...
```
Resultado: OK.

3. Suite canon (todas las pruebas)
```bash
cd go/canon && go test ./... -count=1 -timeout 120s
```
Resultado: OK (toda la suite pasa, incluidos 7 tests nuevos S38).

4. Suite bridge
```bash
cd go/bridge && go test ./... -count=1 -timeout 120s
```
Resultado: OK.

5. S38 integration tests specifically
```bash
cd go/canon && go test -run TestExportContractIntegration -count=1 -v
```
Resultado: 7/7 PASS:
- TestExportContractIntegration_ManifestInvariant
- TestExportContractIntegration_SemanticTextSuppression
- TestExportContractIntegration_ExportLogTerminalDecision
- TestExportContractIntegration_SemanticTextStrategy
- TestExportContractIntegration_ExcludedByRule
- TestExportContractIntegration_NoRegressionS37
- TestExportContractIntegration_EquationNode

## Verificaciones S38

### semantic_text ya no duplica trivialmente text
- TestExportContractIntegration_SemanticTextSuppression verifica que cuando
  semantic_text equals text, it is serialized as null in JSONL.
- TestExportContractIntegration_EquationNode verifica que equation content
  preserves text but semantic_text is null.
- semantic_test.go tests updated: all textual nodes now expect nil semantic_text.

### Manifest no es ambiguo
- TestExportContractIntegration_ManifestInvariant verifica:
  `source_candidate_count == excluded_count + exported_count`
- artifact_role == "canon_export"
- schema_version == "v0"

### Export log es evidencia terminal
- TestExportContractIntegration_ExportLogTerminalDecision verifica:
  - One entry per candidate
  - decision: "exported" or "excluded"
  - exported entries have id, canonical_slug, semantic_text_strategy
  - excluded entries have rule_id

### semantic_text_strategy en vocabulario controlado
- TestExportContractIntegration_SemanticTextStrategy verifica:
  - Only "distinct", "suppressed_equal_to_text", or "not_applicable"

### excluded_by_rule trazable
- TestExportContractIntegration_ExcludedByRule verifica:
  - sum(excluded_by_rule) == excluded_count

### No regresión S37
- TestExportContractIntegration_NoRegressionS37 verifica:
  - document_id, section_path, order_in_document, relations son estables
    entre re-runs con el mismo input.

## Consistencia manifest/JSONL/export.log
- manifest.exported_count == number of JSONL lines (verified in tests)
- manifest.source_candidate_count == total log entries (verified in tests)
- manifest.semantic_text_distinct_count + semantic_text_null_count == exported_count (verified)

## Compatibilidad / límites
- No se detectó regresión en pruebas S34–S37.
- Bridge package compila y pasa tests con los nuevos campos.
- Los campos renombrados (Action→Decision, TiddlerID→SourceRef) fueron
  actualizados en todos los consumidores del repositorio.
