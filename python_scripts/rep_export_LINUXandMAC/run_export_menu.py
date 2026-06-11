#!/usr/bin/env python3
"""
Runner mínimo para abrir el menú interactivo de exportación.
Detecta automáticamente la raíz del repo y lanza el wrapper.
"""
import os
import runpy
import sys
from pathlib import Path

CURRENT_FILE = Path(__file__).resolve()
REPO_ROOT = CURRENT_FILE.parents[2]
PYTHON_SCRIPTS_ROOT = REPO_ROOT / "python_scripts"

# Asegurar que la raíz de módulos Python esté disponible para imports.
if str(PYTHON_SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SCRIPTS_ROOT))
pythonpath = os.environ.get("PYTHONPATH", "")
paths = [p for p in pythonpath.split(os.pathsep) if p]
if str(PYTHON_SCRIPTS_ROOT) not in paths:
    os.environ["PYTHONPATH"] = os.pathsep.join([str(PYTHON_SCRIPTS_ROOT), *paths])

wrapper = PYTHON_SCRIPTS_ROOT / "rep_export_LINUXandMAC" / "scripts" / "export_structure_wrapper_unix.py"
if not wrapper.exists():
    sys.exit(f"No se encontró el wrapper: {wrapper}")

runpy.run_path(str(wrapper), run_name="__main__")
