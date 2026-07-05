#!/usr/bin/env python3
"""
Script: tiddler_exporter_UNIX.py (Linux/macOS)
Plataforma: Linux, macOS

Este script recorre los archivos del repositorio y genera archivos JSON (tiddlers) para TiddlyWiki.
Mejoras:
- Ignora patrones de .gitignore (salvo `estructura.txt` y `.gitignore`).
- Exporta solo archivos con extensiones válidas o nombres especiales, incluyendo `.toml`.
- Detecta cambios usando hashes para exportar solo archivos modificados.
- Añade tags semánticos con `tag_mapper_UNIX.get_tags_for_file`:
  * Tag de tipo con emoji ⚙️ (p.ej. ⚙️ Python).
  * Tag basado en nombre `-ruta_con_underscores` sin emoji.
  * Tag de grupo `--- Codigo`.
- Genera bloque Markdown con syntax highlighting adecuado desde `tag_mapper_UNIX.detect_language`.
- Soporta `--dry-run` para simulación.

Uso:
  python3 tiddler_exporter_UNIX.py [--dry-run]
"""
import os
import sys
import re
import gzip
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
import argparse
from fnmatch import fnmatch
# Import modules robustly so the script can be run as a module (`-m`) or
# as a script (direct path). Try local/top-level imports first, then fall
# back to package-qualified imports if running as `python -m rep_export_LINUXandMAC...`.
try:
    import tag_mapper_UNIX
    from tag_mapper_UNIX import load_ignore_spec
    from cli_utils_UNIX import safe_print
    from detect_root import find_repo_root
except Exception:
    from rep_export_LINUXandMAC import tag_mapper_UNIX
    from rep_export_LINUXandMAC.tag_mapper_UNIX import load_ignore_spec
    from rep_export_LINUXandMAC.cli_utils_UNIX import safe_print
    from rep_export_LINUXandMAC.detect_root import find_repo_root

# ===== Configuración =====
TDC_REPO_ROOT = Path(__file__).resolve().parents[3]
ROOT_DIR = find_repo_root(Path(__file__))
SCRIPT_DIR = Path(__file__).parent
OUTPUT_DIR = TDC_REPO_ROOT / "data" / "out" / "local" / "tiddlers-export"
HASH_DIR = OUTPUT_DIR / "hashes_rep_export"
HASH_FILE = HASH_DIR / ".hashes.json"
# Por defecto no aplicamos .gitignore hasta que se procese la línea de comandos.
# Esto permite habilitar/deshabilitar la respetación de .gitignore vía args.
IGNORE_SPEC = None

VALID_EXT = set(tag_mapper_UNIX.EXTENSION_TAG_MAP.keys()) | {'.toml'}
ALLOWED_NAMES = set(tag_mapper_UNIX.SPECIAL_FILENAMES.keys())
# Límite de tamaño de archivo para evitar cargar binarios enormes en memoria
MAX_FILE_SIZE_BYTES = int(os.environ.get('REPO_EXPORT_MAX_FILE_SIZE', 1 * 1024 * 1024))  # default 1 MB
PREVIEW_BYTES = 65536  # 64 KB
# Listas que pueden ser rellenadas por argumentos CLI
EXCLUDE_DIRS = []  # directorios relativos al ROOT_DIR a excluir (prefijo)
EXCLUDE_PATTERNS = []  # patrones glob para excluir rutas
DEFAULT_EXCLUDED_DIR_NAMES = {
    '.git',
    '.pytest_cache',
    '__pycache__',
    'hashes_rep_export',
    'repository_export.egg-info',
    'tiddler_tag_doc',
    'tiddlers-export',
}
DEFAULT_EXCLUDED_FILE_NAMES = {'.hashes.json'}
DEFAULT_EXCLUDED_REL_DIRS = {
    'data/out/local/tiddlers-export',
    'data/out/local/tiddlers-export/hashes_rep_export',
    'python_scripts/rep_export_LINUXandMAC/tiddlers-export',
}


def _is_excluded_rel_dir(rel_path: str) -> bool:
    rel_path = rel_path.rstrip('/')
    return any(rel_path == ex or rel_path.startswith(ex + '/') for ex in DEFAULT_EXCLUDED_REL_DIRS)

def get_all_files():
    """
    Genera todos los archivos a exportar:
    - Siempre incluye 'estructura.txt' y '.gitignore'.
    - Excluye archivos según .gitignore.
    - Filtra por extensiones válidas o nombres especiales.
    """
    for dirpath, dirnames, filenames in os.walk(ROOT_DIR):
        dirpath = Path(dirpath)
        # Evitar directorios de export/data y excluir directorios solicitados
        filtered = []
        for d in dirnames:
            full = dirpath / d
            try:
                rel_full = full.relative_to(ROOT_DIR).as_posix()
            except Exception:
                rel_full = str(full)
            if d in DEFAULT_EXCLUDED_DIR_NAMES or d.endswith('.egg-info') or _is_excluded_rel_dir(rel_full):
                continue
            skip = False
            for ex in EXCLUDE_DIRS:
                if rel_full == ex or rel_full.startswith(ex + '/'):
                    skip = True
                    break
            if not skip:
                filtered.append(d)
        dirnames[:] = filtered
        for name in filenames:
            path = Path(dirpath) / name
            rel = path.relative_to(ROOT_DIR).as_posix()
            if name in DEFAULT_EXCLUDED_FILE_NAMES:
                continue
            if _is_excluded_rel_dir(rel):
                continue
            # Siempre incluir estos
            if rel in ('estructura.txt', '.gitignore'):
                yield path
                continue
            # Skip si coincide con patrones pasados por --exclude
            if EXCLUDE_PATTERNS and any(fnmatch(rel, pat) for pat in EXCLUDE_PATTERNS):
                continue
            # Skip si la ruta está dentro de un directorio excluido
            if any(rel == ex or rel.startswith(ex + '/') for ex in EXCLUDE_DIRS):
                continue
            # Skip según .gitignore
            if IGNORE_SPEC and IGNORE_SPEC.match_file(rel):
                continue
            # Extensiones y nombres permitidos
            if path.suffix.lower() in VALID_EXT or name in ALLOWED_NAMES:
                yield path

def calc_hash(content: str) -> str:
    return hashlib.sha1(content.encode('utf-8')).hexdigest()


def hash_file_streaming(path: Path) -> str:
    """Calcula SHA-1 en bloques de 64 KB sin cargar el archivo completo en memoria."""
    h = hashlib.sha1()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def safe_title(path: Path) -> str:
    """
    Retorna la ruta relativa natural como display title para TiddlyWiki (separador '/').
    Ejemplo: 'rep_export_LINUXandMAC/tiddler_exporter_UNIX.py'
    """
    return path.relative_to(ROOT_DIR).as_posix()


def sanitize_filename(path: Path) -> str:
    """
    Genera un nombre de archivo seguro para disco.
    Solo permite: letras, dígitos, puntos, guiones y guiones bajos.
    Trunca en 200 caracteres añadiendo sufijo de hash para evitar colisiones.
    """
    rel = path.relative_to(ROOT_DIR).as_posix()
    safe = re.sub(r'[^a-zA-Z0-9._-]', '_', rel.replace('/', '_'))
    safe = safe.lstrip('.-_')
    if not safe:
        safe = f"unnamed_{hashlib.sha1(rel.encode()).hexdigest()[:8]}"
    if len(safe) > 200:
        suffix = hashlib.sha1(rel.encode()).hexdigest()[:8]
        safe = safe[:191] + '_' + suffix
    return safe

def detect_language(path: Path) -> str:
    """Detecta lenguaje para syntax highlighting."""
    ext = path.suffix.lower().lstrip('.')
    return tag_mapper_UNIX.EXTENSION_TAG_MAP.get(path.suffix.lower(), ext)


def build_large_tiddler(file: Path, action: str = 'preview', preview_bytes: int = PREVIEW_BYTES) -> dict:
    """
    Crea un tiddler para archivos grandes sin leer todo su contenido.
    action: 'preview' | 'copy' | 'embed'
    """
    title = safe_title(file)
    tags_semantic = tag_mapper_UNIX.get_tags_for_file(file)
    rel_path = str(file.relative_to(ROOT_DIR))
    size_bytes = file.stat().st_size

    raw_head = b''
    try:
        with open(file, 'rb') as f:
            raw_head = f.read(4096)
    except OSError:
        pass
    is_binary = b'\x00' in raw_head

    if action == 'embed':
        try:
            content = file.read_text(encoding='utf-8', errors='replace')
        except Exception:
            content = ''
        lang = detect_language(file)
        text = f'```{lang}\n{content}\n```'
    elif action == 'copy':
        large_dir = OUTPUT_DIR / 'large'
        large_dir.mkdir(parents=True, exist_ok=True)
        gz_name = sanitize_filename(file) + '.gz'
        gz_path = large_dir / gz_name
        try:
            with open(file, 'rb') as f_in, gzip.open(gz_path, 'wb') as f_out:
                while True:
                    chunk = f_in.read(65536)
                    if not chunk:
                        break
                    f_out.write(chunk)
            copy_ref = str(gz_path.relative_to(OUTPUT_DIR.parent))
        except Exception as e:
            copy_ref = f'[error al copiar: {e}]'
        text = (
            f'> Archivo grande ({size_bytes/1024:.1f} KB). '
            f'Copia comprimida: `{copy_ref}`'
        )
    else:  # 'preview'
        if is_binary:
            text = f'> [binary] Archivo binario ({size_bytes/1024:.1f} KB). Vista previa no disponible.'
        else:
            try:
                preview = raw_head[:preview_bytes].decode('utf-8', errors='replace')
            except Exception:
                preview = ''
            lang = detect_language(file)
            text = (
                f'> PREVIEW: primeros {preview_bytes//1024} KB '
                f'de {size_bytes/1024:.1f} KB totales.\n\n'
                f'```{lang}\n{preview}\n```'
            )

    return {
        'title': title,
        'text': text,
        'type': 'text/markdown',
        'tags': ' '.join(tags_semantic),
        'tags_list': tags_semantic,
        'path': rel_path,
        'large_file': True,
        'size_bytes': size_bytes,
        'is_binary': is_binary,
        'large_action': action,
    }


def export_tiddlers(
    dry_run: bool = False,
    include_large: bool = False,
    large_action: str = 'preview',
    preview_bytes: int = PREVIEW_BYTES,
    max_size: int = None,
):
    """
    Exporta tiddlers JSON para archivos modificados.
    """
    effective_max = max_size if max_size is not None else MAX_FILE_SIZE_BYTES
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    HASH_DIR.mkdir(parents=True, exist_ok=True)
    # Carga hashes previos
    old_hashes = {}
    if HASH_FILE.exists():
        try:
            old_hashes = json.loads(HASH_FILE.read_text(encoding='utf-8'))
        except Exception:
            old_hashes = {}
    new_hashes = {}
    changed = []

    for file in get_all_files():
        rel = str(file.relative_to(ROOT_DIR))
        if file.stat().st_size > effective_max:
            if not include_large:
                safe_print(f"[skip] '{rel}' supera el limite de {effective_max // 1024} KB.")
                continue
            h = hash_file_streaming(file)
            new_hashes[rel] = h
            if old_hashes.get(rel) == h:
                continue
            tiddler = build_large_tiddler(file, action=large_action, preview_bytes=preview_bytes)
            out = OUTPUT_DIR / f"{sanitize_filename(file)}.json"
            if dry_run:
                safe_print(f"[dry-run large] {rel}")
            else:
                out.write_text(json.dumps(tiddler, ensure_ascii=False, indent=2), encoding='utf-8')
                safe_print(f"Exported [large/{large_action}]: {rel}")
            changed.append(rel)
            continue
        h = hash_file_streaming(file)
        new_hashes[rel] = h
        if old_hashes.get(rel) == h:
            continue
        try:
            content = file.read_text(encoding='utf-8', errors='replace')
        except Exception:
            continue
        title = safe_title(file)
        tags = tag_mapper_UNIX.get_tags_for_file(file)
        lang = detect_language(file)
        text_md = (
            "## [[Tags]]\n"
            f"{' '.join(tags)}\n\n"
            f"```{lang}\n{content}\n```"
        )
        tiddler = {
            'title': title,
            'text': text_md,
            'tags': ' '.join(tags),
            'type': 'text/markdown',
            'created': datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')[:17],
            'modified': datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')[:17]
        }
        out = OUTPUT_DIR / f"{sanitize_filename(file)}.json"
        if dry_run:
            safe_print(f"[dry-run] {rel}")
        else:
            out.write_text(json.dumps(tiddler, ensure_ascii=False, indent=2), encoding='utf-8')
            safe_print(f"Exported: {rel}")
        changed.append(rel)

    if not dry_run:
        HASH_DIR.mkdir(parents=True, exist_ok=True)
        HASH_FILE.write_text(json.dumps(new_hashes, indent=2), encoding='utf-8')

    # Reporte final
    safe_print(f"\nTotal cambios: {len(changed)}")
    for c in changed:
        safe_print(f"  - {c}")
if __name__ == '__main__':
    _p = argparse.ArgumentParser(description="Exporta tiddlers JSON del repositorio.")
    _p.add_argument('--dry-run', action='store_true', help="Simular sin escribir archivos.")
    _p.add_argument('--include-large', action='store_true',
                    help="Incluir archivos grandes (por encima de --max-size).")
    _p.add_argument('--large-action', choices=['preview', 'copy', 'embed'], default='preview',
                    help="Cómo exportar archivos grandes: preview (default) | copy | embed.")
    _p.add_argument('--preview-bytes', type=int, default=PREVIEW_BYTES,
                    help=f"Bytes a incluir en el preview (default {PREVIEW_BYTES}).")
    _p.add_argument('--max-size', type=int, default=None,
                    help="Límite de tamaño en bytes. Sobreescribe MAX_FILE_SIZE_BYTES.")
    _p.add_argument('--root', type=Path, default=None,
                    help="Raíz del repositorio objetivo. Sobreescribe detección automática.")
    # Control sobre si respetar .gitignore (por defecto: sí)
    _p.add_argument('--honor-gitignore', dest='honor_gitignore', action='store_true',
                    help='Respetar patrones de .gitignore (por defecto).')
    _p.add_argument('--no-honor-gitignore', dest='honor_gitignore', action='store_false',
                    help="No respetar .gitignore (exportar todo)")
    _p.set_defaults(honor_gitignore=True)
    # Excluir patrones/dirs desde CLI
    _p.add_argument('-e', '--exclude', action='append', default=[],
                    help='Patrón glob para excluir rutas (repetible).')
    _p.add_argument('--exclude-dir', action='append', default=[],
                    help='Directorios a excluir (ruta relativa o absoluta, repetible).')
    _p.add_argument('--exclude-from', type=Path, default=None,
                    help='Archivo con patrones glob a excluir, uno por línea.')
    _args = _p.parse_args()
    if _args.root:
        ROOT_DIR = Path(_args.root).resolve()
    os.environ["REPO_EXPORT_ROOT"] = str(ROOT_DIR)
    # Cargar .gitignore solo si el usuario lo desea
    if getattr(_args, 'honor_gitignore', True):
        IGNORE_SPEC = load_ignore_spec(ROOT_DIR)
    else:
        IGNORE_SPEC = None
    # Procesar exclusiones desde CLI
    EXCLUDE_PATTERNS = list(_args.exclude or [])
    if _args.exclude_from and _args.exclude_from.is_file():
        try:
            extra = [ln.strip() for ln in _args.exclude_from.read_text(encoding='utf-8').splitlines() if ln.strip() and not ln.strip().startswith('#')]
            EXCLUDE_PATTERNS.extend(extra)
        except Exception:
            pass
    EXCLUDE_DIRS = []
    for d in (_args.exclude_dir or []):
        p = Path(d)
        try:
            if p.is_absolute():
                rel = str(p.relative_to(ROOT_DIR).as_posix())
            else:
                rel = str(Path(d).as_posix()).lstrip('./')
            if rel.endswith('/'):
                rel = rel.rstrip('/')
            EXCLUDE_DIRS.append(rel)
        except Exception:
            # fallback: use as-is
            EXCLUDE_DIRS.append(str(d))
    export_tiddlers(
        dry_run=_args.dry_run,
        include_large=_args.include_large,
        large_action=_args.large_action,
        preview_bytes=_args.preview_bytes,
        max_size=_args.max_size,
    )
