#!/usr/bin/env python3
"""Interactive operator menu for the local tiddly-data-converter workflow."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from path_governance import (  # noqa: E402
    DEFAULT_AI_DIR,
    DEFAULT_AUDIT_DIR,
    DEFAULT_CANON_DIR,
    DEFAULT_ENRICHED_DIR,
    DEFAULT_EXPORT_DIR,
    DEFAULT_INPUT_HTML,
    DEFAULT_MICROSOFT_COPILOT_DIR,
    DEFAULT_REVERSE_HTML,
    DEFAULT_REVERSE_REPORT,
    REPO_ROOT,
    as_display_path,
)
from session_sync import DEFAULT_SESSION_SYNC_DIR, scan_session_sync  # noqa: E402


DEFAULT_SESSIONS_DIR = REPO_ROOT / "data" / "sessions"
DEFAULT_TMP_DIR = REPO_ROOT / "data" / "tmp"
DEFAULT_ADMISSION_TMP_DIR = DEFAULT_TMP_DIR / "session_admission"
DEFAULT_ADMISSION_REPORT_DIR = DEFAULT_TMP_DIR / "admissions"
HTML_EXPORT_DIR = DEFAULT_TMP_DIR / "html_export"


@dataclass
class CommandResult:
    args: list[str]
    cwd: Path
    returncode: int
    stdout: str
    stderr: str


@dataclass
class MenuState:
    selected_html: Path | None = None
    last_export_jsonl: Path | None = None
    last_sync_inventory: dict[str, Any] | None = None
    last_sync_candidate_file: Path | None = None
    last_validate_report: Path | None = None
    last_dry_run_report: Path | None = None


def stamp_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def display(path: Path | str | None) -> str:
    if path is None:
        return "-"
    path_obj = Path(path)
    try:
        return as_display_path(path_obj.resolve())
    except OSError:
        return str(path)


def prompt(message: str) -> str:
    try:
        return input(message)
    except EOFError:
        return ""


def pause() -> None:
    if sys.stdin.isatty():
        prompt("\nEnter para volver al menu...")


def command_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("GOCACHE", "/tmp/tdc-go-build")
    env.setdefault("CARGO_TARGET_DIR", "/tmp/tdc-cargo-target")
    return env


def run_command(args: list[str], cwd: Path = REPO_ROOT) -> CommandResult:
    completed = subprocess.run(
        args,
        cwd=cwd,
        env=command_env(),
        check=False,
        capture_output=True,
        text=True,
    )
    return CommandResult(
        args=args,
        cwd=cwd,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def print_command_result(result: CommandResult, max_chars: int = 2400) -> None:
    print(f"$ {' '.join(result.args)}")
    print(f"cwd: {display(result.cwd)}")
    print(f"exit: {result.returncode}")
    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    if stdout:
        print("\nstdout:")
        print(stdout[-max_chars:])
    if stderr:
        print("\nstderr:")
        print(stderr[-max_chars:])


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def parse_stdout_json(stdout: str) -> dict[str, Any] | None:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def count_jsonl_lines(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return sum(1 for line in handle if line.strip())
    except OSError:
        return 0


def canon_shards(canon_dir: Path = DEFAULT_CANON_DIR) -> list[Path]:
    return sorted(canon_dir.glob("tiddlers_*.jsonl"))


def canon_summary(canon_dir: Path = DEFAULT_CANON_DIR) -> dict[str, Any]:
    shards = canon_shards(canon_dir)
    return {
        "shards": shards,
        "line_count": sum(count_jsonl_lines(path) for path in shards),
    }


def select_path(paths: list[Path], label: str, label_func: Any | None = None) -> Path | None:
    if not paths:
        print(f"No se encontraron opciones para {label}.")
        return None
    if len(paths) == 1:
        print(f"{label}: {display(paths[0])}")
        return paths[0]

    print(f"\nSeleccionar {label}:")
    for index, path in enumerate(paths, start=1):
        prefix = f"{label_func(path)} - " if label_func else ""
        print(f"{index}) {prefix}{display(path)}")
    print("0) Volver")
    raw = prompt("> ").strip()
    if not raw or raw == "0":
        return None
    if not raw.isdigit() or not (1 <= int(raw) <= len(paths)):
        print("Seleccion invalida.")
        return None
    return paths[int(raw) - 1]


def detect_html_files() -> list[Path]:
    data_in = REPO_ROOT / "data" / "in"
    return sorted([*data_in.rglob("*.html"), *data_in.rglob("*.htm")])


def html_option_label(path: Path) -> str:
    if path.resolve() == DEFAULT_INPUT_HTML.resolve():
        return "HTML saved actual"
    if "empty" in path.name.lower():
        return "HTML empty / plantilla base"
    return "HTML detectado"


def choose_html(state: MenuState) -> Path | None:
    html_files = detect_html_files()
    if state.selected_html and state.selected_html.exists():
        print(f"HTML actual: {display(state.selected_html)}")
        answer = prompt("Usar este HTML? [Enter = si, c = cambiar] ").strip().lower()
        if answer != "c":
            return state.selected_html

    selected = select_path(html_files, "HTML fuente", html_option_label)
    if selected:
        state.selected_html = selected
    return selected


def recent_files(roots: list[Path], pattern: str, limit: int = 12) -> list[Path]:
    files_by_path: dict[Path, Path] = {}
    for root in roots:
        if root.exists():
            for path in root.rglob(pattern):
                if path.is_file():
                    files_by_path[path.resolve()] = path
    files = list(files_by_path.values())
    return sorted(files, key=lambda path: path.stat().st_mtime, reverse=True)[:limit]


def latest_admission_reports(apply_only: bool = False) -> list[Path]:
    reports = recent_files([DEFAULT_ADMISSION_REPORT_DIR], "*.json", limit=80)
    selected: list[Path] = []
    for path in reports:
        try:
            payload = load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        if apply_only and payload.get("mode") != "apply":
            continue
        if apply_only and not payload.get("rollback_ready"):
            continue
        selected.append(path)
    return selected[:12]


def summarize_report(path: Path) -> str:
    try:
        payload = load_json(path)
    except (OSError, json.JSONDecodeError):
        return "no se pudo leer JSON"
    if not isinstance(payload, dict):
        return "JSON no objeto"

    if "missing_by_id" in payload and "existing_by_id" in payload:
        return (
            f"run_id={payload.get('run_id')}, "
            f"records={payload.get('total_session_records')}, "
            f"existing={len(payload.get('existing_by_id') or [])}, "
            f"missing={len(payload.get('missing_by_id') or [])}, "
            f"conflicts={len(payload.get('same_id_different_content') or [])}, "
            f"invalid={len(payload.get('invalid') or [])}"
        )

    parts = []
    for key in ("mode", "status", "session_id", "candidate_count", "eligible_count", "admitted_count"):
        if key in payload:
            parts.append(f"{key}={payload[key]}")
    for key in ("canon_lines", "eligible_count", "out_of_scope_count", "already_present_count", "inserted_count", "updated_count", "rejected_count"):
        if key in payload and f"{key}={payload[key]}" not in parts:
            parts.append(f"{key}={payload[key]}")
    if "rejected_candidates" in payload:
        parts.append(f"rejected={len(payload.get('rejected_candidates') or [])}")
    reverse = payload.get("reverse_result")
    if isinstance(reverse, dict) and "rejected" in reverse:
        parts.append(f"reverse_rejected={reverse.get('rejected')}")
    if "not_ready" in payload:
        parts.append(f"not_ready={payload.get('not_ready')}")
    return ", ".join(parts) if parts else "sin resumen conocido"


def option_preparation() -> None:
    print("\nEstado del entorno:")
    checks = [
        ("repo root", Path.cwd().resolve() == REPO_ROOT.resolve(), display(REPO_ROOT)),
        ("data/sessions", DEFAULT_SESSIONS_DIR.exists(), display(DEFAULT_SESSIONS_DIR)),
        ("data/out/local", DEFAULT_CANON_DIR.exists(), display(DEFAULT_CANON_DIR)),
        ("python_scripts", (REPO_ROOT / "python_scripts").exists(), "python_scripts"),
        ("admit_session_candidates.py", (REPO_ROOT / "python_scripts" / "admit_session_candidates.py").exists(), ""),
        ("go/canon", (REPO_ROOT / "go" / "canon").exists(), "go/canon"),
        ("go/bridge", (REPO_ROOT / "go" / "bridge").exists(), "go/bridge"),
        ("go/ingesta", (REPO_ROOT / "go" / "ingesta").exists(), "go/ingesta"),
        ("data/tmp", DEFAULT_TMP_DIR.exists(), display(DEFAULT_TMP_DIR)),
        ("python3", shutil.which("python3") is not None, shutil.which("python3") or ""),
        ("go", shutil.which("go") is not None, shutil.which("go") or ""),
    ]
    for name, ok, detail in checks:
        state = "OK" if ok else "FALTA"
        suffix = f" - {detail}" if detail else ""
        print(f"- {name}: {state}{suffix}")
    DEFAULT_TMP_DIR.mkdir(parents=True, exist_ok=True)
    print("\nSiguiente paso recomendado: validar canon o revisar estado del canon.")


def option_canon_status() -> None:
    summary = canon_summary()
    print("\nCanon local:")
    print(f"- shards detectados: {len(summary['shards'])}")
    print(f"- lineas canonicas: {summary['line_count']}")
    for shard in summary["shards"]:
        print(f"  - {display(shard)}: {count_jsonl_lines(shard)} lineas")

    expected = {path.name for path in summary["shards"]}
    allowed_dirs = {"enriched", "ai", "audit", "export", "microsoft_copilot", "reverse_html"}
    unexpected: list[str] = []
    for child in DEFAULT_CANON_DIR.iterdir() if DEFAULT_CANON_DIR.exists() else []:
        if child.name in expected or child.name in allowed_dirs:
            continue
        unexpected.append(child.name)
    print(f"- archivos inesperados en data/out/local: {len(unexpected)}")
    for name in unexpected[:12]:
        print(f"  - {name}")
    print(f"- reverse_html: {'OK' if (DEFAULT_CANON_DIR / 'reverse_html').exists() else 'no existe'}")
    print(f"- reportes de admision recientes: {len(latest_admission_reports())}")
    print("\nSiguiente paso recomendado: validar canon antes de reverse o admision.")


def option_build_from_html(state: MenuState) -> None:
    print("\nConstruir canon desde HTML")
    print("Flujo: HTML vivo -> JSONL temporal -> shards canonicos locales -> validacion")
    selected = choose_html(state)
    if selected:
        print(f"HTML seleccionado: {display(selected)}")
        print("Siguiente paso recomendado: opcion 4 para extraer a JSONL temporal.")


def option_extract_html(state: MenuState) -> None:
    html = choose_html(state)
    if not html:
        return
    run_id = f"export-{stamp_now()}"
    out_dir = HTML_EXPORT_DIR / run_id
    out_jsonl = out_dir / "tiddlers.export.jsonl"
    out_log = out_dir / "tiddlers.export.log"
    manifest = out_dir / "tiddlers.export.manifest.json"
    out_dir.mkdir(parents=True, exist_ok=True)

    result = run_command(
        [
            "go",
            "run",
            "./cmd/export_tiddlers",
            "--html",
            str(html),
            "--out",
            str(out_jsonl),
            "--log",
            str(out_log),
            "--manifest",
            str(manifest),
            "--run-id",
            run_id,
        ],
        cwd=REPO_ROOT / "go" / "bridge",
    )
    print_command_result(result)
    if result.returncode == 0:
        state.last_export_jsonl = out_jsonl
        print("\nSalidas temporales:")
        print(f"- JSONL: {display(out_jsonl)} ({count_jsonl_lines(out_jsonl)} lineas)")
        print(f"- log: {display(out_log)}")
        print(f"- manifest: {display(manifest)}")
        print("Siguiente paso recomendado: opcion 5 para shardizar si quieres reconstruir el canon local.")
    else:
        print("Extraccion fallida. No se escribio el canon.")


def option_shard_jsonl(state: MenuState) -> None:
    candidates = recent_files([HTML_EXPORT_DIR], "tiddlers.export.jsonl", limit=8)
    legacy_tmp = Path("/tmp/tiddlers.export.jsonl")
    if legacy_tmp.exists():
        candidates.append(legacy_tmp)
    if state.last_export_jsonl and state.last_export_jsonl.exists() and state.last_export_jsonl not in candidates:
        candidates.insert(0, state.last_export_jsonl)

    selected = select_path(candidates, "JSONL temporal")
    if not selected:
        return

    print("\nAdvertencia: esta opcion escribe shards en data/out/local.")
    print("JSONL temporal != canon; los shards en data/out/local son el canon local oficial.")
    confirmation = prompt("Escribe WRITE CANON para continuar: ").strip()
    if confirmation != "WRITE CANON":
        print("Shardizacion cancelada. No se modifico el canon.")
        return

    result = run_command(
        [
            "go",
            "run",
            "./cmd/shard_canon",
            "--input",
            str(selected),
            "--out-dir",
            str(DEFAULT_CANON_DIR),
        ],
        cwd=REPO_ROOT / "go" / "canon",
    )
    print_command_result(result)
    if result.returncode == 0:
        option_canon_status()
        print("Siguiente paso recomendado: opcion 6 para validar el canon.")


def run_preflight(mode: str) -> CommandResult:
    return run_command(
        ["go", "run", "./cmd/canon_preflight", "--mode", mode, "--input", str(DEFAULT_CANON_DIR)],
        cwd=REPO_ROOT / "go" / "canon",
    )


def option_validate_canon() -> bool:
    print("\nValidacion strict")
    strict = run_preflight("strict")
    print_command_result(strict)
    if strict.returncode != 0:
        print("Fallo strict. No se recomienda reverse ni admision hasta corregir.")
        return False

    print("\nReverse preflight")
    reverse = run_preflight("reverse-preflight")
    print_command_result(reverse)
    if reverse.returncode != 0:
        print("Fallo reverse-preflight. No se recomienda reverse ni admision hasta corregir.")
        return False

    print("\nEstado final: OK. Condicion critica esperada: not_ready=0 y Rejected=0 en reverse.")
    return True


def print_inventory_summary(inventory: dict[str, Any]) -> None:
    summary = canon_summary()
    print("\nSincronizacion de sesiones")
    print("Canon actual:")
    print(f"- shards: {len(summary['shards'])}")
    print(f"- lineas: {summary['line_count']}")
    print("Sessions:")
    print(f"- archivos detectados: {inventory['total_files_scanned']}")
    print(f"- entregables validos: {inventory['total_session_records']}")
    print(f"- ya existen en canon por ID: {len(inventory['existing_by_id'])}")
    print(f"- faltantes por ID: {len(inventory['missing_by_id'])}")
    print(f"- conflictos: {len(inventory['same_id_different_content'])}")
    print(f"- invalidos: {len(inventory['invalid'])}")
    print(f"- unsupported: {len(inventory['unsupported'])}")
    print(f"- inventario: {inventory['inventory_path']}")
    if inventory.get("generated_candidate_file"):
        print(f"- candidatos faltantes: {inventory['generated_candidate_file']}")


def print_items(title: str, items: list[dict[str, Any]], limit: int = 40) -> None:
    print(f"\n{title}: {len(items)}")
    for item in items[:limit]:
        print(f"- {item.get('id', '-')}: {item.get('title', '-')}")
        print(f"  {item.get('source_path', item.get('path', '-'))}")
        if item.get("message"):
            print(f"  {item['message']}")
    if len(items) > limit:
        print(f"... {len(items) - limit} mas")


def run_admission_command(mode: str, candidate_file: Path, extra: list[str] | None = None) -> tuple[CommandResult, dict[str, Any] | None]:
    args = [
        sys.executable,
        "python_scripts/admit_session_candidates.py",
        mode,
        "--candidate-file",
        str(candidate_file),
        "--sessions-dir",
        str(DEFAULT_SESSIONS_DIR),
        "--canon-dir",
        str(DEFAULT_CANON_DIR),
        "--tmp-dir",
        str(DEFAULT_ADMISSION_TMP_DIR),
        "--report-dir",
        str(DEFAULT_ADMISSION_REPORT_DIR),
    ]
    if extra:
        args.extend(extra)
    result = run_command(args, cwd=REPO_ROOT)
    print_command_result(result)
    return result, parse_stdout_json(result.stdout)


def dry_run_report_is_usable(report_path: Path, candidate_file: Path) -> tuple[bool, str]:
    try:
        payload = load_json(report_path)
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"no se pudo leer dry-run: {exc}"
    if payload.get("mode") != "dry-run":
        return False, "el reporte no es de dry-run"
    if payload.get("status") != "ok":
        return False, "el dry-run no termino ok"
    if payload.get("candidate_file") != as_display_path(candidate_file):
        return False, "el reporte dry-run no corresponde al candidato actual"
    if payload.get("rejected_candidates"):
        return False, "el dry-run tiene candidatos rechazados"
    reverse = payload.get("reverse_result") or {}
    if int(reverse.get("rejected") or 0) != 0:
        return False, "reverse_authoritative tuvo rejected > 0"
    return True, "ok"


def option_session_sync(state: MenuState) -> None:
    print("\nEscaneando data/sessions por ID canonico...")
    try:
        inventory = scan_session_sync(
            sessions_dir=DEFAULT_SESSIONS_DIR,
            canon_dir=DEFAULT_CANON_DIR,
            out_dir=DEFAULT_SESSION_SYNC_DIR,
        )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"No se pudo generar inventario: {exc}")
        return

    state.last_sync_inventory = inventory
    candidate_value = inventory.get("generated_candidate_file")
    state.last_sync_candidate_file = (REPO_ROOT / candidate_value).resolve() if candidate_value else None
    print_inventory_summary(inventory)

    while True:
        print(
            "\nSincronizacion de sesiones\n"
            "1) Ver faltantes\n"
            "2) Ver conflictos\n"
            "3) Ver candidatos generados\n"
            "4) Validar candidatos\n"
            "5) Dry-run de admision\n"
            "6) Apply confirmado\n"
            "7) Rollback ultimo apply\n"
            "0) Volver"
        )
        choice = prompt("> ").strip()
        if choice == "0" or choice == "":
            return
        if choice == "1":
            print_items("Faltantes por ID", inventory["missing_by_id"])
        elif choice == "2":
            print_items("Conflictos same_id_different_content", inventory["same_id_different_content"])
            print_items("Invalidos", inventory["invalid"], limit=20)
        elif choice == "3":
            if state.last_sync_candidate_file:
                print(f"Candidato temporal: {display(state.last_sync_candidate_file)}")
                print(f"Lineas: {count_jsonl_lines(state.last_sync_candidate_file)}")
            else:
                print("No hay faltantes; no se genero archivo de candidatos.")
        elif choice == "4":
            if not state.last_sync_candidate_file:
                print("No hay candidatos faltantes para validar.")
                continue
            if inventory["same_id_different_content"]:
                print("Hay conflictos por ID. Resolver antes de validar admision.")
                continue
            result, payload = run_admission_command("validate", state.last_sync_candidate_file)
            if payload and payload.get("report"):
                state.last_validate_report = (REPO_ROOT / payload["report"]).resolve()
            if result.returncode == 0:
                print("Validacion OK. Siguiente paso recomendado: dry-run.")
        elif choice == "5":
            if not state.last_sync_candidate_file:
                print("No hay candidatos faltantes para dry-run.")
                continue
            if inventory["same_id_different_content"]:
                print("Hay conflictos por ID. Resolver antes de dry-run.")
                continue
            result, payload = run_admission_command("dry-run", state.last_sync_candidate_file)
            if payload and payload.get("report"):
                state.last_dry_run_report = (REPO_ROOT / payload["report"]).resolve()
            if result.returncode == 0:
                print("Dry-run OK. Revisar el reporte antes de apply.")
        elif choice == "6":
            if not state.last_sync_candidate_file:
                print("No hay candidatos faltantes para apply.")
                continue
            if inventory["same_id_different_content"]:
                print("Hay conflictos por ID. Apply bloqueado.")
                continue
            if not state.last_dry_run_report:
                print("Apply bloqueado: no hay dry-run previo en esta ejecucion del menu.")
                continue
            usable, reason = dry_run_report_is_usable(state.last_dry_run_report, state.last_sync_candidate_file)
            if not usable:
                print(f"Apply bloqueado: {reason}")
                continue
            print("\nApply confirmado modificara data/out/local.")
            print(f"- candidatos: {display(state.last_sync_candidate_file)}")
            print(f"- lineas a insertar: {count_jsonl_lines(state.last_sync_candidate_file)}")
            print(f"- dry-run revisable: {display(state.last_dry_run_report)}")
            confirmation = prompt("Escribe APPLY para modificar el canon local: ").strip()
            if confirmation != "APPLY":
                print("Apply cancelado.")
                continue
            run_admission_command("apply", state.last_sync_candidate_file, ["--confirm-apply"])
        elif choice == "7":
            option_rollback()
        else:
            print("Opcion invalida.")


def option_derivatives() -> None:
    print("\nDerivados: canon local -> derivados")
    print("Los derivados no son fuente de verdad y no escriben al canon.")
    for path in (DEFAULT_ENRICHED_DIR, DEFAULT_AI_DIR, DEFAULT_MICROSOFT_COPILOT_DIR, DEFAULT_AUDIT_DIR, DEFAULT_EXPORT_DIR):
        print(f"- {display(path)}: {'OK' if path.exists() else 'no existe'}")

    print("\n1) Generar derivados principales")
    print("2) Validar gobernanza de derivados")
    print("3) Auditoria normativa")
    print("0) Volver")
    choice = prompt("> ").strip()
    if choice == "1":
        confirmation = prompt("Escribe DERIVE para generar derivados locales: ").strip()
        if confirmation != "DERIVE":
            print("Generacion cancelada.")
            return
        result = run_command(
            [
                sys.executable,
                "python_scripts/derive_layers.py",
                "--input-dir",
                str(DEFAULT_CANON_DIR),
                "--enriched-dir",
                str(DEFAULT_ENRICHED_DIR),
                "--ai-dir",
                str(DEFAULT_AI_DIR),
                "--microsoft-copilot-dir",
                str(DEFAULT_MICROSOFT_COPILOT_DIR),
                "--reports-dir",
                str(DEFAULT_AI_DIR / "reports"),
                "--audit-dir",
                str(DEFAULT_AUDIT_DIR),
                "--export-dir",
                str(DEFAULT_EXPORT_DIR),
                "--chunk-target-tokens",
                "1800",
                "--chunk-max-tokens",
                "4000",
            ],
            cwd=REPO_ROOT,
        )
        print_command_result(result)
    elif choice == "2":
        result = run_command(
            [
                sys.executable,
                "python_scripts/validate_corpus_governance.py",
                "--canon-dir",
                str(DEFAULT_CANON_DIR),
                "--ai-dir",
                str(DEFAULT_AI_DIR),
            ],
            cwd=REPO_ROOT,
        )
        print_command_result(result)
    elif choice == "3":
        result = run_command(
            [
                sys.executable,
                "python_scripts/audit_normative_projection.py",
                "--mode",
                "audit",
                "--input-root",
                str(DEFAULT_CANON_DIR),
                "--docs-root",
                "docs",
            ],
            cwd=REPO_ROOT,
        )
        print_command_result(result)


def option_reverse(state: MenuState) -> None:
    html = choose_html(state)
    if not html:
        return
    print("\nEjecutando reverse-preflight antes de reverse...")
    preflight = run_preflight("reverse-preflight")
    print_command_result(preflight)
    if preflight.returncode != 0:
        print("Reverse bloqueado: reverse-preflight fallo.")
        return

    print("\nReverse genera HTML derivado. No cambia la autoridad del canon.")
    confirmation = prompt("Escribe REVERSE para generar HTML derivado: ").strip()
    if confirmation != "REVERSE":
        print("Reverse cancelado.")
        return

    result = run_command(
        [
            "go",
            "run",
            "./cmd/reverse_tiddlers",
            "--html",
            str(html),
            "--canon",
            str(DEFAULT_CANON_DIR),
            "--out-html",
            str(DEFAULT_REVERSE_HTML),
            "--report",
            str(DEFAULT_REVERSE_REPORT),
            "--mode",
            "authoritative-upsert",
        ],
        cwd=REPO_ROOT / "go" / "bridge",
    )
    print_command_result(result)
    if DEFAULT_REVERSE_REPORT.exists():
        print(f"\nReporte: {display(DEFAULT_REVERSE_REPORT)}")
        print(summarize_report(DEFAULT_REVERSE_REPORT))
        try:
            payload = load_json(DEFAULT_REVERSE_REPORT)
            print(f"Rejected: {payload.get('rejected_count', payload.get('rejected', '-'))}")
        except (OSError, json.JSONDecodeError):
            pass


def option_reports() -> None:
    roots = [
        DEFAULT_TMP_DIR,
        DEFAULT_ADMISSION_REPORT_DIR,
        DEFAULT_SESSION_SYNC_DIR,
        DEFAULT_CANON_DIR / "reverse_html",
    ]
    reports = recent_files(roots, "*.json", limit=16)
    print("\nReportes recientes:")
    for index, path in enumerate(reports, start=1):
        print(f"{index}) {display(path)}")
        print(f"   {summarize_report(path)}")
    summary = canon_summary()
    print("\nMetricas canon:")
    print(f"- shards: {len(summary['shards'])}")
    print(f"- lineas: {summary['line_count']}")


def option_rollback() -> None:
    reports = latest_admission_reports(apply_only=True)
    selected = select_path(reports, "reporte apply con rollback disponible")
    if not selected:
        return
    print(f"Reporte seleccionado: {display(selected)}")
    print(summarize_report(selected))
    confirmation = prompt("Escribe ROLLBACK para modificar el canon local: ").strip()
    if confirmation != "ROLLBACK":
        print("Rollback cancelado.")
        return

    result = run_command(
        [
            sys.executable,
            "python_scripts/admit_session_candidates.py",
            "rollback",
            "--admission-report",
            str(selected),
            "--canon-dir",
            str(DEFAULT_CANON_DIR),
            "--tmp-dir",
            str(DEFAULT_TMP_DIR / "session_admission_rollback"),
            "--report-dir",
            str(DEFAULT_ADMISSION_REPORT_DIR),
        ],
        cwd=REPO_ROOT,
    )
    print_command_result(result)


def main_menu() -> None:
    state = MenuState(selected_html=DEFAULT_INPUT_HTML if DEFAULT_INPUT_HTML.exists() else None)
    while True:
        print(
            "\nTiddly Data Converter - Operador local\n\n"
            "1) Preparacion\n"
            "2) Exportar del canon\n"
            "3) Construir canon desde HTML\n"
            "4) Extraer HTML a JSONL temporal\n"
            "5) Shardizar JSONL en canon local\n"
            "6) Validar canon\n"
            "7) Sincronizar entregables de sesiones al canon\n"
            "8) Generar derivados\n"
            "9) Ejecutar reverse\n"
            "10) Ver reportes / metricas\n"
            "11) Rollback de admision\n"
            "0) Salir"
        )
        choice = prompt("> ").strip()
        if choice == "0" or (choice == "" and not sys.stdin.isatty()):
            print("Salida.")
            return
        if choice == "":
            continue
        if choice == "1":
            option_preparation()
        elif choice == "2":
            option_canon_status()
        elif choice == "3":
            option_build_from_html(state)
        elif choice == "4":
            option_extract_html(state)
        elif choice == "5":
            option_shard_jsonl(state)
        elif choice == "6":
            option_validate_canon()
        elif choice == "7":
            option_session_sync(state)
        elif choice == "8":
            option_derivatives()
        elif choice == "9":
            option_reverse(state)
        elif choice == "10":
            option_reports()
        elif choice == "11":
            option_rollback()
        else:
            print("Opcion invalida.")
        pause()


def main() -> int:
    try:
        main_menu()
    except KeyboardInterrupt:
        print("\nInterrumpido.")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
