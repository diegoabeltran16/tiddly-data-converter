# Directorio de fixtures

Este directorio contiene archivos de entrada controlados para tests reproducibles
del `tdc-extractor` y componentes relacionados del milestone M01.

## Política de uso

- Los fixtures de este directorio **sí se versionan** en el repositorio.
- Un fixture debe ser **mínimo**, **controlado** y **representativo** del caso de prueba.
- Los archivos HTML reales del usuario **nunca** se colocan aquí.
- Cada fixture debe tener su propósito declarado en este README.

## Fixtures disponibles

| Archivo | Propósito | Estado |
|---------|-----------|--------|
| `minimal_tiddlywiki.html` | HTML vivo de TiddlyWiki 5.x mínimo controlado para validar extracción básica | **Activo** — 4 tiddlers sintéticos (Alpha, Beta, Sin Texto, `$:/SiteTitle`) |
| `raw_tiddlers_minimal.json` | Artefacto raw validado mínimo para tests de la Ingesta (Go) | **Activo** — 4 tiddlers: normal, sistema, sin timestamps, timestamp malformado |
| `raw_tiddlers_timestamp_ms_from_data.json` | Artefacto raw mínimo derivado de corpus real para validar preservación de milisegundos en timestamps TW5 | **Activo S09** — 1 tiddler con `created=20260409180825708` (ms=708); test de aceptación para política temporal |
| `raw_tiddlers_d1_exact_duplicate.json` | Caso reproducible D1: 2 tiddlers con mismo título y mismo contenido; documenta comportamiento de passthrough pre-canónico de Ingesta | **Activo S11** — derivado del caso `LICENSE` observado en `docs/tiddlers_esp.jsonl`; 2 tiddlers idénticos; `source_position` distinto |
| `raw_tiddlers_d2_same_title_diff_content.json` | Caso reproducible D2: 2 tiddlers con mismo título y contenido distinto; documenta que Ingesta no resuelve colisiones de versión | **Activo S11** — derivado del caso `estructura.txt` (3 versiones observadas); 2 snapshots de árbol en momentos distintos |
| `raw_tiddlers_d4_near_duplicate.json` | Caso reproducible D4: 2 tiddlers con títulos distintos y contenido textualmente muy similar (Jaccard≈1.0); documenta que Ingesta no realiza comparación semántica | **Activo S11** — derivado del par `#### 🌀 Sesión 08` / `#### 🌀🧾 Procedencia de sesión 08` observado en corpus |
| `s43/canon_mixed_multi.jsonl` | Canon mixto mínimo para S43: mezcla líneas exportadas y raw-tiddlers nuevos para validar detección selectiva, inserción múltiple y `source_fields` | **Activo S43** — 2 líneas no raw, 1 raw ya presente y 4 inserciones textuales nuevas |
| `s43/invalid_raw_candidates.jsonl` | Matriz negativa de S43 para validar rechazo de raw-tiddlers con system title, `source_tags` inválidos, tipo fuera de subalcance y `source_fields` reservados | **Activo S43** — 1 raw ya presente y 4 rechazos explícitos |

## Cómo añadir un fixture

1. El fixture debe cubrir un caso de prueba declarado en el contrato del componente.
2. Si el fixture se deriva de un HTML real del usuario, debe ser anonimizado
   o reducido al mínimo necesario para el caso.
3. Documenta el fixture en la tabla de arriba antes de hacer commit.
4. No incluyas datos sensibles, tokens, contraseñas ni rutas absolutas locales.

## Lo que NO va en este directorio

- HTML fuentes reales del usuario (`*.tiddlywiki.html`, `user_input*.html`).
- Artefactos generados en runtime (`raw.tiddlers.json`, `extraction_output/`).
- Binarios, dumps de base de datos u otros artefactos grandes.
