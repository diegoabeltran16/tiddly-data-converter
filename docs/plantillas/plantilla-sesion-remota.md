# Plantilla de sesión diagnóstica remota — tiddly-data-converter

> Usar cuando el Copilot Task Agent debe leer el canon vivo desde OneDrive,
> analizar el código y los derivados, y producir un diagnóstico gobernado.
>
> El agente opera con los **agents secrets/variables** del repositorio.
> No depende del environment `onedrive-remote` (ese es el flujo manual secundario).

---

## Glosario mínimo

| Término | Definición |
|---|---|
| **Canon** | `data/out/local/tiddlers_*.jsonl` — tiddlers canónicos descargados desde OneDrive |
| **Derivados** | `data/out/local/ai/`, `audit/`, `pipeline/`, `enriched/` — artefactos generados del canon |
| **Workspace hidratado** | `data/out/local/` completo tras ejecutar `remote_pull_canon.py` |
| **Diagnóstico temático** | Artefacto analítico en `06_diagnoses/<familia>/`; no es una sesión formal |
| **Familia diagnóstica** | `tema` · `micro_ciclo` · `meso_ciclo` · `proyecto` · `sesion` |
| **Publicación puntual** | `remote_publish_diagnostic.py` — sube un único archivo a OneDrive; nunca borra remotos |
| **Equivalencia rutas** | `data/out/local/sessions/` ↔ `sessions/` en OneDrive (el prefijo `data/out/local/` no se incluye en rutas remotas) |
| **Setup del agente** | `copilot-setup-steps.yml` — hidrata el workspace antes de que el agente diagnostique |

---

## 0. Prerequisito — workspace hidratado

El agente **no debe diagnosticar desde código fuente solamente**.
Antes de analizar, confirmar que `data/out/local/` fue hidratado desde OneDrive:

```bash
# Verificar que el pull ocurrió y no está vacío
test -d data/out/local || echo "BLOQUEO: data/out/local no existe"

# Contar archivos disponibles
find data/out/local -type f | wc -l

# Verificar presencia de canon y derivados
ls data/out/local/tiddlers_*.jsonl 2>/dev/null || echo "AVISO: no hay canon local"
ls data/out/local/sessions/06_diagnoses/ 2>/dev/null || echo "INFO: sin diagnósticos previos"
```

Si `data/out/local/` está vacío, ejecutar el pull primero:

```bash
MSA_TENANT=consumers \
ONEDRIVE_PROJECT_ROOT_NAME=tiddly-data-converter \
ONEDRIVE_ROOT_MODE=approot \
LOCAL_SYNC_TARGET=data/out/local/ \
PULL_CONFLICT_BEHAVIOR=replace \
PULL_CREATE_MISSING_DIRS=true \
PULL_DRY_RUN=false \
python3 python_scripts/remote_pull_canon.py
```

**Regla:** Si el pull falla con HTTP 401, detener y reportar. No diagnosticar desde código fuente como sustituto del canon vivo.

---

## 1. Preflight — verificación de gobernanza

```bash
# Scripts de gobernanza requeridos
test -f python_scripts/diagnostic_governance.py   || echo "BLOQUEO: falta diagnostic_governance.py"
test -f python_scripts/remote_publish_diagnostic.py || echo "BLOQUEO: falta remote_publish_diagnostic.py"
test -f python_scripts/remote_pull_canon.py         || echo "BLOQUEO: falta remote_pull_canon.py"

# Credenciales — solo verificar presencia, nunca imprimir valores
[ -n "$AZURE_CLIENT_ID" ]   && echo "AZURE_CLIENT_ID  : presente" || echo "AZURE_CLIENT_ID  : FALTA"
[ -n "$MSA_REFRESH_TOKEN" ] && echo "MSA_REFRESH_TOKEN: presente" || echo "MSA_REFRESH_TOKEN: FALTA"

# Rutas prohibidas — deben estar ausentes
test ! -d sessions     || echo "BLOQUEO: sessions/ en raíz del repo"
test ! -d data/sessions || echo "BLOQUEO: data/sessions/ existe"
```

---

## 2. Lectura — orden de prioridad

Leer en este orden. Detenerse cuando el contexto sea suficiente para el diagnóstico solicitado.

### 2a. Canon vivo (fuente primaria)

```bash
# Contar tiddlers canónicos por shard
wc -l data/out/local/tiddlers_*.jsonl

# Leer muestra del canon (primeras 5 entradas del shard principal)
head -5 data/out/local/tiddlers_canon.jsonl 2>/dev/null || \
  head -5 data/out/local/tiddlers_0.jsonl 2>/dev/null

# Buscar tiddlers relevantes para el diagnóstico solicitado
grep -l "<término-del-diagnóstico>" data/out/local/tiddlers_*.jsonl
```

### 2b. Derivados AI y auditoría

```bash
# Chunks AI estructurados
ls data/out/local/ai/

# Auditoría del canon
ls data/out/local/audit/

# Artefactos de pipeline
ls data/out/local/pipeline/

# Tiddlers enriquecidos
ls data/out/local/enriched/
```

### 2c. Diagnósticos previos en la misma familia

```bash
# Ver diagnósticos existentes en la familia objetivo
ls data/out/local/sessions/06_diagnoses/<familia>/

# Leer el diagnóstico previo más reciente para evitar repetición
cat data/out/local/sessions/06_diagnoses/<familia>/<último>.md.json | python3 -m json.tool | head -30
```

### 2d. Código fuente relevante

Leer solo los scripts directamente relacionados con el enfoque del diagnóstico.
No leer el repo completo. Usar `grep` para ubicar antes de leer completo.

```bash
# Ubicar función o módulo relevante antes de leer el archivo
grep -rn "<función-o-concepto>" python_scripts/

# Leer solo el script identificado
cat python_scripts/<script-relevante>.py
```

### 2e. Sesiones previas de contexto

```bash
# Balance de la sesión anterior más reciente
ls data/out/local/sessions/04_balance_de_sesion/ | tail -3

# Propuesta de la sesión anterior (qué se recomendó hacer)
cat data/out/local/sessions/05_propuesta_de_sesion/<más-reciente>.md.json | python3 -m json.tool
```

---

## 3. Análisis — enfoque del diagnóstico

El diagnóstico debe responder **tres preguntas estructurales**:

### 3a. Estado del canon

- ¿Cuántos tiddlers hay? ¿Cuántos shards?
- ¿Qué campos están siempre presentes? ¿Cuáles pueden estar vacíos o nulos?
- ¿Hay tiddlers con relaciones capa-1 (`links`, `tags`)? ¿Capa-2 (`content.plain.relations`)?
- ¿Los chunks AI (`ai/`) cubren el canon completo o solo una parte?

### 3b. Eficiencia del pipeline

- ¿El código del script analizado tiene rutas de error claras?
- ¿Hay campos calculados que pueden producir resultados vacíos sin aviso?
- ¿Las reglas de gobernanza (`diagnostic_governance.py`, `path_governance.py`) cubren los casos actuales?
- ¿Hay brechas entre lo que el pipeline produce y lo que el canon requiere?

### 3c. Enfoque específico del diagnóstico solicitado

Responder la pregunta concreta del diagnóstico. No ampliar el análisis más allá del enfoque pedido.
Si la pregunta es ambigua, declararla explícitamente antes de actuar.

---

## 4. Generación del entregable

### Formato del archivo

```json
{
  "title": "#### 🌀 Diagnóstico <familia> <NN> = <slug legible>",
  "type": "text/markdown",
  "created": "YYYYMMDDHHMMSSMMM",
  "modified": "YYYYMMDDHHMMSSMMM",
  "text": "## Diagnóstico <familia> <NN>\n\n..."
}
```

### Convención de nombres

| Familia | Ruta local | Nombre de archivo |
|---|---|---|
| `tema` | `data/out/local/sessions/06_diagnoses/tema/` | `diagnostico-tematico-<NN>-<slug>.md.json` |
| `micro_ciclo` | `data/out/local/sessions/06_diagnoses/micro_ciclo/` | `diagnostico-micro-ciclo-<NN>-<slug>.md.json` |
| `meso_ciclo` | `data/out/local/sessions/06_diagnoses/meso_ciclo/` | `diagnostico-meso-ciclo-<NN>-<slug>.md.json` |
| `proyecto` | `data/out/local/sessions/06_diagnoses/proyecto/` | `diagnostico-proyecto-<NN>-<slug>.md.json` |
| `sesion` | `data/out/local/sessions/06_diagnoses/sesion/` | `diagnostico-sesion-s<NNN>-<slug>.md.json` |

### Estructura interna del campo `text`

```markdown
## Diagnóstico <familia> <NN>

### Fuentes de contexto usadas
- Canon: N tiddlers leídos desde data/out/local/tiddlers_*.jsonl
- Derivados: ai/, audit/, pipeline/ (presentes / ausentes)
- Diagnósticos previos: <lista o "ninguno">
- Código revisado: <scripts consultados>

### [Sección según enfoque solicitado]
...análisis concreto...

### Brechas identificadas
...

### Decisión recomendada
...

### Estado de publicación
- Dry-run: <resultado>
- Live: <pendiente / publicado en sessions/06_diagnoses/<familia>/>
```

### Validar antes de publicar

```bash
# Verificar que el JSON es válido
python3 -m json.tool data/out/local/sessions/06_diagnoses/<familia>/<archivo>.md.json >/dev/null \
  && echo "JSON válido: OK"

# Verificar que el entregable puede convertirse en candidato canónico gobernado
export RUN_ID="remote-diagnostic-preflight-$(date +%Y%m%d%H%M%S)"
python3 python_scripts/session_sync.py scan --run-id "$RUN_ID"

python3 - <<'PY'
import json
import os
from pathlib import Path

inventory = json.loads(Path(f"data/tmp/session_sync/{os.environ['RUN_ID']}/inventory.json").read_text(encoding="utf-8"))
if inventory.get("invalid"):
    raise SystemExit(f"session_sync invalid={len(inventory['invalid'])}")
if inventory.get("blocked_same_id_different_content"):
    raise SystemExit(f"session_sync blocked={len(inventory['blocked_same_id_different_content'])}")
print("session_sync: OK")
PY

CANDIDATE_FILE="$(python3 - <<'PY'
import json
import os
from pathlib import Path

inventory = json.loads(Path(f"data/tmp/session_sync/{os.environ['RUN_ID']}/inventory.json").read_text(encoding="utf-8"))
print(inventory.get("generated_candidate_file") or "")
PY
)"

if [ -n "$CANDIDATE_FILE" ]; then
  EXTRA_ARGS="$(python3 - <<'PY'
import json
import os
from pathlib import Path

inventory = json.loads(Path(f"data/tmp/session_sync/{os.environ['RUN_ID']}/inventory.json").read_text(encoding="utf-8"))
print("--allow-replacements" if inventory.get("replaceable_same_id_different_content") else "")
PY
)"
  python3 python_scripts/admit_session_candidates.py validate \
    --candidate-file "$CANDIDATE_FILE" $EXTRA_ARGS
fi

# Dry-run de publicación
python3 python_scripts/remote_publish_diagnostic.py \
  --local-file  data/out/local/sessions/06_diagnoses/<familia>/<archivo>.md.json \
  --remote-relative-path sessions/06_diagnoses/<familia>/<archivo>.md.json \
  --dry-run
```

**Detener si:** `session_sync` reporta inválidos, conflictos bloqueantes o `validate` rechaza candidatos. No publicar un diagnóstico que no pueda entrar al canon.

---

## 5. Publicación a OneDrive

```bash
# Publicación live (requiere AZURE_CLIENT_ID y MSA_REFRESH_TOKEN en runtime)
python3 python_scripts/remote_publish_diagnostic.py \
  --local-file  data/out/local/sessions/06_diagnoses/<familia>/<archivo>.md.json \
  --remote-relative-path sessions/06_diagnoses/<familia>/<archivo>.md.json
```

**Confirmaciones de publicación exitosa:**

```json
{
  "dry_run": false,
  "status": "uploaded",
  "remote_relative_path": "sessions/06_diagnoses/<familia>/<archivo>.md.json",
  "delete_remote": false
}
```

---

## 6. Restricciones absolutas

| Prohibición | Razón |
|---|---|
| No hacer commit del diagnóstico al repo | Los diagnósticos viven en OneDrive, no en git |
| No crear PR | Flujo diagnóstico es publicación directa a OneDrive |
| No escribir en `tiddlers_*.jsonl` | El canon solo se modifica por el flujo de admisión formal |
| No ejecutar mirror completo | `remote_mirror_out_local.py` no es la ruta de diagnósticos |
| No crear `sessions/` en raíz ni `data/sessions/` | Rutas prohibidas por gobernanza |
| No imprimir secrets en logs | Nunca mostrar valores de `AZURE_CLIENT_ID`, `MSA_REFRESH_TOKEN` |
| No diagnosticar solo desde código si el pull falló | Reportar el fallo; el canon vivo es la fuente primaria |
| No publicar fuera de `sessions/06_diagnoses/` | El script de publicación rechaza otras rutas por diseño |

---

## 7. Manejo de fallos

| Situación | Acción |
|---|---|
| Pull devuelve HTTP 401 | Detener; reportar; no diagnosticar solo desde código |
| `data/out/local/` vacío tras pull | Verificar credenciales; reportar como bloqueante |
| `AZURE_CLIENT_ID` o `MSA_REFRESH_TOKEN` ausente | Ejecutar dry-run; documentar publicación como pendiente |
| JSON del diagnóstico inválido | Corregir antes de intentar publicar |
| `remote_publish_diagnostic.py` rechaza la ruta | La ruta no cumple gobernanza; revisar familia y prefijo |
| Diagnóstico previo cubre el mismo tema | Documentar y extender el existente; no duplicar |
| Objetivo del diagnóstico ambiguo | Declarar la interpretación explícitamente antes de actuar |

---

## 8. Checklist de cierre

```text
[ ] data/out/local/ hidratado desde OneDrive antes de diagnosticar
[ ] Canon leído (tiddlers_*.jsonl) — N tiddlers
[ ] Derivados revisados (ai/, audit/, pipeline/)
[ ] Diagnósticos previos en la misma familia consultados
[ ] Código fuente relevante revisado
[ ] Diagnóstico generado en la ruta gobernada correcta
[ ] JSON válido (python3 -m json.tool pasa)
[ ] session_sync sin inválidos ni conflictos bloqueantes
[ ] Candidatos canónicos validados si se generaron
[ ] Dry-run ejecutado y validado
[ ] Publicación live exitosa → sessions/06_diagnoses/<familia>/
[ ] No se creó PR
[ ] No se hizo commit
[ ] No se escribió en canon
[ ] No se imprimieron secrets
[ ] No se ejecutó mirror completo
```
