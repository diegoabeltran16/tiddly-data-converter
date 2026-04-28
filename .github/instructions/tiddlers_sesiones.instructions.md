---
applyTo: "data/sessions/**"
description: >
  Instruccion local-first para producir artefactos de sesion, lineas
  candidatas en formato canon y evidencia de validacion sin escribir
  directamente en el canon final por defecto.
---

## Instruccion: familia de sesion, candidatos canonicos y cierre reversible

Para toda sesion de trabajo en `tiddly-data-converter`, el agente debe cerrar
con la familia minima de artefactos bajo `data/sessions/`:

1. `data/sessions/00_contratos/<session>.md.json`
2. `data/sessions/01_procedencia/<session>.md.json`
3. `data/sessions/02_detalles_de_sesion/<session>.md.json`
4. `data/sessions/03_hipotesis/<session>.md.json`
5. `data/sessions/04_balance_de_sesion/<session>.md.json`
6. `data/sessions/05_propuesta_de_sesion/<session>.md.json`
7. `data/sessions/06_diagnoses/sesion/<session>.md.json`

El diagnostico de sesion es obligatorio. Los diagnosticos especializados
(`canon`, `derivados`, `hipotesis`, `modulo`, `proyecto`, `repositorio`,
`reverse`, `tema`) solo se generan bajo solicitud explicita o cuando la
instruccion de sesion lo requiera.

## Convencion de titulos de sesion

Todo tiddler que sea resultado de sesion debe tener un `title` iniciado por
`#### 🌀`.

Titulos obligatorios para las familias principales:

- procedencia de sesion: `#### 🌀🧾 Procedencia de sesión ## = <session>`;
- detalles/sesion: `#### 🌀 Sesión ## = <session>`;
- hipotesis de sesion: `#### 🌀🧪 Hipótesis de sesión ## = <session>`.

Las demas familias de cierre deben mantener el prefijo `#### 🌀` y declarar
claramente su familia, por ejemplo `#### 🌀 Balance de sesión ## = <session>`.

## Regla central

`data/sessions/` es una zona de entrega, trazabilidad y staging operativo. No es
canon paralelo.

El canon local sigue siendo `data/out/local/tiddlers_*.jsonl`, pero el agente
no debe escribirlo directamente por defecto. Las nuevas lineas deben quedar
como candidatas bajo `data/sessions/` y solo pueden absorberse mediante un proceso
local o manual que valide antes de aplicar.

## Lectura previa obligatoria

Antes de documentar una sesion que toque canon o reverse, leer como minimo:

1. `.github/instructions/sesiones.instructions.md`
2. `esquemas/canon/canon_guarded_session_rules.md`
3. `docs/Informe_Tecnico_de_Tiddler (Esp).md`
4. los shards canonicos pertinentes dentro de `data/out/local/tiddlers_*.jsonl`, si existen y si el objetivo lo requiere
5. las capas derivadas pertinentes cuando ayuden al analisis

Si el trabajo toca una linea existente, leer el shard y el nodo objetivo antes
de proponer admision o reparacion.

## Destinos de escritura permitidos para agentes

### Siempre permitido

- `data/sessions/**`
- documentacion y scripts del repositorio relacionados con el objetivo

### Permitido como staging canonico

- archivos JSONL candidatos bajo `data/sessions/`, con nombre propio de sesion

### Prohibido por defecto

- `data/out/local/tiddlers_*.jsonl`

### Extraordinario

- `data/out/local/proposals.jsonl`

`proposals.jsonl` queda reservado para recuperacion manual o candidate storage
historico. No debe ser la ruta diaria de cierre.

## Lineas candidatas en formato canon

Toda linea candidata debe:

- estar en JSONL valido;
- exponer la forma canonica vigente;
- declarar `session_origin`;
- declarar `artifact_family`;
- declarar `source_path` hacia el archivo fuente bajo `data/sessions/`;
- declarar procedencia suficiente;
- conservar `canonical_status` o equivalente como `candidate_not_admitted`;
- evitar campos reservados por reverse dentro de `source_fields`;
- quedar lista para `strict`, `reverse-preflight` y reverse autoritativo.

Campos canonicos esperados:

- identidad: `schema_version`, `id`, `key`, `title`, `canonical_slug`, `version_id`
- lectura: `content_type`, `modality`, `encoding`, `is_binary`, `is_reference_only`
- semantica: `role_primary`, `tags`, `taxonomy_path`, `semantic_text`, `content`, `raw_payload_ref`, `mime_type`
- contexto: `document_id`, `section_path`, `order_in_document`, `relations`
- procedencia: `source_tags`, `normalized_tags`, `source_fields`, `text`, `source_type`, `source_position`, `created`, `modified`

## Formato obligatorio de `source_fields`

No usar en `source_fields` claves reservadas o derivadas por reverse:

- reservadas: `schema_version`, `key`, `title`, `text`, `type`, `tags`, `created`, `modified`, `source_type`, `source_tags`, `source_fields`, `source_position`, `source_role`
- derivadas: `id`, `canonical_slug`, `version_id`, `content`, `content.plain`, `content_type`, `modality`, `encoding`, `is_binary`, `is_reference_only`, `role_primary`, `roles_secondary`, `taxonomy_path`, `semantic_text`, `normalized_tags`, `raw_payload_ref`, `asset_id`, `mime_type`, `document_id`, `section_path`, `order_in_document`, `relations`

Usar claves no reservadas para trazabilidad de staging, por ejemplo:

- `session_origin`
- `artifact_family`
- `source_path`
- `provenance_ref`
- `canonical_status`

## Formato obligatorio de tags

Cuando una linea candidata llegue al reverse, `source_tags` sera proyectado a
`tags` de TiddlyWiki con la regla de `formatTW5Tags`:

- si el tag contiene espacio, `[` o `]`, se envuelve en `[[...]]`;
- si no contiene esos caracteres, se deja tal cual.

No escribir a mano una clave `tags` dentro de `source_fields` salvo que coincida
exactamente con esa proyeccion; en general, evitarla.

## Flujo de cierre por defecto

1. Leer canon, derivados e instrucciones pertinentes.
2. Analizar el cambio necesario.
3. Emitir la familia minima bajo `data/sessions/`.
4. Emitir lineas candidatas en formato canon si la sesion deja memoria que deba poder entrar al canon.
5. Validar candidatos y/o copia temporal con comandos reales.
6. Registrar en el diagnostico que paso, que no paso y que queda pendiente.

La sesion no queda bien cerrada solo por la conversacion.

## Admision local

La admision canonica ocurre fuera del staging:

1. copiar el canon actual a una ruta temporal;
2. insertar las lineas candidatas en la copia;
3. ejecutar `strict`;
4. ejecutar `reverse-preflight`;
5. ejecutar reverse autoritativo;
6. exigir `Rejected: 0`;
7. ejecutar tests pertinentes;
8. solo entonces aplicar al canon local si el proceso esta autorizado.

Si cualquier compuerta falla, no modificar `data/out/local/tiddlers_*.jsonl`.

## Comandos reales de validacion

```bash
cd /repositorios/tiddly-data-converter/go/canon
env GOCACHE=/tmp/tdc-go-build go run ./cmd/canon_preflight \
  --mode strict \
  --input <canon-temporal-o-jsonl>
```

```bash
cd /repositorios/tiddly-data-converter/go/canon
env GOCACHE=/tmp/tdc-go-build go run ./cmd/canon_preflight \
  --mode reverse-preflight \
  --input <canon-temporal-o-jsonl>
```

```bash
cd /repositorios/tiddly-data-converter/go/bridge
env GOCACHE=/tmp/tdc-go-build go run ./cmd/reverse_tiddlers \
  --html ../../data/in/'tiddly-data-converter (Saved).html' \
  --canon <canon-temporal> \
  --out-html /tmp/<session>.reverse.html \
  --report /tmp/<session>.reverse-report.json \
  --mode authoritative-upsert
```

## Regla de foco

El objetivo de la sesion no es nutrir el canon con escritura libre. El objetivo
es producir memoria operativa trazable en `data/sessions/`, dejar candidatos
canonicos reversibles cuando correspondan y documentar evidencia suficiente
para que un proceso local decida si puede absorberlos al canon.
