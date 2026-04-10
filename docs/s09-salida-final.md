# Salida final — Sesión 09

---

## A. Decisión de política temporal

### Política elegida
**Preservar milisegundos válidos** de los timestamps TW5 de 17 dígitos (`YYYYMMDDHHmmssSSS`).

### Justificación técnica
1. **Carácter pre-canónico**: La Ingesta no debe perder información válida de forma silenciosa (S05 §2).
2. **Evidencia de corpus real**: 337/338 timestamps del corpus oficial tienen milisegundos no cero (S08).
3. **Reversibilidad**: Truncar daña la reversibilidad — no se puede reconstruir el timestamp TW5 original.
4. **Sin costo semántico**: Go's `time.Time` soporta nanosegundos nativamente; mapear milisegundos es directo.

### Evidencia mínima usada
- Fixture: `tests/fixtures/raw_tiddlers_timestamp_ms_from_data.json` (derivado de corpus real)
- Hallazgo cuantitativo: S08 reportó `ms_likely_truncated=337` de 338 timestamps
- Corpus: `data/tiddly-data-converter (Saved).html` — 363 tiddlers

### Razón de coherencia con carácter pre-canónico
Preservar milisegundos mantiene fidelidad temporal sin invadir responsabilidad del Canon. Permite que el Canon decida serialización definitiva con toda la información disponible.

---

## B. Cambios aplicados o propuestos

### Archivos modificados
| Archivo | Propósito |
|---------|-----------|
| `go/ingesta/parse.go` | Extender `parseTW5Timestamp` para parsear milisegundos (posiciones 14-16) y añadirlos como nanosegundos |
| `go/ingesta/parse_test.go` | Añadir tests unitarios para preservación de milisegundos |
| `go/ingesta/ingest_test.go` | Añadir test de aceptación usando fixture de S08 |
| `tests/fixtures/README.md` | Actualizar estado del fixture a "Activo S09" |

### Archivos creados
| Archivo | Propósito |
|---------|-----------|
| `docs/observacion-duplicados-s09.md` | Propuesta técnica para detección observacional de duplicados (D1-D4) |
| `contratos/m01-s09-ingesta-timestamp-policy.md.json` | Reporte estructurado de cierre de S09 |

### Descripción breve del ajuste

**parse.go (líneas 46-70):**
- Parsear primeros 14 dígitos como timestamp base
- Si hay 17+ caracteres, extraer dígitos 14-16 como milisegundos
- Añadir milisegundos al `time.Time` usando `t.Add(time.Duration(ms) * time.Millisecond)`
- Si milisegundos son malformados, ignorar silenciosamente (preserva precisión de segundos)

**Tests:**
- `TestParseTW5Timestamp_WithMilliseconds`: Valida ms=708, ms=000, ms=999
- `TestParseTW5Timestamp_14DigitsOnly`: Valida compatibilidad con timestamps sin ms
- `TestIngest_TimestampPrecisionFromRealCorpus`: Test de aceptación con fixture de S08

---

## C. Validación

### Comandos ejecutados
```bash
cd go/ingesta
go test -v -count=1
```

### Tests relevantes
```
17 tests, 17 passed, 0 failed — 0.004s
```

**Tests nuevos (3):**
- `TestParseTW5Timestamp_WithMilliseconds` ✅
- `TestParseTW5Timestamp_14DigitsOnly` ✅
- `TestIngest_TimestampPrecisionFromRealCorpus` ✅

**Tests existentes (14):** Todos siguen verdes, sin regresiones.

### Evidencia
La política elegida (preservar milisegundos) queda cubierta por test de aceptación reproducible derivado de corpus real (`TestIngest_TimestampPrecisionFromRealCorpus`).

---

## D. Observación mínima sobre duplicados

### Categorías observadas o definidas
| Categoría | Descripción |
|-----------|-------------|
| **D1** | Mismo título, mismo contenido — Duplicados exactos |
| **D2** | Mismo título, contenido distinto — Colisión de identidad |
| **D3** | Distinto título, mismo contenido — Redundancia de contenido |
| **D4** | Distinto título, contenido similar — Near-duplicates (fuzzy) |

### Alcance real de la observación
- **Solo definición conceptual y propuesta técnica**
- No se implementa detección ni deduplicación en esta sesión
- Propuesta de estructura `IngestReport.duplicates` para sesiones futuras
- Algoritmo conservador propuesto basado en mapas `title → []Tiddler`

### Qué se deja explícitamente fuera
1. Implementación de detección de duplicados
2. Implementación de deduplicación
3. Política de resolución de colisiones (D2)
4. Heurísticas de similitud fuzzy (D4)
5. Asignación de UUIDs canónicos
6. Uso de `docs/tiddlers_esp.jsonl` como autoridad

---

## E. Qué quedó explícitamente fuera

- Modificación del shape `Tiddler` (no fue necesario)
- Implementación del Doctor (`audit()` sigue en `todo!()`)
- Contrato del Canon JSONL
- Bridge completo
- Reverse HTML
- CLI para componentes
- Deduplicación efectiva
- Política de resolución de duplicados

---

## F. Riesgos si se implementa más de la cuenta ahora

### Por qué no cerrar deduplicación
1. **Invasión del Canon**: La Ingesta es pre-canónica; deduplicar puede causar pérdida sin reversibilidad
2. **Política sin evidencia**: El corpus oficial no presenta duplicados de título (0 colisiones)
3. **Complejidad prematura**: La Ingesta ya resuelve parseo de tags, timestamps, campos tipados
4. **Confusión de responsabilidades**: Frontera Doctor → Ingesta → Canon debe mantenerse clara

### Por qué no abrir Canon
El Canon JSONL es posterior a la Ingesta. Abrirlo sin tener Ingesta estable, Doctor implementado y Bridge operativo produciría acoplamiento prematuro.

### Por qué no usar `docs/tiddlers_esp.jsonl` como autoridad
Es auxiliar de observación, no Canon, no tiene UUIDs canónicos estables, no ha sido validado por Doctor.

---

## G. Criterio de cierre de S09

### Estado final
**Cerrada y útil** ✅

### Compuertas cumplidas
| Compuerta | Estado |
|-----------|--------|
| Política temporal decidida y documentada | ✅ |
| Política implementada en `parse.go` | ✅ |
| Test de aceptación usando fixture de S08 | ✅ |
| Hallazgo I-1 de S08 cerrado | ✅ |
| Sin regresiones (14 → 17 tests) | ✅ |
| Categorías de duplicados definidas (D1-D4) | ✅ |
| Límites de observación documentados | ✅ |
| Deduplicación explícitamente no implementada | ✅ |
| Evidencia de corpus real utilizada | ✅ |
| Política coherente con carácter pre-canónico | ✅ |

### Validación adicional
- **Code Review**: ✅ No issues found
- **CodeQL Security Scan**: ✅ No alerts found

---

## H. Siguiente paso sugerido

**Recomendado: `m01-s10-doctor-implementation`**

### Justificación
- Doctor sigue sin implementación (`audit()` = `todo!()`)
- Ingesta ya operativa (17 tests verdes)
- Pipeline Extractor → Ingesta funciona sobre corpus real, pero sin Doctor
- Implementar Doctor permitirá validar integridad estructural antes de Ingesta

### Entregables mínimos de S10
1. Implementar `audit()` en `rust/doctor/src/lib.rs`
2. Validar 6 tests existentes (actualmente `#[ignore]`)
3. Ejecutar Doctor sobre corpus oficial
4. Verificar coherencia entre `DoctorReport` e `IngestReport`
5. Sin regresiones en Extractor (5 tests) ni Ingesta (17 tests)

---

## Metadata de sesión

- **Duración**: ~1.5 horas
- **Commits**: 2
- **Archivos modificados**: 4
- **Archivos creados**: 2
- **Tests**: 14 → 17 (+3)
- **Hallazgos cerrados**: I-1 de S08
- **Validación**: Code Review ✅, CodeQL ✅
