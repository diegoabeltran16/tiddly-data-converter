# Apertura conceptual: Observación de duplicados — S09

**Sesión:** `m01-s09-ingesta-timestamp-policy`  
**Fecha:** 2026-04-10  
**Estado:** Apertura conceptual documentada  
**Alcance:** Definición de categorías observacionales; **NO** implementación ni detección activa

---

## 1. Propósito de este documento

Abrir **conceptualmente** la observación de duplicados y near-duplicates en el pipeline de ingesta, definiendo categorías mínimas sin implementar detección ni resolución.

Este documento **no introduce capacidades nuevas en el código**. Define categorías observacionales y propone un marco técnico conservador para sesiones futuras, respetando la frontera entre observación conceptual (S09) y detección/resolución efectiva (futuro).

**Qué SÍ contiene este documento:**
- Definición de 4 categorías de duplicados (D1-D4)
- Propuesta de estructura técnica (`IngestReport.duplicates`)
- Algoritmo conservador sugerido para sesiones futuras

**Qué NO contiene este documento:**
- Implementación de detección de duplicados
- Código ejecutable para clasificar duplicados
- Modificaciones al `IngestReport` actual
- Política de resolución o deduplicación

---

## 2. Categorías de duplicados observables

Se proponen **cuatro categorías básicas** para clasificar tiddlers potencialmente duplicados o altamente similares:

### Categoría D1: Mismo título, mismo contenido
**Definición:** Dos o más tiddlers con `title` idéntico y `text` idéntico (o ambos null).

**Semántica:**
- Duplicados exactos por contenido.
- Pueden diferir en metadatos (`created`, `modified`, `tags`, etc.).

**Ejemplo:**
```json
[
  {"title": "Alpha", "text": "Body A", "created": "20250101000000000"},
  {"title": "Alpha", "text": "Body A", "created": "20250102000000000"}
]
```

**Observación:** El título es la identidad nominal de un tiddler en TW5. Dos tiddlers con mismo título y mismo contenido son **candidatos fuertes a deduplicación**, pero la decisión de cuál retener (más antiguo, más reciente, fusión de metadatos) pertenece a la política de resolución.

---

### Categoría D2: Mismo título, contenido distinto
**Definición:** Dos o más tiddlers con `title` idéntico pero `text` diferente.

**Semántica:**
- Colisión de identidad nominal.
- Representan estados distintos del mismo tiddler en momentos diferentes, o un conflicto real de versiones.

**Ejemplo:**
```json
[
  {"title": "Alpha", "text": "Version 1", "modified": "20250101000000000"},
  {"title": "Alpha", "text": "Version 2", "modified": "20250102000000000"}
]
```

**Observación:** Este caso es **semánticamente crítico** y requiere política humana. No puede resolverse automáticamente sin regla de precedencia (ej: más reciente gana, o fusión manual, o error bloqueante). La Ingesta **no debe decidir** esta política; debe **detectar y reportar**.

**Hallazgo S08:** El corpus real (`data/tiddly-data-converter (Saved).html`) no presentó duplicados de título (0 colisiones). Esto no invalida la necesidad de detectar este caso en corpus futuros.

---

### Categoría D3: Distinto título, mismo contenido
**Definición:** Dos o más tiddlers con `title` diferente pero `text` idéntico (y no vacío).

**Semántica:**
- Tiddlers nominalmente distintos que comparten contenido exacto.
- Pueden ser copias intencionales, referencias cruzadas, o fragmentos reutilizados.

**Ejemplo:**
```json
[
  {"title": "Alpha", "text": "Shared body"},
  {"title": "Beta", "text": "Shared body"}
]
```

**Observación:** Este caso es **menos crítico** que D2, porque no hay colisión de identidad. Sin embargo, puede indicar redundancia de contenido o necesidad de refactorización (ej: transclusion en TW5). La Ingesta puede **reportar** sin bloquear.

---

### Categoría D4: Distinto título, contenido altamente similar
**Definición:** Dos o más tiddlers con `title` diferente y `text` no idéntico pero altamente similar según alguna métrica de similitud (ej: distancia de Levenshtein, hash fuzzy, n-grams).

**Semántica:**
- Near-duplicates.
- Pueden ser versiones ligeramente modificadas, borradores, o contenido derivado.

**Ejemplo:**
```json
[
  {"title": "Alpha", "text": "This is the body of Alpha."},
  {"title": "Alpha Draft", "text": "This is the body of Alpha!"}
]
```

**Observación:** Este caso es **costoso computacionalmente** y **semánticamente ambiguo**. Requiere definir un umbral de similitud y una métrica. La Ingesta **no debe implementar** detección fuzzy en esta fase. Se deja como apertura para sesiones futuras de triage avanzado.

---

## 3. Qué NO corresponde decidir todavía

La apertura observacional de S09 **explícitamente NO cierra**:

1. **Política de resolución de duplicados:**
   - ¿Qué hacer ante D1 (duplicado exacto)? ¿Retener el más antiguo? ¿El más reciente? ¿Fusionar metadatos?
   - ¿Qué hacer ante D2 (colisión de título)? ¿Error bloqueante? ¿Advertencia con preservación de ambos? ¿Precedencia por timestamp?

2. **Implementación de deduplicación en Ingesta:**
   - La Ingesta es pre-canónica y no debe decidir la identidad canónica definitiva de los tiddlers.
   - La deduplicación pertenece al componente **Canon JSONL** o a una compuerta posterior.

3. **Heurísticas de similitud fuzzy:**
   - Definir umbral de similitud para D4.
   - Elegir métrica (Levenshtein, Jaccard, hash fuzzy, embedding semántico).
   - Estas decisiones requieren evidencia de corpus real y justificación de costo computacional.

4. **Asignación de UUIDs canónicos:**
   - La identidad estable (UUIDv5) pertenece al Canon, no a la Ingesta.

5. **Uso de `docs/tiddlers_esp.jsonl` como autoridad:**
   - Este archivo es auxiliar de observación, no Canon ni fuente de verdad.

---

## 4. Propuesta técnica mínima para sesiones futuras

Si se decide implementar detección observacional (no resolución), se propone:

### 4.1. Extensión del `IngestReport`

Añadir un campo `duplicates` al `IngestReport` con estructura:

```go
type DuplicateObservation struct {
    Category   string   `json:"category"`   // "D1", "D2", "D3", "D4"
    Titles     []string `json:"titles"`     // Títulos involucrados
    Positions  []string `json:"positions"`  // source_position de cada tiddler
    Severity   string   `json:"severity"`   // "info", "warning", "error"
}

type IngestReport struct {
    Verdict        Verdict               `json:"verdict"`
    TiddlerCount   int                   `json:"tiddler_count"`
    IngestedCount  int                   `json:"ingested_count"`
    SkippedCount   int                   `json:"skipped_count"`
    Warnings       []string              `json:"warnings"`
    Errors         []string              `json:"errors"`
    Duplicates     []DuplicateObservation `json:"duplicates,omitempty"`  // Nuevo
}
```

### 4.2. Algoritmo de detección conservador

- **D1 y D2:** Construir un mapa `title → []Tiddler` durante la ingesta. Si `len(tiddlers) > 1` para algún título, clasificar según igualdad de `text`.
- **D3:** Construir un mapa `hash(text) → []Tiddler` donde `hash` puede ser SHA256 simple. Reportar colisiones.
- **D4:** Diferir a sesión futura; requiere métrica de similitud costosa.

### 4.3. Severidad propuesta

| Categoría | Severidad | Veredicto sugerido |
|-----------|-----------|--------------------|
| D1        | `warning` | `warning` (no bloqueante; puede ser legítimo) |
| D2        | `warning` o `error` | Depende de política (diferir decisión a S10+) |
| D3        | `info`    | `ok` (no bloqueante; puede ser intencional) |
| D4        | `info`    | `ok` (si se implementa) |

---

## 5. Límites de alcance de la observación

- **La detección NO es deduplicación.**
- **La Ingesta NO debe modificar ni descartar tiddlers duplicados.**
- **La Ingesta SOLO reporta observaciones en `IngestReport.duplicates`.**
- **La decisión de qué hacer con los duplicados pertenece al Bridge o al Canon.**

---

## 6. Evidencia del corpus real (S08)

- Corpus: `data/tiddly-data-converter (Saved).html` (363 tiddlers)
- Hallazgo: **0 duplicados de título** detectados.
- Conclusión: El corpus oficial actual **no presenta colisiones de título**.

Esto **no invalida** la necesidad de detectar duplicados en corpus futuros. La ausencia de duplicados en este corpus particular no implica que el sistema no los encontrará nunca.

---

## 7. Siguiente paso sugerido

**Opción A — Implementar observación D1+D2 en S10:**
- Añadir `IngestReport.duplicates`.
- Detectar duplicados de título (D1 y D2) durante la ingesta.
- Reportar sin resolver.
- Validar con fixture sintético que contenga duplicados deliberados.
- **No** implementar D3 ni D4 todavía.

**Opción B — Diferir observación hasta después del Canon:**
- Mantener la Ingesta sin detección de duplicados.
- Delegar toda observación al componente Canon JSONL o a un componente de análisis post-canónico.
- Justificación: La Ingesta ya tiene suficiente complejidad; añadir duplicados puede dificultar el debugging.

**Decisión:** Diferida a supervisión humana.

---

## 8. Riesgos de implementar deduplicación ahora

1. **Invasión del Canon:** La Ingesta no debe decidir la identidad canónica definitiva. Deduplicar en Ingesta puede producir pérdida de información sin reversibilidad.

2. **Política sin evidencia suficiente:** El corpus oficial no presenta duplicados. Implementar política de resolución sin casos reales puede producir reglas incorrectas.

3. **Complejidad prematura:** La Ingesta ya resuelve parseo de tags, timestamps, campos tipados. Añadir deduplicación incrementa superficie de error y dificulta debugging.

4. **Confusión de responsabilidades:** La frontera Doctor → Ingesta → Canon debe mantenerse clara. La Ingesta es **transformación semántica pre-canónica**, no **resolución de identidad canónica**.

---

## 9. Criterio de cierre de la apertura observacional

Esta propuesta se considera **cerrada y útil** si:

- [x] Las cuatro categorías (D1, D2, D3, D4) quedan definidas con semántica clara.
- [x] Los límites de alcance (qué SÍ y qué NO) quedan explícitos.
- [x] Se propone una estructura técnica mínima (`IngestReport.duplicates`).
- [x] Se propone un algoritmo conservador para D1+D2 (sin implementar).
- [x] Se documenta la evidencia del corpus real (S08: 0 duplicados).
- [x] Se declara explícitamente que la deduplicación NO corresponde a S09.
- [x] Se deja un siguiente paso claro (S10 o diferimiento).

---

## 10. Estado final de esta apertura conceptual

**Cerrada como apertura conceptual documentada.**

S09 **no implementa** detección de duplicados. Define categorías observacionales (D1-D4) y propone estructura técnica conservadora para sesiones futuras.

**Lo que S09 cierra:**
- [x] Definición conceptual de 4 categorías de duplicados
- [x] Alcance delimitado (observación vs resolución)
- [x] Riesgos documentados de implementación prematura
- [x] Propuesta técnica conservadora para `IngestReport.duplicates`

**Lo que S09 NO implementa:**
- [ ] Detección activa de duplicados en `go/ingesta/`
- [ ] Modificaciones al `IngestReport` actual
- [ ] Algoritmo de clasificación ejecutable
- [ ] Política de resolución o deduplicación

La **detección observacional** de duplicados queda **abierta como línea conceptual futura de triage**, con categorías definidas, alcance delimitado y riesgos documentados.

La **implementación efectiva** y la **política de resolución** quedan **explícitamente diferidas** a sesiones posteriores o a componentes posteriores del pipeline (Canon JSONL).
