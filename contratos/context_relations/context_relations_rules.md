# S37 — Contexto documental y relaciones explícitas (reglas)

## Objetivo
Definir una capa mínima, determinista y auditable para que cada línea canónica exponga:
- `document_id`
- `section_path`
- `order_in_document`
- `relations`

## Jerarquía de evidencia
1. Campo explícito en fuente.
2. Marcador estructural explícito.
3. Orden fuente ya disponible.
4. Wikilinks explícitos resolubles.
5. Fallback vacío/nulo permitido.

## `document_id`
- Se calcula con UUIDv5 (S30), payload canónico:
  - `type: "document"`
  - `uuid_spec_version: "v1"`
  - `document_key: <clave documental estable>`
- Precedencia de `document_key`:
  - `source_fields.document_key`
  - `source_fields.document.id` / `source_fields.document_id`
  - prefijo lógico de `source_position`
  - `source:unknown`
- No se permite fuga de rutas absolutas del host.

## `section_path`
- Forma: `[]string` (no blob plano).
- Precedencia:
  - `source_fields.section_path` (JSON array válido)
  - `section_path` explícito en JSON del `text`
  - derivación conservadora desde tags estructurales y nivel de `title`
  - `[]` si no hay evidencia suficiente
- Preserva títulos visibles; no inventa niveles.

## `order_in_document`
- Entero base 0.
- Derivado del orden de entrada del exporter.
- Sin ordenamientos artificiales por slug/título/id.

## `relations`
- Shape mínimo por relación:
  - `type`
  - `target_id`
  - `evidence`
- Vocabulario permitido en S37:
  - `child_of`
  - `references`
- Evidencias emitidas:
  - `structural_tag`
  - `wikilink`
  - `explicit_field`
- Resolución de targets (sin fuzzy):
  1. `title` exacto
  2. `key` exacto
  3. `canonical_slug` exacto
  4. `ambiguous` o `unresolved` => no emitir
- Orden/dedupe:
  - orden por `type`, `target_id`, `evidence`
  - dedupe exacto por tríada.

## Observabilidad
`manifest` incluye:
- `document_count`
- `nodes_with_section_path_count`
- `nodes_with_relations_count`
- `relation_counts.child_of`
- `relation_counts.references`

`export.log` (entradas incluidas) incluye:
- `context_info.document_id`
- `context_info.order_in_document`
- `context_info.section_path_length`
- `context_info.relation_count`
- `context_info.relation_resolution_status`
