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

El diagnóstico de sesión (tipo `sesion`) es el único diagnóstico obligatorio
del paquete. Los diagnósticos especializados (`canon`, `derivados`,
`hipotesis`, `modulo`, `proyecto`, `repositorio`, `reverse`, `tema`) son
opcionales: solo se generan bajo solicitud explícita del operador en el prompt
de sesión. No se generan automáticamente bajo ninguna otra condición.

## Gobernanza de rutas de artefactos de sesion

### Raiz activa de artefactos

La unica raiz activa para artefactos de sesion es:

```
data/out/local/sessions/
```

### Rutas clasificadas

| Ruta | Clasificacion | Politica |
|---|---|---|
| `data/out/local/sessions/` | **Activa** | Raiz gobernada para todos los artefactos de sesion |
| `data/sessions/` | **Prohibida / Legacy** | Gitignoreada; no escribir nuevos entregables ahi |
| `data/out/sessions/` | **Prohibida / Typo** | No existe; error tipografico historico |

### Artefactos de diagnóstico de sesión

Los diagnósticos de sesión (familia `sesion`) van bajo:

```
data/out/local/sessions/06_diagnoses/sesion/
```

### Politica de permanencia y validacion

Las lineas candidatas y artefactos de sesion deben permanecer bajo
`data/out/local/sessions/` hasta pasar, en este orden, validacion local,
`strict`, `reverse-preflight` y reverse sin rechazos. Si una linea candidata
no pasa alguna de estas validaciones, el agente debe registrar el error en el
diagnostico y detener el proceso hasta que se resuelva.

## Convencion de titulos de sesion

Todo tiddler que sea resultado de sesion debe tener un `title` iniciado por
`#### 🌀`.

### Regla de numeración universal — formato `XXXX`

**Todos** los números de sesión, rango o secuencia que aparezcan en un título
de tiddler deben usar exactamente **4 dígitos con ceros a la izquierda**:

```
n → f'{int(n):04d}'   # Python
```

Ejemplos:
- Sesión 1   → `0001`
- Sesión 97  → `0097`
- Sesión 124 → `0124`
- Temático 7 → `0007`
- Temático 33→ `0033`

**Prohibiciones absolutas** (nunca usar en títulos de tiddlers):

| Forma incorrecta | Forma correcta | Motivo |
|---|---|---|
| `S0124` | `0124` | El prefijo `S` no es parte del título canónico |
| `S97` | `0097` | Prefijo `S` + padding insuficiente |
| `S85-S94` | `0085-0094` | Prefijo `S` en rangos de sesión |
| `011`, `033` | `0011`, `0033` | Padding de 3 dígitos en lugar de 4 |
| `01`, `09` | `0001`, `0009` | Padding de 2 dígitos en lugar de 4 |
| `(siguiente tras S0115)` | _(eliminar)_ | Texto extra no canónico en el título |
| `0116 (siguiente tras...)` | `0116` | Paréntesis no canónicos |

El prefijo `S` es **solo** para uso en código, rutas de archivo o texto libre
de narrativa. **Nunca aparece dentro del campo `title` de un tiddler.**

> **Aclaración de alcance**: esta prohibición aplica exclusivamente al contenido
> del campo `title`. El campo JSON `session` de los artefactos `.md.json` **sí**
> usa `"S0129"` como identificador de código (ej. `"session": "S0129"`); eso es
> correcto y no viola esta regla.

### Títulos obligatorios por familia de sesión

`<NNNN>` = número de sesión formateado como `f'{n:04d}'`.

> Si el número de sesión no puede determinarse antes de producir los artefactos,
> el agente debe detenerse y solicitar al operador el número de sesión antes de
> generar ningún artefacto. No usar placeholders como `0000` o `XXXX` en
> artefactos reales.

- contrato de sesion: `#### 🌀 Contrato de sesión <NNNN> = <slug>`;
- procedencia de sesion: `#### 🌀🧾 Procedencia de sesión <NNNN> = <slug>`;
- detalles/sesion: `#### 🌀 Sesión <NNNN> = <slug>`;
- hipotesis de sesion: `#### 🌀🧪 Hipótesis de sesión <NNNN> = <slug>`;
- balance de sesion: `#### 🌀 Balance de sesión <NNNN> = <slug>`;
- propuesta de sesion: `#### 🌀 Propuesta de sesión <NNNN> = <slug>`;
- diagnostico de sesion: `#### 🌀 Diagnóstico de sesión <NNNN> = <slug>`.

`<slug>` es la parte restante del identificador tras eliminar el prefijo
`mXX-sNNNN-` y, si está presente inmediatamente después, el prefijo `session-`.
Si ninguno de estos prefijos está presente, el identificador se usa tal cual.
No se elimina ningún otro prefijo.

### Títulos obligatorios para diagnósticos de ciclo

#### Diagnóstico temático

`<XXXX>` = número secuencial del diagnóstico formateado como `f'{n:04d}'`.

```
#### 🌀 Diagnóstico temático <XXXX> = <slug>
```

Ejemplos correctos:
```
#### 🌀 Diagnóstico temático 0001 = alineacion-de-roles-v0
#### 🌀 Diagnóstico temático 0010 = complejidad de scripts críticos y plan de modularización segura
#### 🌀 Diagnóstico temático 0033 = frontera canon/archivo para diagnósticos temáticos y admisión gobernada
```

#### Diagnóstico de microciclo

`<XXXX>` y `<YYYY>` = números de sesión formateados como `f'{n:04d}'`.

```
#### 🌀 Diagnóstico de microciclo = sesiones <XXXX>-<YYYY>
#### 🌀 Diagnóstico de microciclo parcial = sesiones <XXXX>-<YYYY>
```

Ejemplos correctos:
```
#### 🌀 Diagnóstico de microciclo = sesiones 0001-0004
#### 🌀 Diagnóstico de microciclo = sesiones 0085-0094
#### 🌀 Diagnóstico de microciclo = sesiones 0105-0114
#### 🌀 Diagnóstico de microciclo parcial = sesiones 0115-0120
```

#### Diagnóstico de mesociclo

```
#### 🌀 Diagnóstico de mesociclo = microciclos <XXXX>-<YYYY>
```

Ejemplos correctos:
```
#### 🌀 Diagnóstico de mesociclo = microciclos 0005-0034
#### 🌀 Diagnóstico de mesociclo = microciclos 0065-0094
```

#### Diagnóstico de proyecto

```
#### 🌀 Diagnóstico de proyecto = <slug>
```

Si el slug hace referencia a una sesión, el número también debe seguir el
formato `XXXX`:
```
#### 🌀 Diagnóstico de proyecto = estado completo del repositorio post-0097
```

### Diagnósticos de ciclo de sesiones

Los diagnósticos de ciclo son sesiones diagnósticas propias.
No forman parte del paquete obligatorio de entregables de una sesión ordinaria.
Cuando el propósito explícito de la sesión es producir un diagnóstico de ciclo,
ese diagnóstico sí forma parte de sus entregables obligatorios.

Una sesión ordinaria produce sus 7 entregables normales.

Una sesión diagnóstica de microciclo produce:
- sus 7 entregables normales de sesión;
- el diagnóstico de microciclo correspondiente.

Una sesión diagnóstica de mesociclo produce:
- sus 7 entregables normales de sesión;
- el diagnóstico de mesociclo correspondiente.

#### Clasificación de tipos de sesión

El sistema distingue seis tipos de sesión relevantes para la gobernanza de
artefactos:

| Tipo | Toca código | Entregables obligatorios | Observación |
|---|---|---|---|
| Diagnóstico puro | No | 7 normales | Se detiene si requiere infraestructura |
| Infraestructura diagnóstica | Sí | 7 normales + diagnósticos explícitos | — |
| Sesión mixta | Limitado | 7 normales + diagnóstico mayor | Declarar qué parte es cada cosa |
| Sesión práctica/desarrollo | Sí | 7 normales | — |
| Sesión teórica/analítica | No | 7 normales | Ver descripción |
| Híbrida/transicional | Según caso | 7 normales + justificación | Excepción temporal |

#### Procedimiento para determinar entregables obligatorios

1. ¿Es una sesión diagnóstica de ciclo (microciclo o mesociclo)?
   → Sí: produce los 7 entregables normales **más** el diagnóstico de ciclo correspondiente.
   → No: continuar.
2. ¿Se solicitó explícitamente un diagnóstico de ciclo u otro diagnóstico especializado?
   → Sí: añadirlo a los 7 entregables normales.
   → No: continuar.
3. Producir los 7 entregables normales de sesión. El diagnóstico de sesión (tipo
   `sesion`) es siempre obligatorio.

Descripción detallada de cada tipo:

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
   Siempre produce los 7 entregables normales de sesión. El contenido sustantivo
   (contratos, hipótesis, propuesta) es especialmente relevante cuando la sesión:
   (a) añade o modifica algún tiddler en sessions/00–05, (b) cambia una entrada
   de `source_fields` que afecta la procedencia, o (c) introduce una nueva
   decisión arquitectónica documentada en `03_hipotesis` o `05_propuesta_de_sesion`.

6. **Híbrida/transicional**.
   Este tipo de sesión solo es válido si el operador lo declara explícitamente
   en el prompt, indicando la razón por la que no puede separarse en diagnóstico
   puro e infraestructura diagnóstica.
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

Formato sugerido de archivo (números de sesión con 4 dígitos, sin prefijo `S`):

```txt
m04-micro-ciclo-0085-0094-diagnostico.md.json
```

Formato obligatorio de título (4 dígitos, sin prefijo `S`):

```txt
#### 🌀 Diagnóstico de microciclo = sesiones 0085-0094
#### 🌀 Diagnóstico de microciclo = sesiones 0065-0074
```

#### Diagnóstico de mesociclo

Uso:

Diagnóstico agregado de 3 microciclos.

Ruta oficial:

```txt
data/out/local/sessions/06_diagnoses/meso-ciclo/
```

Formato sugerido de archivo (números de sesión con 4 dígitos, sin prefijo `S`):

```txt
m04-meso-ciclo-0064-0094-diagnostico.md.json
```

Formato obligatorio de título (4 dígitos, sin prefijo `S`):

```txt
#### 🌀 Diagnóstico de mesociclo = microciclos 0005-0034
#### 🌀 Diagnóstico de mesociclo = microciclos 0065-0094
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

Claves permitidas en `source_fields`: `session_origin`, `artifact_family`,
`source_path`, `provenance_ref`, `canonical_status` y cualquier clave de
seguimiento específica del proyecto con prefijo `x_`. Toda otra clave es
forbidden.

## Formato obligatorio de tags

Cuando una linea candidata llegue al reverse, `source_tags` sera proyectado a
`tags` de TiddlyWiki con la regla de `formatTW5Tags`:

- si el tag contiene espacio, `[` o `]`, se envuelve en `[[...]]`;
- si no contiene esos caracteres, se deja tal cual.

No escribir a mano una clave `tags` dentro de `source_fields` salvo que coincida
exactamente con esa proyeccion; en general, evitarla.

## Schema canónico de artefactos `.md.json`

Todo archivo `.md.json` bajo `data/out/local/sessions/` debe seguir este schema estricto.

### Herramienta oficial de autoría

Usar **siempre** el generador canónico para producir los 7 entregables de sesión:

```bash
python3 src/python_scripts/generate_session_deliverables.py generate \
  --session-id mXX-sNNNN \
  --topic <slug-del-tema> \
  --sessions-dir data/out/local/sessions/
```

No escribir los archivos a mano. El generador garantiza que todos los campos
obligatorios existen, que los campos prohibidos están ausentes y que los
timestamps están en el formato correcto.

Si los archivos ya existen (p. ej. se regenera la sesión), añadir `--force`
para sobreescribirlos:

```bash
python3 src/python_scripts/generate_session_deliverables.py generate \
  --session-id mXX-sNNNN \
  --topic <slug-del-tema> \
  --sessions-dir data/out/local/sessions/ \
  --force
```

Si el generador falla (directorio incorrecto, dependencia faltante, formato
de `session-id` inválido): corregir el error reportado en stderr, no escribir
los archivos a mano. Si el fallo es irrecuperable, registrarlo en el diagnóstico
y detener el cierre.

### Campos obligatorios

| Campo | Formato | Ejemplo |
|---|---|---|
| `title` | `#### 🌀 [emoji] <Familia> de sesión <NNNN> = <slug>` | `#### 🌀 Contrato de sesión 0128 = normalizacion-titulos` |
| `type` | Tipo MIME (debe contener `/`) | `"text/markdown"` |
| `created` | 17 dígitos TiddlyWiki: `YYYYMMDDHHmmSSmmm` | `"20260516000000000"` |
| `modified` | 17 dígitos TiddlyWiki: `YYYYMMDDHHmmSSmmm` | `"20260516000000000"` |
| `session_id` | `mXX-sNNNN` | `"m04-s0128"` |
| `module` | `mXX` | `"m04"` |
| `session` | `SNNNN` (S mayúscula + 4 dígitos) — identificador de código, **no** es el campo `title` | `"S0128"` |
| `status` | `"delivered"` | `"delivered"` |
| `canonical_slug` | kebab-case | `"m04-s0128-contrato-normalizacion-titulos"` |
| `tags` | array de strings | `["sesion", "contrato", "m04", "s0128"]` |
| `text` | string de contenido | `"Contenido del artefacto..."` |

### Campos prohibidos

Los siguientes campos **nunca** deben aparecer en un artefacto `.md.json`:

| Campo prohibido | Motivo | Campo correcto |
|---|---|---|
| `created_at` | Formato ISO, no TiddlyWiki | `created` (17 dígitos) |
| `updated_at` | Formato ISO, no TiddlyWiki | `modified` (17 dígitos) |
| `artifact_family` | Campo interno de candidatos canon, no de artefactos fuente | — |
| `role_primary` | Campo derivado del canon | — |
| `source_type` | Campo derivado de la admisión; no pertenece al artefacto fuente | — |

### Reglas de formato

- **`type`**: debe ser un tipo MIME válido (contiene `/`). Los valores `"contrato"`,
  `"procedencia"`, `"detalles"`, `"hipotesis"`, `"balance"`, `"propuesta"`,
  `"diagnostico"` son **inválidos** y causarán que `reverse_tiddlers` descarte
  silenciosamente el artefacto del HTML generado.
- **`created` / `modified`**: deben tener exactamente 17 dígitos en formato
  TiddlyWiki `YYYYMMDDHHmmSSmmm`. El formato ISO `"2026-05-16T00:00:00Z"` es
  **inválido** y será rechazado como `schema_invalid`.
- **`title`**: el número de sesión no debe llevar prefijo `S`. `"sesión S0128"` es
  inválido; `"sesión 0128"` es correcto.
- **Formato raíz**: el archivo debe ser un objeto JSON `{...}`, **no** un array
  `[{...}]`. El formato de array es el formato de exportación TiddlyWiki, no el
  formato canónico de artefacto fuente.

### Clasificación `schema_invalid`

`session_sync scan` ejecuta validación de schema en cada archivo `.md.json` antes
de construir el candidato. Un archivo con errores de schema recibe la clasificación
`schema_invalid` y es excluido del candidato (no entra al canon). El mensaje de error
enumera cada campo problemático. Esta es la compuerta que impide que artefactos
malformados contaminen el canon.

### Ejemplo de salida canónica

Invocación para la sesión hipotética `m04-s0129`:

```bash
python3 src/python_scripts/generate_session_deliverables.py generate \
  --session-id m04-s0129 \
  --topic "ejemplo de entregables canónicos" \
  --sessions-dir data/out/local/sessions/
```

Archivos producidos (uno por familia, orden de rutas):

```
data/out/local/sessions/
├── 00_contratos/
│   └── m04-s0129-contrato-ejemplo-de-entregables-canonicos.md.json
├── 01_procedencia/
│   └── m04-s0129-procedencia-ejemplo-de-entregables-canonicos.md.json
├── 02_detalles_de_sesion/
│   └── m04-s0129-ejemplo-de-entregables-canonicos.md.json
├── 03_hipotesis/
│   └── m04-s0129-hipotesis-ejemplo-de-entregables-canonicos.md.json
├── 04_balance_de_sesion/
│   └── m04-s0129-balance-ejemplo-de-entregables-canonicos.md.json
├── 05_propuesta_de_sesion/
│   └── m04-s0129-propuesta-ejemplo-de-entregables-canonicos.md.json
└── 06_diagnoses/sesion/
    └── diagnostico-sesion-s0129-ejemplo-de-entregables-canonicos.md.json
```

Contenido canónico del contrato (todos los demás son análogos):

```json
{
  "title": "#### 🌀 Contrato de sesión 0129 = ejemplo de entregables canónicos",
  "type": "text/markdown",
  "created": "20260527141751601",
  "modified": "20260527141751601",
  "session_id": "m04-s0129",
  "module": "m04",
  "session": "S0129",
  "status": "delivered",
  "canonical_slug": "m04-s0129-contrato-ejemplo-de-entregables-canonicos",
  "tags": ["sesion", "contrato", "m04", "s0129"],
  "text": "<!-- el agente rellena solo este campo -->"
}
```

Variaciones por familia:

| Familia | `title` | nombre de archivo |
|---|---|---|
| contrato | `#### 🌀 Contrato de sesión 0129 = …` | `{sid}-contrato-{slug}.md.json` |
| procedencia | `#### 🌀🧾 Procedencia de sesión 0129 = …` | `{sid}-procedencia-{slug}.md.json` |
| detalles | `#### 🌀 Sesión 0129 = …` | `{sid}-{slug}.md.json` |
| hipótesis | `#### 🌀🧪 Hipótesis de sesión 0129 = …` | `{sid}-hipotesis-{slug}.md.json` |
| balance | `#### 🌀 Balance de sesión 0129 = …` | `{sid}-balance-{slug}.md.json` |
| propuesta | `#### 🌀 Propuesta de sesión 0129 = …` | `{sid}-propuesta-{slug}.md.json` |
| diagnóstico | `#### 🌀 Diagnóstico de sesión 0129 = …` | `diagnostico-sesion-s0129-{slug}.md.json` |

Notas:
- `detalles` no incluye "detalles" en el nombre del archivo.
- `diagnostico` no lleva el módulo (`m04-`) en el nombre del archivo; sí en `session_id`.
- `canonical_slug` coincide exactamente con el nombre del archivo **sin** `.md.json`.
- El agente solo modifica el campo `"text"`. Todos los demás campos se dejan como los generó el script.

### Validación obligatoria antes de `session_sync scan`

Antes de ejecutar `session_sync scan`, validar todos los artefactos:

```bash
python3 src/python_scripts/generate_session_deliverables.py validate-dir \
  data/out/local/sessions/
```

Si hay archivos con errores de schema, corregirlos antes de continuar. La herramienta
lista cada error por campo y archivo.

Ante errores `schema_invalid` en archivos existentes:
- Si el archivo fue generado por el script → usar `--force` para regenerar.
- Si fue editado manualmente → editar el campo incorrecto directamente.
- Si el error es `forbidden field present` → eliminar el campo del JSON.
- Si el error es `invalid TiddlyWiki timestamp` → convertir a 17 dígitos:
  `"2026-05-27T14:00:00Z"` → `"20260527140000000"`.
- Si el error es `not a MIME type` en `"type"` → cambiar a `"text/markdown"`.

No continuar al paso de `session_sync scan` hasta que `validate-dir` reporte
`✓ All N file(s) valid.`

---

## Flujo de cierre por defecto

1. Leer canon, derivados e instrucciones pertinentes.
2. Analizar el cambio necesario.
3. Emitir la familia mínima usando el generador canónico:
   ```bash
   python3 src/python_scripts/generate_session_deliverables.py generate \
     --session-id mXX-sNNNN \
     --topic <slug-del-tema> \
     --sessions-dir data/out/local/sessions/
   ```
4. Validar el schema de todos los artefactos emitidos:
   ```bash
   python3 src/python_scripts/generate_session_deliverables.py validate-dir \
     data/out/local/sessions/
   ```
   Corregir cualquier error `schema_invalid` antes de continuar.
5. Emitir lineas candidatas en formato canon si la sesion deja memoria que deba poder entrar al canon.
6. Validar candidatos y/o copia temporal con comandos reales.
7. Registrar en el diagnostico que paso, que no paso y que queda pendiente.

La sesion no queda bien cerrada solo por la conversacion.

El flujo de cierre (pasos 1–7) produce el staging. La admisión local es un
proceso separado, ejecutado posteriormente por el operador. El agente nunca
ejecutará la admisión local de forma autónoma.

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

### Conflictos entre candidatos

Si dos sesiones producen candidatos con el mismo `id` o `key`, el proceso de
admisión debe rechazar ambos y requerir resolución manual. El agente debe
declarar el conflicto en `04_balance_de_sesion` cuando lo detecte durante la
sesión actual.

## Comandos reales de validacion

```bash
cd /repositorios/tiddly-data-converter/src/go/canon
env GOCACHE=/tmp/tdc-go-build go run ./cmd/canon_preflight \
  --mode strict \
  --input <canon-temporal-o-jsonl>
```

```bash
cd /repositorios/tiddly-data-converter/src/go/canon
env GOCACHE=/tmp/tdc-go-build go run ./cmd/canon_preflight \
  --mode reverse-preflight \
  --input <canon-temporal-o-jsonl>
```

```bash
cd /repositorios/tiddly-data-converter/src/go/bridge
env GOCACHE=/tmp/tdc-go-build go run ./cmd/reverse_tiddlers \
  --html ../../../data/in/'tiddly-data-converter (Saved).html' \
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

---

## Gobernanza de diagnósticos no sesionales

### Diferencia entre sesión normal y diagnóstico no sesional

| Tipo | Patrón de nombre | Destino | Llega al canon |
|---|---|---|---|
| Sesión normal | `mXX-sNNNN-slug.md.json` | `data/out/local/sessions/00_contratos/` … `05_propuesta_de_sesion/` | Sí, via admission gate |
| Diagnóstico no sesional | Ver patrones por familia | `data/out/local/sessions/06_diagnoses/<familia>/` | No directamente |

Los diagnósticos no sesionales son artefactos de análisis del ciclo de trabajo.
No son tiddlers canon. Viven en `06_diagnoses/` y se sincronizan a OneDrive
via publicación puntual o, en mantenimiento controlado, via mirror completo.

### Familias válidas y nombres esperados

Todos los números en nombres de archivo también usan 4 dígitos sin prefijo `S`.

| Familia | Subfolder | Patrón de nombre | Ejemplo |
|---|---|---|---|
| `tema` | `06_diagnoses/tema/` | `diagnostico-tematico-XXXX-slug.md.json` | `diagnostico-tematico-0008-chunks-ai.md.json` |
| `micro_ciclo` | `06_diagnoses/micro-ciclo/` | `mXX-micro-ciclo-XXXX-YYYY-diagnostico.md.json` | `m04-micro-ciclo-0085-0094-diagnostico.md.json` |
| `meso_ciclo` | `06_diagnoses/meso-ciclo/` | `mXX-meso-ciclo-XXXX-YYYY-diagnostico.md.json` | `m04-meso-ciclo-0065-0094-diagnostico.md.json` |
| `proyecto` | `06_diagnoses/proyecto/` | `diagnostico-proyecto-slug.md.json` o `mXX-diagnostico-proyecto-slug.md.json` | `m04-diagnostico-proyecto-estado-post-0097.md.json` |
| `sesion` | `06_diagnoses/sesion/` | `diagnostico-sesion-sNNNN-slug.md.json` | `diagnostico-sesion-s0124-normalizacion-titulos.md.json` |

Solo estas cinco familias son válidas. Cualquier otro subdirectorio bajo `06_diagnoses/`
es inválido y debe rechazarse.

La extensión obligatoria es `.md.json`. Archivos con extensión `.json`, `.md` o `.txt` son rechazados.

### Títulos por familia de diagnóstico no sesional

Formato canónico de título para cada familia. En todos los casos los números
siguen la regla universal: 4 dígitos, sin prefijo `S`.

| Familia | Patrón de título canónico |
|---|---|
| `tema` | `#### 🌀 Diagnóstico temático XXXX = <slug>` |
| `micro_ciclo` | `#### 🌀 Diagnóstico de microciclo = sesiones XXXX-YYYY` |
| `micro_ciclo` (parcial) | `#### 🌀 Diagnóstico de microciclo parcial = sesiones XXXX-YYYY` |
| `meso_ciclo` | `#### 🌀 Diagnóstico de mesociclo = microciclos XXXX-YYYY` |
| `proyecto` | `#### 🌀 Diagnóstico de proyecto = <slug>` |
| `sesion` | `#### 🌀 Diagnóstico de sesión NNNN = <slug>` |

Donde `XXXX` y `YYYY` son números de 4 dígitos obtenidos con `f'{int(n):04d}'`.

**No agregar texto entre el número y el `=`** como `(siguiente tras ...)`,
`(post-sesión ...)` u otras anotaciones. El campo `text` del tiddler es el
lugar para esa información, no el `title`.

### Cómo llega un diagnóstico a OneDrive

```
1. El agente produce el diagnóstico local:
   data/out/local/sessions/06_diagnoses/<familia>/<nombre>.md.json

2. La publicación puntual lo envía a OneDrive (requiere dry_run=false):
   remote_publish_diagnostic.py → OneDrive approot:/tiddly-data-converter/sessions/06_diagnoses/<familia>/

3. Para traer un diagnóstico remoto al local (pull):
   El agente remoto deposita el archivo en OneDrive _remote_outbox/sessions/
   remote_pull_sessions.py lo baja a data/tmp/remote_inbox/
   El operador mueve manualmente al subfolder correcto de 06_diagnoses/
```

**Crear un archivo en el runner remoto NO equivale automáticamente a verlo en OneDrive.**
El workflow de publicación puntual debe ejecutarse con `dry_run=false` para que
los archivos lleguen. El mirror completo (`remote_mirror_out_local.py`) no debe
ser la ruta normal para diagnósticos no sesionales producidos en un workspace
remoto que puede tener `data/out/local/` vacío o incompleto.

Equivalencia obligatoria:

```txt
Local:
data/out/local/sessions/06_diagnoses/tema/

OneDrive:
sessions/06_diagnoses/tema/
```

En OneDrive no debe esperarse `data/out/local/`; esa raíz solo existe como
origen local gitignoreado.

### SYNC_DRY_RUN y dry_run

Cuando `SYNC_DRY_RUN=true` (valor por defecto):
- El mirror simula las operaciones pero no escribe en OneDrive.
- El pull no puede autenticar sin credenciales, por lo que solo muestra la política.
- Ningún diagnóstico llega a OneDrive por mirror completo.

Para publicación diagnóstica puntual real, el operador debe ejecutar
`remote_publish_diagnostic.yml` con input `dry_run=false`. Para mirror completo
real, el operador debe ejecutar `remote_mirror_out_local.yml` con
`SYNC_DRY_RUN=false` y confirmación explícita. **No cambiar estos valores por
defecto en el repositorio.**

### Cómo verificar que un diagnóstico remoto llegó realmente

```bash
# Verificar en el inbox local después de un pull real:
ls data/tmp/remote_inbox/

# Verificar en OneDrive después de una publicación puntual real:
# Revisar via Microsoft Graph Explorer o el cliente OneDrive sincronizado.
```

### Publicación puntual segura

Ejemplo dry-run:

```bash
src/python_scripts/remote_publish_diagnostic.py \
  --local-file data/out/local/sessions/06_diagnoses/tema/diagnostico-tematico-0008-chunks-ai-estructurados-relacion-propagada-a-chunks.md.json \
  --remote-relative-path sessions/06_diagnoses/tema/diagnostico-tematico-0008-chunks-ai-estructurados-relacion-propagada-a-chunks.md.json \
  --dry-run
```

Ejemplo live:

```bash
src/python_scripts/remote_publish_diagnostic.py \
  --local-file data/out/local/sessions/06_diagnoses/tema/diagnostico-tematico-0008-chunks-ai-estructurados-relacion-propagada-a-chunks.md.json \
  --remote-relative-path sessions/06_diagnoses/tema/diagnostico-tematico-0008-chunks-ai-estructurados-relacion-propagada-a-chunks.md.json
```

Este flujo usa Microsoft Graph, `ONEDRIVE_ROOT_MODE=approot`,
`ONEDRIVE_PROJECT_ROOT_NAME=tiddly-data-converter`, crea carpetas faltantes
cuando `REMOTE_CREATE_MISSING_DIRS=true`, respeta
`REMOTE_CONFLICT_BEHAVIOR=replace|skip`, y nunca borra archivos remotos.

### Gobernanza de rutas

- **Permitida:** `data/out/local/sessions/06_diagnoses/<familia>/`
- **Prohibida:** cualquier ruta fuera de esa raíz
- **Prohibida:** `data/sessions/`, `data/out/sessions/`, `sessions/` en raíz
- **Rechazada:** ruta con `..` (path traversal)
- **Rechazada:** ruta absoluta

La lógica centralizada está en `src/python_scripts/diagnostic_governance.py`.
El allowlist del pull está en `src/python_scripts/remote_pull_sessions.py::_is_allowed_outbox_file`.
