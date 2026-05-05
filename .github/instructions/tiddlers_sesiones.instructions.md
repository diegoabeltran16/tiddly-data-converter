---
applyTo: "data/out/local/sessions/**"
description: >
  Instruccion local-first para producir artefactos de sesion, lineas
  candidatas en formato canon y evidencia de validacion sin escribir
  directamente en el canon final por defecto.
---

## Instruccion: familia de sesion, candidatos canonicos y cierre reversible

Para toda sesion de trabajo en `tiddly-data-converter`, el agente debe cerrar
con la familia minima de artefactos bajo `data/out/local/sessions/`:

1. `data/out/local/sessions/00_contratos/<session>.md.json`
2. `data/out/local/sessions/01_procedencia/<session>.md.json`
3. `data/out/local/sessions/02_detalles_de_sesion/<session>.md.json`
4. `data/out/local/sessions/03_hipotesis/<session>.md.json`
5. `data/out/local/sessions/04_balance_de_sesion/<session>.md.json`
6. `data/out/local/sessions/05_propuesta_de_sesion/<session>.md.json`
7. `data/out/local/sessions/06_diagnoses/sesion/<session>.md.json`

El diagnostico de sesion es obligatorio. Los diagnosticos especializados
(`canon`, `derivados`, `hipotesis`, `modulo`, `proyecto`, `repositorio`,
`reverse`, `tema`) solo se generan bajo solicitud explicita o cuando la
instruccion de sesion lo requiera.

## Gobernanza de rutas de artefactos de sesion

La unica raiz activa para artefactos de sesion es:

```
data/out/local/sessions/
```

Rutas clasificadas:

| Ruta | Clasificacion | Politica |
|---|---|---|
| `data/out/local/sessions/` | **Activa** | Raiz gobernada para todos los artefactos de sesion |
| `data/sessions/` | **Prohibida / Legacy** | Gitignoreada; no escribir nuevos entregables ahi |
| `data/out/sessions/` | **Prohibida / Typo** | No existe; error tipografico historico |

Los logs auxiliares de diagnostico tambien van bajo:

```
data/out/local/sessions/06_diagnoses/sesion/
```

Las lineas candidatas y artefactos de sesion deben permanecer bajo
`data/out/local/sessions/` hasta pasar validacion local, `strict`,
`reverse-preflight` y reverse sin rechazos.

## Convencion de titulos de sesion

Todo tiddler que sea resultado de sesion debe tener un `title` iniciado por
`#### 🌀`.

Titulos obligatorios para las familias principales:

- contrato de sesion: `#### 🌀 Contrato de sesión <NN> = <slug>`;
- procedencia de sesion: `#### 🌀🧾 Procedencia de sesión <NN> = <slug>`;
- detalles/sesion: `#### 🌀 Sesión <NN> = <slug>`;
- hipotesis de sesion: `#### 🌀🧪 Hipótesis de sesión <NN> = <slug>`;
- balance de sesion: `#### 🌀 Balance de sesión <NN> = <slug>`;
- propuesta de sesion: `#### 🌀 Propuesta de sesión <NN> = <slug>`;
- diagnostico de sesion: `#### 🌀 Diagnóstico de sesión <NN> = <slug>`.

`<NN>` corresponde al numero de sesion extraido de `mXX-sNN-...`; `<slug>` es
el resto del identificador sin el prefijo `mXX-sNN-` y sin `session-` cuando
aparezca como prefijo operativo.

### Diagnósticos de ciclo de sesiones

Los diagnósticos de ciclo son sesiones diagnósticas propias.
No forman parte del paquete obligatorio de entregables de toda sesión.

Una sesión normal produce sus 7 entregables ordinarios.

Una sesión diagnóstica de microciclo produce:
- sus 7 entregables normales de sesión;
- el diagnóstico de microciclo correspondiente.

Una sesión diagnóstica de mesociclo produce:
- sus 7 entregables normales de sesión;
- el diagnóstico de mesociclo correspondiente.

#### Clasificación de tipos de sesión

El sistema distingue seis tipos de sesión relevantes para la gobernanza de
artefactos:

1. **Diagnóstico puro**.
   Lee evidencia y produce el diagnóstico solicitado.
   No toca código, tests ni instrucciones.
   Si descubre que necesita modificar infraestructura para poder producir el
   diagnóstico, debe detenerse y reportar el bloqueo.

2. **Infraestructura diagnóstica**.
   Ajusta instrucciones, scripts o tests para mejorar el sistema diagnóstico.
   Debe producir los 7 entregables normales de sesión, además de cualquier
   diagnóstico explícitamente solicitado.

3. **Sesión mixta**.
   Combina ajuste técnico limitado con un diagnóstico mayor.
   Debe producir los 7 entregables normales de sesión y declarar qué parte fue
   infraestructura y qué parte fue diagnóstico.

4. **Sesión práctica/desarrollo**.
   Implementa o corrige superficies del sistema: código, tests, CI, canon,
   scripts, documentación operativa o integraciones.
   Debe producir los 7 entregables normales de sesión.

5. **Sesión teórica/analítica**.
   Produce análisis, contratos, decisiones, hipótesis o diseño sin necesidad de
   tocar código.
   Debe producir entregables normales cuando cambia memoria, procedencia o
   dirección del proyecto.

6. **Híbrida/transicional**.
   Solo es aceptable mientras el flujo diagnóstico se está estabilizando.
   Debe quedar marcada como excepción y explicar por qué no pudo separarse en
   diagnóstico puro e infraestructura diagnóstica.

Regla madura:

Cuando el sistema diagnóstico ya está disponible, una sesión diagnóstica pura
no debe tocar código. Las correcciones de scripts, tests o instrucciones deben
abrirse como sesión de infraestructura diagnóstica.

#### Gobernanza de procedencia diagnóstica

Los diagnósticos deben declarar de dónde sale cada conclusión importante y no
confundir ausencia de staging con ausencia histórica.

Jerarquía de lectura:

1. **Diagnósticos previos específicos**.
   Para mesociclos, leer primero los microdiagnósticos ya producidos.

2. **Sessions local**.
   Leer `data/out/local/sessions/` cuando exista evidencia reciente o staging
   operativo.

3. **Canon local**.
   Leer `data/out/local/tiddlers_*.jsonl` cuando `sessions/` haya sido depurado
   o para validar completitud canónica.

4. **Auditorías y derivados**.
   Leer `data/out/local/audit/`, `data/out/local/enriched/` o
   `data/out/local/ai/` solo si ayudan a validar una hipótesis concreta.

5. **Repositorio**.
   Leer código, tests, workflows e instrucciones para validar el estado
   arquitectónico actual.

6. **Espejo remoto**.
   El remoto/OneDrive es superficie de sincronización y paridad. No es fuente
   de verdad superior al canon local salvo que una sesión futura lo declare de
   forma explícita.

Completitud diagnóstica:

- **Completitud en staging local**: `presente`, `parcial`, `ausente` o
  `depurado`.
- **Completitud canónica**: `admitida completa`, `admitida parcial` o
  `no encontrada`.
- **Fuente usada**: `microdiagnóstico`, `sessions`, `canon`, `auditoría`,
  `repositorio` o `remoto dry-run`.

Regla:

Depurar `sessions/` es válido cuando el canon local ya absorbió la evidencia.
El diagnóstico debe registrar esa diferencia en vez de interpretar la ausencia
local como pérdida automática de memoria.

#### Diagnóstico de microciclo

Uso:

Diagnóstico agregado de 10 sesiones recientes o consecutivas.

Ruta oficial:

```txt
data/out/local/sessions/06_diagnoses/micro-ciclo/
```

Formato sugerido de archivo:

```txt
m04-micro-ciclo-s085-s094-diagnostico.md.json
```

Formato obligatorio de título:

```txt
#### 🌀 Diagnóstico de microciclo = sesiones S85-S94
#### 🌀 Diagnóstico de microciclo = sesiones S65-S74
```

#### Diagnóstico de mesociclo

Uso:

Diagnóstico agregado de 3 microciclos.

Ruta oficial:

```txt
data/out/local/sessions/06_diagnoses/meso-ciclo/
```

Formato sugerido de archivo:

```txt
m04-meso-ciclo-s064-s094-diagnostico.md.json
```

Formato obligatorio de título:

```txt
#### 🌀 Diagnóstico de mesociclo = microciclos S64-S94
#### 🌀 Diagnóstico de mesociclo = microciclos S65-S94
```

Regla:

El mesociclo debe consumir diagnósticos de microciclo ya existentes.
No debe releer 30 sesiones crudas si los 3 microciclos requeridos ya existen.

## Regla central

`data/out/local/sessions/` es una zona de entrega, trazabilidad y staging operativo. No es
canon paralelo.

El canon local sigue siendo `data/out/local/tiddlers_*.jsonl`, pero el agente
no debe escribirlo directamente por defecto. Las nuevas lineas deben quedar
como candidatas bajo `data/out/local/sessions/` y solo pueden absorberse mediante un proceso
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

- `data/out/local/sessions/**`
- documentacion y scripts del repositorio relacionados con el objetivo

### Permitido como staging canonico

- archivos JSONL candidatos bajo `data/out/local/sessions/`, con nombre propio de sesion

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
- declarar `source_path` hacia el archivo fuente bajo `data/out/local/sessions/`;
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
3. Emitir la familia minima bajo `data/out/local/sessions/`.
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
es producir memoria operativa trazable en `data/out/local/sessions/`, dejar candidatos
canonicos reversibles cuando correspondan y documentar evidencia suficiente
para que un proceso local decida si puede absorberlos al canon.
