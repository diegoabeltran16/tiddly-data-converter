---
applyTo: "data/out/local/sessions/**/*.md.json"
description: >
  Dueño normativo del formato, actualización y validación de los artefactos
  de sesión .md.json compatibles con TiddlyWiki y canonizables por TDC.
---

# Tiddlers de sesión y schema `.md.json`

## Alcance

Este archivo gobierna:

- la forma técnica de los artefactos `.md.json`;
- sus campos obligatorios y prohibidos;
- su actualización determinista;
- su validación local;
- su compatibilidad con TiddlyWiki;
- su capacidad de producir líneas candidatas.

No gobierna:

- metodología o instrucciones de sesión;
- nombres, rutas y títulos canónicos;
- contenido epistemológico de los entregables;
- diagnósticos no sesionales;
- publicación remota;
- líneas candidatas o admisión al canon.

Aplicar:

- `canonical_session_family.instructions.md` para familia, rutas, títulos,
  identidad, candidatas y S66;
- la instrucción especializada de cada entregable para su contenido;
- `diagnosticos_no_sesionales.instructions.md` para diagnósticos especializados
  y publicación remota.

## Artefactos sujetos al schema

El schema aplica exactamente a:

- `Contrato de sesión`;
- `Procedencia de sesión`;
- `Sesión`;
- `Hipótesis de sesión`;
- `Balance de sesión`;
- `Propuesta de sesión`;
- `Diagnóstico de sesión`.

Cada entregable debe:

- usar extensión `.md.json`;
- contener un único objeto JSON;
- ser importable como tiddler;
- conservar contenido Markdown en `text`;
- cumplir el schema antes de generar candidatas;
- poder transformarse mediante el productor autoritativo.

Un archivo válido y canonizable no está admitido automáticamente en el canon.

## Schema obligatorio

Todo artefacto debe contener exactamente los campos requeridos por el schema
vigente.

| Campo | Restricción |
|---|---|
| `title` | Título exacto gobernado por la familia canónica |
| `type` | `"text/markdown"` |
| `created` | Timestamp TiddlyWiki de 17 dígitos |
| `modified` | Timestamp TiddlyWiki de 17 dígitos |
| `session_id` | Patrón `mXX-sNNNN` |
| `module` | Patrón `mXX` |
| `session` | Patrón `SNNNN` |
| `status` | `"delivered"` |
| `canonical_slug` | Kebab-case estable y propio del entregable |
| `tags` | Array de strings |
| `text` | Markdown no vacío |

Ejemplo mínimo:

```json
{
  "title": "#### 🌀 Contrato de sesión 0183 = admision-relacional-canonica-gobernada",
  "type": "text/markdown",
  "created": "20260726090000000",
  "modified": "20260726113000000",
  "session_id": "m04-s0183",
  "module": "m04",
  "session": "S0183",
  "status": "delivered",
  "canonical_slug": "m04-s0183-contrato-admision-relacional-canonica-gobernada",
  "tags": ["sesion", "contrato", "m04", "s0183"],
  "text": "# Contrato de sesión\n\nContenido estructurado."
}
````

`status: "delivered"` representa la disponibilidad técnica del artefacto.

No demuestra por sí mismo que:

* el entregable esté cerrado;
* la familia esté completa;
* la sesión haya terminado;
* exista una línea candidata;
* el artefacto haya sido admitido al canon.

## Reglas de formato

* El archivo debe contener `{...}`, no `[{...}]`.
* El JSON debe ser válido y estar codificado en UTF-8.
* No uses comentarios ni comas finales.
* `type` debe ser exactamente `"text/markdown"`.
* `created` y `modified` deben cumplir `^\d{17}$`.
* `tags` debe ser un array, no un string.
* `text` debe contener Markdown estructurado.
* `title` debe coincidir exactamente con la familia correspondiente.
* `canonical_slug` debe permanecer estable durante la sesión.
* Cada familia debe tener su propio `canonical_slug`.
* No uses valores `null` para reemplazar campos obligatorios.

Los números de sesión y títulos se gobiernan únicamente en
`canonical_session_family.instructions.md`.

## Campos prohibidos

No incluyas en los artefactos fuente:

| Campo             | Razón                                   |
| ----------------- | --------------------------------------- |
| `created_at`      | Sustituye incorrectamente a `created`   |
| `updated_at`      | Sustituye incorrectamente a `modified`  |
| `artifact_family` | Pertenece a la representación candidata |
| `role_primary`    | Es información derivada                 |
| `source_type`     | Es información derivada                 |
| `tmap.id`         | No pertenece al schema de sesión        |

No introduzcas aliases para campos existentes.

Una modificación del schema requiere actualizar de forma coordinada:

* generador;
* validadores;
* consumidores;
* fixtures;
* documentación;
* migración de artefactos existentes cuando corresponda.

## Autoría

Usa por defecto el generador oficial:

```bash
python3 src/python_scripts/generate_session_deliverables.py generate \
  --session-id mXX-sNNNN \
  --topic <slug> \
  --sessions-dir data/out/local/sessions/
```

El generador debe producir los siete entregables con:

* rutas oficiales;
* títulos canónicos;
* identidad coherente;
* timestamps válidos;
* tags estructurados;
* schema compatible.

Antes de usar `--force`:

1. confirma que la sesión autoriza regeneración;
2. lee los archivos existentes;
3. preserva contenido válido;
4. evita reemplazos destructivos;
5. revisa el diff resultante.

Si el generador falla:

* corrige la causa;
* registra el error;
* no sustituyas el proceso con un formato improvisado;
* detén el cierre si no puede garantizarse el schema.

La edición manual solo es válida cuando conserva el schema y supera la
validación oficial.

## Actualización determinista

Al actualizar un entregable:

* modifica el mismo archivo;
* conserva `title`;
* conserva `session_id`;
* conserva `canonical_slug`;
* conserva `created`;
* actualiza `modified`;
* reconcilia `tags`;
* actualiza `text`;
* valida el resultado.

No crees copias `inicial`, `final`, `v2`, `revisado` o equivalentes.

No reemplaces un artefacto válido sin leer y reconciliar su contenido.

## Validación obligatoria

Después de crear o modificar artefactos, ejecuta:

```bash
python3 src/python_scripts/generate_session_deliverables.py validate-dir \
  --sessions-dir data/out/local/sessions/
```

La validación debe comprobar, como mínimo:

* JSON válido;
* objeto único;
* campos obligatorios;
* ausencia de campos prohibidos;
* formatos de timestamp;
* identificadores;
* títulos;
* rutas;
* tags;
* contenido `text`;
* coherencia de identidad.

No continúes hacia generación de candidatas cuando `validate-dir` reporte
errores.

Cuando `session_sync scan` encuentre un archivo inválido:

* clasifícalo como `schema_invalid`;
* exclúyelo del candidato;
* registra el motivo;
* corrige el artefacto fuente;
* repite la validación.

No modifiques el validador para aceptar un artefacto incorrecto sin una
decisión explícita de cambio de schema.

## Canonizabilidad

El schema válido es una condición necesaria para canonizar un entregable.

También se requiere:

* título canónico;
* identidad estable;
* contenido suficiente;
* procedencia verificable;
* productor autorizado;
* compatibilidad con el canon vigente.

Secuencia:

```text
.md.json válido
→ productor autoritativo
→ línea candidata
→ validación S66
→ autorización
→ admisión local
```

No escribas directamente desde el `.md.json` al canon.

No confundas:

```text
schema válido
≠ candidato válido
≠ artefacto admitido
```

Para candidatas y admisión aplica
`canonical_session_family.instructions.md`.

## Diagnósticos

Este archivo gobierna únicamente el `Diagnóstico de sesión` que forma parte de
la familia obligatoria.

No gobierna:

* diagnósticos temáticos;
* microdiagnósticos;
* diagnósticos de microciclo;
* diagnósticos de mesociclo;
* diagnósticos de proyecto;
* publicación o recuperación desde OneDrive.

Esas reglas deben vivir en
`diagnosticos_no_sesionales.instructions.md`.

Los diagnósticos especializados no sustituyen el `Diagnóstico de sesión`.

## Superficies de escritura

Permitido:

* artefactos `.md.json` bajo las rutas oficiales de sesión;
* modificaciones de productores y validadores autorizadas por el contrato.

Prohibido por defecto:

* escribir directamente en `data/out/local/tiddlers_*.jsonl`;
* usar `proposals.jsonl` como ruta ordinaria;
* crear artefactos fuera de las rutas gobernadas;
* usar extensiones alternativas.

La superficie de sesión es staging, no canon paralelo.

## Prohibiciones

* No uses Markdown libre como sustituto del `.md.json`.
* No serialices el tiddler como array.
* No cambies los nombres de los campos.
* No agregues campos derivados al artefacto fuente.
* No cambies títulos o rutas desde esta instrucción.
* No declares cierre por superar el schema.
* No declares admisión por generar una candidata.
* No publiques diagnósticos remotos desde esta instrucción.
* No copies aquí las compuertas completas de S66.

## Criterio de cumplimiento

Esta instrucción se cumple cuando:

* los siete entregables usan objetos `.md.json` válidos;
* todos respetan el mismo schema técnico;
* mantienen nombres, títulos, rutas e identidades canónicas;
* conservan timestamps y actualización determinista;
* superan `validate-dir`;
* pueden producir candidatas mediante el productor autoritativo;
* no se confunde validación, canonizabilidad y admisión.

````

## Extracción necesaria

La sección retirada sobre:

- familias de diagnósticos especializados;
- nombres y títulos de diagnósticos;
- `diagnostic_governance.py`;
- publicación puntual;
- OneDrive;
- `SYNC_DRY_RUN`;
- pull remoto;

no debe eliminarse definitivamente. Debe convertirse en un dueño independiente:

```text
.github/instructions/diagnosticos_no_sesionales.instructions.md
````
