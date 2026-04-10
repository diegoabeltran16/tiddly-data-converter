# Observación de duplicados y near-duplicates — `m01-s11-ingesta-dedup-triage`

**Sesión:** `m01-s11-ingesta-dedup-triage`
**Milestone:** `M01 — Extracción e inspección crítica`
**Fecha:** 2026-04-10
**Estado:** cerrada con aperturas

---

## A. Corpus observado

| Elemento | Valor |
|----------|-------|
| Fuente principal de observación | `docs/tiddlers_esp.jsonl` (316 tiddlers; artefacto manual auxiliar, **no Canon**) |
| Corpus real del proyecto | `data/tiddly-data-converter (Saved).html` (referenciado como contexto; no re-procesado en S11) |
| Artefactos de referencia de sesiones anteriores | `contratos/m01-s08-ingesta-data-triage.md.json`, `contratos/m01-s09-ingesta-timestamp-policy.md.json` |

**Por qué se eligió `docs/tiddlers_esp.jsonl`:**
El objetivo era observar patrones de duplicados sobre un corpus con suficiente densidad sin re-ejecutar el pipeline de extracción completo. El JSONL con 316 entradas provee una muestra manipulable, con variedad de tipos de tiddler (estructurales, sesiones, código, contratos). Se usa **solo como contraste auxiliar**: no es Canon ni fuente autoritativa.

El corpus real (`data/*.html`, 363 tiddlers, procesado en S08) no fue re-procesado en S11. S08 ya registró que no existían colisiones de título en ese corpus (`0 duplicated titles`). El JSONL permite observar patrones de duplicación que pueden surgir en otros escenarios de importación/re-exportación.

---

## B. Criterio de observación

### Señales usadas para detectar duplicados

1. **Igualdad de título**: dos o más tiddlers con el mismo campo `title`.
2. **Hash MD5 del contenido normalizado** (`text` tras colapso de espacios blancos): detecta contenido idéntico independientemente del título.
3. **Similitud de Jaccard sobre tokenización por palabras** (`\w+`, case-insensitive): detecta near-duplicates cuando el umbral supera 0.85.

### Categorías D1–D4 en esta sesión

| Categoría | Definición operacional |
|-----------|----------------------|
| **D1** | Mismo `title` + mismo contenido (`text` normalizado idéntico). Colisión perfecta. |
| **D2** | Mismo `title` + contenido distinto. Misma identidad nominal, versiones diferentes. |
| **D3** | Distinto `title` + mismo contenido (hash idéntico). Alias semántico o copia renombrada. |
| **D4** | Distinto `title` + contenido altamente similar (Jaccard > 0.85). Near-duplicate semántico. |

### Provisionalidad explícita

- Jaccard sobre tokens no es un criterio semántico robusto; es solo una señal de primera aproximación.
- El JSONL no es Canon: los hallazgos son observaciones sobre un artefacto auxiliar, no verdades del dominio.
- La categoría D3 no fue confirmada en este corpus (ver §C).

---

## C. Hallazgos

### Hallazgo H1 — D1: duplicados perfectos de archivos de código/texto del repositorio

| Atributo | Valor |
|----------|-------|
| Categoría | **D1** (mismo título + mismo contenido) |
| Volumen | 18 pares identificados |
| Ejemplos representativos | `LICENSE`, `contratos/contratos.txt`, `go/go.txt`, `rust/rust.txt`, `tests/test.txt`, `packaging/packaging.txt`, `scripts/scripts.txt`, `rust/extractor/src/lib.rs`, `tests/fixtures/README.md` |
| Evidencia | Todos los pares tienen hash MD5 idéntico y `title` idéntico; `source_position` difiere entre los dos miembros del par (posiciones consecutivas: 112/113, 127/128, 152/153, etc.) |

**Por qué es útil para trabajo futuro:**
Este patrón indica que el corpus fue importado o guardado dos veces sin deduplicación en la capa de UI de TiddlyWiki. Son duplicados de origen acumulativo, no de evolución. La futura política de Canon debe identificar este caso como D1 y elegir uno por `source_position` más reciente o por `created` más reciente, o emitir una advertencia al operador.

**Fixture derivado:** `tests/fixtures/raw_tiddlers_d1_exact_duplicate.json`

---

### Hallazgo H2 — D2: mismo título, versiones evolutivas distintas

| Atributo | Valor |
|----------|-------|
| Categoría | **D2** (mismo título + contenido distinto) |
| Caso observado | `estructura.txt` — 3 tiddlers con el mismo título (`[144]`, `[145]`, `[146]`) y contenidos distintos (diferentes snapshots del árbol de directorios en distintos momentos del proyecto) |
| Evidencia | `[144]`: árbol sin `.github/workflows`; `[145]`: árbol sin `.github`; `[146]`: árbol completo con CI. Jaccard entre `[144]` y `[146]` = 0.78 (similar pero no idéntico). |
| Naturaleza | Evolución del proyecto capturada como tiddlers separados con el mismo título; cada uno representa una "foto" del árbol de archivos en un momento distinto |

**Por qué es útil para trabajo futuro:**
D2 es el caso más complejo para deduplicación: implica decisión sobre qué versión es la autoritativa. Las opciones son: (a) tomar la versión con `modified` más reciente, (b) preservar todas las versiones como historial, (c) emitir advertencia de colisión al operador. Esta decisión NO corresponde a la Ingesta sino al Canon.

**Fixture derivado:** `tests/fixtures/raw_tiddlers_d2_same_title_diff_content.json`

---

### Hallazgo H3 — D3: no confirmado en este corpus

| Atributo | Valor |
|----------|-------|
| Categoría | **D3** (distinto título + mismo contenido) |
| Resultado | 0 grupos confirmados en `docs/tiddlers_esp.jsonl` |
| Nota | Los 17 grupos con hash MD5 idéntico resultaron ser todos D1 (mismo título también); no se encontró ningún par con contenido idéntico y títulos distintos |

**Observación epistemológica:** La ausencia de D3 en este corpus no implica que no pueda ocurrir en otros contextos de importación. La categoría queda en el radar observacional.

---

### Hallazgo H4 — D4: near-duplicates semánticos

| Atributo | Valor |
|----------|-------|
| Categoría | **D4** (distinto título + contenido altamente similar) |
| Volumen | Múltiples pares con Jaccard > 0.85 |
| Casos más informativos | (A) `#### 🌀 Sesión 08 = ingesta-data-triage` [41] ↔ `#### 🌀🧾 Procedencia de sesión 08` [61] (Jaccard=1.00 por tokens); (B) `contratos/m01-s01-extractor-contract.md` [129] ↔ `m01-s01-extractor-contract.md` [162] (Jaccard=1.00); (C) `contratos/m01-s02-extractor-bootstrap.json` [131] ↔ `docs/tiddlers_esp/m01-s02-extractor-bootstrap.json` [141] (Jaccard=1.00) |

**Caso A (H4-A): sesión vs procedencia**
El tiddler `#### 🌀 Sesión 08` contiene como `text` el JSON del tiddler de procedencia con título `#### 🌀🧾 Procedencia de sesión 08 = ingesta-data-triage`. Son tiddlers con roles distintos en la arquitectura del knowledge graph (referencia de sesión vs. tiddler de procedencia epistemológica), pero el vocabulario compartido hace que la similitud por tokens sea máxima. **No son duplicados en sentido semántico** — son tiddlers relacionados con roles diferentes.

**Caso B/C (H4-B, H4-C): mismos archivos, distintas rutas de referencia**
Pares como `contratos/m01-s01-extractor-contract.md` ↔ `m01-s01-extractor-contract.md` son referencias al mismo archivo desde dos contextos de nombre distintos. El contenido core es similar pero uno puede tener metadatos adicionales (ej. tags de código).

**Por qué es útil para trabajo futuro:**
D4 es el caso que requiere comparación semántica real, no solo comparación de hashes. Una política de deduplicación debe distinguir entre: (a) D4 por vocabulario compartido en tiddlers de roles diferentes (como H4-A, que NO son duplicados reales) y (b) D4 por el mismo artefacto referenciado desde rutas distintas (como H4-B/C, que sí pueden ser candidatos a consolidación).

**Fixture derivado:** `tests/fixtures/raw_tiddlers_d4_near_duplicate.json`

---

## D. Fixtures nuevos creados

| Fixture | Ruta | Categoría | Propósito | Estado |
|---------|------|-----------|-----------|--------|
| `raw_tiddlers_d1_exact_duplicate.json` | `tests/fixtures/raw_tiddlers_d1_exact_duplicate.json` | D1 | 2 tiddlers con título `LICENSE` y contenido idéntico; documenta passthrough pre-canónico de Ingesta para D1 | **Creado** |
| `raw_tiddlers_d2_same_title_diff_content.json` | `tests/fixtures/raw_tiddlers_d2_same_title_diff_content.json` | D2 | 2 tiddlers `estructura.txt` con snapshots distintos del árbol; documenta que Ingesta no resuelve colisiones de versión | **Creado** |
| `raw_tiddlers_d4_near_duplicate.json` | `tests/fixtures/raw_tiddlers_d4_near_duplicate.json` | D4 | Par sesión/procedencia con Jaccard≈1.0 por tokens y títulos distintos; documenta que Ingesta no realiza comparación semántica | **Creado** |

---

## E. Cambios aplicados

| Archivo | Propósito | Estado |
|---------|-----------|--------|
| `tests/fixtures/raw_tiddlers_d1_exact_duplicate.json` | Fixture D1 nuevo | Creado |
| `tests/fixtures/raw_tiddlers_d2_same_title_diff_content.json` | Fixture D2 nuevo | Creado |
| `tests/fixtures/raw_tiddlers_d4_near_duplicate.json` | Fixture D4 nuevo | Creado |
| `go/ingesta/ingest_test.go` | 3 tests de passthrough añadidos: `TestIngest_D1ExactDuplicatePassthrough`, `TestIngest_D2SameTitleDiffContentPassthrough`, `TestIngest_D4NearDuplicatePassthrough` | Modificado |
| `tests/fixtures/README.md` | Tabla de fixtures actualizada con las 3 nuevas entradas S11 | Modificado |
| `docs/observacion-duplicados-s11.md` | Este documento | Creado |
| `contratos/m01-s11-ingesta-dedup-triage.md.json` | Contrato de sesión serializado para TiddlyWiki | Creado |

### Confirmación de restricciones de paralelismo

**Archivos prohibidos NO tocados:**
- `rust/doctor/**` — sin modificaciones
- `.github/workflows/ci.yml` — sin modificaciones
- `go/ingesta/parse.go` — sin modificaciones
- `go/ingesta/ingest.go` — sin modificaciones
- `go/ingesta/error.go` — sin modificaciones
- `go/ingesta/tiddler.go` — sin modificaciones
- Fixtures de timestamps de S09 — solo lectura

---

## F. Qué quedó explícitamente fuera

- **Política de deduplicación definitiva** — no se cierra en S11; queda diferida al Canon.
- **Implementación de lógica de detección de duplicados en Ingesta** — la Ingesta es pre-canónica y no debe implementar deduplicación (S05 §9.8).
- **Merge o colapso de tiddlers** — no se realiza ninguna consolidación de tiddlers en este corpus.
- **Reapertura de política de timestamps de S09** — no aplica a S11.
- **Uso de `docs/tiddlers_esp.jsonl` como Canon** — se usó solo como contraste auxiliar.
- **Doctor** — no se tocó ningún archivo de `rust/doctor/`.
- **Canon JSONL** — no existe todavía; no se proyecta en S11.
- **CLI para Ingesta o Extractor** — fuera de alcance.
- **Procesamiento de `data/tiddly-data-converter (Saved).html` en S11** — el corpus real fue observado en S08; S11 usó el JSONL como sustituto de observación.

---

## G. Riesgos si se implementa más de la cuenta ahora

**Por qué no corresponde aún deduplicar:**
La Ingesta es un componente pre-canónico. Implementar lógica de deduplicación en Ingesta violaría el contrato S05 §9.8 ("deduplication belongs to Canon") y mezclaría responsabilidades. El Canon no existe todavía; cualquier política de deduplicación implementada prematuramente en Ingesta se convertiría en deuda técnica o en regla tácita no documentada.

**Por qué no corresponde aún tocar Canon:**
El contrato del Canon JSONL no existe en este milestone. Definir una política de deduplicación sin ese contrato es especulación prematura que puede contradecir decisiones futuras del Canon.

**Por qué no corresponde usar `docs/tiddlers_esp.jsonl` como autoridad:**
El JSONL es un artefacto de control de versiones personal y manual. No fue producido por el pipeline. Tiene duplicados que son artefactos de doble exportación (H1/D1), no de la lógica del sistema. Tomar decisiones sobre identidad canónica de tiddlers basándose en él sería estabilizar hipótesis basadas en un artefacto no canónico.

**Riesgo de clasificar D4 como duplicados verdaderos sin análisis semántico:**
El caso H4-A muestra que un Jaccard=1.0 por tokens no implica que los tiddlers sean duplicados semánticos: pueden ser tiddlers con roles distintos en el knowledge graph. Implementar deduplicación solo por similitud textual produciría falsos positivos y merges incorrectos.

---

## H. Criterio de cierre de S11

**`cerrada con aperturas`**

| Compuerta | Estado |
|-----------|--------|
| Corpus seleccionado y observado | ✅ |
| Criterio de observación explícito (D1–D4) | ✅ |
| Hallazgos clasificados con evidencia | ✅ (H1=D1, H2=D2, H3=D3-ausente, H4=D4) |
| Fixtures D1, D2 y D4 creados y versionados | ✅ |
| Tests de passthrough añadidos (18 tests, 18 verdes) | ✅ |
| `tests/fixtures/README.md` actualizado | ✅ |
| Contrato de sesión `.md.json` producido | ✅ |
| No se tocaron archivos prohibidos | ✅ |
| No se cerró política de deduplicación | ✅ (diferido correctamente) |
| No se reabrió política de timestamps de S09 | ✅ |
| No se invadió Doctor ni Canon | ✅ |

**Aperturas explícitas:**
- La categoría D3 no fue confirmada; queda en el radar.
- La distinción entre D4 "roles diferentes" (no-duplicado real) y D4 "misma referencia en rutas distintas" (candidato a consolidación) requiere criterio semántico más fino que Jaccard sobre tokens.
- La política de deduplicación definitiva queda para una sesión futura dedicada al Canon.

---

## I. Siguiente paso sugerido

**Abrir `m01-s12-canon-contract` — sesión de definición del contrato del Canon JSONL.**

Objetivo: formalizar el contrato del componente Canon (identidad canónica de tiddler, criterio de deduplicación, política de colisión D1/D2/D4). Esta sesión usa los hallazgos de S11 como evidencia de diseño. Solo cuando ese contrato exista será coherente implementar lógica de deduplicación en alguna capa del pipeline.

**Condición mínima:** los fixtures D1, D2 y D4 producidos en S11 deben ser usados como casos de aceptación del futuro contrato de Canon.
