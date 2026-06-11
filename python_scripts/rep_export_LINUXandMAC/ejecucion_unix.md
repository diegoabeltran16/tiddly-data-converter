# Ejecución — Linux / macOS

Guía rápida para ejecutar la herramienta integrada en `python_scripts/rep_export_LINUXandMAC/`.

## Escenario
El exportador vive como código versionable dentro de `python_scripts/` y sus salidas runtime quedan bajo `data/out/local/tiddlers-export/`.

## Requisitos
- Python 3.7+
- `tree` (opcional para estructura ASCII)
- bash/zsh

## Preparar el entorno
```bash
cd /ruta/al/repo
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install pathspec
# opcional (tests)
pip install pytest
```
Si `venv` falla por `ensurepip` revisa `README.md` para la opción `--without-pip` + `get-pip.py`.

## Uso interactivo (wrapper)
```bash
PYTHONPATH=python_scripts python3 python_scripts/rep_export_LINUXandMAC/run_export_menu.py
```
Elige `2` para exportar tiddlers JSON o `3` para generar estructura y exportar.

## Ejecución directa (dry-run)
```bash
PYTHONPATH=python_scripts python3 python_scripts/rep_export_LINUXandMAC/tiddler_exporter_UNIX.py --dry-run --root .
```

## Ejecución real
```bash
PYTHONPATH=python_scripts python3 python_scripts/rep_export_LINUXandMAC/tiddler_exporter_UNIX.py --root .
```
Incluyendo archivos grandes:
```bash
PYTHONPATH=python_scripts python3 python_scripts/rep_export_LINUXandMAC/tiddler_exporter_UNIX.py --root . --include-large --large-action preview
# forzar limite a 5MB
PYTHONPATH=python_scripts python3 python_scripts/rep_export_LINUXandMAC/tiddler_exporter_UNIX.py --root . --max-size 5242880
```
O usar variable de entorno:
```bash
export REPO_EXPORT_MAX_FILE_SIZE=5242880
PYTHONPATH=python_scripts python3 python_scripts/rep_export_LINUXandMAC/tiddler_exporter_UNIX.py --root . --include-large
```

## Verificar salida
```bash
ls -R data/out/local/tiddlers-export | sed -n '1,200p'
# ver un JSON
cat data/out/local/tiddlers-export/<archivo>.json | less
```

## Comprobaciones rápidas
```bash
python3 --version
python3 -c 'import sys; print(sys.executable)'
python3 -m pip --version
```

## Salir del venv
```bash
deactivate
# o cerrar la terminal
```

## Notas
- Usa `--dry-run` primero si no estás seguro del resultado.
- Si la carpeta está anidada y la detección de raíz no es la esperada, fuerza la raíz con `--root <ruta>` o define `REPO_EXPORT_ROOT`.
