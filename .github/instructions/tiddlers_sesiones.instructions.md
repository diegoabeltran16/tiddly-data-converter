---
applyTo: "contratos/**"
description: >
  Instruccion local-first para cierre contractual y absorcion canónica directa
  de memoria semántica de sesión. proposals.jsonl queda como artefacto legado y
  extraordinario, no como ruta diaria de cierre.
---

## Instruccion: cierre directo en canon y proposals legado

Para toda sesion de trabajo en `tiddly-data-converter`, el agente debe cerrar
con al menos 1 contrato `.md.json` en `contratos/`.

Si la sesion deja memoria semántica-documental propia de cierre
(`#### 🌀 Sesión ...`, `#### 🌀🧪 Hipótesis ...`, `#### 🌀🧾 Procedencia ...`
y, cuando aplique, familia `#### 🌀📦 ...`), esas lineas deben absorberse
directamente en `data/out/local/tiddlers_*.jsonl`.

## Regla central

El canon local sigue mandando:

- fuente de verdad: `data/out/local/tiddlers_*.jsonl`
- lectura: permitida
- derivacion: permitida
- cierre semántico-documental directo en canon: requerido para la producción propia de la sesión
- `data/out/local/proposals.jsonl`: legado y extraordinario
- escritura directa libre por agente: **prohibida**

La escritura directa sigue siendo gobernada: solo se admite sobre targets
explícitos, con preservación de líneas no objetivo y con compuertas de
validación reales.

## Lectura previa obligatoria

Antes de documentar una sesion que toque canon,
leer como minimo:

1. `esquemas/canon/canon_guarded_session_rules.md`
2. `docs/Informe_Tecnico_de_Tiddler (Esp).md`
3. los shards canonicos pertinentes dentro de `data/out/local/tiddlers_*.jsonl`
4. las capas derivadas pertinentes (`data/out/local/enriched/`, `data/out/local/ai/`) cuando ayuden al analisis

Si el trabajo toca una linea existente, leer el shard y el nodo objetivo antes
de escribir.

## Destinos de escritura permitidos para agentes

### 1. Siempre permitido

- `contratos/*.md.json`
- documentacion y scripts del repositorio

### 2. Cierre semántico-documental requerido

- `data/out/local/tiddlers_*.jsonl`

Cuando la sesion produzca memoria estructural propia, el cierre debe quedar
absorbido aqui y no en `proposals.jsonl`.

### 3. Extraordinario

- `data/out/local/proposals.jsonl`

`proposals.jsonl` queda reservado para recuperación manual, candidate storage
histórico o lotes excepcionales que todavía no deban absorberse al canon base.

## Artefacto canónico de sesión

Toda línea de cierre directo debe:

- vivir en `data/out/local/tiddlers_*.jsonl`
- escribirse ya canonizada
- poder incluir lineas de sesion, procedencia, hipotesis o dependencias
- quedar lista para `strict` y `reverse-preflight`

Campos obligatorios esperados:

- identidad: `schema_version`, `id`, `key`, `title`, `canonical_slug`, `version_id`
- lectura: `content_type`, `modality`, `encoding`, `is_binary`, `is_reference_only`
- semantica: `role_primary`, `tags`, `taxonomy_path`, `semantic_text`, `content`, `raw_payload_ref`, `mime_type`
- contexto: `document_id`, `section_path`, `order_in_document`, `relations`
- procedencia: `source_tags`, `normalized_tags`, `source_fields`, `text`, `source_type`, `source_position`, `created`, `modified`

## Formato obligatorio de source_fields.tags

Cuando `source_fields` incluye la clave `"tags"`, su valor debe seguir exactamente
la misma regla que `formatTW5Tags` del motor de reverse:

- si el tag **contiene espacio, `[` o `]`** → envolverlo: `[[tag con espacios]]`
- si el tag **no contiene ninguno de esos caracteres** → dejarlo tal cual: `session:m03-s54`

Ejemplos correctos:

```
[[## 🧭🧱 Protocolo de Sesión]] [[#### 🌀 Sesión 54 = ...]] session:m03-s54 milestone:m03 mode:local topic:ejemplo
```

Tags como `session:m03-s54`, `milestone:m03`, `mode:local`, `topic:xxx` **NO** llevan `[[...]]`.
Envolverlos en `[[...]]` cuando no corresponde produce `source-fields-reserved-conflict` en el reverse.

La cadena en `source_fields.tags` debe coincidir byte a byte con lo que produce
`formatTW5Tags(source_tags)`. Si hay duda, derivarla de `source_tags` usando esa regla.

## Flujo por defecto

1. Leer canon y derivados locales.
2. Analizar el cambio necesario.
3. Emitir contrato de sesion en `contratos/`.
4. Escribir directo en `data/out/local/tiddlers_*.jsonl` la memoria semántica-documental propia de la sesión cuando exista.
5. Validar `strict` y `reverse-preflight` antes de considerar la sesión cerrada.

Regla adicional obligatoria:

- el contrato `.md.json` creado o actualizado por la sesión también debe quedar absorbido en canon como nodo de artefacto del repo (`contratos/<session>.md.json`) o actualizar su nodo existente si ya estaba presente
- esta regla aplica a todas las sesiones y no sustituye la familia semántica `#### 🌀 ...`; la complementa

La sesion puede quedar cerrada solo con contrato si no produjo memoria
semántica-documental nueva ni cambió nodos canónicos.

## Flujo extraordinario: proposals legado

Solo cuando el trabajo requiera candidate storage extraordinario o recuperación
manual, el agente puede escribir en `data/out/local/proposals.jsonl`.

En ese caso debe:

1. justificar por qué no corresponde absorción directa inmediata en canon
2. dejar líneas ya canonizadas
3. evitar usar `proposals.jsonl` como bypass del cierre normal
4. validar el lote extraordinario solo si el archivo o batch se usará operativamente

## Flujo gobernado de escritura directa

Toda absorción directa en canon debe:

1. identificar el target exacto en canon
2. justificar el cambio como cierre de sesión o reparación gobernada
3. preservar byte a byte toda linea no objetivo
4. correr:

```bash
cd go/canon
env GOCACHE=/tmp/tdc-go-build go run ./cmd/canon_preflight --mode strict --input ../../data/out/local
```

5. y, si aplica al reverse:

```bash
cd go/canon
env GOCACHE=/tmp/tdc-go-build go run ./cmd/canon_preflight --mode reverse-preflight --input ../../data/out/local
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
- absorber en el canon la memoria estructural propia de la sesión
- y dejar `proposals.jsonl` fuera de la lógica diaria

La sesion no se considera bien cerrada solo por la conversacion. Se considera
bien cerrada cuando existe el contrato `.md.json` y, cuando corresponda, la
absorción directa correcta en `data/out/local/tiddlers_*.jsonl`.
