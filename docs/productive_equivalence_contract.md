# Contrato de equivalencia productiva gobernada v2

`productive-equivalence-contract/v2` compara tres superficies que conservan responsabilidades distintas:

- Baseline: referencia histórica o el último corpus productivo admitido; detecta pérdidas y cambios sobre identidades compartidas.
- Staging actual: derivación candidata a promoción.
- Canon vigente: única autoridad de pertenencia, identidad estable y `version_id` actual.

El baseline no autoriza registros y el canon no sustituye la comparación histórica.

## Clasificación

Una alta es `added_from_current_canon` solo si su identidad existe en el canon vigente y su versión derivada coincide con la canónica. Un ID compartido es `canonical_update` solo si su versión cambió desde el baseline y coincide con el canon vigente.

Con la misma versión, cualquier cambio de proyección lógica es `unexpected_semantic_regression` y bloquea. Una transición de versión que no coincide con el canon es `invalid_version_transition` y bloquea. Una ausencia histórica es `removed_historical_record` y bloquea: v2 no define una política de eliminación.

También bloquean pertenencia canónica inválida, identidad o familia incompatibles, duplicados, cambios de esquema y chunks sobre el máximo duro. Los chunks no deben crecer por cada alta canónica; pueden permanecer estables cuando el contrato de chunking excluye la alta y no hay pérdida o mismatch compartido.

## Firmas y migración

Las firmas compactas contienen identidad, `version_id`, hashes de semántica, hints de recuperación, metadata, filtro RAG, campos de chunking, esquema y proyección lógica. Los anchors de chunks comparan `canon_id`, no número de shard o línea: estos últimos son ubicación física no identidad canónica.

Las proyecciones nuevas publican la versión de fuente explícitamente en AI y Copilot. Para baselines históricos anteriores a ese campo, el validador acepta la versión ya declarada dentro de `semantic_text` únicamente como compatibilidad de lectura; la autoridad continúa siendo el canon vigente.

El reporte principal v2 conserva solo conteos y explicaciones. `canonical_evolution_summary.json` y `canonical_evolution_ids.json` contienen el resumen y las listas auditables por separado.

## Baseline estable y autorización

Hasta que exista el primer `productive_rag_manifest.json` admitido, el baseline histórico explícito se usa como bootstrap. Después, el resolvedor normal selecciona el corpus del último manifest productivo admitido; la procedencia histórica no se convierte en una dependencia funcional de una sesión.

Un cambio de manifest invalida autorizar, trial, rollback y promoción anteriores para el manifest actual. La equivalencia no habilita escritura: el trial y la promoción definitiva siguen exigiendo autorizaciones humanas independientes y ligadas al hash del manifest vigente.
