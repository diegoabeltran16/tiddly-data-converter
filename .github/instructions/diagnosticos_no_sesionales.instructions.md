---
applyTo: "data/out/local/sessions/06_diagnoses/**"
description: >
  Dueño normativo de los diagnósticos especializados no sesionales, sus
  familias, nombres, rutas, validación y publicación remota gobernada.
---

# Diagnósticos no sesionales

## Alcance

Este archivo gobierna:

- diagnósticos temáticos;
- diagnósticos de microciclo;
- diagnósticos de mesociclo;
- diagnósticos de proyecto;
- sus rutas, nombres y títulos;
- su validación local;
- su publicación y recuperación remota.

No gobierna:

- el `Diagnóstico de sesión` obligatorio;
- la familia ordinaria de siete entregables;
- la metodología de sesión;
- las líneas candidatas;
- la admisión al canon.

El `Diagnóstico de sesión` vive en:

```text
data/out/local/sessions/06_diagnoses/sesion/
````

y se gobierna mediante:

* `canonical_session_family.instructions.md`;
* `tiddlers_sesiones.instructions.md`.

Los diagnósticos no sesionales no sustituyen el diagnóstico ordinario de una
sesión.

## Cuándo producirlos

Produce un diagnóstico no sesional únicamente cuando:

* el usuario lo solicita;
* constituye el objetivo explícito de una sesión diagnóstica;
* un ciclo de trabajo requiere consolidar evidencia distribuida;
* el análisis excede el alcance del diagnóstico de una sesión concreta.

No crees diagnósticos especializados para compensar un `Diagnóstico de sesión`
incompleto.

## Familias válidas

Solo se permiten estas cuatro familias:

| Familia       | Subdirectorio               |
| ------------- | --------------------------- |
| `tema`        | `06_diagnoses/tema/`        |
| `micro_ciclo` | `06_diagnoses/micro-ciclo/` |
| `meso_ciclo`  | `06_diagnoses/meso-ciclo/`  |
| `proyecto`    | `06_diagnoses/proyecto/`    |

Cualquier otro subdirectorio especializado es inválido salvo decisión
normativa explícita.

La extensión obligatoria es:

```text
.md.json
```

No uses `.json`, `.md`, `.txt` ni extensiones alternativas.

## Nombres de archivo

### Diagnóstico temático

Patrón:

```text
diagnostico-tematico-NNNN-<slug>.md.json
```

Ejemplo:

```text
diagnostico-tematico-0008-chunks-ai.md.json
```

### Diagnóstico de microciclo

Patrón:

```text
mXX-micro-ciclo-NNNN-NNNN-diagnostico.md.json
```

Ejemplo:

```text
m04-micro-ciclo-0085-0094-diagnostico.md.json
```

### Diagnóstico de mesociclo

Patrón:

```text
mXX-meso-ciclo-NNNN-NNNN-diagnostico.md.json
```

Ejemplo:

```text
m04-meso-ciclo-0065-0094-diagnostico.md.json
```

### Diagnóstico de proyecto

Patrones permitidos:

```text
diagnostico-proyecto-<slug>.md.json
mXX-diagnostico-proyecto-<slug>.md.json
```

Usa el prefijo de módulo solo cuando el diagnóstico esté limitado a un módulo.

## Títulos canónicos

Usa exactamente uno de estos patrones:

```text
#### 🌀 Diagnóstico temático NNNN = <slug>
#### 🌀 Diagnóstico de microciclo = sesiones NNNN-NNNN
#### 🌀 Diagnóstico de microciclo parcial = sesiones NNNN-NNNN
#### 🌀 Diagnóstico de mesociclo = microciclos NNNN-NNNN
#### 🌀 Diagnóstico de proyecto = <slug>
```

Reglas:

* todos los números usan cuatro dígitos;
* los títulos no usan prefijo `S`;
* no agregues comentarios entre el número y `=`;
* no incluyas estados, fechas o explicaciones dentro del título;
* registra aclaraciones y alcance en el campo `text`.

## Formato técnico

Cada diagnóstico debe:

* ser un objeto JSON único;
* usar extensión `.md.json`;
* contener Markdown estructurado en `text`;
* usar timestamps TiddlyWiki cuando el schema los requiera;
* usar `tags` como array;
* conservar una identidad estable;
* superar los validadores aplicables.

No serialices el diagnóstico como array.

No agregues campos derivados o internos sin soporte del productor y del
validador.

Los diagnósticos no sesionales son artefactos de análisis. No son
automáticamente tiddlers del canon.

## Contenido mínimo

Todo diagnóstico debe declarar:

* familia;
* alcance;
* periodo o unidades analizadas;
* objetivo;
* fuentes consultadas;
* método;
* observaciones;
* inferencias;
* contradicciones;
* limitaciones;
* riesgos;
* conclusiones;
* pendientes;
* relación con sesiones o ciclos relevantes.

Distingue siempre:

* fuente primaria;
* fuente auxiliar;
* observación;
* inferencia del agente;
* conclusión no verificable.

No presentes ausencia de staging como pérdida histórica sin revisar primero el
canon local y las demás fuentes autoritativas.

## Autoridad de fuentes

Para reconstrucción diagnóstica, usa de forma situada:

1. diagnósticos previos específicos y vigentes;
2. artefactos relevantes de `data/out/local/sessions/`;
3. canon local en `data/out/local/tiddlers_*.jsonl`;
4. auditorías y derivados necesarios;
5. código, tests, workflows e instrucciones;
6. superficies remotas cuando exista una pregunta concreta de paridad.

El orden orienta la consulta, pero no reemplaza la evaluación de:

* autoridad;
* vigencia;
* propósito;
* completitud.

Una superficie remota no tiene autoridad superior al canon local por defecto.

Si dos fuentes se contradicen, registra la contradicción. No la resuelvas
mediante selección silenciosa.

## Validación local

Antes de publicar:

* valida el JSON;
* valida nombre y extensión;
* valida la familia;
* valida la ruta;
* valida el título;
* verifica que `text` no esté vacío;
* revisa identificadores y referencias;
* confirma que no exista path traversal;
* revisa el diff.

La gobernanza central de rutas debe permanecer en:

```text
src/python_scripts/diagnostic_governance.py
```

No dupliques su allowlist en scripts paralelos.

## Rutas permitidas

Permitidas:

```text
data/out/local/sessions/06_diagnoses/tema/
data/out/local/sessions/06_diagnoses/micro-ciclo/
data/out/local/sessions/06_diagnoses/meso-ciclo/
data/out/local/sessions/06_diagnoses/proyecto/
```

Prohibidas:

```text
data/sessions/
data/out/sessions/
sessions/
```

Rechaza:

* rutas absolutas;
* segmentos `..`;
* familias desconocidas;
* extensiones no autorizadas;
* escrituras fuera de `06_diagnoses/`.

## Proyección remota

La equivalencia remota es:

```text
Local:
data/out/local/sessions/06_diagnoses/<familia>/<archivo>

OneDrive:
sessions/06_diagnoses/<familia>/<archivo>
```

La raíz `data/out/local/` no existe dentro de OneDrive.

La copia remota es una proyección operativa. No reemplaza al archivo local ni
al canon.

## Publicación puntual

Usa para publicación ordinaria:

```bash
src/python_scripts/remote_publish_diagnostic.py \
  --local-file <ruta-local> \
  --remote-relative-path sessions/06_diagnoses/<familia>/<archivo> \
  --dry-run
```

Elimina `--dry-run` únicamente cuando el usuario autorice una publicación real.

La publicación debe:

* usar Microsoft Graph;
* operar bajo la raíz configurada;
* crear carpetas solo cuando la política lo permita;
* respetar el comportamiento de conflicto;
* no borrar archivos remotos;
* registrar el resultado.

Crear un archivo en un runner remoto no demuestra que haya llegado a OneDrive.

## Dry-run

Conserva los valores seguros por defecto.

* `SYNC_DRY_RUN=true` simula operaciones.
* `dry_run=true` no publica.
* Un pull sin credenciales no demuestra acceso remoto.
* El mirror completo no debe ser la vía ordinaria para publicar un diagnóstico.

No cambies los valores predeterminados para forzar una ejecución real.

Una publicación real requiere autorización explícita.

## Mirror completo

Usa el mirror completo solo para mantenimiento controlado.

No lo uses como sustituto de la publicación puntual cuando:

* el workspace remoto está incompleto;
* `data/out/local/` está vacío;
* solo debe publicarse un diagnóstico;
* no se ha validado la paridad del árbol completo.

La ejecución real del mirror requiere:

* `SYNC_DRY_RUN=false`;
* confirmación explícita;
* revisión previa de las diferencias;
* protección contra borrado remoto.

## Recuperación remota

El flujo de entrada es:

```text
OneDrive _remote_outbox/sessions/
→ remote_pull_sessions.py
→ data/tmp/remote_inbox/
→ revisión humana
→ movimiento a la familia local correcta
```

El pull no debe escribir directamente en la ruta definitiva del diagnóstico.

Antes de incorporar un archivo recuperado:

* valida nombre;
* valida familia;
* valida schema;
* revisa contenido;
* confirma procedencia;
* identifica conflictos con archivos locales.

El allowlist del pull permanece en:

```text
src/python_scripts/remote_pull_sessions.py::_is_allowed_outbox_file
```

## Verificación de publicación

Después de una publicación real, verifica mediante una fuente independiente:

* cliente OneDrive sincronizado;
* Microsoft Graph;
* pull real hacia `data/tmp/remote_inbox/`.

No declares publicada una salida solo porque el comando terminó sin error
visible.

Registra:

* archivo local;
* ruta remota;
* modo dry-run o real;
* resultado;
* error;
* comprobación posterior.

## Canon y candidatas

Los diagnósticos no sesionales no ingresan directamente al canon.

Cuando una conclusión diagnóstica deba conservarse canónicamente:

1. determina qué contenido debe promoverse;
2. produce el artefacto de sesión correspondiente;
3. genera una línea candidata;
4. aplica `canonical_session_family.instructions.md`;
5. conserva el diagnóstico como fuente de evidencia.

No conviertas todo el diagnóstico en memoria canónica por defecto.

## Prohibiciones

* No sustituyas el `Diagnóstico de sesión`.
* No inventes familias.
* No cambies nombres o títulos sin decisión normativa.
* No publiques sin validación local.
* No publiques en modo real sin autorización.
* No trates OneDrive como autoridad canónica.
* No uses mirror completo como ruta ordinaria.
* No escribas directamente desde remoto al canon.
* No declares llegada remota sin verificación.
* No mezcles aquí el schema de los siete entregables ordinarios.
* No copies las compuertas completas de S66.

## Criterio de cumplimiento

La instrucción se cumple cuando:

* el diagnóstico pertenece a una familia válida;
* usa nombre, título, ruta y extensión correctos;
* distingue fuentes, observaciones e inferencias;
* supera la validación local;
* conserva trazabilidad con sesiones o ciclos;
* toda publicación real fue autorizada y verificada;
* remoto permanece como proyección, no como autoridad;
* cualquier promoción canónica ocurre mediante una sesión y S66.

````

Con esta extracción quedan separadas dos rutas cognitivas:

```text
tiddlers_sesiones.instructions.md
→ siete entregables ordinarios
→ schema .md.json
→ canonizabilidad

diagnosticos_no_sesionales.instructions.md
→ diagnósticos especializados
→ ciclos y proyecto
→ publicación y recuperación remota
