# Plantilla de sesión remota — tiddly-data-converter

> Usar cuando el agente opera sobre una rama GitHub y/o ambiente remoto con acceso
> a OneDrive mediante el environment `onedrive-remote`.

---

## Glosario mínimo

| Término | Definición breve |
|---|---|
| **Environment oficial** | `onedrive-remote` — único environment GitHub para publicación OneDrive |
| **OneDrive remoto** | `approot:/tiddly-data-converter/` — raíz del proyecto en OneDrive |
| **Diagnóstico no sesional** | Artefacto analítico en `sessions/06_diagnoses/<familia>/` en OneDrive |
| **Sesión formal** | Produce 7 entregables en `data/out/local/sessions/`; puede generar candidatas canónicas |
| **Publicación puntual** | `remote_publish_diagnostic.py` — sube un solo archivo a OneDrive; no borra remotos |
| **Mirror completo** | `remote_mirror_out_local.py` — sincroniza `data/out/local/` completo; no es la ruta normal para diagnósticos |
| **Equivalencia rutas** | `data/out/local/sessions/` ↔ `sessions/` en OneDrive (no incluir prefijo `data/out/local/` en rutas remotas) |
| **remote-mirror** | Environment legacy retirado — no recrear; usar `onedrive-remote` |

---

## 1. Preflight — parada temprana

```bash
git branch --show-current       # verificar rama
git rev-parse --short HEAD      # verificar commit
git log -1 --oneline            # verificar contexto
```

**Detener si:** la rama no contiene los scripts de gobernanza requeridos:

```bash
test -f python_scripts/diagnostic_governance.py || echo "BLOQUEO: falta diagnostic_governance.py"
test -f python_scripts/remote_publish_diagnostic.py || echo "BLOQUEO: falta remote_publish_diagnostic.py"
test -f .github/workflows/remote_publish_diagnostic.yml || echo "BLOQUEO: falta workflow de publicación"
```

**Regla de parada temprana:**

Si la rama no contiene la gobernanza requerida, no producir diagnóstico ni artefactos.
Reportar la precondición fallida y detener.

Verificar variables de environment (sin imprimir valores sensibles):

```bash
# Solo verificar presencia, nunca imprimir valores
[ -n "$AZURE_CLIENT_ID" ] && echo "AZURE_CLIENT_ID: presente" || echo "AZURE_CLIENT_ID: FALTA"
[ -n "$MSA_REFRESH_TOKEN" ] && echo "MSA_REFRESH_TOKEN: presente" || echo "MSA_REFRESH_TOKEN: FALTA"
```

---

## 2. Presupuesto de lectura

1. No leer el canon remoto salvo que esté disponible y el objetivo lo exija.
2. Leer solo los scripts relevantes para el objetivo.
3. Verificar existencia de rutas antes de listar sus contenidos.
4. Resumir outputs largos; no pegar más de 30 líneas sin síntesis.

**Reglas de eficiencia:**

- Usar `grep` antes de leer archivos completos.
- Si el workspace remoto tiene `data/out/local/` vacío o incompleto, no usar mirror completo como ruta de diagnósticos.
- Identificar la diferencia entre "no existe localmente" y "no existe en OneDrive" antes de actuar.

---

## 3. Ejecución — publicación de diagnóstico

### 3a. Diagnóstico local → OneDrive (publicación puntual)

Producir el archivo local:

```text
data/out/local/sessions/06_diagnoses/<familia>/<nombre>.md.json
```

Ejemplo para familia `tema`:

```text
data/out/local/sessions/06_diagnoses/tema/diagnostico-tematico-08-slug.md.json
```

Validar dry-run antes de publicar:

```bash
python3 python_scripts/remote_publish_diagnostic.py \
  --local-file data/out/local/sessions/06_diagnoses/tema/diagnostico-tematico-08-slug.md.json \
  --remote-relative-path sessions/06_diagnoses/tema/diagnostico-tematico-08-slug.md.json \
  --dry-run
```

Publicar live (requiere `AZURE_CLIENT_ID` y `MSA_REFRESH_TOKEN` en runtime):

```bash
python3 python_scripts/remote_publish_diagnostic.py \
  --local-file data/out/local/sessions/06_diagnoses/tema/diagnostico-tematico-08-slug.md.json \
  --remote-relative-path sessions/06_diagnoses/tema/diagnostico-tematico-08-slug.md.json
```

### 3b. OneDrive → local (pull)

```bash
python3 python_scripts/remote_pull_sessions.py
# Resultado en: data/tmp/remote_inbox/
# El operador mueve manualmente al subfolder correcto de 06_diagnoses/
```

### 3c. Mirror completo (mantenimiento controlado)

Solo usar si `data/out/local/` está completo y el operador lo solicitó explícitamente.
No usar como ruta normal para diagnósticos producidos en workspace remoto incompleto.

```bash
# Verificar dry_run por defecto antes de cualquier mirror live
echo "SYNC_DRY_RUN: ${SYNC_DRY_RUN:-true (default)}"
```

---

## 4. Equivalencia rutas local ↔ OneDrive

```text
LOCAL (gitignoreado, nunca en GitHub):
  data/out/local/sessions/06_diagnoses/tema/

OneDrive (approot:/tiddly-data-converter/):
  sessions/06_diagnoses/tema/
```

**Regla:** No incluir `data/out/local/` en las rutas remotas. La raíz `data/out/local/`
mapea directamente a la raíz del proyecto en OneDrive.

**Verificación de llegada real:**

```bash
# Después de un pull real, verificar en inbox local:
ls data/tmp/remote_inbox/

# OneDrive no se puede verificar sin acceso a Graph o cliente sincronizado.
# "Crear un archivo en el runner remoto" ≠ "el archivo llegó a OneDrive"
```

---

## 5. Validación

```bash
python3 -m py_compile python_scripts/diagnostic_governance.py
python3 -m py_compile python_scripts/remote_publish_diagnostic.py
python3 -m py_compile python_scripts/remote_mirror_out_local.py
python3 -m py_compile python_scripts/remote_pull_sessions.py
python3 -m pytest -q
```

Validar ausencia de referencias activas a `remote-mirror`:

```bash
grep -Rn "remote-mirror" .github python_scripts | grep -v "legacy\|retirad\|#" || echo "OK"
```

Validar que el environment activo es `onedrive-remote`:

```bash
grep "environment:" .github/workflows/remote_*.yml
# Esperado: environment: onedrive-remote (en todos)
```

---

## 6. Cierre — familia mínima

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

**Títulos prohibidos:**

```text
🌀📐 Propuesta   🌀📋 Detalles   🌀🔬 Hipótesis   🌀🩺 Diagnóstico   🌀⚖️ Balance
```

---

## 7. Manejo de fallos

| Situación | Acción |
|---|---|
| Rama incorrecta | Detener; reportar bloqueo; no producir artefactos |
| Falta `diagnostic_governance.py` | Detener; la rama no tiene gobernanza requerida |
| `AZURE_CLIENT_ID` ausente | Ejecutar en dry-run; no publicar live |
| `MSA_REFRESH_TOKEN` ausente | Ejecutar en dry-run; no publicar live |
| Environment `onedrive-remote` no disponible | No ejecutar live; documentar como pendiente |
| Workspace remoto sin `data/out/local/` | No usar mirror completo; producir artefacto y publicar puntualmente |
| Archivo no llegó a OneDrive tras publicación | Verificar logs del workflow; revisar credenciales |
| Test falla | Diagnosticar; documentar si es pre-existente |
| Objetivo ambiguo | Declarar explícitamente antes de actuar |

---

## 8. Prohibiciones

- No recrear el environment `remote-mirror`.
- No publicar en OneDrive con `SYNC_DRY_RUN=true` (default) sin cambiarlo explícitamente.
- No imprimir ni almacenar secrets.
- No hardcodear valores de `AZURE_CLIENT_ID`, `AZURE_TENANT_ID` ni `MSA_REFRESH_TOKEN`.
- No crear `data/sessions/`, `sessions/` raíz ni `data/local/`.
- No usar mirror completo como ruta normal para diagnósticos desde workspace remoto incompleto.
- No asumir que "crear un archivo en el runner" equivale a "el archivo llegó a OneDrive".
- No usar emojis adicionales en títulos de familias principales de sesión.
