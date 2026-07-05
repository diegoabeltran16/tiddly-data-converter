#!/usr/bin/env python3
"""
Módulo: cli_utils_UNIX.py
Ubicación: rep-export-LINUXandMAC/

Utilidades comunes para scripts CLI de Linux/macOS:
- safe_print         → Imprime mensajes evitando errores de codificación (emojis).
- prompt_yes_no      → Preguntas interactivas Sí/No con valor por defecto.
- run_cmd            → Ejecutar comandos externos mostrando stdout en vivo.
- get_additional_args→ Parsear argumentos libres introducidos por el usuario.
- confirm_overwrite  → Confirmar sobrescritura de archivos existentes.
- load_ignore_spec   → Cargar patrones de .gitignore (opcional).
- is_ignored         → Verifica si una ruta debe ser ignorada por .gitignore (opcional).
"""
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple, Optional

def safe_print(message: str) -> None:
    """Imprime cadena sin fallar si la consola no soporta algunos caracteres."""
    try:
        print(message)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or 'utf-8'
        filtered = message.encode(encoding, errors='ignore').decode(encoding)
        print(filtered)

def prompt_yes_no(question: str, default: bool = False) -> bool:
    """Pregunta interactiva Sí/No con valor por defecto."""
    default_str = 'S/n' if default else 's/N'
    while True:
        resp = input(f"{question} [{default_str}]: ").strip().lower()
        if not resp:
            return default
        if resp in ('s', 'si', 'y', 'yes'):
            return True
        if resp in ('n', 'no'):
            return False
        safe_print("❗ Respuesta inválida. Usa 's' o 'n'.")

def run_cmd(cmd: List[str], cwd: Optional[Path] = None, env: Optional[dict] = None) -> Tuple[int, str, str]:
    """
    Ejecuta un comando externo y muestra la salida en tiempo real.
    - `env` (opcional): diccionario de entorno para pasar a subprocess.
    Retorna (exit_code, None, None) para compatibilidad.
    """
    safe_print(f"\n▶️ Ejecutando: {' '.join(cmd)}\n")
    process = subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd is not None else None,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )
    for line in process.stdout:
        print(line, end='')  # Muestra cada línea en tiempo real
    process.wait()
    return process.returncode, None, None

def get_additional_args(script_name: str) -> List[str]:
    """Solicita al usuario argumentos adicionales para un script CLI."""
    extras = input(f"Argumentos extra para {script_name} (separados por espacios), o Enter para ninguno: ").strip()
    return extras.split() if extras else []

def confirm_overwrite(path: Path) -> bool:
    """Si `path` existe, pregunta si el usuario desea sobrescribirlo."""
    if path.exists():
        return prompt_yes_no(f"El archivo '{path.name}' ya existe. ¿Sobrescribir?", default=False)
    return True

# Opcional: Si quieres máxima paridad con Windows, agrega:
try:
    from pathspec import PathSpec
except ImportError:
    PathSpec = None

def load_ignore_spec(repo_root: Path):
    """
    Carga y compila los patrones de `.gitignore` desde el directorio raíz.
    Devuelve un PathSpec usable para match_file(path).
    """
    if PathSpec is None:
        return None
    gitignore = repo_root / '.gitignore'
    if not gitignore.is_file():
        return None
    lines = [
        ln.strip() for ln in gitignore.read_text(encoding='utf-8').splitlines()
        if ln.strip() and not ln.strip().startswith('#')
    ]
    if not lines:
        return None
    return PathSpec.from_lines('gitwildmatch', lines)

def is_ignored(path: Path, ignore_spec):
    """
    Verifica si una ruta debe ser ignorada por `.gitignore`.
    Path debe ser relativo o absoluto dentro de repo_root.
    """
    if ignore_spec is None:
        return False
    rel = str(path)
    return ignore_spec.match_file(rel)
