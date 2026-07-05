#!/usr/bin/env python3
"""
📦 Módulo: tag_mapper_UNIX.py (Linux/macOS)
🎯 Plataforma: Linux / macOS

Función:
Genera tags semánticos para archivos del repositorio.
Orden de precedencia:
1. Tags personalizados desde JSON en `tiddler_tag_doc/`.
2. Tag derivado por extensión o nombre especial.
3. Fallback `--- 🧬 Por Clasificar`.

También provee:
- `load_ignore_spec(repo_root)` para interpretar `.gitignore`.
- `detect_language(file_path)` para syntax highlighting.

Salida:
List[str] con tags en sintaxis TiddlyWiki (`[[TagName]]`).
"""
import json
import os
from pathlib import Path
from typing import List, Dict, Any

# Intentar importar pathspec para respetar .gitignore
try:
    import pathspec  # type: ignore
except ImportError:
    pathspec = None  # type: ignore

# ========================================
# Rutas y carga de JSON personalizados
# ========================================
TIDDLER_TAG_DIR = Path(__file__).resolve().parent / "tiddler_tag_doc"

# Mapa de título a tags personalizados
title_to_tags: Dict[str, List[str]] = {}
if TIDDLER_TAG_DIR.is_dir():
    for json_file in sorted(TIDDLER_TAG_DIR.glob("*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for item in data:
                    title = item.get("title", "").strip()
                    tags_str = item.get("tags", "").strip()
                    if title and tags_str:
                        title_to_tags[title] = tags_str.split()
        except Exception as e:
            print(f"⚠️ Error leyendo {json_file.name}: {e}")

# ========================================
# Mapeo extensión → Tag
# ========================================
EXTENSION_TAG_MAP: Dict[str, str] = {
    # Code
    ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript", ".go": "Go", ".rs": "Rust",
    ".java": "Java", ".c": "C", ".cpp": "C++", ".cc": "C++", ".hpp": "C++",
    ".rb": "Ruby", ".php": "PHP", ".kt": "Kotlin", ".swift": "Swift",
    # Scripting
    ".sh": "Shell", ".bash": "Shell", ".ps1": "PowerShell", ".bat": "Batch",
    # Markup/data
    ".md": "Markdown", ".html": "HTML", ".css": "CSS", ".xml": "XML",
    ".json": "JSON", ".yml": "YAML", ".yaml": "YAML", ".toml": "TOML",
    ".csv": "CSV", ".sql": "SQL", ".txt": "Text"
}

SPECIAL_FILENAMES: Dict[str, str] = {
    "Dockerfile": "Dockerfile",
    "Makefile": "Makefile",
    "README": "README",
    "LICENSE": "License",
    ".gitignore": "Git"
}

DEFAULT_TAG = "--- 🧬 Por Clasificar"


def _repo_root_for_tags() -> Path:
    env_root = os.environ.get("REPO_EXPORT_ROOT")
    if env_root:
        candidate = Path(env_root).resolve()
        if candidate.is_dir():
            return candidate
    module_dir = Path(__file__).resolve().parent
    git_roots = [
        candidate
        for candidate in module_dir.parents
        if (candidate / ".git").exists()
    ]
    if git_roots:
        return git_roots[-1]
    return module_dir.parent

# ========================================
# Función para interpretar .gitignore
# ========================================
def load_ignore_spec(repo_root: Path) -> Any:
    """
    Retorna un PathSpec para ignorar rutas según .gitignore.
    Si pathspec no está disponible, nunca ignora nada.
    """
    if pathspec:
        gitignore = repo_root / '.gitignore'
        if gitignore.is_file():
            patterns = gitignore.read_text(encoding='utf-8').splitlines()
            return pathspec.PathSpec.from_lines('gitwildmatch', patterns)
    # Dummy spec que no ignora
    class DummySpec:
        def match_file(self, file_path: str) -> bool:
            return False
    return DummySpec()

# ========================================
# Mapeo para syntax highlighting
# ========================================
HIGHLIGHT_MAP: Dict[str, str] = {
    '.py': 'python', '.js': 'javascript', '.ts': 'typescript', '.go': 'go', '.rs': 'rust',
    '.java': 'java', '.c': 'c', '.cpp': 'cpp', '.txt': 'text', '.md': 'markdown',
    '.json': 'json', '.html': 'html', '.css': 'css', '.yml': 'yaml', '.xml': 'xml'
}

SPECIAL_HIGHLIGHT: Dict[str, str] = {
    '.gitignore': 'gitignore',
    'Dockerfile': 'dockerfile',
    'Makefile': 'makefile',
    'README': 'markdown',
    'LICENSE': 'text'
}

# ========================================
# Funciones principales
# ========================================

def detect_language(file_path: Path) -> str:
    """Devuelve la etiqueta de lenguaje para bloques Markdown."""
    name = file_path.name
    if name in SPECIAL_HIGHLIGHT:
        return SPECIAL_HIGHLIGHT[name]
    return HIGHLIGHT_MAP.get(file_path.suffix.lower(), 'text')

def get_tags_for_file(file_path: Path) -> List[str]:
    """Devuelve lista de tags TiddlyWiki para `file_path`."""
    # Construir título basado en ruta (debe coincidir con safe_title del exporter)
    try:
        repo_root = _repo_root_for_tags()
        rel = file_path.relative_to(repo_root)
        title = rel.as_posix()
    except Exception:
        title = file_path.name

    # Cargar tags personalizados si existen
    if title in title_to_tags:
        tags = title_to_tags[title].copy()
    else:
        # Derivar tag de tipo con emoji
        name = file_path.name
        ext = file_path.suffix.lower()
        if name in SPECIAL_FILENAMES:
            base = SPECIAL_FILENAMES[name]
        elif ext in EXTENSION_TAG_MAP:
            base = EXTENSION_TAG_MAP[ext]
        else:
            base = DEFAULT_TAG
        if base == DEFAULT_TAG:
            tags = [f"[[{base}]]"]
        else:
            tags = [f"[[⚙️ {base}]]"]

    # Tag basado en nombre de archivo (sin emoji)
    tags.append(f"[[{title}]]")
    # Tag de grupo sin emoji
    tags.append("[[--- Codigo]]")

    return tags

# CLI para pruebas rápidas
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Uso: python tag_mapper_UNIX.py <ruta_archivo>")
        sys.exit(1)
    result = get_tags_for_file(Path(sys.argv[1]))
    print(result)
