---
applyTo: "contratos/**"
description: >
  Instruccion local-first para el cierre de sesiones con contrato y para la
  emision de lineas JSONL de sesion compatibles con el canon. El layout vigente
  es data/in, data/out/{local,remote} y data/reverse_html.
---

## Instruccion: cierre de sesiones y propuestas JSONL

Para toda sesion de trabajo en `tiddly-data-converter`, el agente debe cerrar
con al menos 1 contrato `.md.json` en `contratos/`.

Si la sesion ademas deja nuevas lineas canonicas candidatas o ajustes sobre
lineas ya existentes, el agente debe producir o ampliar `data/out/local/proposals.jsonl`,
no una escritura directa al shard canonico fuente.

## Regla central

El canon local sigue mandando:

- fuente de verdad: `data/out/local/tiddlers_*.jsonl`
- lectura: permitida
- derivacion: permitida
- propuestas: permitidas
- escritura directa por agente: **prohibida por defecto**

La excepcion solo existe cuando la sesion o el usuario ordenan de forma
explicita un **merge canonico gobernado** o una reparacion canonica puntual.

## Lectura previa obligatoria

Antes de emitir una propuesta o de documentar una sesion que toque canon,
leer como minimo:

1. `esquemas/canon/canon_guarded_session_rules.md`
2. `docs/Informe_Tecnico_de_Tiddler (Esp).md`
3. los shards canonicos pertinentes dentro de `data/out/local/tiddlers_*.jsonl`
4. las capas derivadas pertinentes (`data/out/local/enriched/`, `data/out/local/ai/`) cuando ayuden al analisis

Si el trabajo toca una linea existente, leer el shard y el nodo objetivo antes
de proponer cambios.

## Destinos de escritura permitidos para agentes

### 1. Siempre permitido

- `contratos/*.md.json`
- `data/out/local/proposals.jsonl`
- documentacion y scripts del repositorio

### 2. Prohibido por defecto

- `data/out/local/tiddlers_*.jsonl`

La escritura directa en estos shards requiere mandato explicito del usuario o
de una sesion gobernada de merge/reparacion canonicamente justificada.

## Artefacto de propuesta de sesion

Toda propuesta debe:

- vivir en `data/out/local/`
- escribirse como JSONL
- contener lineas individuales ya canonizadas, no solo compatibles
- acumularse en `data/out/local/proposals.jsonl`
- poder incluir lineas de sesion, procedencia, hipotesis o dependencias

Campos obligatorios esperados:

- identidad: `schema_version`, `id`, `key`, `title`, `canonical_slug`, `version_id`
- lectura: `content_type`, `modality`, `encoding`, `is_binary`, `is_reference_only`
- semantica: `role_primary`, `tags`, `taxonomy_path`, `semantic_text`, `content`, `raw_payload_ref`, `mime_type`
- contexto: `document_id`, `section_path`, `order_in_document`, `relations`
- procedencia: `source_tags`, `normalized_tags`, `source_fields`, `text`, `source_type`, `source_position`, `created`, `modified`

## Flujo por defecto

1. Leer canon y derivados locales.
2. Analizar el cambio necesario.
3. Emitir contrato de sesion en `contratos/`.
4. Emitir lineas JSONL canonizadas en `data/out/local/proposals.jsonl` si hay cambio canonico sugerido.
5. No tocar `data/out/local/tiddlers_*.jsonl` salvo mandato explicito de merge.

La sesion puede quedar cerrada con contrato + archivo JSONL de sesion sin tocar
el canon.

## Flujo excepcional: merge canonico gobernado

Solo cuando el usuario o la sesion lo ordenen de forma explicita, el agente
puede operar sobre `data/out/local/tiddlers_*.jsonl`.

En ese caso debe:

1. identificar el target exacto en canon
2. justificar el cambio como merge/reparacion gobernada
3. preservar byte a byte toda linea no objetivo
4. correr:

```bash
cd go/canon
env GOCACHE=/tmp/go-build go run ./cmd/canon_preflight --mode strict --input ../../data/out/local
```

5. y, si aplica al reverse:

```bash
cd go/canon
env GOCACHE=/tmp/go-build go run ./cmd/canon_preflight --mode reverse-preflight --input ../../data/out/local
```

6. regenerar capas derivadas solo si el merge cambia efectivamente el canon

## Rutas obsoletas

No crear artefactos nuevos en:

- `docs/tiddlers_de_sesiones/`

El layout vigente es `data/in`, `data/out/local`, `data/out/remote`, `data/reverse_html`.

## Regla de foco

El objetivo de la sesion no es "nutrir el canon" con escritura libre.
El objetivo es:

- leer el canon
- respetarlo
- y dejar lineas JSONL canonizadas en `data/out/local/proposals.jsonl`

La sesion no se considera bien cerrada solo por la conversacion. Se considera
bien cerrada cuando existe el contrato `.md.json` y, cuando corresponda, existe
la actualizacion correcta de `data/out/local/proposals.jsonl`.
