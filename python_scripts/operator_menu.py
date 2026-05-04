#!/usr/bin/env python3
"""Interactive operator menu for the local tiddly-data-converter workflow."""

from __future__ import annotations

import json
import hashlib
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
    sorted_canon_shards,
)
from session_sync import DEFAULT_SESSION_SYNC_DIR, scan_session_sync  # noqa: E402
from tdc_cat import (  # noqa: E402
    tdc_cat_error,
    tdc_cat_loading,
    tdc_cat_loading_start,
    tdc_cat_loading_stop,
    tdc_cat_open,
    tdc_cat_success,
    tdc_cat_warning,
)


DEFAULT_SESSIONS_DIR = REPO_ROOT / "data" / "out" / "local" / "sessions"
DEFAULT_TMP_DIR = REPO_ROOT / "data" / "tmp"
DEFAULT_ADMISSION_TMP_DIR = DEFAULT_TMP_DIR / "session_admission"
DEFAULT_ADMISSION_REPORT_DIR = DEFAULT_TMP_DIR / "admissions"
HTML_EXPORT_DIR = DEFAULT_TMP_DIR / "html_export"
RECONSTRUCTION_DIR = DEFAULT_TMP_DIR / "reconstruction"
QUALITY_REPORT_DIR = DEFAULT_TMP_DIR / "canonical_quality"
MAIN_SEED_HTML = REPO_ROOT / "data" / "in" / "objeto_de_estudio_trazabilidad_y_desarrollo.html"
BOOTSTRAP_AUX_HTML = REPO_ROOT / "data" / "in" / "empty-store.html"
CANON_SHARD_MAX_LINES = 100


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
    last_reconstruction_report: Path | None = None
    last_reverse_report: Path | None = None
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


def parse_stdout_json_payload(stdout: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return parse_stdout_json(stdout)
    return payload if isinstance(payload, dict) else None


def count_jsonl_lines(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return sum(1 for line in handle if line.strip())
    except OSError:
        return 0


def canonical_file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.name.encode("utf-8"))
    digest.update(b"\0")
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def file_content_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def canon_tree_manifest(canon_dir: Path = DEFAULT_CANON_DIR) -> dict[str, Any]:
    digest = hashlib.sha256()
    shards = canon_shards(canon_dir)
    shard_entries: list[dict[str, Any]] = []
    for shard in shards:
        data_hash = hashlib.sha256()
        byte_count = 0
        digest.update(shard.name.encode("utf-8"))
        digest.update(b"\0")
        with shard.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
                data_hash.update(chunk)
                byte_count += len(chunk)
        digest.update(b"\0")
        shard_entries.append(
            {
                "path": as_display_path(shard),
                "name": shard.name,
                "line_count": count_jsonl_lines(shard),
                "byte_count": byte_count,
                "sha256": f"sha256:{data_hash.hexdigest()}",
            }
        )
    return {
        "root": as_display_path(canon_dir),
        "hash": f"sha256:{digest.hexdigest()}",
        "shard_count": len(shards),
        "line_count": sum(item["line_count"] for item in shard_entries),
        "byte_count": sum(item["byte_count"] for item in shard_entries),
        "shards": shard_entries,
        "has_real_content": bool(shards) and any(item["byte_count"] > 0 for item in shard_entries),
    }


def canon_tree_hash(canon_dir: Path = DEFAULT_CANON_DIR) -> str:
    return str(canon_tree_manifest(canon_dir)["hash"])


def canon_shards(canon_dir: Path = DEFAULT_CANON_DIR) -> list[Path]:
    return sorted_canon_shards(canon_dir)


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
    role = source_role_for_html(path)
    if role == "seed":
        return "Semilla reusable principal"
    if role == "bootstrap_aux":
        return "Superficie auxiliar/base"
    return "HTML de trabajo"


def source_role_for_html(path: Path) -> str:
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    if resolved == MAIN_SEED_HTML.resolve():
        return "seed"
    if resolved == BOOTSTRAP_AUX_HTML.resolve():
        return "bootstrap_aux"
    return "working"


def describe_source_role(role: str) -> str:
    labels = {
        "seed": "semilla reusable principal",
        "working": "superficie de trabajo",
        "bootstrap_aux": "superficie auxiliar/base",
    }
    return labels.get(role, role)


def run_reconstruction_gate(
    source_html: Path,
    mode: str,
    output_target: Path,
    *,
    requires_backup: bool,
    requires_hash_report: bool,
    input_jsonl: Path | None = None,
    reconstruction_run_dir: Path | None = None,
    report_dir: Path | None = None,
    show_result: bool = True,
) -> tuple[bool, dict[str, Any] | None, CommandResult | None]:
    if not shutil.which("cargo"):
        print("Compuerta Rust bloqueada: cargo no esta disponible.")
        return False, None, None

    role = source_role_for_html(source_html)
    args = [
        "cargo",
        "run",
        "--quiet",
        "--bin",
        "audit",
        "--",
        "reconstruction-plan",
        str(REPO_ROOT),
        "--source-html",
        str(source_html),
        "--source-role",
        role,
        "--mode",
        mode,
        "--output-target",
        str(output_target),
    ]
    if input_jsonl is not None:
        args.extend(["--input-jsonl", str(input_jsonl)])
    if reconstruction_run_dir is not None:
        args.extend(["--reconstruction-run-dir", str(reconstruction_run_dir)])
    args.extend(
        [
            "--requires-backup",
            "true" if requires_backup else "false",
            "--requires-hash-report",
            "true" if requires_hash_report else "false",
        ]
    )
    result = run_command(args, cwd=REPO_ROOT / "rust" / "doctor")
    payload = parse_stdout_json_payload(result.stdout)
    if payload is not None and report_dir is not None:
        report_dir.mkdir(parents=True, exist_ok=True)
        gate_report = {
            "run_id": report_dir.name,
            "timestamp": stamp_now(),
            "report_kind": "rust_reconstruction_gate",
            "source_html": as_display_path(source_html),
            "source_role": role,
            "mode": mode,
            "output_target": as_display_path(output_target),
            "input_jsonl": as_display_path(input_jsonl) if input_jsonl else None,
            "backup_required": requires_backup,
            "hash_report_required": requires_hash_report,
            "gate_verdict": payload.get("verdict"),
            "gate_exit_code": result.returncode,
            "gate_report": payload,
        }
        write_json(report_dir / "gate-report.json", gate_report)
    if show_result:
        verdict = payload.get("verdict") if payload else "sin_json"
        errors = payload.get("errors") if payload else "-"
        print("\nCompuerta Rust de plan de reconstruccion:")
        print(f"- fuente: {display(source_html)} ({describe_source_role(role)})")
        print(f"- modo: {mode}")
        print(f"- destino: {display(output_target)}")
        if input_jsonl is not None:
            print(f"- JSONL temporal: {display(input_jsonl)}")
        if report_dir is not None:
            print(f"- reporte gate: {display(report_dir / 'gate-report.json')}")
        print(f"- veredicto: {verdict}")
        print(f"- errores: {errors}")
        if result.returncode != 0:
            print_command_result(result, max_chars=1600)
    return result.returncode == 0, payload, result


def write_reconstruction_report(run_dir: Path, payload: dict[str, Any]) -> Path:
    report_path = run_dir / "reconstruction-report.json"
    write_json(report_path, payload)
    return report_path


def copy_canon_shards(run_dir: Path, name: str, canon_dir: Path = DEFAULT_CANON_DIR) -> Path:
    snapshot_dir = run_dir / name
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    for existing in snapshot_dir.glob("tiddlers_*.jsonl"):
        existing.unlink()
    for shard in canon_shards(canon_dir):
        shutil.copy2(shard, snapshot_dir / shard.name)
    return snapshot_dir


def backup_canon_shards(run_dir: Path) -> Path:
    return copy_canon_shards(run_dir, "canon_before", DEFAULT_CANON_DIR)


def latest_reconstruction_reports(rollback_only: bool = False) -> list[Path]:
    reports = recent_files([RECONSTRUCTION_DIR], "reconstruction-report.json", limit=80)
    selected: list[Path] = []
    for path in reports:
        try:
            payload = load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        if rollback_only and not payload.get("rollback_ready"):
            continue
        selected.append(path)
    return selected[:12]


def reverse_rejected_count(report_path: Path) -> int | None:
    try:
        payload = load_json(report_path)
    except (OSError, json.JSONDecodeError):
        return None
    value = payload.get("rejected_count", payload.get("rejected"))
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def reverse_evidence_report(state: MenuState | None = None) -> Path | None:
    candidates: list[Path] = []
    if state and state.last_reverse_report and state.last_reverse_report.exists():
        candidates.append(state.last_reverse_report)
    if DEFAULT_REVERSE_REPORT.exists():
        candidates.append(DEFAULT_REVERSE_REPORT)
    candidates.extend(recent_files([DEFAULT_CANON_DIR / "reverse_html", RECONSTRUCTION_DIR], "reverse-report.json", limit=8))
    for path in candidates:
        if path.exists() and reverse_rejected_count(path) == 0:
            return path
    return None


def derivative_continuity_ok(state: MenuState | None = None) -> tuple[bool, str, Path | None]:
    report = reverse_evidence_report(state)
    if not report:
        return False, "no hay reporte reverse reciente con Rejected: 0", None
    return True, "ok", report


def choose_html(state: MenuState) -> Path | None:
    html_files = detect_html_files()
    if state.selected_html and state.selected_html.exists():
        print(f"HTML actual: {display(state.selected_html)}")
        answer = prompt("Usar este HTML? [Enter = si, c = cambiar] ").strip().lower()
        if answer != "c":
            print(f"Rol declarado: {describe_source_role(source_role_for_html(state.selected_html))}")
            return state.selected_html

    selected = select_path(html_files, "HTML fuente", html_option_label)
    if selected:
        state.selected_html = selected
        print(f"Rol declarado: {describe_source_role(source_role_for_html(selected))}")
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
            f"replaceable={len(payload.get('replaceable_same_id_different_content') or [])}, "
            f"blocked={len(payload.get('blocked_same_id_different_content') or [])}, "
            f"invalid={len(payload.get('invalid') or [])}"
        )

    if "gate_verdict" in payload and "canon_before_hash" in payload:
        return (
            f"run_id={payload.get('run_id')}, "
            f"gate={payload.get('gate_verdict')}, "
            f"shard_exit={payload.get('shard_exit_code')}, "
            f"post_validation={payload.get('post_shard_validation_ok')}, "
            f"rollback_ready={payload.get('rollback_ready')}, "
            f"canon_modified={payload.get('canon_modified')}"
        )

    if payload.get("report_kind") == "rust_reconstruction_gate":
        return (
            f"run_id={payload.get('run_id')}, "
            f"mode={payload.get('mode')}, "
            f"gate={payload.get('gate_verdict')}, "
            f"exit={payload.get('gate_exit_code')}"
        )

    if payload.get("mode") == "reverse_projection":
        return (
            f"run_id={payload.get('run_id')}, "
            f"gate={payload.get('gate_verdict')}, "
            f"reverse_exit={payload.get('reverse_exit_code')}, "
            f"reverse_rejected={payload.get('reverse_rejected')}, "
            f"derivatives_ready={payload.get('derivatives_ready')}"
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
        ("data/out/local/sessions", DEFAULT_SESSIONS_DIR.exists(), display(DEFAULT_SESSIONS_DIR)),
        ("data/out/local", DEFAULT_CANON_DIR.exists(), display(DEFAULT_CANON_DIR)),
        ("python_scripts", (REPO_ROOT / "python_scripts").exists(), "python_scripts"),
        ("admit_session_candidates.py", (REPO_ROOT / "python_scripts" / "admit_session_candidates.py").exists(), ""),
        ("go/canon", (REPO_ROOT / "go" / "canon").exists(), "go/canon"),
        ("go/bridge", (REPO_ROOT / "go" / "bridge").exists(), "go/bridge"),
        ("go/ingesta", (REPO_ROOT / "go" / "ingesta").exists(), "go/ingesta"),
        ("data/tmp", DEFAULT_TMP_DIR.exists(), display(DEFAULT_TMP_DIR)),
        ("python3", shutil.which("python3") is not None, shutil.which("python3") or ""),
        ("go", shutil.which("go") is not None, shutil.which("go") or ""),
        ("cargo", shutil.which("cargo") is not None, shutil.which("cargo") or ""),
    ]
    for name, ok, detail in checks:
        state = "OK" if ok else "FALTA"
        suffix = f" - {detail}" if detail else ""
        print(f"- {name}: {state}{suffix}")
    DEFAULT_TMP_DIR.mkdir(parents=True, exist_ok=True)

    if shutil.which("cargo") and (REPO_ROOT / "rust" / "doctor").exists():
        result = run_command(
            ["cargo", "run", "--quiet", "--bin", "audit", "--", "perimeter", str(REPO_ROOT)],
            cwd=REPO_ROOT / "rust" / "doctor",
        )
        state = "OK" if result.returncode == 0 else "ERROR"
        print(f"- rust kernel perimeter: {state}")
        if result.returncode != 0:
            print_command_result(result, max_chars=1200)
    else:
        print("- rust kernel perimeter: FALTA - cargo o rust/doctor no disponible")

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
        run_dir = RECONSTRUCTION_DIR / f"diagnostic-{stamp_now()}"
        run_reconstruction_gate(
            selected,
            "diagnostic",
            DEFAULT_TMP_DIR / "reconstruction_plan",
            requires_backup=False,
            requires_hash_report=False,
            report_dir=run_dir,
        )
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
    gate_report_dir = RECONSTRUCTION_DIR / run_id
    gate_ok, _, _ = run_reconstruction_gate(
        html,
        "staging",
        out_dir,
        requires_backup=False,
        requires_hash_report=True,
        report_dir=gate_report_dir,
    )
    if not gate_ok:
        print("Extraccion bloqueada por la compuerta Rust. No se escribio salida temporal.")
        return
    out_dir.mkdir(parents=True, exist_ok=True)

    tdc_cat_loading("Extraer HTML a JSONL temporal")
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
        write_reconstruction_report(
            gate_report_dir,
            {
                "run_id": run_id,
                "timestamp": stamp_now(),
                "mode": "staging",
                "source_html": as_display_path(html),
                "source_role": source_role_for_html(html),
                "source_html_hash": file_content_hash(html),
                "input_jsonl": as_display_path(out_jsonl),
                "input_jsonl_hash": file_content_hash(out_jsonl),
                "output_target": as_display_path(out_dir),
                "export_manifest": as_display_path(manifest),
                "gate_report": as_display_path(gate_report_dir / "gate-report.json"),
                "export_exit_code": result.returncode,
                "rollback_ready": False,
            },
        )
        print("\nSalidas temporales:")
        print(f"- JSONL: {display(out_jsonl)} ({count_jsonl_lines(out_jsonl)} lineas)")
        print(f"- log: {display(out_log)}")
        print(f"- manifest: {display(manifest)}")
        print(f"- reporte reconstruccion: {display(gate_report_dir / 'reconstruction-report.json')}")
        print("Siguiente paso recomendado: opcion 5 para shardizar si quieres reconstruir el canon local.")
        tdc_cat_success("Extraccion completada.")
    else:
        tdc_cat_error()
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

    html = choose_html(state)
    if not html:
        print("Shardizacion cancelada: se requiere fuente HTML explicita.")
        return

    run_id = f"reconstruction-{stamp_now()}"
    run_dir = RECONSTRUCTION_DIR / run_id
    gate_ok, gate_payload, gate_result = run_reconstruction_gate(
        html,
        "write_local_canon",
        DEFAULT_CANON_DIR,
        requires_backup=True,
        requires_hash_report=True,
        input_jsonl=selected,
        reconstruction_run_dir=run_dir,
        report_dir=run_dir,
    )
    if not gate_ok:
        print("Shardizacion bloqueada por la compuerta Rust. No se modifico el canon.")
        return

    print("\nAdvertencia: esta opcion escribe shards en data/out/local.")
    print("JSONL temporal != canon; los shards en data/out/local son el canon local oficial.")
    print(f"Politica de shardizacion: maximo {CANON_SHARD_MAX_LINES} lineas por archivo.")
    print(f"Fuente HTML declarada: {display(html)}")
    print(f"JSONL temporal: {display(selected)}")
    print(f"Destino de salida: {display(DEFAULT_CANON_DIR)}")
    print(f"Backup/reporte: {display(run_dir)}")
    confirmation = prompt("Escribe WRITE CANON para continuar: ").strip()
    if confirmation != "WRITE CANON":
        print("Shardizacion cancelada. No se modifico el canon.")
        return

    run_dir.mkdir(parents=True, exist_ok=True)
    before_manifest = canon_tree_manifest(DEFAULT_CANON_DIR)
    before_hash = str(before_manifest["hash"])
    backup_dir = backup_canon_shards(run_dir)
    backup_manifest = canon_tree_manifest(backup_dir)
    backup_matches_before = backup_manifest["hash"] == before_hash
    before_had_canon = before_manifest["shard_count"] > 0 and before_manifest["has_real_content"]
    empty_before_authorized = backup_matches_before and before_manifest["shard_count"] == 0
    backup_usable = (
        backup_matches_before
        and before_had_canon
        and backup_manifest["has_real_content"]
    )
    if not backup_usable and not empty_before_authorized:
        report_path = write_reconstruction_report(
            run_dir,
            {
                "run_id": run_id,
                "timestamp": stamp_now(),
                "mode": "write_local_canon",
                "source_html": as_display_path(html),
                "source_role": source_role_for_html(html),
                "input_jsonl": as_display_path(selected),
                "output_target": as_display_path(DEFAULT_CANON_DIR),
                "backup_dir": as_display_path(backup_dir),
                "canon_before": before_manifest,
                "canon_before_hash": before_hash,
                "backup_manifest": backup_manifest,
                "backup_matches_before": backup_matches_before,
                "empty_before_authorized": empty_before_authorized,
                "gate_verdict": gate_payload.get("verdict") if gate_payload else None,
                "gate_report": gate_payload,
                "gate_exit_code": gate_result.returncode if gate_result else None,
                "shard_exit_code": None,
                "status": "blocked_backup_unusable",
                "rollback_ready": False,
            },
        )
        state.last_reconstruction_report = report_path
        print("Shardizacion bloqueada: el backup no representa un canon previo real y verificable.")
        print(f"Reporte de reconstruccion: {display(report_path)}")
        return
    if empty_before_authorized:
        print("Canon previo vacio detectado: se conservara evidencia before/after, sin rollback a canon previo real.")
    input_hash = canonical_file_hash(selected)
    input_content_hash = file_content_hash(selected)

    tdc_cat_loading("Shardizar JSONL en canon local")
    result = run_command(
        [
            "go",
            "run",
            "./cmd/shard_canon",
            "--input",
            str(selected),
            "--out-dir",
            str(DEFAULT_CANON_DIR),
            "--max-lines",
            str(CANON_SHARD_MAX_LINES),
        ],
        cwd=REPO_ROOT / "go" / "canon",
    )
    print_command_result(result)
    after_manifest = canon_tree_manifest(DEFAULT_CANON_DIR)
    after_hash = str(after_manifest["hash"])
    after_dir = copy_canon_shards(run_dir, "canon_after", DEFAULT_CANON_DIR)
    after_snapshot_manifest = canon_tree_manifest(after_dir)
    strict_result: CommandResult | None = None
    strict_payload: dict[str, Any] | None = None
    reverse_preflight_result: CommandResult | None = None
    reverse_preflight_payload: dict[str, Any] | None = None
    if result.returncode == 0:
        print("\nValidacion post-shardizacion: strict")
        strict_result = run_preflight("strict")
        print_command_result(strict_result)
        strict_payload = parse_stdout_json_payload(strict_result.stdout)

        print("\nValidacion post-shardizacion: reverse-preflight")
        reverse_preflight_result = run_preflight("reverse-preflight")
        print_command_result(reverse_preflight_result)
        reverse_preflight_payload = parse_stdout_json_payload(reverse_preflight_result.stdout)

    validation_ok = (
        result.returncode == 0
        and strict_result is not None
        and strict_result.returncode == 0
        and reverse_preflight_result is not None
        and reverse_preflight_result.returncode == 0
    )
    report_path = write_reconstruction_report(
        run_dir,
        {
            "run_id": run_id,
            "timestamp": stamp_now(),
            "mode": "write_local_canon",
            "source_html": as_display_path(html),
            "source_role": source_role_for_html(html),
            "source_html_hash": file_content_hash(html),
            "input_jsonl": as_display_path(selected),
            "input_jsonl_hash": input_hash,
            "input_jsonl_content_hash": input_content_hash,
            "output_target": as_display_path(DEFAULT_CANON_DIR),
            "backup_dir": as_display_path(backup_dir),
            "canon_after_dir": as_display_path(after_dir),
            "canon_before": before_manifest,
            "canon_after": after_manifest,
            "backup_manifest": backup_manifest,
            "canon_after_snapshot": after_snapshot_manifest,
            "canon_before_hash": before_hash,
            "canon_after_hash": after_hash,
            "shard_max_lines": CANON_SHARD_MAX_LINES,
            "backup_matches_before": backup_matches_before,
            "empty_before_authorized": empty_before_authorized,
            "gate_verdict": gate_payload.get("verdict") if gate_payload else None,
            "gate_report": gate_payload,
            "gate_exit_code": gate_result.returncode if gate_result else None,
            "shard_exit_code": result.returncode,
            "shard_report": parse_stdout_json_payload(result.stdout),
            "strict_exit_code": strict_result.returncode if strict_result else None,
            "strict_report": strict_payload,
            "reverse_preflight_exit_code": reverse_preflight_result.returncode if reverse_preflight_result else None,
            "reverse_preflight_report": reverse_preflight_payload,
            "post_shard_validation_ok": validation_ok,
            "reverse_required_for_derivatives": True,
            "derivatives_ready": False,
            "rollback_ready": backup_usable,
            "canon_modified": before_hash != after_hash,
        },
    )
    state.last_reconstruction_report = report_path
    print(f"\nReporte de reconstruccion: {display(report_path)}")
    print(f"- backup: {display(backup_dir)}")
    print(f"- canon_after: {display(after_dir)}")
    print(f"- hash before: {before_hash}")
    print(f"- hash after:  {after_hash}")
    if result.returncode == 0:
        option_canon_status()
        if validation_ok:
            tdc_cat_success("Shardizacion y cadena de validacion OK.")
            print("Cadena post-shardizacion OK: strict + reverse-preflight.")
            print("Siguiente paso recomendado: opcion 9 para ejecutar reverse. Derivados siguen bloqueados hasta Rejected: 0.")
        else:
            tdc_cat_warning("Shardizacion aplicada, pero validacion pendiente.")
            print("Continuidad bloqueada: strict y reverse-preflight deben pasar antes de reverse o derivados.")
    else:
        tdc_cat_error()


def run_preflight(mode: str) -> CommandResult:
    return run_command(
        ["go", "run", "./cmd/canon_preflight", "--mode", mode, "--input", str(DEFAULT_CANON_DIR)],
        cwd=REPO_ROOT / "go" / "canon",
    )


def option_validate_canon() -> bool:
    tdc_cat_loading("Validar canon — strict + reverse-preflight")
    print("\nValidacion strict")
    strict = run_preflight("strict")
    print_command_result(strict)
    if strict.returncode != 0:
        tdc_cat_error("Fallo strict. Corregir antes de reverse o admision.")
        print("Fallo strict. No se recomienda reverse ni admision hasta corregir.")
        return False

    print("\nReverse preflight")
    reverse = run_preflight("reverse-preflight")
    print_command_result(reverse)
    if reverse.returncode != 0:
        tdc_cat_error("Fallo reverse-preflight. Corregir antes de reverse o admision.")
        print("Fallo reverse-preflight. No se recomienda reverse ni admision hasta corregir.")
        return False

    print("\nEstado final: OK. Condicion critica esperada: not_ready=0 y Rejected=0 en reverse.")
    tdc_cat_success("Strict + reverse-preflight OK.")
    return True


def run_doctor_quality_report(kind: str, input_path: Path, report_path: Path) -> tuple[CommandResult | None, dict[str, Any] | None]:
    if not shutil.which("cargo"):
        print("Compuerta Rust bloqueada: cargo no esta disponible.")
        return None, None
    result = run_command(
        [
            "cargo",
            "run",
            "--quiet",
            "--bin",
            "audit",
            "--",
            kind,
            str(REPO_ROOT),
            "--input",
            str(input_path),
            "--report",
            str(report_path),
        ],
        cwd=REPO_ROOT / "rust" / "doctor",
    )
    payload = parse_stdout_json_payload(result.stdout)
    if payload is None and report_path.exists():
        try:
            payload = load_json(report_path)
        except (OSError, json.JSONDecodeError):
            payload = None
    return result, payload


def option_canon_quality() -> None:
    run_dir = QUALITY_REPORT_DIR / f"quality-{stamp_now()}"
    run_dir.mkdir(parents=True, exist_ok=True)
    line_report = run_dir / "canonical-line-gate.json"
    deep_report = run_dir / "deep-node-inspect.json"

    print("\nAuditoria Rust de calidad canonica")
    print("No escribe data/out/local; solo emite reportes bajo data/tmp/canonical_quality.")

    line_result, line_payload = run_doctor_quality_report(
        "canonical-line-gate",
        DEFAULT_CANON_DIR,
        line_report,
    )
    if line_payload:
        counts = line_payload.get("counts") or {}
        print("\nCanonical-line gate:")
        print(f"- reporte: {display(line_report)}")
        print(f"- veredicto: {line_payload.get('verdict')}")
        print(f"- lineas leidas: {line_payload.get('lines_read')}")
        print(f"- ok: {counts.get('canon_line_ok', 0)}")
        print(f"- warning: {counts.get('canon_line_warning', 0)}")
        print(f"- incomplete: {counts.get('canon_line_incomplete', 0)}")
        print(f"- inconsistent: {counts.get('canon_line_inconsistent', 0)}")
        print(f"- rejected: {counts.get('canon_line_rejected', 0)}")
        print(f"- familias con deriva: {len(line_payload.get('template_families_with_drift') or [])}")
        print(f"- perfiles de familia: {len(line_payload.get('family_profiles') or [])}")
        modal = line_payload.get("modal_projection_audit") or {}
        if modal:
            print("- auditoria modal:")
            print(f"  - lineas relevantes: {modal.get('relevant_lines', 0)}")
            print(f"  - proyectadas: {modal.get('projected_lines', 0)}")
            print(f"  - sin proyeccion: {modal.get('missing_projection_lines', 0)}")
            projection_counts = modal.get("projection_counts") or {}
            if projection_counts:
                summary = ", ".join(f"{key}={value}" for key, value in sorted(projection_counts.items()))
                print(f"  - proyecciones: {summary}")
        debt = line_payload.get("debt_summary") or {}
        if debt:
            print("- separacion de deuda:")
            print(f"  - deuda modal: {debt.get('modal_debt_lines', 0)} lineas")
            print(f"  - deuda modal de assets: {debt.get('asset_modal_debt_lines', 0)} lineas")
            print(f"  - deriva historica de plantillas: {debt.get('template_drift_families_historical', 0)} familias")
            print(f"  - warnings de riqueza: {debt.get('richness_warning_lines', 0)} lineas")
        triage = line_payload.get("incomplete_line_triage") or []
        print(f"- triage de incompletas: {len(triage)} grupos")
        for item in triage[:5]:
            print(
                f"  - {item.get('family')}: {item.get('line_count')} "
                f"lineas, prioridad={item.get('priority')}, razon={item.get('reason')}"
            )
    else:
        print("Canonical-line gate no produjo JSON parseable.")
        if line_result:
            print_command_result(line_result, max_chars=1600)

    deep_result, deep_payload = run_doctor_quality_report(
        "deep-node-inspect",
        DEFAULT_CANON_DIR,
        deep_report,
    )
    if deep_payload:
        counts = deep_payload.get("counts") or {}
        print("\nDeep-node inspector:")
        print(f"- reporte: {display(deep_report)}")
        print(f"- veredicto: {deep_payload.get('verdict')}")
        print(f"- nodos leidos: {deep_payload.get('nodes_read')}")
        print(f"- campos inspeccionados: {deep_payload.get('inspected_text_fields')}")
        print(f"- hallazgos: {deep_payload.get('findings_count')}")
        print(f"- JSON estructural: {counts.get('structural_json', 0)}")
        print(f"- JSON valido: {counts.get('valid_json', 0)}")
        print(f"- JSON recuperable: {counts.get('recoverable_json', 0)}")
        print(f"- fragmentos JSON: {counts.get('json_fragment', 0)}")
        print(f"- JSON pedagogico/fixture: {counts.get('pedagogical_json', 0)}")
        print(f"- JSON invalido/reportable: {counts.get('invalid_json', 0)}")
        print(f"- tablas markdown: {counts.get('markdown_table', 0)}")
    else:
        print("Deep-node inspector no produjo JSON parseable.")
        if deep_result:
            print_command_result(deep_result, max_chars=1600)

    print("\nSiguiente paso recomendado: revisar reportes y decidir si alguna familia requiere hardening posterior.")


def option_modal_delta_staging() -> None:
    run_id = f"s77-modal-assets-{stamp_now()}"
    normalized_jsonl = DEFAULT_TMP_DIR / "s76-modal-export" / "local-normalized-modal.jsonl"
    print("\nStaging de delta modal controlado")
    print("Compara canon vivo contra la copia normalizada S76 y no modifica data/out/local.")
    if not normalized_jsonl.exists():
        print(f"No existe la copia normalizada esperada: {display(normalized_jsonl)}")
        return

    result = run_command(
        [
            sys.executable,
            "python_scripts/stage_modal_delta.py",
            "--run-id",
            run_id,
            "--run-gates",
        ],
        cwd=REPO_ROOT,
    )
    print_command_result(result)
    payload = parse_stdout_json(result.stdout)
    if not payload:
        print("El staging no produjo resumen JSON parseable.")
        return

    print("\nResultado:")
    print(f"- reporte: {payload.get('report')}")
    print(f"- patch JSONL: {payload.get('patch_jsonl')}")
    print(f"- staged canon: {payload.get('staged_canon_dir')}")
    print(f"- lineas cambiadas en comparacion S76: {payload.get('changed_line_count')}")
    print(f"- delta seleccionado: {payload.get('selected_count')}")
    gates = payload.get("gates") or {}
    print(f"- strict: {gates.get('strict')}")
    print(f"- reverse-preflight: {gates.get('reverse_preflight')}")
    print(f"- reverse: {gates.get('reverse_authoritative')} (Rejected: {gates.get('reverse_rejected')})")
    print("- canon modificado: no")


def print_inventory_summary(inventory: dict[str, Any]) -> None:
    summary = canon_summary()
    print("\nSincronizacion de sesiones")
    print("Canon actual:")
    print(f"- shards: {len(summary['shards'])}")
    print(f"- lineas: {summary['line_count']}")
    print("Sessions:")
    print(f"- archivos detectados: {inventory['total_files_scanned']}")
    print(f"- entregables validos: {inventory['total_session_records']}")
    print(f"- ya existen iguales en canon por ID: {len(inventory['existing_by_id'])}")
    print(f"- faltantes por ID: {len(inventory['missing_by_id'])}")
    print(f"- diferencias reemplazables por ID: {len(inventory.get('replaceable_same_id_different_content') or [])}")
    print(f"- conflictos bloqueantes: {len(inventory.get('blocked_same_id_different_content') or [])}")
    print(f"- invalidos: {len(inventory['invalid'])}")
    print(f"- unsupported: {len(inventory['unsupported'])}")
    print(f"- inventario: {inventory['inventory_path']}")
    if inventory.get("generated_missing_candidate_file"):
        print(f"- candidatos faltantes: {inventory['generated_missing_candidate_file']}")
    if inventory.get("generated_replacement_candidate_file"):
        print(f"- candidatos de reemplazo: {inventory['generated_replacement_candidate_file']}")
    if inventory.get("generated_candidate_file"):
        print(f"- candidatos sincronizables: {inventory['generated_candidate_file']}")


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


def sync_admission_extra_args(inventory: dict[str, Any]) -> list[str]:
    if inventory.get("replaceable_same_id_different_content"):
        return ["--allow-replacements"]
    return []


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
    print("\nEscaneando data/out/local/sessions por ID canonico...")
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
            "2) Ver diferencias reemplazables\n"
            "3) Ver conflictos bloqueantes\n"
            "4) Ver candidatos generados\n"
            "5) Validar candidatos\n"
            "6) Dry-run de admision\n"
            "7) Apply confirmado\n"
            "8) Rollback ultimo apply\n"
            "0) Volver"
        )
        choice = prompt("> ").strip()
        if choice == "0" or choice == "":
            return
        if choice == "1":
            print_items("Faltantes por ID", inventory["missing_by_id"])
        elif choice == "2":
            print_items(
                "Diferencias reemplazables por mismo ID y source_path",
                inventory.get("replaceable_same_id_different_content") or [],
            )
        elif choice == "3":
            print_items(
                "Conflictos bloqueantes",
                inventory.get("blocked_same_id_different_content") or [],
            )
            print_items("Invalidos", inventory["invalid"], limit=20)
        elif choice == "4":
            if state.last_sync_candidate_file:
                print(f"Candidato sincronizable: {display(state.last_sync_candidate_file)}")
                print(f"Lineas: {count_jsonl_lines(state.last_sync_candidate_file)}")
                if inventory.get("replaceable_same_id_different_content"):
                    print("Modo: incluye reemplazos controlados; se usara --allow-replacements.")
            else:
                print("No hay faltantes ni reemplazos; no se genero archivo de candidatos.")
        elif choice == "5":
            if not state.last_sync_candidate_file:
                print("No hay candidatos sincronizables para validar.")
                continue
            if inventory.get("blocked_same_id_different_content"):
                print("Hay conflictos bloqueantes por ID. Resolver antes de validar admision.")
                continue
            result, payload = run_admission_command(
                "validate",
                state.last_sync_candidate_file,
                sync_admission_extra_args(inventory),
            )
            if payload and payload.get("report"):
                state.last_validate_report = (REPO_ROOT / payload["report"]).resolve()
            if result.returncode == 0:
                print("Validacion OK. Siguiente paso recomendado: dry-run.")
        elif choice == "6":
            if not state.last_sync_candidate_file:
                print("No hay candidatos sincronizables para dry-run.")
                continue
            if inventory.get("blocked_same_id_different_content"):
                print("Hay conflictos bloqueantes por ID. Resolver antes de dry-run.")
                continue
            result, payload = run_admission_command(
                "dry-run",
                state.last_sync_candidate_file,
                sync_admission_extra_args(inventory),
            )
            if payload and payload.get("report"):
                state.last_dry_run_report = (REPO_ROOT / payload["report"]).resolve()
            if result.returncode == 0:
                print("Dry-run OK. Revisar el reporte antes de apply.")
        elif choice == "7":
            if not state.last_sync_candidate_file:
                print("No hay candidatos sincronizables para apply.")
                continue
            if inventory.get("blocked_same_id_different_content"):
                print("Hay conflictos bloqueantes por ID. Apply bloqueado.")
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
            print(f"- lineas a sincronizar: {count_jsonl_lines(state.last_sync_candidate_file)}")
            print(f"- faltantes nuevos: {len(inventory['missing_by_id'])}")
            print(f"- reemplazos controlados: {len(inventory.get('replaceable_same_id_different_content') or [])}")
            print(f"- dry-run revisable: {display(state.last_dry_run_report)}")
            confirmation = prompt("Escribe APPLY para modificar el canon local: ").strip()
            if confirmation != "APPLY":
                print("Apply cancelado.")
                continue
            run_admission_command(
                "apply",
                state.last_sync_candidate_file,
                [*sync_admission_extra_args(inventory), "--confirm-apply"],
            )
        elif choice == "8":
            option_rollback()
        else:
            print("Opcion invalida.")


def option_derivatives(state: MenuState) -> None:
    print("\nDerivados: canon local -> derivados")
    print("Los derivados no son fuente de verdad y no escriben al canon.")
    continuity_ok, reason, reverse_report = derivative_continuity_ok(state)
    if continuity_ok and reverse_report:
        print(f"- evidencia reverse: OK ({display(reverse_report)}, Rejected: 0)")
    else:
        print(f"- evidencia reverse: BLOQUEADA - {reason}")
    for path in (DEFAULT_ENRICHED_DIR, DEFAULT_AI_DIR, DEFAULT_MICROSOFT_COPILOT_DIR, DEFAULT_AUDIT_DIR, DEFAULT_EXPORT_DIR):
        print(f"- {display(path)}: {'OK' if path.exists() else 'no existe'}")

    print("\n1) Generar derivados principales")
    print("2) Validar gobernanza de derivados")
    print("3) Auditoria normativa")
    print("0) Volver")
    choice = prompt("> ").strip()
    if choice == "1":
        if not continuity_ok:
            print("Generacion bloqueada: ejecuta reverse y exige Rejected: 0 antes de derivados.")
            return
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
    run_dir = RECONSTRUCTION_DIR / f"reverse-{stamp_now()}"
    gate_ok, gate_payload, gate_result = run_reconstruction_gate(
        html,
        "reverse_projection",
        DEFAULT_REVERSE_HTML,
        requires_backup=False,
        requires_hash_report=True,
        report_dir=run_dir,
    )
    if not gate_ok:
        print("Reverse bloqueado por la compuerta Rust.")
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

    tdc_cat_loading("Ejecutar reverse authoritative-upsert")
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
    reverse_payload: dict[str, Any] | None = None
    if DEFAULT_REVERSE_REPORT.exists():
        print(f"\nReporte: {display(DEFAULT_REVERSE_REPORT)}")
        print(summarize_report(DEFAULT_REVERSE_REPORT))
        try:
            reverse_payload = load_json(DEFAULT_REVERSE_REPORT)
            rejected = reverse_payload.get("rejected_count", reverse_payload.get("rejected", "-"))
            print(f"Rejected: {rejected}")
        except (OSError, json.JSONDecodeError):
            pass
    reverse_rejected = None
    if reverse_payload:
        try:
            reverse_rejected = int(reverse_payload.get("rejected_count", reverse_payload.get("rejected")))
        except (TypeError, ValueError):
            reverse_rejected = None
    reverse_ok = result.returncode == 0 and reverse_rejected == 0
    report_path = write_reconstruction_report(
        run_dir,
        {
            "run_id": run_dir.name,
            "timestamp": stamp_now(),
            "mode": "reverse_projection",
            "source_html": as_display_path(html),
            "source_role": source_role_for_html(html),
            "source_html_hash": file_content_hash(html),
            "output_target": as_display_path(DEFAULT_REVERSE_HTML),
            "gate_verdict": gate_payload.get("verdict") if gate_payload else None,
            "gate_report": gate_payload,
            "gate_exit_code": gate_result.returncode if gate_result else None,
            "reverse_preflight_exit_code": preflight.returncode,
            "reverse_preflight_report": parse_stdout_json_payload(preflight.stdout),
            "reverse_exit_code": result.returncode,
            "reverse_report_path": as_display_path(DEFAULT_REVERSE_REPORT),
            "reverse_result": reverse_payload,
            "reverse_rejected": reverse_rejected,
            "derivatives_ready": reverse_ok,
            "rollback_ready": False,
        },
    )
    state.last_reverse_report = DEFAULT_REVERSE_REPORT if reverse_ok else report_path
    if reverse_ok:
        tdc_cat_success("Reverse OK. Rejected: 0. Continuidad hacia derivados habilitada.")
        print("Reverse OK con Rejected: 0. Continuidad hacia derivados habilitada.")
    elif result.returncode != 0:
        tdc_cat_error()
        print("Continuidad hacia derivados bloqueada: reverse debe terminar con Rejected: 0.")
    else:
        tdc_cat_warning(f"Reverse terminado con rechazos ({reverse_rejected}). Revisar reporte.")
        print("Continuidad hacia derivados bloqueada: reverse debe terminar con Rejected: 0.")


def option_reports() -> None:
    roots = [
        DEFAULT_TMP_DIR,
        DEFAULT_ADMISSION_REPORT_DIR,
        DEFAULT_SESSION_SYNC_DIR,
        RECONSTRUCTION_DIR,
        QUALITY_REPORT_DIR,
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


def run_reconstruction_rollback_gate(report_path: Path) -> tuple[bool, dict[str, Any] | None, CommandResult | None]:
    if not shutil.which("cargo"):
        print("Compuerta Rust bloqueada: cargo no esta disponible.")
        return False, None, None
    result = run_command(
        [
            "cargo",
            "run",
            "--quiet",
            "--bin",
            "audit",
            "--",
            "reconstruction-rollback",
            str(REPO_ROOT),
            "--report",
            str(report_path),
        ],
        cwd=REPO_ROOT / "rust" / "doctor",
    )
    payload = parse_stdout_json_payload(result.stdout)
    print("\nCompuerta Rust de rollback de reconstruccion:")
    print(f"- reporte: {display(report_path)}")
    print(f"- veredicto: {payload.get('verdict') if payload else 'sin_json'}")
    print(f"- errores: {payload.get('errors') if payload else '-'}")
    if result.returncode != 0:
        print_command_result(result, max_chars=1600)
    return result.returncode == 0, payload, result


def option_reconstruction_rollback() -> None:
    reports = latest_reconstruction_reports(rollback_only=True)
    selected = select_path(reports, "reporte de reconstruccion con rollback disponible")
    if not selected:
        return
    try:
        payload = load_json(selected)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"No se pudo leer reporte: {exc}")
        return

    print(f"Reporte seleccionado: {display(selected)}")
    print(summarize_report(selected))
    gate_ok, gate_payload, gate_result = run_reconstruction_rollback_gate(selected)
    if not gate_ok:
        print("Rollback bloqueado por la compuerta Rust. No se modifico el canon.")
        return

    backup_value = payload.get("backup_dir")
    if not backup_value:
        print("Rollback bloqueado: el reporte no declara backup_dir.")
        return
    backup_dir = (REPO_ROOT / backup_value).resolve() if not Path(backup_value).is_absolute() else Path(backup_value)
    if not backup_dir.exists():
        print(f"Rollback bloqueado: no existe backup {display(backup_dir)}.")
        return

    print("\nAdvertencia: rollback de reconstruccion reemplazara tiddlers_*.jsonl en data/out/local.")
    print(f"- backup fuente: {display(backup_dir)}")
    print(f"- hash esperado: {payload.get('canon_before_hash')}")
    confirmation = prompt("Escribe ROLLBACK RECONSTRUCTION para restaurar el canon local: ").strip()
    if confirmation != "ROLLBACK RECONSTRUCTION":
        print("Rollback cancelado.")
        return

    run_dir = selected.parent
    rollback_stamp = stamp_now()
    rollback_before_dir = copy_canon_shards(run_dir, f"rollback_before_{rollback_stamp}", DEFAULT_CANON_DIR)
    rollback_before_manifest = canon_tree_manifest(rollback_before_dir)

    for shard in canon_shards(DEFAULT_CANON_DIR):
        shard.unlink()
    for shard in canon_shards(backup_dir):
        shutil.copy2(shard, DEFAULT_CANON_DIR / shard.name)

    restored_manifest = canon_tree_manifest(DEFAULT_CANON_DIR)
    print("\nValidacion post-rollback: strict")
    strict = run_preflight("strict")
    print_command_result(strict)
    print("\nValidacion post-rollback: reverse-preflight")
    reverse_preflight = run_preflight("reverse-preflight")
    print_command_result(reverse_preflight)
    validation_ok = strict.returncode == 0 and reverse_preflight.returncode == 0

    rollback_report = run_dir / f"rollback-report-{rollback_stamp}.json"
    write_json(
        rollback_report,
        {
            "run_id": run_dir.name,
            "timestamp": rollback_stamp,
            "mode": "rollback_reconstruction",
            "source_report": as_display_path(selected),
            "backup_dir": as_display_path(backup_dir),
            "rollback_before_dir": as_display_path(rollback_before_dir),
            "rollback_before": rollback_before_manifest,
            "restored_canon": restored_manifest,
            "expected_restored_hash": payload.get("canon_before_hash"),
            "restored_hash": restored_manifest["hash"],
            "gate_verdict": gate_payload.get("verdict") if gate_payload else None,
            "gate_report": gate_payload,
            "gate_exit_code": gate_result.returncode if gate_result else None,
            "strict_exit_code": strict.returncode,
            "strict_report": parse_stdout_json_payload(strict.stdout),
            "reverse_preflight_exit_code": reverse_preflight.returncode,
            "reverse_preflight_report": parse_stdout_json_payload(reverse_preflight.stdout),
            "post_rollback_validation_ok": validation_ok,
        },
    )
    print(f"\nReporte de rollback: {display(rollback_report)}")
    if validation_ok and restored_manifest["hash"] == payload.get("canon_before_hash"):
        print("Rollback completado y validado.")
    else:
        print("Rollback aplicado, pero la validacion minima no quedo OK. Revisar reporte antes de continuar.")


def option_mcp_manager() -> None:
    subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "mcp_env_manager.py")],
        cwd=REPO_ROOT,
    )


def main_menu() -> None:
    state = MenuState()
    while True:
        tdc_cat_open()
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
            "12) Rollback de reconstruccion\n"
            "13) Auditar calidad canonica / nodos\n"
            "14) Configurar MCP / mirror remoto\n"
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
            option_derivatives(state)
        elif choice == "9":
            option_reverse(state)
        elif choice == "10":
            option_reports()
        elif choice == "11":
            option_rollback()
        elif choice == "12":
            option_reconstruction_rollback()
        elif choice == "13":
            option_canon_quality()
        elif choice == "14":
            option_mcp_manager()
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
