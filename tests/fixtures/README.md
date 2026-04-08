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
