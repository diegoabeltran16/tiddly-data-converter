# Data Layout

## Autoridad

- `data/in/`: entradas locales
- `data/out/local/tiddlers_*.jsonl`: canon operativo y única fuente de verdad
- `data/out/local/proposals.jsonl`: artefacto legado para recuperación manual o candidate storage extraordinario; no es la ruta diaria de cierre semántico de sesión

## Derivados locales

- `data/out/local/reverse_html/`: HTML derivado y reportes de reverse
- `data/out/local/enriched/`
- `data/out/local/ai/`
- `data/out/local/audit/`
- `data/out/local/export/`

Reglas:

- los derivados pueden borrarse y regenerarse
- `reverse_html/` no es canon
- `data/out/remote/` no es autoridad local

## Notas de gobernanza

- `state:live-path` marca nodos vivos del repo cuando existe evidencia canónica explícita
- `state:historical-snapshot` marca rutas históricas o desalineadas
- `status:archival-only` conserva nodos en canon pero los deja fuera de usos derivados generales
- `source_fields["tmap.id"]` no debe quedar en `PENDIENTE-*`
- si no existe tag explícito, `corpus_state` puede caer en `repo_path` o `general` por regla heurística gobernada

## Fuentes machine-readable

- `contratos/policy/canon_policy_bundle.json`: catálogo de `corpus_state`, resolución y transiciones
- `contratos/projections/derived_layers_registry.json`: mapa de autoridad y linaje entre capas
- `scripts/validate_corpus_governance.py`: validación ejecutable contra el layout real
