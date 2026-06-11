# 🧠 repository-export
[![CI - Run Tests](https://github.com/diegoabeltran16/repository-export/actions/workflows/python-tests.yml/badge.svg)](https://github.com/diegoabeltran16/repository-export/actions/workflows/python-tests.yml)

> Repositorio multiplataforma para exportar estructuras de proyectos y generar tiddlers TiddlyWiki con control de versiones y pruebas automatizadas.
**Automatiza la creación de documentación semántica a partir de cualquier repositorio de código.**
Convierte cada archivo fuente en un tiddler compatible con [TiddlyWiki](https://tiddlywiki.com), con etiquetas, fechas y contenido listo para navegar, estudiar o versionar.

---

## 🎯 Propósito del proyecto

Permite:
- Documentar código automáticamente
- Clasificar archivos por tipo o contexto semántico
- Versionar documentación sin esfuerzo
- Estudiar repositorios de terceros de forma estructurada

---

## 🛠️ ¿Qué hace?

✔️ Recorre todo el proyecto<br>
✔️ Detecta cambios reales en archivos<br>
✔️ Genera un archivo `.json` por cada archivo válido<br>
✔️ Cada archivo se convierte en un tiddler TiddlyWiki con:
- Título basado en su ruta
- Metadatos básicos (tipo detectado y fechas)
- Bloque de código con resaltado (`markdown`, `python`, `go`, etc.)
- Fecha de creación y modificación


---

## 💻 Uso básico

1. Clona el repositorio que deseas escanear y exportar
2. Dependiendo de tu sistema operativo (OS) descarga la carpeta 
rep-export-LINUXandMAC o rep-export-Windows
3. Pega la carpeta en tu repositorio y asegurate de tener:
**✅ Requisitos**
- Python 3.7+
- Comando `tree` instalado (`sudo apt install tree` o `brew install tree`)
- PowerShell (Windows) o bash/zsh (Unix)
4. (Opcional) Ajusta patrones de exclusión en `.gitignore` o usa `--exclude` / `--exclude-from` para filtrar qué se incluye.
5. Corre el comando que se ajuste a tus OS y elije el menu de opciones que se ajuste a tus necesidades

### Preparar entorno (recomendado)
Antes de ejecutar cualquier script, crea y activa un entorno virtual e instala la dependencia `pathspec`:

En Windows (PowerShell):
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install pathspec
```

En Linux / macOS (bash):
```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install pathspec
```

Nota rápida (si el comando `venv` se queda bloqueado o muestra una traza con `ensurepip`):

- En Windows intenta usar el lanzador: `py -3 -m venv .venv` y luego `.\.venv\Scripts\Activate.ps1`.
- Si sigue fallando, crea el entorno sin `pip` y haz bootstrap manualmente:
	```powershell
	python -m venv .venv --without-pip
	Invoke-WebRequest -UseBasicParsing https://bootstrap.pypa.io/get-pip.py -OutFile get-pip.py
	.\.venv\Scripts\python.exe get-pip.py
	```
- Alternativa: si el entorno ya está activado pero falta `pip`, ejecuta dentro del venv:
	```powershell
	python -m ensurepip --upgrade
	```

Qué esperar al ejecutar el wrapper:

- `--dry-run` o elegir "Simulación" en el menú no escribe archivos; solo muestra qué se haría.
- Ejecución real escribe tiddlers JSON en `data/out/local/tiddlers-export/` (copias gzip en `data/out/local/tiddlers-export/large/` si usas `--include-large --large-action copy`) y hashes en `data/out/local/tiddlers-export/hashes_rep_export/.hashes.json`.

Copiar `repository-export` a otro repo (scripts)

Si prefieres copiar la carpeta completa y excluir metadata/artefactos locales, hay scripts útiles en `scripts/`:

- `scripts/copy_repo.sh` — bash/rsync (Linux/macOS)
- `scripts/copy_repo.ps1` — PowerShell/Robocopy (Windows)

Ejemplo (bash):
```bash
# desde el directorio que contiene repository-export
./scripts/copy_repo.sh ./repository-export /ruta/al/repo/tools/repository-export
```

Ejemplo (PowerShell):
```powershell
# desde la carpeta del proyecto
.\scripts\copy_repo.ps1 -Source .\repository-export -Dest D:\ruta\al\repo\tools\repository-export
```

Ambos excluyen por defecto: `.git`, `.venv`, `tiddlers-export`, `__pycache__` y `.pytest_cache`.

Comprobaciones rápidas (ver que todo está listo)

```powershell
# 1) Versión de Python
python --version

# 2) Ejecutable usado
python -c "import sys; print(sys.executable)"

# 3) Pip y paquete necesario
python -m pip --version
python -m pip show pathspec || pip install pathspec

# 4) Dry-run del exportador (no escribe archivos)
python rep_export_Windows\tiddler_exporter_windows.py --dry-run --root . --new-schema

# 5) Listar salidas (si ejecutas real export)
Get-ChildItem -Recurse .\data\out\local\tiddlers-export\ | Select-Object FullName, Length
```

Salir del entorno virtual (`venv`)

- En PowerShell o Command Prompt (Windows):
```powershell
deactivate
# o cerrar la ventana de la terminal
```
- En bash (Linux/macOS):
```bash
deactivate
# o cerrar la terminal
```

### Requisitos para desarrollo y tests

Para ejecutar los tests y trabajar en el proyecto localmente, tras crear y activar el entorno virtual instale las dependencias de desarrollo:

En Windows (PowerShell):
```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install pathspec pytest
```

En Linux / macOS (bash):
```bash
source .venv/bin/activate
python -m pip install --upgrade pip
pip install pathspec pytest
```

Opcional (recomendado para facilitar imports locales):
```bash
pip install -e .
```

Configuración recomendada para VS Code

- Seleccione el intérprete del proyecto: `Ctrl+Shift+P` → `Python: Select Interpreter` → elija el `.venv` del proyecto.
- (Opcional) Añada `.vscode/settings.json` con las siguientes opciones para que Pylance indexe los módulos locales y habilite `pytest` en el panel de tests:

```json
{
	"python.analysis.extraPaths": [
		"rep_export_Windows",
		"rep_export_LINUXandMAC"
	],
	"python.testing.pytestEnabled": true,
	"python.testing.pytestArgs": ["tests"]
}
```

Con esto Pylance dejará de mostrar advertencias "could not be resolved" para los módulos locales y VS Code podrá ejecutar `pytest` desde el panel de tests.

Nota sobre detección de raíz: los scripts principales aceptan la opción `--root <ruta>` y respetan la variable de entorno `REPO_EXPORT_ROOT`. Úsalo cuando la herramienta esté anidada dentro de otro repositorio para forzar la raíz objetivo.

### Archivos grandes

Al iniciar el wrapper, se escanea el repositorio y se muestra un resumen estadístico (total de archivos, media, mediana, P75). Si hay archivos que superan el límite, el menú te pregunta qué hacer:

| Opción | Resultado |
|--------|-----------|
| 1 — Omitir (default) | Los archivos grandes se saltan |
| 2 — Preview | Se exporta un fragmento de hasta 64 KB |
| 3 — Copy | Se crea una copia gzip en `data/out/local/tiddlers-export/large/` |
| 4 — Embed | El contenido completo se incrusta en el tiddler |
| 5 — Ajustar límite | Permite redefinir el MAX y ver cuántos archivos quedan |

El límite por defecto es **1 MB**. Puedes sobrescribirlo de dos formas:

```bash
# Variable de entorno (persiste en la sesión)
export REPO_EXPORT_MAX_FILE_SIZE=5242880   # 5 MB

# Flag directo al exportador
python tiddler_exporter_windows.py --max-size 5242880
```

Luego ejecuta el wrapper correspondiente según tu OS:

**Nota:** La funcionalidad de carga de tags personalizados desde la carpeta `tiddler_tag_doc` ha sido desactivada. El exportador genera tiddlers JSON basados en la estructura y el contenido del repositorio, sin procesamiento semántico adicional.

### Linux / macOS
```bash
python3 rep-export-LINUXandMAC/scripts/export_structure_wrapper_unix.py
```

### Windows

```bash
python rep_export_Windows\scripts_windows\export_structure_wrapper_windows.py
```

### Uso interactivo (menú)
Los wrappers incluyen un menú interactivo que simplifica las tareas comunes. Al ejecutar el script verás opciones similares a:

- `1)` Generar estructura ASCII
- `2)` Exportar tiddlers JSON
- `3)` Generar estructura y exportar tiddlers
- `4)` Ayuda
- `5)` Salir

Selecciona la opción deseada escribiendo su número y sigue las indicaciones en pantalla (confirmaciones, flags adicionales, etc.).

## 🧭 ¿Para qué sirve?

| Caso | Beneficio |
|------|-----------|
| Estudiar un repo ajeno | Documentación lista para navegar |
| Auditar bugs o deuda técnica | Filtra por tags o analiza estructura |
| Automatizar CI/CD | Exportación controlada por cambios reales |
| Crear datasets para LLM | Markdown estructurado + semántica limpia |

---

## 🔎 Filosofía

- Modularidad
- Simplicidad (KISS)
- Documentación como parte del código
- Mantenibilidad multiplataforma

> “Cualquiera puede hablar, muestrame el codigo” — Linus Torvalds

---

## 📄 Licencia
Apache 2.0 — Puedes usarlo, modificarlo y distribuirlo libremente, siempre que mantengas el aviso de licencia y las condiciones incluidas. 
Este proyecto está hecho para crecer contigo.  
Úsalo, modifícalo, exprímelo.  
Y si lo mejoras: compártelo.


PYTHONPATH=python_scripts python3 python_scripts/rep_export_LINUXandMAC/run_export_menu.py
