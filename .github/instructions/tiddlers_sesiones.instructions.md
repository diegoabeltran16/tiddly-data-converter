---
applyTo: "data/out/local/sessions/**"
description: >
  Instruccion local-first para validar artefactos .md.json de sesion,
  diagnosticos no sesionales y evidencia de cierre sin escribir directamente
  en el canon final por defecto.
---

## Instruccion: tiddlers de sesion y schema de artefactos

Nota de cumplimiento S66: la familia minima, rutas oficiales, convencion
`#### 🌀`, numeracion de 4 digitos, lineas candidatas y compuertas de admision
se definen en `.github/instructions/canonical_session_family.instructions.md`.
Este archivo no redefine F; solo gobierna el schema de artefactos `.md.json`,
la validacion local de esos artefactos y los diagnosticos no sesionales.

## Lectura previa obligatoria

Antes de documentar una sesion que toque canon, reverse o artefactos de sesion,
leer como minimo:

1. `.github/instructions/canonical_session_family.instructions.md`
2. `.github/instructions/sesiones.instructions.md`
3. `esquemas/canon/canon_guarded_session_rules.md`, si hay candidatos o canon
4. `docs/Informe_Tecnico_de_Tiddler (Esp).md`, si hay reverse o TiddlyWiki
5. shards canonicos pertinentes dentro de `data/out/local/tiddlers_*.jsonl`, si existen y si el objetivo lo requiere
6. capas derivadas pertinentes cuando ayuden al analisis

Si el trabajo toca una linea existente, leer el shard y el nodo objetivo antes
de proponer admision o reparacion.

## Destinos de escritura permitidos para agentes

### Siempre permitido

- `data/out/local/sessions/**`
- documentacion y scripts del repositorio relacionados con el objetivo

### Permitido como staging canonico

- archivos JSONL candidatos bajo la ruta gobernada por S66, con nombre propio de sesion

### Prohibido por defecto

- `data/out/local/tiddlers_*.jsonl`

### Extraordinario

- `data/out/local/proposals.jsonl`

`proposals.jsonl` queda reservado para recuperacion manual o candidate storage
historico. No debe ser la ruta diaria de cierre.

## Schema canonico de artefactos `.md.json`

Todo archivo `.md.json` bajo `data/out/local/sessions/` debe seguir este schema
estricto. La familia y los titulos se definen en S66; este apartado define la
forma tecnica del archivo fuente.

### Herramienta oficial de autoria

Usar el generador canonico cuando se produzcan los entregables ordinarios de
sesion:

```bash
python3 src/python_scripts/generate_session_deliverables.py generate \
  --session-id mXX-sNNNN \
  --topic <slug-del-tema> \
  --sessions-dir data/out/local/sessions/
```

Si los archivos ya existen y la sesion autoriza regeneracion, usar `--force`.
Si el generador falla, corregir el error reportado; si el fallo es
irrecuperable, registrarlo en el diagnostico y detener el cierre.

### Campos obligatorios

| Campo | Formato | Ejemplo |
|---|---|---|
| `title` | Titulo canonico definido por S66 | `#### 🌀 Contrato de sesión 0128 = normalizacion-titulos` |
| `type` | Tipo MIME con `/` | `"text/markdown"` |
| `created` | 17 digitos TiddlyWiki: `YYYYMMDDHHmmSSmmm` | `"20260516000000000"` |
| `modified` | 17 digitos TiddlyWiki: `YYYYMMDDHHmmSSmmm` | `"20260516000000000"` |
| `session_id` | `mXX-sNNNN` | `"m04-s0128"` |
| `module` | `mXX` | `"m04"` |
| `session` | `SNNNN` como identificador tecnico | `"S0128"` |
| `status` | `"delivered"` | `"delivered"` |
| `canonical_slug` | kebab-case estable | `"m04-s0128-contrato-normalizacion-titulos"` |
| `tags` | array de strings | `["sesion", "contrato", "m04", "s0128"]` |
| `text` | string de contenido markdown | `"Contenido del artefacto..."` |

### Campos prohibidos

Los siguientes campos nunca deben aparecer en un artefacto `.md.json`:

| Campo prohibido | Motivo | Campo correcto |
|---|---|---|
| `created_at` | Formato ISO, no TiddlyWiki | `created` |
| `updated_at` | Formato ISO, no TiddlyWiki | `modified` |
| `artifact_family` | Campo interno de candidatos canon, no de artefactos fuente | - |
| `role_primary` | Campo derivado del canon | - |
| `source_type` | Campo derivado de la admision | - |

### Reglas de formato

- `type` debe ser un MIME valido; valores como `"contrato"` o `"diagnostico"` son invalidos.
- `created` y `modified` deben tener exactamente 17 digitos TiddlyWiki.
- El campo `title` sigue la regla S66: el numero de sesion no lleva prefijo `S`.
- El archivo debe ser un objeto JSON `{...}`, no un array `[{...}]`.

### Clasificacion `schema_invalid`

`session_sync scan` ejecuta validacion de schema en cada archivo `.md.json` antes
de construir el candidato. Un archivo con errores de schema recibe la
clasificacion `schema_invalid` y queda excluido del candidato.

### Validacion obligatoria antes de `session_sync scan`

```bash
python3 src/python_scripts/generate_session_deliverables.py validate-dir \
  --sessions-dir data/out/local/sessions/
```

No continuar al paso de `session_sync scan` hasta que `validate-dir` reporte que
los archivos son validos.

## Flujo de cierre por defecto

1. Leer canon, derivados e instrucciones pertinentes.
2. Analizar el cambio necesario.
3. Emitir la familia minima siguiendo S66 y el generador cuando aplique.
4. Validar schema de los artefactos emitidos.
5. Emitir candidatas solo si la sesion deja memoria que deba poder entrar al canon.
6. Validar candidatos o copia temporal con comandos reales cuando corresponda.
7. Registrar en el diagnostico que paso, que no paso y que queda pendiente.

La sesion no queda cerrada solo por la conversacion. La admision local es un
proceso separado y autorizado; este archivo no la redefine.

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
