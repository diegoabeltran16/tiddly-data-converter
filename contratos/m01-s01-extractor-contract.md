# Contrato operativo inicial: Extractor HTML
**Sesión:** `m01-s01-extractor-contract`
**Milestone:** `M01 — Extracción e inspección crítica`
**Fecha:** 2026-04-06
**Estado:** borrador validado por sesión contractual

---

## 1. Nombre del componente

`Extractor HTML`

---

## 2. Rol dentro del sistema

**Zona arquitectónica:** `Extracción e Inspección`
**Posición en el pipeline:** primer motor real del sistema, inmediatamente posterior al Bridge/Orquestación local y anterior al Doctor.

El Extractor HTML es la **frontera crítica de entrada** del pipeline HTML → Canon. Ningún dato del HTML vivo de TiddlyWiki cruza hacia el núcleo sin pasar primero por él.

**Ownership técnico dominante:** Rust.

---

## 3. Objetivo del componente

Leer un archivo HTML vivo de TiddlyWiki indicado por ruta, localizar las unidades válidas (tiddlers reales), separar señal de ruido estructural y producir un artefacto raw lossless suficientemente fiel para que el Doctor pueda inspeccionarlo y el núcleo canónico pueda recibirlo con confianza.

El Extractor no interpreta, no canoniza ni asigna identidades canónicas. **Su única responsabilidad es extraer con máxima fidelidad estructural**.

---

## 4. Entradas autorizadas

| Tipo | Descripción | Obligatoriedad |
|------|-------------|----------------|
| Ruta de archivo local | Ruta absoluta o relativa al HTML vivo de TiddlyWiki | Obligatoria |
| Señal de modo | Indicación de que el flujo activo es `html → canon` (vs. `canon → reverse`) | Implícita desde el Bridge |

**Restricción explícita:** El Extractor no asume que el archivo fuente vive permanentemente dentro del repositorio. La ruta puede apuntar a cualquier archivo local válido accesible en tiempo de ejecución.

---

## 5. Salidas esperadas

| Artefacto | Forma | Condición |
|-----------|-------|-----------|
| `raw.tiddlers.json` | Array JSON de objetos tiddler crudos, uno por tiddler extraído | Extracción exitosa |
| `extraction_report` | Estructura con conteos, advertencias y diagnóstico mínimo | Siempre, incluso en fallo parcial |

### Forma mínima de `raw.tiddlers.json`

```json
[
  {
    "title": "string",
    "raw_fields": { "...": "..." },
    "raw_text": "string | null",
    "source_position": "string | null"
  }
]
```

> `raw_fields` preserva los campos tal como aparecen en el HTML sin interpretación canónica.
> `source_position` es provisional: puede ser selector CSS, índice de bloque u offset, según implemente Rust.
> El formato exacto de `raw.tiddlers.json` debe cerrarse en la siguiente sesión (`m01-s02`).

### Forma mínima de `extraction_report`

```json
{
  "status": "ok | partial | error",
  "tiddler_count": 0,
  "warnings": [],
  "errors": [],
  "uninterpretable_blocks": []
}
```

---

## 6. Responsabilidades explícitas

1. Leer el archivo HTML local desde la ruta indicada.
2. Localizar el contenedor de tiddlers en el HTML (con el mecanismo de localización relevante para TiddlyWiki 5.x).
3. Iterar sobre los tiddlers encontrados y extraer sus campos sin modificarlos.
4. Preservar el contenido raw de cada tiddler (`text`, `title`, y demás campos) sin normalización ni interpretación semántica.
5. Reportar cuántos tiddlers fueron encontrados y cuántos no pudieron ser interpretados.
6. Señalizar qué bloques del HTML no resultaron interpretables, con suficiente información para localizar el problema.
7. Fallar de forma explícita si el archivo no existe, no es legible o no contiene estructura reconocible de TiddlyWiki.
8. Producir siempre un `extraction_report`, incluso en caso de fallo parcial.

---

## 7. Límites del componente

El Extractor HTML **no debe hacer**:

- Asignar UUIDs canónicos ni identificadores estables.
- Normalizar campos, valores de tags ni contenido textual.
- Validar integridad semántica (eso es responsabilidad del Doctor).
- Ejecutar reverse ni depender de la zona Canon/Reversibilidad.
- Depender de Python, Go, UI ni de ningún otro componente distinto al Bridge (que le entrega la ruta).
- Escribir en el Canon JSONL ni en derivados del núcleo.
- Asumir que la UI o el Bridge ya validaron el HTML: debe tratar la entrada como potencialmente rota.
- Retener estado entre ejecuciones: cada invocación es independiente.

---

## 8. Invariantes mínimas

1. **Fidelidad del raw:** el contenido de `raw_text` y `raw_fields` nunca es modificado respecto de lo que aparece en el HTML fuente.
2. **Ningún tiddler inventado:** el Extractor no puede producir tiddlers que no existan en el HTML fuente.
3. **Siempre hay reporte:** si la extracción termina (con éxito, parcialmente o en error), debe existir un `extraction_report` con `status` definido.
4. **Determinismo:** el mismo HTML bajo las mismas reglas produce el mismo conjunto raw.
5. **No contamina Canon:** el artefacto raw no es el Canon y no puede cruzar directamente al núcleo sin pasar por el Doctor.
6. **Independencia de ruta:** el componente funciona si la ruta indicada es válida y accesible; no asume ubicación fija del HTML fuente.

---

## 9. Fallos bloqueantes

Los siguientes fallos deben detener la ejecución del pipeline y emitirse como `status: "error"` en el reporte, con mensaje descriptivo:

| Condición | Código sugerido (provisional) |
|-----------|-------------------------------|
| Archivo no encontrado en la ruta indicada | `ERR_FILE_NOT_FOUND` |
| Archivo no legible (permisos, corrupción) | `ERR_FILE_NOT_READABLE` |
| Archivo encontrado pero sin estructura TiddlyWiki reconocible | `ERR_NOT_TIDDLYWIKI_HTML` |
| Cero tiddlers extraídos en un HTML que sí es TiddlyWiki | `ERR_ZERO_TIDDLERS` |
| Fallo en el parseo del HTML (estructura rota irrecuperable) | `ERR_HTML_PARSE_FATAL` |

> Los nombres de código son provisionales. Deben formalizarse en Rust como variantes de error tipado en la siguiente sesión.

---

## 10. Casos borde prioritarios

1. **HTML vacío o de tamaño cero:** debe fallar con `ERR_FILE_NOT_READABLE` o `ERR_NOT_TIDDLYWIKI_HTML`.
2. **HTML de TiddlyWiki con cero tiddlers:** debe fallar con `ERR_ZERO_TIDDLERS` y no producir un raw vacío silencioso.
3. **HTML con un tiddler cuyos campos están parcialmente vacíos:** debe extraerse y marcarse en `warnings`, pero no bloquearse.
4. **HTML con bloques irreconocibles junto a tiddlers válidos:** extracción parcial con `status: "partial"`, bloques no interpretables en `uninterpretable_blocks`.
5. **HTML de TiddlyWiki de versión distinta a la esperada:** degradación controlada o warning, no fallo silencioso.
6. **Tiddler con campo `text` muy grande:** debe extraerse sin truncación; el Extractor no limita tamaño.
7. **Caracteres especiales, unicode y emojis en títulos y campos:** deben preservarse intactos, sin escape ni sanitización.
8. **HTML con encoding no UTF-8:** debe detectarse y reportarse en `warnings` o `errors` según la capacidad de recuperación.

---

## 11. Criterios de aceptación

Una implementación inicial del Extractor HTML es aceptable si cumple **todos** los siguientes:

- [ ] Extrae correctamente el conjunto de tiddlers de un HTML vivo de TiddlyWiki 5.x real.
- [ ] No modifica `raw_text` ni `raw_fields` respecto del fuente.
- [ ] Produce `extraction_report` en todos los casos (éxito, parcial y error).
- [ ] Falla explícitamente (no silenciosamente) ante los cinco fallos bloqueantes declarados.
- [ ] Reporta bloques no interpretables en lugar de ignorarlos.
- [ ] Funciona con una ruta local arbitraria (no asume que el HTML vive dentro del repo).
- [ ] El artefacto raw producido no es el Canon ni puede cruzar directamente al núcleo.
- [ ] Pasa los tests con al menos un fixture controlado (HTML real o sintético mínimo).
- [ ] No tiene dependencias externas no justificadas para la extracción core.
- [ ] El comportamiento es determinístico: el mismo HTML produce el mismo raw en ejecuciones repetidas.

---

## 12. Scaffold mínimo inicial

```
rust/
  extractor/
    Cargo.toml               ← crate: tdc-extractor
    src/
      lib.rs                 ← lógica de extracción (entry point del crate)
      error.rs               ← tipos de error tipados (ERR_* como enum)
      report.rs              ← struct ExtractionReport
      raw.rs                 ← struct RawTiddler

contratos/
  m01-s01-extractor-contract.md   ← este documento

tests/
  fixtures/
    minimal_tiddlywiki.html  ← HTML mínimo controlado para tests (versionado)
    README.md                ← declara la política del directorio de fixtures
  extractor/
    test_extraction.rs       ← tests de integración mínima (o integrados en el crate)
```

**Justificación de cada elemento:**

- `rust/extractor/` — crate Rust independiente del resto del workspace; ownership claro desde el inicio.
- `src/lib.rs` — expone la función de extracción y permite testing limpio.
- `src/error.rs` — errores tipados desde el inicio; evita `unwrap()` y fallos silenciosos.
- `src/report.rs` — struct del reporte de extracción, separado de la lógica de parsing.
- `src/raw.rs` — struct del tiddler raw; frontera explícita entre lo extraído y lo canónico.
- `contratos/m01-s01-extractor-contract.md` — este documento, versionado como parte del desarrollo.
- `tests/fixtures/minimal_tiddlywiki.html` — fixture mínimo controlado para tests reproducibles.
- `tests/fixtures/README.md` — declara qué puede versionarse y qué no.
- `tests/extractor/` — tests de integración separados del crate si el workspace lo justifica; pueden empezar dentro del crate.

**No se crea todavía:**

- `main.rs` con CLI completa (pertenece a la fase de integración con el Bridge).
- Nada en `go/` ni en `python/` (no corresponde a esta sesión).
- Estructura de módulos internos adicionales (se revelarán al implementar).

---

## 13. Regla inicial de `.gitignore`

Añadir al `.gitignore` existente:

```gitignore
# Extractor HTML — artefactos de build Rust
rust/extractor/target/

# Artefactos de extracción temporales (generados en runtime, no fixtures)
data/raw/
data/extraction_output/

# HTML fuente del usuario (nunca debe entrar al repo como fuente viva)
# Solo se versionan fixtures controlados bajo tests/fixtures/
*.tiddlywiki.html
user_input*.html
```

**Lo que SÍ se versiona:**

| Artefacto | Razón |
|-----------|-------|
| `tests/fixtures/minimal_tiddlywiki.html` | Fixture controlado y mínimo; necesario para CI y reproducibilidad |
| `tests/fixtures/README.md` | Declara la política del directorio |
| `contratos/m01-s01-extractor-contract.md` | Este contrato; trazabilidad del milestone |
| Todo el código fuente Rust en `rust/extractor/src/` | Obvio |
| `rust/extractor/Cargo.toml` | Manifiesto del crate |

**Lo que no se versiona:**

| Artefacto | Razón |
|-----------|-------|
| `rust/extractor/target/` | Build artifacts de Rust |
| HTML reales del usuario | No son fixtures controlados; no deben contaminar el repo |
| `raw.tiddlers.json` generados en runtime | Salida efímera; se regeneran desde el HTML fuente |

---

## 14. Pseudocódigo hipotético mínimo

```text
fn extract(html_path: &Path) -> Result<(Vec<RawTiddler>, ExtractionReport), ExtractorError>:

  // 1. Verificar existencia y lectura del archivo
  if not exists(html_path):
    return Err(ERR_FILE_NOT_FOUND)
  
  content = read_file(html_path)?  // ERR_FILE_NOT_READABLE si falla

  // 2. Localizar el contenedor de tiddlers en el HTML
  //    (para TiddlyWiki 5.x: elementos <div> con atributo data-tiddler o
  //     script blocks application/json / text/plain con tiddlers embebidos)
  tiddler_blocks = locate_tiddler_containers(content)
  
  if tiddler_blocks is empty:
    return Err(ERR_NOT_TIDDLYWIKI_HTML)

  // 3. Iterar y extraer cada bloque
  raw_tiddlers = []
  warnings = []
  uninterpretable = []
  
  for block in tiddler_blocks:
    match parse_raw_tiddler(block):
      Ok(raw) => raw_tiddlers.push(raw)
      Err(partial) => uninterpretable.push(partial.description)

  // 4. Validar que se extrajo al menos uno
  if raw_tiddlers is empty:
    return Err(ERR_ZERO_TIDDLERS)

  // 5. Construir reporte
  status = if uninterpretable.is_empty() { "ok" } else { "partial" }
  report = ExtractionReport {
    status,
    tiddler_count: raw_tiddlers.len(),
    warnings,
    errors: [],
    uninterpretable_blocks: uninterpretable
  }

  return Ok((raw_tiddlers, report))
```

> Este pseudocódigo expresa la composición lógica esperada, no la implementación final en Rust.
> La estrategia de localización del contenedor (CSS selector, block type, versión TW) se decide en la siguiente sesión.

---

## 15. Pendientes abiertos para la siguiente sesión (`m01-s02`)

| Pendiente | Prioridad | Razón de apertura |
|-----------|-----------|-------------------|
| Definir la estrategia de localización del contenedor TiddlyWiki en el HTML (qué selector/estructura aplica para TW 5.x) | Alta | Depende de inspección real del HTML fuente |
| Cerrar el formato exacto de `raw.tiddlers.json` (qué campos mínimos se incluyen siempre, cuáles son opcionales) | Alta | Necesario antes de implementar el Doctor |
| Definir el mecanismo de paso entre Extractor y Doctor (archivo temporal, pipe, canal Rust) | Alta | Afecta la forma del contrato entre componentes |
| Formalizar los tipos de error como enum Rust (`ExtractorError`) | Alta | Necesario para compilar el crate |
| Crear o validar el fixture `minimal_tiddlywiki.html` para tests | Alta | Sin fixture no hay tests reproducibles |
| Decidir si los tests de integración viven dentro del crate o en `tests/extractor/` separado | Media | Depende de cómo crezca el workspace Rust |
| Estudiar la viabilidad de dependencia HTML parsing en Rust (`scraper`, `html5ever`) bajo la política de mínima dependencia justificada | Media | No se cierra sin evaluación |
| Definir el contrato del Doctor: qué recibe del Extractor y qué devuelve al Bridge | Media | Sesión `m01-s02` debería abrir este contrato |

---

*Este contrato fue producido en sesión `m01-s01-extractor-contract` como artefacto estructurado inicial del Milestone 01.*
*No congela la implementación interna del Extractor. Su función es permitir que la siguiente sesión comience sin redefinir el objetivo.*
