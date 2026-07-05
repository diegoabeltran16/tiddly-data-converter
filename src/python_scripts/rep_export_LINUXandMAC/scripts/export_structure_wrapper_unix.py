#!/usr/bin/env python3
"""
🤖 Asistente interactivo de exportación para Linux/macOS
Ubicación: rep-export-LINUXandMAC/scripts/export_structure_wrapper_unix.py

Guía paso a paso para:
 1) Generar estructura ASCII
 2) Exportar tiddlers JSON
 3) Ejecutar ambos secuencialmente
 4) Mostrar ayuda
 5) Salir

Utiliza `cli_utils_UNIX.py` para:
- prompt_yes_no, confirm_overwrite
- run_cmd con salida detallada
- get_additional_args
- safe_print para evitar errores Unicode
"""
import sys
import os
from pathlib import Path

# Incluir raiz de modulos y carpeta del paquete para imports directos/paquete.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rep_export_LINUXandMAC.cli_utils_UNIX import (
    prompt_yes_no,
    run_cmd,
    get_additional_args,
    confirm_overwrite,
    safe_print
)
from rep_export_LINUXandMAC.large_file_scanner import scan_large_files, fmt_size


def show_help():
    safe_print(__doc__)
    safe_print("Ejemplo: opción 3 ejecuta ambos pasos en secuencia.")


def get_menu_choice() -> str:
    choice = input("Selecciona [1-5]: ").strip()
    if choice not in ('1','2','3','4','5'):
        safe_print("❌ Opción inválida. Debe ser 1-5.")
        return get_menu_choice()
    return choice


def main():
    base = Path(__file__).resolve().parent.parent
    repo_root = base.parents[2]
    python_scripts_root = base.parent
    target_root = repo_root
    struct = base / 'generate_structure_UNIX.py'
    export = base / 'tiddler_exporter_UNIX.py'

    # Verificar scripts
    missing = [s for s in (struct, export) if not s.is_file()]
    if missing:
        safe_print(f"❌ No se encontraron: {', '.join(str(m) for m in missing)}")
        sys.exit(1)

    # Sobreescritura opcional de la raíz del repositorio
    root_override = None
    if prompt_yes_no("¿Especificar raíz del repositorio manualmente?", default=False):
        root_override = input("Ruta del repositorio objetivo: ").strip() or None
    if root_override:
        target_root = Path(root_override).resolve()

    # --- Escaneo de archivos grandes ---
    scan_root = target_root
    large_include = False
    large_action = 'preview'
    large_max_size = None

    try:
        stats = scan_large_files(scan_root)
    except Exception:
        stats = None

    if stats and stats.large:
        safe_print(f"\n⚠  Archivos grandes detectados: {len(stats.large)} archivo(s)")
        safe_print(f"   Repositorio: {stats.total} archivos  |  Media: {fmt_size(int(stats.mean))}  |  Mediana: {fmt_size(int(stats.median))}  |  P75: {fmt_size(int(stats.p75))}")
        safe_print(f"   Límite MAX sugerido: {fmt_size(stats.suggested_max_bytes)}")
        safe_print("   Top archivos grandes:")
        for fpath, fsize in stats.large[:5]:
            try:
                rel = fpath.relative_to(scan_root)
            except ValueError:
                rel = fpath
            safe_print(f"     {fmt_size(fsize):>10}  {rel}")
        safe_print("\n¿Qué hacer con los archivos grandes?")
        safe_print("  1) Omitir (default)")
        safe_print("  2) Incluir todos — modo: preview (primeros 64 KB de texto)")
        safe_print("  3) Incluir todos — modo: copy (copia gzip en tiddlers-export/large/)")
        safe_print("  4) Incluir todos — modo: embed (contenido completo en tiddler)")
        safe_print("  5) Ajustar límite MAX y re-evaluar")
        large_choice = input("Selecciona [1-5, Enter=1]: ").strip() or '1'
        if large_choice == '2':
            large_include, large_action = True, 'preview'
        elif large_choice == '3':
            large_include, large_action = True, 'copy'
        elif large_choice == '4':
            large_include, large_action = True, 'embed'
        elif large_choice == '5':
            try:
                mb = float(input(f"  Nuevo límite en MB [{stats.suggested_max_bytes // (1024*1024):.1f}]: ").strip() or str(stats.suggested_max_bytes / (1024*1024)))
                large_max_size = int(mb * 1024 * 1024)
                safe_print(f"  Límite establecido: {fmt_size(large_max_size)}")
                stats2 = scan_large_files(scan_root, large_max_size)
                safe_print(f"  Con este límite: {len(stats2.large)} archivo(s) grande(s)")
            except (ValueError, Exception):
                safe_print("  Valor inválido, se usará el límite por defecto.")
    elif stats:
        safe_print(f"\n✅ Sin archivos grandes detectados ({stats.total} archivos, máximo sugerido: {fmt_size(stats.suggested_max_bytes)})")

    while True:
        safe_print("\n=== Menú de Opciones ===")
        safe_print("1) Generar estructura ASCII")
        safe_print("2) Exportar tiddlers JSON")
        safe_print("3) Generar estructura y exportar tiddlers")
        safe_print("4) Ayuda")
        safe_print("5) Salir")
        choice = get_menu_choice()

        if choice == '5':
            safe_print("👋 ¡Hasta luego!")
            break
        if choice == '4':
            show_help()
            continue

        # Paso 1: Generar estructura
        if choice in ('1','3'):
            safe_print("\n🛠️ Configuración Estructura ASCII")
            args = []
            if prompt_yes_no("¿Excluir patrones de .gitignore? (no oculta .gitignore)", default=False):
                args.append('--honor-gitignore')

            # Nota informativa y sugerencias inferidas
            safe_print("\nNota: por defecto sugerimos excluir artefactos comunes: target/, __pycache__/,")
            safe_print("*:Zone.Identifier, rep_export_* y 'tiddly-data-converter (Saved).html'.")

            # Helper: selección múltiple por números (ej: 1,3-5)
            def prompt_multi_select(prompt_text, options):
                safe_print(prompt_text)
                for i, opt in enumerate(options, start=1):
                    safe_print(f"  {i}) {opt}")
                sel = input("Selecciona números separados por comas (Enter=ninguno, 'all'=todos): ").strip()
                if not sel:
                    return []
                if sel.lower() in ('all', 'a'):
                    return list(range(1, len(options) + 1))
                chosen = set()
                for part in sel.split(','):
                    part = part.strip()
                    if '-' in part:
                        try:
                            a, b = part.split('-', 1)
                            a1, b1 = int(a), int(b)
                            for n in range(a1, b1 + 1):
                                if 1 <= n <= len(options):
                                    chosen.add(n)
                        except Exception:
                            continue
                    else:
                        try:
                            n = int(part)
                            if 1 <= n <= len(options):
                                chosen.add(n)
                        except Exception:
                            continue
                return sorted(chosen)

            # Construir sugerencias basadas en la estructura del repo y archivos grandes
            suggested = []
            scan_root = target_root
            # sugerencias base (solo añadir si existen en el repo)
            base_candidates = [
                'target/', '__pycache__/', '*:Zone.Identifier', 'rep_export_*',
                'data/tiddly-data-converter (Saved).html', 'docs/tiddlers_esp.jsonl'
            ]
            for pat in base_candidates:
                if pat.endswith('/'):
                    # directorio: buscar cualquier carpeta con ese nombre
                    name = pat.rstrip('/')
                    if any(scan_root.glob(f"**/{name}")):
                        suggested.append(pat)
                elif '*' in pat:
                    if any(scan_root.glob(pat)):
                        suggested.append(pat)
                else:
                    if (scan_root / pat).exists():
                        suggested.append(pat)

            # añadir sugerencias derivadas de archivos grandes (top 8)
            large_suggestions = []
            if stats and stats.large:
                for p, size in stats.large[:8]:
                    try:
                        rel = p.relative_to(scan_root)
                    except Exception:
                        rel = p
                    large_suggestions.append(f"{rel} ({fmt_size(size)})")

            options = suggested + large_suggestions
            if options:
                safe_print("\nPuedo sugerir excluir estos elementos del árbol (recomendado):")
                selected = prompt_multi_select("Elige lo que quieres excluir:", options)
                for idx in selected:
                    opt = options[idx - 1]
                    # limpiar el texto si viene con tamaño entre paréntesis
                    if ' (' in opt and opt.endswith(')'):
                        opt = opt[:opt.rfind(' (')]
                    args += ['-e', opt]

                # inferir exclusión por extensión si muchos archivos grandes comparten extensión
                exts = {}
                for idx in selected:
                    opt = options[idx - 1]
                    if ' (' in opt and opt.endswith(')'):
                        opt = opt[:opt.rfind(' (')]
                    ext = Path(opt).suffix.lower()
                    if ext:
                        exts[ext] = exts.get(ext, 0) + 1
                for ext, count in exts.items():
                    if count >= 1:
                        if prompt_yes_no(f"¿Excluir todos los archivos '*{ext}' de la vista?", default=False):
                            args += ['-e', f"*{ext}"]

            else:
                safe_print("No se detectaron sugerencias automáticas para este repositorio.")

            # Permitir añadir patrones personalizados al final
            if prompt_yes_no("¿Agregar patrones de exclusión adicionales manualmente?", default=False):
                extra = input("Patrones (separados por comas, ej: '*.log,build/*'): ").strip()
                for pat in [p.strip() for p in extra.split(',') if p.strip()]:
                    args += ['-e', pat]

            out_name = input("Nombre de salida [estructura.txt]: ").strip() or 'estructura.txt'
            out_path = target_root / out_name
            if confirm_overwrite(out_path):
                args += ['--output', out_name, '--force']
                if root_override:
                    args += ['--root', root_override]
                safe_print("⏳ Generando estructura, esto puede tardar unos segundos...")
                # Ejecutar desde la raíz del repo y forzar PYTHONPATH para que los
                # subprocesos puedan importar el paquete correctamente.
                env = os.environ.copy()
                env['PYTHONPATH'] = str(python_scripts_root)
                code, _, _ = run_cmd([sys.executable, str(struct), '-v'] + args, cwd=repo_root, env=env)
                if code != 0:
                    if prompt_yes_no("Error al generar. Volver al menú?", default=True):
                        continue
                    sys.exit(code)
            else:
                safe_print("🔸 Generación de estructura cancelada.")

        # Paso 2: Exportar tiddlers
        if choice in ('2','3'):
            safe_print("\n🛠️ Configuración Exportación Tiddlers")
            exp_args = []
            if prompt_yes_no("¿Simulación (dry-run)?", default=False):
                exp_args.append('--dry-run')
            # Preguntar si el usuario quiere excluir carpetas una por una
            if prompt_yes_no("¿Deseas excluir carpetas una por una antes de exportar? (preguntar carpeta a carpeta)", default=False):
                try:
                    candidates = sorted([p for p in target_root.iterdir() if p.is_dir()], key=lambda p: p.name.lower())
                except Exception:
                    candidates = []
                skip_names = {'.git', 'tiddlers-export', 'rep_export_LINUXandMAC', 'rep_export_Windows', '.venv', 'venv', '__pycache__', '.pytest_cache'}
                for d in candidates:
                    if d.name in skip_names:
                        continue
                    try:
                        rel = d.relative_to(target_root).as_posix()
                    except Exception:
                        rel = d.as_posix()
                    if prompt_yes_no(f"¿Excluir carpeta '{rel}'?", default=False):
                        exp_args += ['--exclude-dir', rel]
            # Preguntar si respetar .gitignore al exportar (por defecto: sí)
            if not prompt_yes_no("¿Respetar patrones de .gitignore al exportar? (recomendado)", default=True):
                exp_args.append('--no-honor-gitignore')
            # Pasar configuración de archivos grandes
            if large_include:
                exp_args += ['--include-large', '--large-action', large_action]
            if large_max_size is not None:
                exp_args += ['--max-size', str(large_max_size)]
            if root_override:
                exp_args += ['--root', root_override]
            # Ejecutar export desde la raíz del repo y con PYTHONPATH apuntando a la raíz.
            env = os.environ.copy()
            env['PYTHONPATH'] = str(python_scripts_root)
            code, _, _ = run_cmd([sys.executable, str(export)] + exp_args, cwd=repo_root, env=env)
            if code != 0:
                if prompt_yes_no("Error al exportar. Volver al menú?", default=True):
                    continue
                sys.exit(code)
            if '--dry-run' in exp_args and prompt_yes_no("Dry-run completado. Ejecutar real?", default=True):
                real_args = [a for a in exp_args if a != '--dry-run']
                env = os.environ.copy()
                env['PYTHONPATH'] = str(python_scripts_root)
                code, _, _ = run_cmd([sys.executable, str(export)] + real_args, cwd=repo_root, env=env)
                if code != 0:
                    sys.exit(code)

        safe_print("\n✅ Operación completada con éxito.")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        safe_print("\n⚠️ Interrupción por usuario. Saliendo...")
        sys.exit(1)
