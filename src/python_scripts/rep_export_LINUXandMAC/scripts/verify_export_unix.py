#!/usr/bin/env python3
"""
Script: verify_export_unix.py
Ubicación: rep_export_LINUXandMAC/scripts/

Comprueba la integridad de los tiddlers exportados en tiddlers-export/:
  - Valida que cada .json sea parseable.
  - Verifica que los campos mínimos (title, text, type, tags) estén presentes.
  - Muestra un conteo final y sale con código 1 si hay problemas.

Uso:
  python3 rep_export_LINUXandMAC/scripts/verify_export_unix.py
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cli_utils_UNIX import safe_print

REQUIRED_FIELDS = {'title', 'text', 'type', 'tags'}


def main():
    repo_root = Path(__file__).resolve().parents[4]
    out_dir = repo_root / 'data' / 'out' / 'local' / 'tiddlers-export'
    hash_file = out_dir / 'hashes_rep_export' / '.hashes.json'

    if not out_dir.is_dir():
        safe_print(f"❌ Directorio no encontrado: {out_dir}")
        sys.exit(1)

    json_files = sorted(out_dir.glob('*.json'))
    if not json_files:
        safe_print("⚠️  Sin archivos en tiddlers-export/")
        sys.exit(1)

    ok, bad = [], []
    for jf in json_files:
        try:
            data = json.loads(jf.read_text(encoding='utf-8'))
        except Exception as e:
            bad.append(f"JSON inválido: {jf.name} → {e}")
            continue
        missing = REQUIRED_FIELDS - set(data.keys())
        if missing:
            bad.append(f"Campos faltantes en {jf.name}: {sorted(missing)}")
        else:
            ok.append(jf.name)

    hash_count = 0
    if hash_file.exists():
        try:
            hash_count = len(json.loads(hash_file.read_text(encoding='utf-8')))
        except Exception:
            pass

    safe_print(f"\n📋 Verificación: {out_dir}")
    safe_print(f"  Archivos exportados : {len(json_files)}")
    if hash_count:
        safe_print(f"  Entradas en hashes  : {hash_count}")
    safe_print(f"  ✅ Válidos           : {len(ok)}")
    if bad:
        safe_print(f"  ❌ Con problemas     : {len(bad)}")
        for b in bad:
            safe_print(f"     — {b}")
        sys.exit(1)
    safe_print("  Todo en orden.")


if __name__ == '__main__':
    main()
