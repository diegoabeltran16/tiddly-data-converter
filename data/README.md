# Data Layout

## Autoridad

- `data/out/local/sessions/`: artefactos versionables de sesión, staging operativo y líneas candidatas; no es canon paralelo
- `data/in/`: entradas locales
- `data/out/local/tiddlers_*.jsonl`: canon operativo y única fuente de verdad
- `data/out/local/proposals.jsonl`: artefacto legado para recuperación manual o candidate storage extraordinario; no es la ruta diaria de cierre semántico de sesión
- `data/tmp/session_admission/`: copias temporales de canon para validar admisión sin tocar canon final
- `data/tmp/admissions/`: reportes JSON de `validate`, `dry-run`, `apply` y `rollback`

## Derivados locales

- `data/out/local/reverse_html/`: HTML derivado y reportes de reverse
- `data/out/local/enriched/`
- `data/out/local/ai/`
- `data/out/local/audit/`
- `data/out/local/export/`
- `data/out/local/tiddlers-export/`: salida runtime del exportador de repositorio; contiene tiddlers JSON documentales y estado incremental bajo `hashes_rep_export/.hashes.json`; no es canon ni reemplaza `data/out/local/export/`
- `data/out/local/microsoft_copilot/`: proyección derivada legible por Microsoft Copilot y otros agentes remotos; regenerable, trazable, no autoritativa y emitida como JSON/CSV/TXT; incluye sublayer `copilot_agent/` con paquete semántico reversible (`corpus.txt`, `entities.json`, `relations.csv`)

Reglas:

- los derivados pueden borrarse y regenerarse
- `microsoft_copilot/` no usa `.jsonl` como salida final primaria de lectura; JSON estructura, CSV tabula y TXT contextualiza
- `reverse_html/` no es canon
- `data/out/remote/` no es autoridad local
- las líneas candidatas producidas en `data/out/local/sessions/` solo pueden absorberse al canon local tras validación local, `strict`, `reverse-preflight`, reverse autoritativo con `Rejected: 0` y tests pertinentes
- `python_scripts/admit_session_candidates.py` orquesta ese flujo de admisión y rollback con compuertas reales
- la verificación reproducible S69 se ejecuta con `bash tests/fixtures/s69/run_session_admission_test.sh` y usa fixtures temporales bajo `data/tmp/`

## Notas de gobernanza

- `state:live-path` marca nodos vivos del repo cuando existe evidencia canónica explícita
- `state:historical-snapshot` marca rutas históricas o desalineadas
- `status:archival-only` conserva nodos en canon pero los deja fuera de usos derivados generales
- `source_fields["tmap.id"]` no debe quedar en `PENDIENTE-*`
- si no existe tag explícito, `corpus_state` puede caer en `repo_path` o `general` por regla heurística gobernada

## Fuentes machine-readable

- `data/out/local/sessions/00_contratos/policy/canon_policy_bundle.json`: catálogo de `corpus_state`, resolución y transiciones
- `data/out/local/sessions/00_contratos/projections/derived_layers_registry.json`: mapa de autoridad y linaje entre capas
- `python_scripts/validate_corpus_governance.py`: validación ejecutable contra el layout real
