---
applyTo: "contratos/**"
description: >
  Instrucción determinista para la generación e inserción en canon de los 3 nodos
  obligatorios de sesión (Procedencia, Hipótesis, Sesión) en los shards JSONL
  de out/tiddlers_*.jsonl. Se activa cuando el agente cierra una sesión con contrato.
  Flujo vigente desde S44: los nodos de sesión van directamente al canon reversible.
  PROHIBIDO crear archivos en docs/tiddlers_de_sesiones/ (ruta obsoleta).
---

## Instrucción: Inserción de nodos de sesión en canon

Para toda sesión de trabajo en `tiddly-data-converter`, el agente debe generar e insertar en los shards canónicos (`out/tiddlers_*.jsonl`) exactamente tres nodos JSONL: **Procedencia**, **Hipótesis** y **Sesión**, en ese orden de elaboración.

Esta instrucción es determinista y no negociable. No puede omitirse, acortarse ni sustituirse por prose libre o resúmenes conversacionales.

**PROHIBICIÓN ABSOLUTA:** No crear archivos en `docs/tiddlers_de_sesiones/`. Esa ruta es obsoleta desde S44. El flujo de cierre activo es sincronización directa en el canon.

---

### Lectura previa obligatoria — regla determinista

Antes de generar cualquier nodo de sesión, el agente **debe leer**:

1. Los shards canónicos `out/tiddlers_2.jsonl`, `out/tiddlers_3.jsonl` y `out/tiddlers_4.jsonl` para localizar los nodos de sesión más recientes y entender el patrón de naming, tags, relaciones y profundidad de contenido real del repositorio.
2. El archivo `docs/Informe_Tecnico_de_Tiddler (Esp).md` para respetar el modelo epistemológico del sistema: distinción entre dato, hipótesis y reporte; papel de la procedencia; disciplina estructural vs exploración intelectual.

Si alguno de estos recursos no está disponible, el agente debe detenerse y declararlo antes de continuar.

No generes nodos sin haber completado esta lectura. No bases la estructura solo en memoria o en ejemplos genéricos: usa siempre el patrón real del repositorio.

---

### Determinación dinámica del milestone y la sesión

El milestone y el número de sesión se extraen del slug del contrato activo de la sesión:

- Formato del slug: `mXX-sNN-<nombre>` (ejemplo: `m02-s19-canon-jsonl-gate-v0`)
- `milestone` = `mXX` (ejemplo: `m02`)
- `session_num` = `NN` (ejemplo: `19`)
- `session_slug` = `<nombre>` (ejemplo: `canon-jsonl-gate-v0`)

Si el slug no está explícito, el agente debe preguntar antes de continuar. No asumas ni inventes el número de sesión ni el milestone.

---

### Destino canónico: inserción en shards JSONL

Los tres nodos deben insertarse como nuevas líneas JSONL en los siguientes shards, **en este orden**:

```
tiddlers_2.jsonl  ← appended: #### 🌀 Sesión {NN} = {session_slug}
tiddlers_3.jsonl  ← appended: #### 🌀🧪 Hipótesis de sesión {NN} = {session_slug}
tiddlers_4.jsonl  ← inserted before bibliographic block: #### 🌀🧾 Procedencia de sesión {NN}
```

Cada nodo es una **línea JSONL individual** (un objeto JSON en línea única, sin array wrapper). El orden de elaboración es: Procedencia primero, luego Hipótesis, luego Sesión. Esta secuencia no es arbitraria: la Sesión integra lo que Procedencia e Hipótesis ya han delimitado.

**Títulos canónicos exactos:**

```
#### 🌀🧾 Procedencia de sesión {NN}
#### 🌀🧪 Hipótesis de sesión {NN} = {session_slug}
#### 🌀 Sesión {NN} = {session_slug}
```

Después de insertar los 3 nodos, validar con:
```bash
cd go/canon && env GOCACHE=/tmp/go-build go run ./cmd/canon_preflight --mode strict --input ../../out
```

---

### Estructura JSONL obligatoria — nodo canónico

Cada nodo es un objeto JSON en una sola línea (JSONL) con los campos del schema canónico v0:

```json
{"schema_version":"v0","id":"urn:uuid:PENDIENTE-GENERACION-CONVERTIDOR","key":"<título>","title":"<título>","canonical_slug":"<slug-normalizado>","version_id":"sha256:<hex>","content_type":"application/json","modality":"metadata","encoding":"utf-8","is_binary":false,"is_reference_only":false,"role_primary":"<session|hypothesis|provenance>","tags":[...],"taxonomy_path":[...],"semantic_text":null,"content":{"plain":"<inner-json-string>"},"raw_payload_ref":null,"mime_type":"application/json","document_id":null,"section_path":[],"order_in_document":null,"relations":[...],"source_tags":[...],"normalized_tags":[...],"source_fields":{"tmap.id":"PENDIENTE-S{NN}-{PROC|HIP|SES}-001"},"text":"<inner-json-string>","source_type":"application/json","source_position":null,"created":"YYYYMMDDHHmmssSSS","modified":"YYYYMMDDHHmmssSSS"}
```

El campo `text` y el campo `content.plain` contienen la **misma cadena**: el JSON interno válido serializado como string.

El `tmap.id` siempre usa el marcador `PENDIENTE-S{NN}-{PROC|HIP|SES}-001` hasta que el convertidor asigne un UUID real. El `id` siempre es `"urn:uuid:PENDIENTE-GENERACION-CONVERTIDOR"`. No sustituyas esos marcadores por valores inventados.

---

### Estructura JSON obligatoria — contenido interno (campo `text`)

El campo `text` contiene una cadena JSON serializada que, parseada, produce un objeto con estos campos:

```json
{
  "id": "urn:uuid:PENDIENTE-GENERACION-CONVERTIDOR",
  "title": "<título exacto>",
  "rol_principal": "<dato|hipótesis|reporte>",
  "roles_secundarios": ["<rol>"],
  "tags": ["<tag1>", "<tag2>", "..."],
  "relations": [{"type": "<tipo>", "target": "<destino>"}],
  "content": {
    "plain": "<resumen en prosa plana>",
    "markdown": "<contenido estructurado en markdown>"
  },
  "meta": {
    "status": "<validado|borrador>",
    "epistemic_state": "<dato|hipótesis|evidencia>"
  },
  "provenance": [
    {"actor": "human", "origin": "human", "method": "compiled", "source_ref": "..."},
    {"actor": "ai", "origin": "ai", "method": "generated", "source_ref": "..."}
  ],
  "metacognition": {
    "certainty": "<1-3>",
    "ambiguity": "<1-3>",
    "notes": "..."
  }
}
```

El campo `id` siempre es `"urn:uuid:PENDIENTE-GENERACION-CONVERTIDOR"`. No lo sustituyas.

---

### Especificación por tipo de tiddler

#### 1. Tiddler de Procedencia — `#### 🌀🧾 Procedencia de sesión {NN}.json`

Registra la genealogía epistémica de la sesión: de dónde surgieron los aportes relevantes, qué fuentes previas se activaron y por qué.

**Campos internos específicos:**

- `rol_principal`: `"dato"`
- `roles_secundarios`: `["reporte"]`
- `tags` internos: incluir `"core:procedencia-epistemologica"`, `"layer:sesion"`, `"session:mXX-sNN"`, `"milestone:mXX"` y `topic:*` relevantes del dominio
- `relations`: incluir `parte_de → ## 🧾🧱 Procedencia epistemológica`, `usa → ## 🧭🧱 Protocolo de Sesión`, `usa → #### 🌀 Sesión {NN} = {slug}`, `usa → mXX-sNN-{slug}`, y `usa →` a tiddlers de sesiones previas que sean fuentes reales de esta sesión
- `meta.epistemic_state`: `"dato"`
- `content.markdown`: sección numerada de **Entradas de procedencia**, con una subsección por cada fuente real usada en la sesión (origen, fuente concreta, modalidad de obtención, actor, aporte incorporado), seguida de una **Síntesis epistemológica local** y una **Distinción clave**

**Tags externos** (campo `tags` del wrapper):
```
[[## 🧾🧱 Procedencia epistemológica]] [[## 🌀🧱 Desarrollo y Evolución]] [[## 🧭🧱 Protocolo de Sesión]] [[#### 🌀🧪 Hipótesis de sesión {NN-1} = {slug-prev}]]
```

---

#### 2. Tiddler de Hipótesis — `#### 🌀🧪 Hipótesis de sesión {NN} = {session_slug}.json`

Registra qué hipótesis quedaron fortalecidas por la sesión y qué hipótesis nuevas nacen de ella.

**Campos internos específicos:**

- `rol_principal`: `"hipótesis"`
- `roles_secundarios`: `["concepto"]`
- `tags` internos: incluir `"core:hipotesis"`, `"layer:sesion"`, `"session:sNN"` (sin milestone como prefijo), `"milestone:mXX"`, `"mode:desarrollo_pragmatico"` cuando aplique, y `topic:*` relevantes
- `relations`: incluir `parte_de → ## 🧪🧱 Hipótesis`, `usa → ## 🧭🧱 Protocolo de Sesión`, `usa →` a sesiones previas relevantes (como tiddler y como contrato), `usa → #### 🌀 Sesión {NN} = {slug}`
- `meta.epistemic_state`: `"hipótesis"`
- `content.markdown`: dos bloques distintos:
  - **Bloque 1. Hipótesis fortalecidas** por la sesión (con número, formulación, contexto de fortalecimiento, estatuto, relación con el tema)
  - **Bloque 2. Nuevas hipótesis** que nacen para sesiones siguientes (con número continuando desde el Bloque 1, formulación, contexto de surgimiento, estatuto, relación con el tema)
  - Cerrar con una **Distinción clave** que delimite qué cerró y qué dejó abierto la sesión

**Tags externos** (campo `tags` del wrapper):
```
[[## 🧪🧱 Hipótesis]] [[## 🌀🧱 Desarrollo y Evolución]] [[## 🧭🧱 Protocolo de Sesión]] [[#### 🌀 Sesión {NN} = {session_slug}]]
```

---

#### 3. Tiddler de Sesión — `#### 🌀 Sesión {NN} = {session_slug}.json`

Registra el trabajo real de la sesión: objetivo, actividades, hallazgos, decisiones, artefactos y cierre.

**Campos internos específicos:**

- `rol_principal`: `"reporte"`
- `roles_secundarios`: `["evento"]`
- `tags` internos: incluir `"core:desarrollo-y-evolucion"`, `"layer:sesion"`, `"session:mXX-sNN"`, `"milestone:mXX"`, `"mode:*"` cuando aplique, y `topic:*` relevantes
- `relations`: incluir `parte_de → ## 🌀🧱 Desarrollo y Evolución`, `usa → ## 🧭🧱 Protocolo de Sesión`, `usa →` a sesiones previas relevantes (tiddler y contrato), `usa → mXX-sNN-{slug}`, `define → #### 🌀🧪 Hipótesis de sesión {NN} = {slug}`, `define → #### 🌀🧾 Procedencia de sesión {NN}`
- `meta.epistemic_state`: `"evidencia"`
- `content.markdown`: reporte estructurado que incluye:
  - **Objetivo local de la sesión**
  - **Qué se trabajó** (subsecciones por actividad)
  - **Resultado local de la sesión** (operativo, hallazgos, decisiones)
  - **Decisiones tomadas** (explícitas, numeradas)
  - **Artefactos producidos o modificados** (rutas reales)
  - **Qué cambió localmente en el estado del tema**
  - **Cierre local de la sesión** (compuertas cumplidas + ambigüedades abiertas)
  - **Aperturas que deja la sesión** (inmediata y secundarias)
  - **Distinción clave** al final

**Tags externos** (campo `tags` del wrapper), conjunto completo de referencias al sistema:
```
[[## 🧭🧱 Protocolo de Sesión]] [[## 🌀🧱 Desarrollo y Evolución]] [[## 🎯🧱 Detalles del tema]] [[## 📚🧱 Glosario y Convenciones]] [[## 🗂🧱 Principios de Gestion]] [[## 🧠🧱 Política de Memoria Activa]] [[## 🧪🧱 Hipótesis]] [[## 🧰🧱 Elementos específicos]] [[#### referencias especificas 🌀]] [[## 🧾🧱 Procedencia epistemológica]] [[### 🎯 5. Arquitectura 🌀]] [[### 🎯 6. Componentes 🌀]] [[### 🎯 7. Algoritmos y matematicas 🌀]] [[### 🎯 8. Ingeniería asistida por IA 🌀]]
```

---

### Reglas de contenido — no negociables

**A. El contenido markdown debe ser derivado y situado.**
No uses plantillas genéricas ni texto de relleno. El contenido de `content.markdown` debe reflejar lo que realmente ocurrió en la sesión: qué contratos se leyeron, qué artefactos se tocaron, qué hallazgos emergieron, qué quedó abierto. Si no puedes inferirlo con base contractual real, deja la sección marcada como `[PENDIENTE — requiere revisión humana]`.

**B. Las relaciones deben ser reales.**
Los campos `relations` solo deben apuntar a tiddlers que realmente existen en el canon (`out/tiddlers_*.jsonl`) o a contratos en `contratos/`. No inventes targets.

**C. La profundidad de la Procedencia debe reflejar las fuentes reales.**
La Procedencia no es un resumen del objetivo: es un registro de de dónde vino la información usada. Cada entrada de procedencia tiene actor, origen, fuente concreta, modalidad y aporte incorporado.

**D. Las Hipótesis deben distinguir entre fortalecidas y nuevas.**
No mezcles hipótesis previas que continúan con hipótesis emergentes de la sesión. El Bloque 1 y el Bloque 2 son estructuralmente distintos.

**E. El tiddler de Sesión no es la Hipótesis ni la Procedencia.**
El nodo de Sesión integra ambos y añade el registro operativo: qué se ejecutó, qué se produjo, qué se decidió. No repitas contenido que ya está en los otros dos nodos.

**F. `meta.status`:**
- Usa `"validado"` cuando la sesión esté cerrada y revisada.
- Usa `"borrador"` cuando esté en progreso o pendiente de revisión humana.

**G. `metacognition.certainty` y `.ambiguity`:**
- Escala 1 a 3: 1 = baja, 2 = media, 3 = alta.
- La certeza baja es preferible a inflar una hipótesis como hecho.

---

### Reglas de conservadurismo

- No inventes procedencia.
- No promociones hipótesis como hechos consolidados.
- No llenes huecos con intuición libre.
- No sobreexplicites contexto que ya está en otros nodos del sistema.
- Si falta información crítica, deja la provisionalidad explícita en `metacognition.notes`.

---

### Validación antes de entregar

Antes de declarar la sesión cerrada, verifica:

1. Los tres nodos están insertados en los shards correctos (`tiddlers_2.jsonl`, `tiddlers_3.jsonl`, `tiddlers_4.jsonl`).
2. `canon_preflight --mode strict` pasa con 0 errores.
3. El campo `text` de cada nodo es JSON interno válido (parseable).
4. Los títulos en el nodo externo (`title`) y en el JSON interno (`title`) coinciden exactamente.
5. El milestone inferido es coherente con el slug del contrato activo.
6. Las relaciones apuntan a targets que existen en el sistema.

Si alguna validación falla, corregir antes de cerrar la sesión.

---

### Integración con contratos y PRs

Esta instrucción opera dentro del marco de `contratos.instructions.md` y `PRcommits.instructions.md`.

- La generación e inserción de los tres nodos de sesión en el canon es el cierre mínimo documental de la sesión.
- Si la sesión respalda cambios sustantivos en un PR, debe existir además al menos un contrato `.md.json` en `contratos/`, conforme a `contratos.instructions.md`.
- Los nodos de sesión no reemplazan el contrato de sesión, ni el contrato reemplaza los nodos: son artefactos complementarios con roles distintos.
- Los commits y PRs deben seguir la estructura de `docs/estructura_de_commits_tiddly-data-converter.JSON` (o `contratos/estructura_de_commits_tiddly-data-converter.JSON`).

---

### Regla de foco

No conviertas la generación de tiddlers en exploración difusa. El objetivo es producir tres artefactos estructurados y situados que registren fielmente la sesión. Cada palabra en el contenido debe poder trazarse a una fuente real de la sesión.

La sesión no se considera cerrada por la conversación. Se considera cerrada cuando los tres nodos JSONL están insertados en el canon (`out/tiddlers_2.jsonl`, `out/tiddlers_3.jsonl`, `out/tiddlers_4.jsonl`), el contrato está en `contratos/`, y `canon_preflight` pasa sin errores.
