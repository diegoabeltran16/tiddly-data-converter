#!/usr/bin/env python3
"""
relation_review_menu.py — S0127
Módulo auxiliar: Revisión relacional [EXPERIMENTAL].

Responsabilidades:
  - Presentar una sección experimental claramente delimitada en el menú local.
  - Ejecutar validación dry-run de relaciones candidatas ya existentes.
  - Mostrar explícitamente que generación y admisión canónica están BLOQUEADAS.
  - Mostrar el último reporte humano si existe.
  - No generar candidatos nuevos.
  - No invocar --apply.
  - No modificar data/out/local/tiddlers_*.jsonl.

Restricciones S0127:
  - Generación automática de relaciones: BLOQUEADA
  - Admisión canónica relacional: BLOQUEADA
  - --apply: NUNCA invocado
  - Canon: NO modificado
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
SCRIPT_DIR: Path = Path(__file__).resolve().parent

RELATIONS_DIR: Path = (
    REPO_ROOT / "data" / "out" / "local" / "pipeline" / "relations_candidates"
)
DEFAULT_CANDIDATES_INPUT: Path = (
    RELATIONS_DIR / "relations_candidates.sample.jsonl"
)
DEFAULT_VALIDATION_REPORT: Path = (
    RELATIONS_DIR / "relations_candidates.validation_report.json"
)
DEFAULT_HUMAN_REVIEW: Path = (
    RELATIONS_DIR / "relations_candidates.human_review.md"
)
CANON_ROOT: Path = REPO_ROOT / "data" / "out" / "local"
VALIDATOR_SCRIPT: Path = SCRIPT_DIR / "validate_relation_candidates.py"

# ---------------------------------------------------------------------------
# Texto de estado de bloqueo (invariante de sesión S0127)
# ---------------------------------------------------------------------------

BLOCK_STATUS_LINES: list[str] = [
    "[EXPERIMENTAL] Revisión relacional",
    "- Generación automática: BLOQUEADA",
    "- Admisión canónica:     BLOQUEADA",
    "- Modo actual:           validación dry-run",
    "- Canon modificado:      NO",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _prompt(message: str) -> str:
    try:
        return input(message)
    except EOFError:
        return ""


def _display(path: Path) -> str:
    """Ruta relativa al REPO_ROOT para display."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def show_block_status(
    report_path: Path | None = None,
    human_review_path: Path | None = None,
) -> None:
    """Imprime el encabezado de estado de bloqueo de S0127."""
    for line in BLOCK_STATUS_LINES:
        print(line)
    rp = report_path or DEFAULT_VALIDATION_REPORT
    hr = human_review_path or DEFAULT_HUMAN_REVIEW
    print(f"- Reporte JSON:        {_display(rp)}")
    print(f"- Reporte humano:      {_display(hr)}")


# ---------------------------------------------------------------------------
# Opción 1: Validar relaciones candidatas existentes (dry-run)
# ---------------------------------------------------------------------------


def option_validate_candidates() -> int:
    """
    Valida relaciones candidatas existentes en modo dry-run.

    Invariantes:
      - Nunca invoca --apply.
      - Nunca genera candidatos nuevos.
      - Nunca modifica tiddlers_*.jsonl.

    Retorna el exit code del validador (0 = OK, != 0 = problema o advertencia).
    """
    print("\n[EXPERIMENTAL] Validar relaciones candidatas existentes (dry-run)")
    print("- Generación automática: BLOQUEADA")
    print("- Admisión canónica:     BLOQUEADA")
    print("- Modo: dry-run (ningún candidato será escrito en el canon)")

    # ── Verificar directorio ────────────────────────────────────────────────
    if not RELATIONS_DIR.exists():
        print(
            f"\nNo existe el directorio de candidatos: {_display(RELATIONS_DIR)}"
        )
        print("No se encontraron relaciones candidatas para revisar.")
        print("Esta opción no genera candidatos nuevos en S0127.")
        print("Crea el directorio y añade candidatos para usar esta opción.")
        return 1

    # ── Verificar archivo de candidatos ────────────────────────────────────
    if not DEFAULT_CANDIDATES_INPUT.exists():
        print(
            "\nNo se encontraron relaciones candidatas para revisar."
        )
        print(f"Ruta esperada: {_display(DEFAULT_CANDIDATES_INPUT)}")
        print("Esta opción no genera candidatos nuevos en S0127.")
        return 1

    # ── Construir comando: --dry-run requerido; --apply NUNCA ───────────────
    cmd: list[str] = [
        sys.executable,
        str(VALIDATOR_SCRIPT),
        "--input",
        str(DEFAULT_CANDIDATES_INPUT),
        "--canon-root",
        str(CANON_ROOT),
        "--report",
        str(DEFAULT_VALIDATION_REPORT),
        "--human-review",
        str(DEFAULT_HUMAN_REVIEW),
        "--dry-run",
        # --apply está EXPLÍCITAMENTE ausente (S0127)
    ]

    print(f"\nEjecutando validador dry-run...")
    print(f"  Input:        {_display(DEFAULT_CANDIDATES_INPUT)}")
    print(f"  Canon root:   {_display(CANON_ROOT)}")
    print(f"  Reporte JSON: {_display(DEFAULT_VALIDATION_REPORT)}")
    print(f"  Reporte human:{_display(DEFAULT_HUMAN_REVIEW)}")

    completed = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )

    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    if stdout:
        print("\n" + stdout)
    if stderr:
        print("\nstderr:")
        print(stderr[:800])

    if completed.returncode == 0:
        print("\n✅ Validación dry-run completada sin errores fatales.")
    else:
        print(
            f"\n⚠️  Validador terminó con exit code {completed.returncode}. "
            "Revisar salida y reporte."
        )

    print()
    show_block_status()
    return completed.returncode


# ---------------------------------------------------------------------------
# Opción 2: Ver último reporte humano
# ---------------------------------------------------------------------------


def option_view_human_report() -> None:
    """
    Muestra el último reporte humano de revisión relacional.

    Si no existe, instruye al usuario a ejecutar la validación dry-run primero.
    No altera ningún archivo.
    """
    print("\n[EXPERIMENTAL] Último reporte humano de relaciones candidatas")

    if not DEFAULT_HUMAN_REVIEW.exists():
        print("No hay reporte humano disponible todavía.")
        print("Ejecute primero la validación dry-run (opción 1).")
        return

    print(f"Reporte: {_display(DEFAULT_HUMAN_REVIEW)}\n")
    try:
        content = DEFAULT_HUMAN_REVIEW.read_text(encoding="utf-8")
        lines = content.splitlines()
        # Mostrar hasta 120 líneas para no saturar la terminal
        for line in lines[:120]:
            print(line)
        if len(lines) > 120:
            print(
                f"\n... ({len(lines) - 120} líneas adicionales — "
                f"ver archivo completo: {_display(DEFAULT_HUMAN_REVIEW)})"
            )
    except OSError as exc:
        print(f"No se pudo leer el reporte: {exc}")


# ---------------------------------------------------------------------------
# Submenú principal: Revisión relacional [EXPERIMENTAL]
# ---------------------------------------------------------------------------

_MENU_HEADER = """\

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Revisión relacional [EXPERIMENTAL]
  Generación automática de relaciones:  BLOQUEADA
  Admisión canónica relacional:         BLOQUEADA
  Modo actual:                          dry-run
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Validar relaciones candidatas existentes (dry-run)
2. Ver último reporte humano
3. Generar plan dry-run de admisión relacional [NO ESCRIBE CANON]
0. Volver"""

# Ruta de salida del plan de admisión (S0135)
_ADMISSION_PLAN_DIR: Path = (
    REPO_ROOT / "data" / "out" / "local" / "pipeline" / "relations_admission" / "s0135"
)
_ADMISSION_PLAN_SCRIPT: Path = SCRIPT_DIR / "build_relation_admission_plan.py"


def option_generate_admission_plan() -> None:
    """Genera el plan dry-run de admisión relacional (S0135).

    BLOQUEADO: S0135 solo genera plan dry-run. No escribe relaciones en el canon.
    """
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("  Generar plan dry-run de admisión relacional (S0135)")
    print("  BLOQUEADO: S0135 solo genera plan dry-run.")
    print("  No escribe relaciones en el canon.")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

    if not _ADMISSION_PLAN_SCRIPT.exists():
        print(f"[ERROR] Script no encontrado: {_ADMISSION_PLAN_SCRIPT}")
        return

    cmd = [
        sys.executable,
        str(_ADMISSION_PLAN_SCRIPT),
        "--canon-glob", str(CANON_ROOT / "tiddlers_*.jsonl"),
        "--candidates-dir", str(RELATIONS_DIR),
        "--out-dir", str(_ADMISSION_PLAN_DIR),
        "--dry-run",
    ]
    print(f"Ejecutando plan dry-run de admisión relacional...")
    print(f"Salida: {_display(_ADMISSION_PLAN_DIR)}\n")

    import subprocess
    result = subprocess.run(cmd, capture_output=False)

    if result.returncode == 0:
        plan_path = _ADMISSION_PLAN_DIR / "s0135_relation_admission_plan.json"
        print(f"\n✅ Plan generado. Ver: {_display(plan_path)}")
    elif result.returncode == 1:
        print("\n⚠️  Plan generado con advertencias (ver salida arriba).")
    else:
        print(f"\n[ERROR] Error al generar el plan (código {result.returncode}).")


def option_relation_review_menu() -> None:
    """
    Submenú experimental de revisión relacional.

    Contrato S0127/S0135:
      - Generación: BLOQUEADA
      - Admisión canónica: BLOQUEADA
      - --apply: NUNCA ejecutado
      - tiddlers_*.jsonl: NO modificados
    """
    while True:
        print(_MENU_HEADER)
        choice = _prompt("> ").strip()

        if choice == "0" or choice == "":
            return

        if choice == "1":
            option_validate_candidates()
        elif choice == "2":
            option_view_human_report()
        elif choice == "3":
            option_generate_admission_plan()
        else:
            print("Opción inválida.")


# ---------------------------------------------------------------------------
# Punto de entrada directo (útil para prueba manual)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    option_relation_review_menu()
