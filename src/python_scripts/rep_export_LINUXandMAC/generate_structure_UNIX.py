#!/usr/bin/env python3
"""
Script: generate_structure.py
Plataformas objetivo: Linux y macOS

Genera un archivo `estructura.txt` que muestra el árbol completo
filtrado del repositorio usando solo caracteres ASCII y codificado en UTF-8.
Admite exclusiones sensibles y respetar .gitignore, así como ejecución en "dry-run".

Nota: la salida incluye por defecto una nota final que indica que se han
excluido artefactos comunes como `target/`, caches (`__pycache__`), metadatos
de Windows (`*:Zone.Identifier`), exportes (`rep_export_*`) y archivos
temporales (p. ej. "tiddly-data-converter (Saved).html") para mantener una
vista de estructura mínima.

Uso:
    python3 generate_structure.py [--output PATH]
                                                             [--honor-gitignore]
                                                             [-e PATRON ...] [--exclude-from FILE]
                                                             [--dry-run] [-v]
"""
import os
import sys
import argparse
import logging
import tempfile
from pathlib import Path
try:
    from pathspec import PathSpec
    PATHSPEC_AVAILABLE = True
except Exception:
    PathSpec = None
    PATHSPEC_AVAILABLE = False
from fnmatch import fnmatch
from detect_root import find_repo_root

# Exclusiones por defecto
IGNORED_DIRS = {
    '.git', '.svn', '.hg', '.idea', 'node_modules',
    'dist', 'build', 'venv', '.mypy_cache', '__pycache__'
}
IGNORED_FILES = {'.DS_Store'}
IGNORED_EXT = {
    '.pyc', '.class', '.o', '.exe', '.dll', '.so', '.dylib', '.pdb'
}

ALWAYS_EXCLUDE = {
    '.env', 'secret.env', '*.key', '*.pem', '*.crt', '*.p12', '*.db', '*.sqlite', '*.pyc',
    '__pycache__/', '__pycache__/*', '.vscode/', '.vscode/*', '.idea/', '.idea/*', '.DS_Store',
    'node_modules/', 'node_modules/*', 'dist/', 'dist/*', 'build/', 'build/*', 'venv/', 'venv/*',
    '.mypy_cache/', '.mypy_cache/*', '.git/', '.git/*',
    # Exclusiones adicionales para mantener la vista mínima
    'target/', 'target/*', '*/target/', '*/target/*',
    'rep_export_*', 'rep_export_*/', 'rep_export_*/*',
    '*:Zone.Identifier',
    'tiddly-data-converter (Saved).html', '*/tiddly-data-converter (Saved).html',
}


def load_ignore_spec(repo_root: Path):
    """Carga PathSpec desde .gitignore si existe."""
    gitignore = repo_root / '.gitignore'
    if not gitignore.is_file():
        return None
    lines = [
        ln.strip() for ln in gitignore.read_text(encoding='utf-8').splitlines()
        if ln.strip() and not ln.strip().startswith('#')
    ]
    if not lines:
        return None
    # Si PathSpec está disponible, usarlo; si no, devolver un fallback simple
    if PATHSPEC_AVAILABLE and PathSpec is not None:
        return PathSpec.from_lines('gitwildmatch', lines)
    logging.warning("Módulo 'pathspec' no disponible: usando fallback simple para .gitignore")

    class SimpleSpec:
        def __init__(self, patterns):
            self.patterns = patterns

        def match_file(self, rel: str) -> bool:
            # Intentar emparejar con fnmatch y algunas reglas simples
            for pat in self.patterns:
                # Normalizar patrones que comienzan con '/'
                p = pat.lstrip('/')
                if fnmatch(rel, p) or fnmatch(rel + ('/' if not rel.endswith('/') else ''), p):
                    return True
                # Si el patrón termina en '/', tratarlo como directorio
                if p.endswith('/') and rel.startswith(p.rstrip('/')):
                    return True
            return False

    return SimpleSpec(lines)


def should_skip(path: Path, repo_root: Path, exclude_patterns, honor_gitignore: bool, ignore_spec: PathSpec):
    rel = path.relative_to(repo_root).as_posix()
    if path.is_dir() and not rel.endswith('/'):
        rel += '/'
    # .gitignore
    if honor_gitignore and ignore_spec and ignore_spec.match_file(rel):
        # Excepciones: siempre incluir .gitignore y estructura.txt
        if rel in ('.gitignore', 'estructura.txt'):
            return False
        return True
    # Patrones extra (glob)
    all_patterns = list(exclude_patterns) + list(ALWAYS_EXCLUDE)
    if any(fnmatch(rel, pat) for pat in all_patterns):
        logging.info(f"Excluyendo por patrón: {rel}")
        return True
    # Ocultos (excepto .gitignore y .github)
    if path.name.startswith('.') and path.name not in {'.gitignore', '.github'}:
        return True
    return False


def ascii_tree(root: Path, repo_root: Path, prefix='', args=None, ignore_spec=None):
    """Construye lista de líneas con árbol ASCII filtrado"""
    exclude_patterns = getattr(args, 'exclude', []) or []
    honor_gitignore = getattr(args, 'honor_gitignore', False)

    lines = []
    try:
        entries = sorted(root.iterdir(), key=lambda p: p.name.lower())
    except PermissionError:
        logging.warning(f"Permiso denegado: {root}")
        return lines

    entries = [
        e for e in entries
        if not should_skip(e, repo_root, exclude_patterns, honor_gitignore, ignore_spec)
    ]

    for idx, entry in enumerate(entries):
        connector = '└── ' if idx == len(entries) - 1 else '├── '
        lines.append(f"{prefix}{connector}{entry.name}")
        if entry.is_dir() and not entry.is_symlink():
            extension = '    ' if idx == len(entries) - 1 else '│   '
            lines += ascii_tree(entry, repo_root, prefix + extension, args, ignore_spec)
    return lines


def write_atomic(path: Path, lines):
    """Escribe de forma atómica reemplazando el archivo destino."""
    tmp = tempfile.NamedTemporaryFile(
        'w',
        delete=False,
        encoding='utf-8',
        dir=path.parent
    )
    with tmp:
        tmp.write('\n'.join(lines))
    Path(tmp.name).replace(path)
    logging.info(f"Estructura escrita en {path}")


def parse_args():
    p = argparse.ArgumentParser(
        description="Genera un árbol ASCII del proyecto con exclusiones de privacidad."
    )
    p.add_argument(
        '--output', '-o', type=Path, default=Path('estructura.txt'),
        help="Archivo de destino (por defecto: <root>/estructura.txt)"
    )
    p.add_argument(
        '--honor-gitignore', action='store_true',
        help="Excluir patrones listados en .gitignore"
    )
    p.add_argument(
        '-e', '--exclude', action='append', default=[],
        help="Patrón glob adicional a excluir (repetible)"
    )
    p.add_argument(
        '--exclude-from', type=Path,
        help="Archivo con patrones glob a excluir (uno por línea)"
    )
    p.add_argument(
        '--dry-run', action='store_true',
        help="Imprime árbol sin escribir archivo"
    )
    p.add_argument(
        '-v', '--verbose', action='count', default=0,
        help="Aumenta nivel de detalle en logs"
    )
    p.add_argument('--force', '-f', action='store_true', help="Sobrescribir sin preguntar.")
    p.add_argument('--root', type=Path, default=None,
                   help="Raíz del repositorio a analizar. Sobreescribe detección automática.")
    return p.parse_args()


def main():
    args = parse_args()
    level = logging.WARNING - (10 * args.verbose)
    logging.basicConfig(level=level, format='[%(levelname)s] %(message)s')

    repo_root = Path(args.root).resolve() if args.root else find_repo_root(Path(__file__))
    os.chdir(repo_root)

    ignore_spec = load_ignore_spec(repo_root) if args.honor_gitignore else None

    if args.exclude_from and args.exclude_from.is_file():
        extra = [
            line.strip() for line in
            args.exclude_from.read_text(encoding='utf-8').splitlines()
            if line.strip() and not line.startswith('#')
        ]
        args.exclude.extend(extra)

    logging.info(f"Generando estructura desde {repo_root}")
    lines = ascii_tree(
        repo_root, repo_root, prefix='',
        args=args, ignore_spec=ignore_spec
    )
    # Añadir nota explicativa al final del árbol para la vista mínima
    note_lines = [
        '',
        '# Nota: se han excluido de esta vista los artefactos de build (target/),',
        '# caches (__pycache__), metadatos de Windows (*:Zone.Identifier),',
        '# copias de exportación (rep_export_*) y archivos temporales como',
        '# "tiddly-data-converter (Saved).html" para mantener la estructura mínima.',
    ]
    lines.extend(note_lines)

    if args.dry_run:
        print('\n'.join(lines))
        logging.info("[dry-run] no se escribió archivo")
        return

    output_path = args.output if args.output.is_absolute() else repo_root / args.output

    if output_path.exists() and not args.force:
        resp = input(f"El archivo '{output_path.name}' ya existe. ¿Sobrescribir? [s/N]: ").strip().lower()
        if resp not in ('s', 'y', 'si', 'yes'):
            print("Operación cancelada por el usuario.")
            return

    write_atomic(output_path, lines)
    print(f"\n📂 Estructura exportada a: {output_path}")


if __name__ == '__main__':
    main()
