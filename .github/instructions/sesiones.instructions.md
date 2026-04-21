# Plantilla de instruccion de sesion para agentes

## tiddly-data-converter — plantilla local-first con cierre directo en canon, proposals legado y reversibilidad obligatoria

---

## 0. Contexto minimo de la sesion

- **Sesion:** `mXX-sNN-<slug-de-la-sesion>`
- **Modo:** `local`
- **Repositorio:** `tiddly-data-converter`
- **Objetivo principal:** `<describir aqui el objetivo puntual de la sesion>`
- **Restriccion principal:** `<anotar aqui la restriccion mas importante si existe>`

Frase rectora por defecto:

> El trabajo semántico de la sesión no debe quedar fuera del sistema.
> Debe cerrar dentro del canon.
> Debe poder reversearse después.

---

## 1. Layout operativo vigente

La sesion debe asumir como verdad operativa el layout consolidado en S49:

- `data/in/` = entradas locales, incluido el HTML vivo
- `data/out/local/` = canon local, derivados locales y propuestas
- `data/out/remote/` = proyeccion o intercambio remoto preparado, no autoritativo
- `data/out/local/reverse_html/` = salida HTML de reverse y sus reportes

Reglas centrales:

- `data/out/local/tiddlers_*.jsonl` es la fuente de verdad local
- `data/out/local/proposals.jsonl` queda como artefacto legado o extraordinario, no como ruta diaria de cierre
- `data/out/local/enriched/`, `data/out/local/ai/`, `data/out/local/audit/` y `data/out/local/export/` son capas derivadas
- `data/out/local/reverse_html/` no es canon
- `data/out/remote/` no habilita integracion cloud productiva por si sola

---

## 2. Capa normativa activa minima

Antes de ejecutar cualquier accion, leer integramente, respetar y usar como normativa activa de la sesion:

- `.github/instructions/contratos.instructions.md`
- `.github/instructions/PRcommits.instructions.md`, si la sesion toca commits o PR
- `.github/instructions/tiddlers_sesiones.instructions.md`
- `esquemas/canon/canon_guarded_session_rules.md`
- `esquemas/canon/derived_field_rules.md`
- `README.md`
- `data/README.md`
- contratos o reportes previos directamente relevantes al objetivo
- shards canonicos pertinentes dentro de `data/out/local/tiddlers_*.jsonl`

Si la sesion toca dependencias, toolchains, CI/CD, supply chain, librerias, seguridad o superficie externa, leer ademas los nodos y contratos de dependencias que ya existan y sean pertinentes.

Tratamiento obligatorio:

- considerar estos artefactos normativa activa
- priorizar la lectura situada sobre la lectura indiscriminada
- expandirse solo hacia contexto con impacto real sobre el objetivo local

---

## 3. Regla de autoridad del canon

El canon local sigue mandando:

- lectura del canon: permitida
- derivacion desde canon: permitida
- escritura directa gobernada sobre `data/out/local/tiddlers_*.jsonl`: requerida para la memoria semántica-documental propia de la sesión
- `data/out/local/proposals.jsonl`: legado y extraordinario

La escritura directa sigue siendo gobernada:

- solo puede tocar targets explícitos
- debe preservar líneas no objetivo
- y debe pasar validación real antes de cerrar

---

## 4. Fuentes activas obligatorias

La sesion debe trabajar con base en:

### 4.1 Repositorio real

- arbol actual del repositorio
- archivos presentes en local
- rutas realmente vigentes
- scripts y entrypoints reales

### 4.2 Canon local

- `data/out/local/tiddlers_1.jsonl`
- `data/out/local/tiddlers_2.jsonl`
- `data/out/local/tiddlers_3.jsonl`
- `data/out/local/tiddlers_4.jsonl`
- `data/out/local/tiddlers_5.jsonl`
- `data/out/local/tiddlers_6.jsonl`
- `data/out/local/tiddlers_7.jsonl`

### 4.3 Capas derivadas, cuando ayuden al analisis o a la validacion

- `data/out/local/enriched/`
- `data/out/local/ai/`
- `data/out/local/audit/`
- `data/out/local/export/`

### 4.4 Entradas y reverse, cuando apliquen

- `data/in/`
- `data/out/local/reverse_html/`

---

## 5. Cierre permitido y cierre prohibido

### 5.1 Cierre permitido por defecto

La sesion debe cerrar mediante:

- contrato `.md.json` en `contratos/`
- actualizacion de documentacion, scripts o configuracion si el objetivo lo exige
- escritura directa gobernada en `data/out/local/tiddlers_*.jsonl` cuando la sesion produzca memoria semántica-documental propia
- absorción o actualización en canon del propio artefacto `contratos/mXX-sNN-<slug>.md.json` como nodo path-like del repo

### 5.2 Cierre prohibido por defecto

No cerrar creando artefactos nuevos en:

- `docs/tiddlers_de_sesiones/`

No considerar bien cerrada una sesion solo por la conversacion si faltan los artefactos exigidos.

### 5.3 Regla critica

No insertar ni actualizar lineas en `data/out/local/tiddlers_*.jsonl` si los tests o validaciones fallan.

---

## 6. Artefactos semanticos de cierre

Aunque la capa de escritura autonoma ya no va por archivos fisicos separados en `docs/tiddlers_de_sesiones/`, el cierre semantico debe seguir contemplando, cuando aplique, estas piezas:

- `#### 🌀 Sesión {NN} = {session_slug}`
- `#### 🌀🧪 Hipótesis de sesión {NN} = {session_slug}`
- `#### 🌀🧾 Procedencia de sesión {NN} = {session_slug}`

Y, cuando corresponda:

- lineas de dependencias
- ajustes canonicos compatibles con el formato vigente

Regla de soporte:

- estas piezas deben escribirse como lineas JSONL ya canonizadas directamente en `data/out/local/tiddlers_*.jsonl`
- `data/out/local/proposals.jsonl` queda solo para uso extraordinario o recuperación manual
- el contrato `.md.json` de la sesión también debe quedar representado o actualizado en canon como artefacto real del repositorio

---

## 7. Flujo por defecto de trabajo

1. **Leer**
   - instruccion de sesion
   - normativa activa
   - estructura actual del repositorio
   - canon y derivados pertinentes

2. **Diagnosticar**
   - objetivo real
   - rutas implicadas
   - dependencias y riesgos
   - estado inicial antes de tocar nada

3. **Ejecutar**
   - cambios tecnicos necesarios
   - ajustes de rutas, scripts, docs o contratos segun corresponda
   - y absorcion directa en canon cuando la sesion produzca memoria estructural propia

4. **Validar**
   - tests automatizados pertinentes
   - comandos de verificacion relevantes
   - coherencia de rutas
   - coherencia documental
   - pipeline local si aplica
   - export o reverse si el objetivo los toca

5. **Cerrar**
   - crear o actualizar contrato en `contratos/mXX-sNN-<slug>.md.json`
   - documentar lo realizado, lo no realizado, los limites y las validaciones

6. **Uso extraordinario de proposals**
   - solo si existe una razon tecnica concreta para no absorber todavia al canon base

Nunca al reves.

---

## 8. Flujo gobernado de cierre directo

Cuando la sesion produzca memoria semántica-documental propia, el agente debe:

1. identificar el target exacto en canon
2. justificar el cambio como cierre o reparacion gobernada
3. preservar toda linea no objetivo
4. evitar duplicaciones o colisiones
5. validar el resultado antes de cerrar

Compuertas minimas:

```bash
cd /repositorios/tiddly-data-converter/go/canon
env GOCACHE=/tmp/tdc-go-build go run ./cmd/canon_preflight \
  --mode strict \
  --input ../../data/out/local
```

Si el cambio afecta reverse:

```bash
cd /repositorios/tiddly-data-converter/go/canon
env GOCACHE=/tmp/tdc-go-build go run ./cmd/canon_preflight \
  --mode reverse-preflight \
  --input ../../data/out/local
```

Si el canon cambia efectivamente, regenerar capas derivadas y repetir las validaciones pertinentes.

## 8.1 Flujo extraordinario: proposals legado

Solo cuando haga falta candidate storage extraordinario o recuperación manual:

1. justificar por qué no corresponde absorción directa inmediata
2. escribir líneas ya canonizadas
3. no usar `proposals.jsonl` como bypass del cierre normal

---

## 9. Flujo operativo del repositorio cuando la sesion toca export o reverse

### 9.1 Exportacion

Flujo correcto:

1. `export_tiddlers` desde `go/bridge` para producir un JSONL temporal
2. `shard_canon` desde `go/canon` para escribir `data/out/local/tiddlers_*.jsonl`
3. `canon_preflight --mode strict` para validar el canon local

### 9.2 Reverse

Flujo correcto:

1. `canon_preflight --mode reverse-preflight` sobre `data/out/local`
2. `reverse_tiddlers` desde `go/bridge`
3. salida en `data/out/local/reverse_html/`

Regla:

- `reverse_tiddlers` nunca debe tratarse como escritor del canon

---

## 10. Criterio sobre archivos tocados

Los archivos modificados por el objetivo tecnico:

- si deben quedar mencionados en el contrato y en la procedencia
- no deben convertirse automaticamente en nodos nuevos por cada archivo tocado

Si una ruta deja de existir o cambia de funcion:

- actualizar docs, scripts o contratos si corresponde
- no inventar continuidad semantica sin evidencia

---

## 11. Lo que el agente debe hacer

1. entender el objetivo puntual de la sesion
2. inspeccionar el estado real del repositorio
3. detectar rutas y artefactos implicados
4. modificar, mover o crear solo lo necesario
5. respetar la arquitectura vigente
6. actualizar documentacion operativa si el cambio la afecta
7. ejecutar verificaciones y tests pertinentes
8. dejar trazabilidad clara del trabajo realizado
9. cerrar con contrato y, cuando aplique, con absorción canónica directa

---

## 12. Lo que el agente no debe hacer

1. reabrir decisiones cerradas sin razon tecnica fuerte
2. crear artefactos nuevos en `docs/tiddlers_de_sesiones/`
3. usar `data/out/local/proposals.jsonl` como cierre diario
4. insertar lineas canonicas antes de validar
5. inventar rutas, relaciones o clasificaciones no sustentadas
6. declarar integracion cloud productiva viva si no existe
7. tratar `data/out/remote/` como fuente de verdad
8. declarar exito sin contrato y sin evidencia de validacion
9. envolver en `[[...]]` tags que no contienen espacio, `[` ni `]` en `source_fields.tags`
10. derivar `canonical_slug` reemplazando `/` o `.` con guiones — esos caracteres se eliminan, no se convierten
11. declarar el cierre semántico como completo si el reverse real no ha corrido o ha reportado `rejected > 0`

---

## 13. Contenido minimo del contrato

El contrato en `contratos/` debe contener como minimo:

- identidad de la sesion
- objetivo real
- alcance
- archivos o rutas implicadas
- restricciones y riesgos
- decisiones tomadas
- validaciones esperadas
- resultado final esperado
- lo que no se hizo o quedo fuera, si aplica

Seleccionar la familia documental correcta:

- contrato operativo
- registro o reporte operativo
- reporte de politica o decision tecnica

---

## 14. Contenido minimo de las lineas canonicas directas

Toda linea escrita directamente en `data/out/local/tiddlers_*.jsonl` debe salir ya canonizada y respetar el formato vigente del canon.

Campos minimos esperados:

- identidad: `schema_version`, `id`, `key`, `title`, `canonical_slug`, `version_id`
- lectura: `content_type`, `modality`, `encoding`, `is_binary`, `is_reference_only`
- semantica: `role_primary`, `tags`, `taxonomy_path`, `semantic_text`, `content`, `raw_payload_ref`, `mime_type`
- contexto: `document_id`, `section_path`, `order_in_document`, `relations`
- procedencia: `source_tags`, `normalized_tags`, `source_fields`, `text`, `source_type`, `source_position`, `created`, `modified`

No dejar cierres semánticos como borradores informales o JSON parcial.

### 14.1 Regla estricta: `source_fields.tags`

El campo `source_fields.tags` debe seguir **exactamente** la misma lógica que `formatTW5Tags` del motor de reverse (`go/bridge/reverse_tiddlers.go`):

- Si el tag **contiene espacio, `[` o `]`** → envolverlo en `[[tag]]`
- Si el tag **no contiene ninguno de esos tres caracteres** → dejarlo tal cual, sin `[[...]]`

Tabla de referencia:

| Tag | Resultado correcto | Error común |
|---|---|---|
| `## 🧭🧱 Protocolo de Sesión` | `[[## 🧭🧱 Protocolo de Sesión]]` | — |
| `#### 🌀 Sesión 58 = route-fix-...` | `[[#### 🌀 Sesión 58 = route-fix-...]]` | — |
| `session:m03-s58` | `session:m03-s58` | `[[session:m03-s58]]` ← INCORRECTO |
| `milestone:m03` | `milestone:m03` | `[[milestone:m03]]` ← INCORRECTO |
| `topic:route-migration` | `topic:route-migration` | `[[topic:route-migration]]` ← INCORRECTO |
| `contratos/m03-s58-...md.json` | `contratos/m03-s58-...md.json` | `[[contratos/m03-s58-...md.json]]` ← INCORRECTO |

Los paths de archivo como `contratos/m03-s58-<slug>.md.json` **no contienen espacios** y por tanto **no deben ir envueltos** en `[[...]]`. Envolverlos produce `source-fields-reserved-conflict` en el reverse y bloquea la escritura del HTML.

La cadena completa de `source_fields.tags` debe coincidir byte a byte con lo que produce `formatTW5Tags(source_tags)`. Antes de escribir la línea, verificar cada tag individualmente contra esta regla.

### 14.2 Regla estricta: `canonical_slug`

El `canonical_slug` se deriva de `title` mediante el algoritmo de `CanonicalSlugOf` (`go/canon/identity.go`). El algoritmo tiene cinco pasos en orden:

1. Normalización NFKC (`ﬁ` → `fi`, etc.)
2. NFD + eliminar diacríticos combinantes (`é` → `e`, `ó` → `o`, `ú` → `u`, `ñ` → `n`)
3. Minúsculas
4. Todo espacio o secuencia de espacios → un solo `-`
5. **Eliminar todo carácter que no sea `[a-z0-9-]`** — esto incluye `/`, `.`, `=`, `#`, `🌀`, `🧪`, `🧾`, `@`, `_`

Consecuencias críticas del paso 5:

| Fragmento del título | Resultado en slug |
|---|---|
| `#### 🌀 Sesión 58` | `sesion-58` |
| `contratos/m03-s58-slug.md.json` | `contratosm03-s58-slugmdjson` |
| `= route-fix` | `-route-fix` |

Los caracteres `/` y `.` **no se convierten en guión**: se **eliminan**. Un slug derivado de un path de archivo como `contratos/m03-s58-<slug>.md.json` queda sin separadores entre `contratos` y el nombre del archivo.

Antes de escribir cualquier línea, verificar que `canonical_slug` coincide con lo que produce el algoritmo aplicado al `title` exacto del nodo.

### 14.3 Regla estricta: `id` (UUIDv5)

El campo `id` se calcula con UUIDv5 (RFC 4122 §4.3) usando:

- namespace: `uuid.NAMESPACE_URL`
- name: JSON canónico (claves ordenadas, sin espacios) de `{"key": "<title>", "type": "tiddler_node", "uuid_spec_version": "v1"}`

El `key` siempre es igual al `title` completo (incluyendo emoji y caracteres especiales).

Para verificar antes de escribir:

```python
import uuid, json
title = "#### 🌀 Sesión 58 = route-fix-readme-structural-cleanup"
payload = {"key": title, "type": "tiddler_node", "uuid_spec_version": "v1"}
name = json.dumps(payload, sort_keys=True, separators=(',',':'), ensure_ascii=False)
print(str(uuid.uuid5(uuid.NAMESPACE_URL, name)))
```

---

## 15. Validacion minima esperada

La sesion debe correr las compuertas que realmente correspondan a su alcance.

Segun el objetivo, esto puede incluir:

- tests locales del componente tocado
- `canon_preflight --mode strict`
- `canon_preflight --mode reverse-preflight`
- `python3 python_scripts/derive_layers.py`
- smoke tests del pipeline
- verificacion de exportacion
- verificacion de reverse
- verificacion de README y documentacion operativa

No inflar validaciones sin relacion con la sesion, pero tampoco cerrar sin evidencia razonable.

### 15.1 Compuerta obligatoria: reverse real cuando la sesion escribe nodos en canon

Toda sesion que escriba nodos directamente en `data/out/local/tiddlers_*.jsonl` **debe ejecutar el reverse real** antes de declararse cerrada, no solo `reverse-preflight`:

```bash
cd /repositorios/tiddly-data-converter/go/bridge
env GOCACHE=/tmp/tdc-go-build go run ./cmd/reverse_tiddlers \
  --html ../../data/in/'tiddly-data-converter (Saved).html' \
  --canon ../../data/out/local \
  --out-html ../../data/out/local/reverse_html/tiddly-data-converter.derived.html \
  --report ../../data/out/local/reverse_html/reverse-report.json \
  --mode authoritative-upsert
```

`reverse-preflight` verifica invariantes de canon pero **no detecta** conflictos en `source_fields` (como `source-fields-reserved-conflict`). Solo el reverse real los detecta.

Si el reverse termina con `exit status 3` o reporta `rejected > 0`:

1. leer `data/out/local/reverse_html/reverse-report.json`
2. buscar la decisión con `"decision": "rejected"` y el `rule_id`
3. corregir el nodo en canon antes de cerrar
4. repetir `strict` → `reverse-preflight` → reverse real hasta que `rejected: 0`

La sesión no está cerrada hasta que el reverse reporta `Rejected: 0`.

---

## 16. Si la sesion falla

Si los cambios no pasan validacion, el agente debe:

1. no escribir ni actualizar canon base si no pasa validación
2. no degradar el cierre a `proposals.jsonl` como atajo
3. dejar constancia en el contrato de:
   - que se intento
   - que fallo
   - que pruebas no pasaron
   - que bloqueo el cierre
4. no falsear el estado como exitoso

---

## 17. README y documentacion operativa

Si la sesion altera el modo correcto de ejecutar el proyecto, derivar capas, correr export, correr reverse o cerrar el flujo, el agente debe actualizar tambien:

- `README.md`
- `data/README.md`, si cambia el layout o la funcion de `data/`
- documentacion operativa pertinente
- scripts de ejecucion, si aplica

La documentacion actualizada debe reflejar el procedimiento vigente, no el historico.

---

## 18. Salida final obligatoria del agente

### A. Trabajo realizado

- que hizo exactamente

### B. Archivos afectados

- que archivos modifico
- que archivos movio
- que archivos creo
- que archivos elimino, si aplica

### C. Validacion

- que tests ejecuto
- que verificaciones corrio
- si pasaron o no

### D. Cierre contractual

- path del contrato creado o actualizado

### E. Cierre canonico gobernado

- confirmar si la memoria semántica de la sesión quedó absorbida directamente en `data/out/local/tiddlers_*.jsonl`
- confirmar si `data/out/local/proposals.jsonl` se mantuvo fuera del cierre diario
- si no hubo escritura canonica, explicar brevemente por que no hacia falta
