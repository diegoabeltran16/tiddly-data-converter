#!/usr/bin/env python3
"""
Módulo: large_file_scanner.py  (compartido, mismo contenido en ambos árboles)
Escanea un repositorio y devuelve estadísticas de tamaño de archivos.

Uso:
    from large_file_scanner import scan_large_files, fmt_size, suggest_max

    stats = scan_large_files(root_path, max_bytes=1_048_576)
    # stats.large  → lista de (Path, int_bytes) ordenada desc
    # stats.total  → int, archivos escaneados
    # stats.mean   → float KB
    # stats.median → float KB
    # stats.p75    → float KB
    # stats.suggested_max_bytes → int
"""
import os
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple

# Directorios a ignorar al escanear (igual que los exporters)
_SKIP_DIRS = {'tiddlers-export', 'tiddler_tag_doc', '.git', '__pycache__',
              'node_modules', '.venv', 'venv', 'dist', 'build'}


@dataclass
class ScanResult:
    large: List[Tuple[Path, int]] = field(default_factory=list)
    total: int = 0
    mean: float = 0.0
    median: float = 0.0
    p75: float = 0.0
    suggested_max_bytes: int = 1 * 1024 * 1024


def fmt_size(bytes_: int) -> str:
    """Formatea bytes en B, KB o MB, legible para humanos."""
    if bytes_ >= 1024 * 1024:
        return f"{bytes_ / (1024*1024):.2f} MB"
    if bytes_ >= 1024:
        return f"{bytes_ / 1024:.1f} KB"
    return f"{bytes_} B"


def suggest_max(median_bytes: float) -> int:
    """
    Propone MAX = max(1 MB, 2 × mediana).
    Útil como punto de partida cuando el repo tiene archivos medianos pequeños.
    """
    return max(1 * 1024 * 1024, int(2 * median_bytes))


def scan_large_files(root: Path, max_bytes: int = 1 * 1024 * 1024) -> ScanResult:
    """
    Recorre root y recopila tamaños de todos los archivos (excluyendo _SKIP_DIRS).
    Devuelve ScanResult con archivos > max_bytes y estadísticas del repo.

    Args:
        root:       directorio raíz del repositorio a analizar.
        max_bytes:  umbral en bytes; archivos que superen esto se reportan como "grandes".

    Returns:
        ScanResult poblado con la lista de archivos grandes y estadísticas.
    """
    sizes: List[int] = []
    large: List[Tuple[Path, int]] = []

    for dirpath, dirnames, filenames in os.walk(root):
        # Filtrar directorios ignorados in-place para no descender
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for name in filenames:
            path = Path(dirpath) / name
            try:
                size = path.stat().st_size
            except OSError:
                continue
            sizes.append(size)
            if size > max_bytes:
                large.append((path, size))

    if not sizes:
        return ScanResult()

    sorted_sizes = sorted(sizes)
    n = len(sorted_sizes)
    median_val = statistics.median(sorted_sizes)
    p75_idx = int(0.75 * n)
    p75_val = sorted_sizes[min(p75_idx, n - 1)]
    mean_val = statistics.mean(sorted_sizes)

    large_sorted = sorted(large, key=lambda x: x[1], reverse=True)

    return ScanResult(
        large=large_sorted,
        total=n,
        mean=mean_val / 1024,
        median=median_val / 1024,
        p75=p75_val / 1024,
        suggested_max_bytes=suggest_max(median_val),
    )
