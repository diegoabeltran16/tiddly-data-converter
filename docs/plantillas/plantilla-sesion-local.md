# Plantilla de sesión local — tiddly-data-converter

> Usar cuando el agente tiene acceso al repositorio, `data/out/local/`, tests, scripts y canon local.

---

## Glosario mínimo

| Término | Definición breve |
|---|---|
| **Canon local** | `data/out/local/tiddlers_*.jsonl` — fuente de verdad local |
| **Línea candidata** | Objeto JSONL bajo `data/out/local/sessions/` aún no admitido al canon |
| **Derivado** | Artefacto generado desde el canon: `ai/`, `enriched/`, `audit/` |
| **Reverse-preflight** | Validación previa a reverse autoritativo; exige 0 rechazos |
| **Diagnóstico no sesional** | Artefacto analítico en `06_diagnoses/<familia>/`; no entra al canon directamente |
| **Sesión formal** | Produce 7 entregables en `data/out/local/sessions/`; puede generar candidatas canónicas |
| **Session root** | `data/out/local/sessions/` — raíz gobernada; `data/sessions/` está prohibida |

---

## 1. Preflight

```bash
git branch --show-current       # confirmar rama
git rev-parse --short HEAD      # confirmar commit
git status --short              # verificar estado limpio
```

**Detener si:** la rama no es la esperada o hay cambios no comprometidos que no deben tocarse.

Verificar que existen:

```bash
ls data/out/local/tiddlers_*.jsonl    # canon requerido
ls python_scripts/diagnostic_governance.py
ls python_scripts/admit_session_candidates.py
```

**Detener si:** falta el canon o un script crítico para el objetivo de la sesión. Reportar el bloqueo.

---

## 2. Presupuesto de lectura

Leer en este orden; parar en cuanto el objetivo esté claro:

1. Instrucciones normativas obligatorias para el tipo de sesión (solo las necesarias).
2. Rutas directamente relacionadas con el objetivo (búsqueda dirigida > lectura masiva).
3. Shard(s) canónico(s) relevante(s) solo si el objetivo toca el canon.
4. Sesiones previas relevantes (`data/out/local/sessions/`) solo si hay continuidad declarada.
5. Derivados (`ai/`, `enriched/`, `audit/`) solo si validan una hipótesis concreta.

**Reglas de eficiencia:**

- Usar `grep` o búsquedas dirigidas antes de leer archivos completos.
- Resumir salidas largas; no pegar outputs de más de 50 líneas sin resumen.
- Si una precondición crítica falla en el paso 1, detener antes de leer más.
- No leer `tiddlers_*.jsonl` completo si solo se necesita buscar un tiddler específico.

---

## 3. Ejecución

### 3a. Cambios en código/scripts/tests

- Hacer cambios mínimos y atómicos.
- Ejecutar `python3 -m py_compile <script>` antes de cualquier test.
- No introducir dependencias nuevas sin justificación explícita.
- No cambiar `SYNC_DRY_RUN=true` a `false` sin input explícito del operador.
- No imprimir ni almacenar secrets.

### 3b. Correcciones canónicas

Si la sesión requiere corregir el canon:

```bash
# 1. Crear copia temporal con correcciones
python3 -c "..." > /tmp/s104-canon-corrected.jsonl

# 2. Normalizar (regenera id, version_id, canonical_slug)
go run ./go/canon/cmd/canon_preflight --mode normalize \
  --input /tmp/s104-canon-corrected.jsonl \
  --output /tmp/s104-canon-normalized.jsonl

# 3. Validar strict
go run ./go/canon/cmd/canon_preflight --mode strict \
  --input /tmp/s104-canon-normalized.jsonl
# Exigir: "STRICT PASSED"

# 4. Validar reverse-preflight
go run ./go/canon/cmd/canon_preflight --mode reverse-preflight \
  --input /tmp/s104-canon-normalized.jsonl
# Exigir: "REVERSE-PREFLIGHT PASSED"

# 5. Solo si ambas pasan: aplicar al canon real
```

**No modificar `tiddlers_*.jsonl` directamente sin pasar por strict + reverse-preflight.**

### 3c. Producción de candidatas canónicas

Si la sesión genera memoria que debe poder entrar al canon:

1. Producir líneas JSONL candidatas bajo `data/out/local/sessions/`.
2. Incluir: `session_origin`, `artifact_family`, `source_path`, `canonical_status: candidate_not_admitted`.
3. No usar en `source_fields` claves reservadas (ver instrucción `tiddlers_sesiones`).
4. El operador decide cuándo admitir al canon real.

### 3d. Diagnósticos no sesionales

Destino local:

```text
data/out/local/sessions/06_diagnoses/<familia>/<nombre>.md.json
```

Familias válidas: `tema`, `micro-ciclo`, `meso-ciclo`, `proyecto`, `sesion`

Patrón por familia:

| Familia | Patrón |
|---|---|
| `tema` | `diagnostico-tematico-NN-slug.md.json` |
| `micro-ciclo` | `mXX-micro-ciclo-sNNN-sNNN-diagnostico.md.json` |
| `meso-ciclo` | `mXX-meso-ciclo-sNNN-sNNN-diagnostico.md.json` |
| `proyecto` | `diagnostico-proyecto-NN-slug.md.json` |
| `sesion` | `diagnostico-sesion-sNNN-slug.md.json` |

---

## 4. Validación

```bash
python3 -m pytest -q                    # suite completa
python3 -m py_compile python_scripts/*.py  # compilación Python
```

Documentar salvedades si algún test falla por razón pre-existente (ver `project_preexisting_test_failures.md`).

Validar ausencia de rutas prohibidas:

```bash
find . -type d \( -path "./sessions" -o -path "./data/sessions" -o -path "./data/local" \) -print
```

Validar ausencia de títulos inconsistentes en sessions:

```bash
grep -rl "🌀📐\|🌀📋\|🌀🔬\|🌀🩺\|🌀⚖️" data/out/local/sessions/ || echo "OK"
```

---

## 5. Cierre — familia mínima

Producir 7 archivos bajo `data/out/local/sessions/`:

| Carpeta | Título |
|---|---|
| `00_contratos/` | `#### 🌀 Contrato de sesión NNNN = slug` |
| `01_procedencia/` | `#### 🌀🧾 Procedencia de sesión NNNN = slug` |
| `02_detalles_de_sesion/` | `#### 🌀 Sesión NNNN = slug` |
| `03_hipotesis/` | `#### 🌀🧪 Hipótesis de sesión NNNN = slug` |
| `04_balance_de_sesion/` | `#### 🌀 Balance de sesión NNNN = slug` |
| `05_propuesta_de_sesion/` | `#### 🌀 Propuesta de sesión NNNN = slug` |
| `06_diagnoses/sesion/` | `#### 🌀 Diagnóstico de sesión NNNN = slug` |

**Títulos prohibidos (no usar emoji adicional en familias principales):**

```text
🌀📐 Propuesta   🌀📋 Detalles   🌀🔬 Hipótesis   🌀🩺 Diagnóstico   🌀⚖️ Balance
```

---

## 6. Manejo de fallos

| Situación | Acción |
|---|---|
| Falta el canon | Reportar bloqueo; no continuar si el objetivo toca el canon |
| Falta un script | Reportar; evaluar si hay alternativa gobernada |
| Test falla | Diagnosticar si es pre-existente o nuevo; documentar en diagnóstico de sesión |
| Strict falla | Revisar qué campos derivados están incorrectos; usar normalize primero |
| Reverse-preflight falla | Revisar relaciones rotas o campos reservados; no aplicar al canon |
| Ruta prohibida detectada | Eliminar o mover a ruta correcta antes de continuar |
| Objetivo ambiguo | Declarar el objetivo local explícitamente antes de actuar |

---

## 7. Prohibiciones

- No escribir en `data/out/local/tiddlers_*.jsonl` sin flujo gobernado.
- No crear `data/sessions/`, `sessions/` raíz ni `data/local/`.
- No imprimir ni almacenar secrets.
- No cambiar `SYNC_DRY_RUN=true` sin input explícito.
- No usar emojis adicionales en títulos de familias principales de sesión.
- No modificar canon directamente sin pasar strict + reverse-preflight.
