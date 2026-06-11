#!/usr/bin/env python3
"""
Módulo: detect_root.py  (Linux / macOS)
Detecta automáticamente la raíz del repositorio objetivo.

Precedencia:
1. Variable de entorno REPO_EXPORT_ROOT
2. Búsqueda de .git subiendo desde el directorio del módulo.
   Si hay múltiples aciertos (herramienta anidada dentro de otro repo)
   devuelve el más externo — el repo que contiene la herramienta.
3. Fallback: parent inmediato del directorio del módulo.

Uso:
    from detect_root import find_repo_root
    ROOT_DIR = find_repo_root(Path(__file__))
"""
import os
import sys
from pathlib import Path


def find_repo_root(caller_file: Path) -> Path:
    """
    Devuelve la raíz del repositorio que contiene (o analiza) esta herramienta.

    Casos soportados
    ----------------
    - Uso correcto (solo carpeta copiada):
        mi-proyecto/rep_export_LINUXandMAC/__file__
        → devuelve  mi-proyecto/

    - Herramienta anidada como repo completo:
        mi-proyecto/repository-export/rep_export_LINUXandMAC/__file__
        → recorre .git de repository-export/ y el de mi-proyecto/
        → devuelve el más externo: mi-proyecto/

    - Modo standalone / desarrollo:
        repository-export/rep_export_LINUXandMAC/__file__
        → solo encuentra .git de repository-export/
        → devuelve repository-export/

    Args:
        caller_file: Path(__file__) del módulo que invoca esta función.

    Returns:
        Path resuelto a la raíz del repositorio objetivo.
    """
    # 1. Variable de entorno tiene máxima prioridad
    env = os.environ.get("REPO_EXPORT_ROOT")
    if env:
        p = Path(env).resolve()
        if p.is_dir():
            return p
        print(
            f"[detect_root] ADVERTENCIA: REPO_EXPORT_ROOT='{env}' no es un directorio válido. Se ignora.",
            file=sys.stderr,
        )

    # 2. Buscar .git subiendo desde el directorio del módulo
    module_dir = Path(caller_file).resolve().parent
    git_roots = [
        candidate
        for candidate in module_dir.parents
        if (candidate / ".git").exists()
    ]

    if git_roots:
        # Devuelve el más externo (outermost = último de la lista, más alto en el árbol).
        # En repos anidados evita quedarse en la carpeta de la herramienta.
        return git_roots[-1]

    # 3. Fallback: parent directo del módulo (comportamiento original)
    fallback = module_dir.parent
    print(
        f"[detect_root] ADVERTENCIA: No se encontró ningún .git subiendo desde '{module_dir}'.\n"
        f"  → Usando fallback: '{fallback}'.\n"
        "  → Especifica la raíz con REPO_EXPORT_ROOT=<path> o la opción --root.",
        file=sys.stderr,
    )
    return fallback
