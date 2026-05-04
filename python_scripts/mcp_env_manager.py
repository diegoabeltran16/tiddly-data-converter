#!/usr/bin/env python3
"""MCP / remote mirror configuration manager.

Interactive submenu for managing the .env contract (S88) and operating
the OneDrive remote mirror. Usable standalone or via operator_menu.py.

Variables (visible on display):
  AGENT_ADMISSION_SCRIPT, AGENT_DIRECT_CANON_WRITE,
  AGENT_PRIMARY_READ_ROOT, AGENT_SESSION_ROOT, LOCAL_SYNC_SOURCE,
  MSA_TENANT, ONEDRIVE_PROJECT_ROOT_NAME, ONEDRIVE_ROOT_MODE,
  REMOTE_CONFLICT_BEHAVIOR, REMOTE_CREATE_MISSING_DIRS,
  REMOTE_DELETE_EXTRANEOUS, REMOTE_SYNC_MODE, SYNC_DRY_RUN

Secrets (hidden input, masked on display):
  AZURE_CLIENT_ID, AZURE_TENANT_ID, MSA_REFRESH_TOKEN
"""

from __future__ import annotations

import getpass
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
ENV_PATH = REPO_ROOT / ".env"

# ---------------------------------------------------------------------------
# Contract — exact names from S88 / GitHub Environment "remote-mirror"
# ---------------------------------------------------------------------------

VARIABLES: list[str] = [
    "AGENT_ADMISSION_SCRIPT",
    "AGENT_DIRECT_CANON_WRITE",
    "AGENT_PRIMARY_READ_ROOT",
    "AGENT_SESSION_ROOT",
    "LOCAL_SYNC_SOURCE",
    "MSA_TENANT",
    "ONEDRIVE_PROJECT_ROOT_NAME",
    "ONEDRIVE_ROOT_MODE",
    "REMOTE_CONFLICT_BEHAVIOR",
    "REMOTE_CREATE_MISSING_DIRS",
    "REMOTE_DELETE_EXTRANEOUS",
    "REMOTE_SYNC_MODE",
    "SYNC_DRY_RUN",
]

SECRETS: list[str] = [
    "AZURE_CLIENT_ID",
    "AZURE_TENANT_ID",
    "MSA_REFRESH_TOKEN",
]

ALL_KEYS: list[str] = VARIABLES + SECRETS

VARIABLE_DESCRIPTIONS: dict[str, str] = {
    "AGENT_ADMISSION_SCRIPT":     "Script que valida candidatos de sesion antes de admitirlos al canon",
    "AGENT_DIRECT_CANON_WRITE":   "Si 'true', el agente escribe directamente al canon (usar con precaucion)",
    "AGENT_PRIMARY_READ_ROOT":    "Raiz de lectura primaria del agente (vacio = repo local)",
    "AGENT_SESSION_ROOT":         "Raiz de sesiones del agente (vacio = data/out/local/sessions)",
    "LOCAL_SYNC_SOURCE":          "Carpeta local a sincronizar hacia OneDrive (ej: data/out/local)",
    "MSA_TENANT":                 "Tenant Microsoft: 'consumers' para ctas personales, o tenant ID",
    "ONEDRIVE_PROJECT_ROOT_NAME": "Nombre de la carpeta raiz del proyecto en OneDrive App Folder",
    "ONEDRIVE_ROOT_MODE":         "Modo de raiz OneDrive: 'approot' (App Folder) o 'drive' (raiz)",
    "REMOTE_CONFLICT_BEHAVIOR":   "Accion ante conflicto: 'overwrite', 'skip' o 'error'",
    "REMOTE_CREATE_MISSING_DIRS": "Si 'true', crea carpetas remotas que no existen",
    "REMOTE_DELETE_EXTRANEOUS":   "Si 'true', elimina archivos remotos ausentes localmente",
    "REMOTE_SYNC_MODE":           "Modo de sincronizacion: 'upload_only' u otro modo definido",
    "SYNC_DRY_RUN":               "Si 'true', simula el sync sin subir ningun archivo",
}

SECRET_DESCRIPTIONS: dict[str, str] = {
    "AZURE_CLIENT_ID":   "ID de la aplicacion Azure AD registrada para este proyecto",
    "AZURE_TENANT_ID":   "ID del tenant Azure AD (para org; vacio si cuenta Microsoft personal)",
    "MSA_REFRESH_TOKEN": "Token de actualizacion Microsoft — permite auth sin volver a iniciar sesion",
}

ENV_TEMPLATE = """\
AGENT_ADMISSION_SCRIPT=
AGENT_DIRECT_CANON_WRITE=
AGENT_PRIMARY_READ_ROOT=
AGENT_SESSION_ROOT=
LOCAL_SYNC_SOURCE=

MSA_TENANT=
ONEDRIVE_PROJECT_ROOT_NAME=
ONEDRIVE_ROOT_MODE=
REMOTE_CONFLICT_BEHAVIOR=
REMOTE_CREATE_MISSING_DIRS=
REMOTE_DELETE_EXTRANEOUS=
REMOTE_SYNC_MODE=
SYNC_DRY_RUN=

AZURE_CLIENT_ID=
AZURE_TENANT_ID=
MSA_REFRESH_TOKEN=
"""

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
TOKEN_URL_TMPL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"


# ---------------------------------------------------------------------------
# .env helpers — safe read / write without duplicating keys
# ---------------------------------------------------------------------------

def read_env_values(path: Path = ENV_PATH) -> dict[str, str]:
    """Parse .env into key→value dict (skips comments and blank lines)."""
    if not path.is_file():
        return {}
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip()
    return result


def write_env_key(key: str, value: str, path: Path = ENV_PATH) -> None:
    """Set key=value in .env, updating in-place without duplicating the key."""
    if not path.is_file():
        path.write_text(f"{key}={value}\n", encoding="utf-8")
        return

    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    new_lines: list[str] = []
    found = False
    for line in lines:
        stripped = line.rstrip("\n\r")
        if stripped.startswith(f"{key}=") or stripped == key:
            new_lines.append(f"{key}={value}\n")
            found = True
        else:
            new_lines.append(line)

    if not found:
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines.append("\n")
        new_lines.append(f"{key}={value}\n")

    path.write_text("".join(new_lines), encoding="utf-8")


def _is_gitignored(path: Path) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "-q", str(path)],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    return result.returncode == 0


# ---------------------------------------------------------------------------
# Auth / Graph helpers (stdlib only — no extra dependencies)
# ---------------------------------------------------------------------------

def _exchange_token(
    tenant: str, client_id: str, refresh_token: str
) -> tuple[str | None, str]:
    """Exchange refresh token for access_token.

    Returns (token, "") on success, (None, error_message) on failure.
    """
    token_url = TOKEN_URL_TMPL.format(tenant=tenant or "consumers")
    body = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "client_id": client_id,
        "refresh_token": refresh_token,
        "scope": "Files.ReadWrite.AppFolder offline_access",
    }).encode()
    try:
        req = urllib.request.Request(token_url, data=body, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
        if "access_token" in result:
            return result["access_token"], ""
        return None, result.get("error_description", "Sin access_token en respuesta")
    except urllib.error.HTTPError as exc:
        try:
            body_err = json.loads(exc.read())
            return None, body_err.get("error_description", str(exc))
        except Exception:
            return None, str(exc)
    except Exception as exc:
        return None, str(exc)


# ---------------------------------------------------------------------------
# Menu helpers
# ---------------------------------------------------------------------------

def _prompt(msg: str) -> str:
    try:
        return input(msg)
    except EOFError:
        return ""


def _pause() -> None:
    if sys.stdin.isatty():
        _prompt("\nEnter para continuar...")


def _config_summary() -> str:
    """One-line summary of configuration state for the menu header."""
    if not ENV_PATH.is_file():
        return ".env no inicializado"
    values = read_env_values()
    vars_set = sum(1 for k in VARIABLES if values.get(k))
    secrets_set = sum(1 for k in SECRETS if values.get(k))
    return f"{vars_set}/{len(VARIABLES)} variables · {secrets_set}/{len(SECRETS)} secrets configurados"


# ---------------------------------------------------------------------------
# Menu actions
# ---------------------------------------------------------------------------

def action_init_env() -> None:
    """Initialize .env — create if absent, add missing keys if present."""
    if not ENV_PATH.is_file():
        ENV_PATH.write_text(ENV_TEMPLATE, encoding="utf-8")
        print("  .env creado con el contrato completo.")
    else:
        existing = read_env_values()
        missing = [k for k in ALL_KEYS if k not in existing]
        if not missing:
            print("  .env existe y contiene todas las claves del contrato.")
        else:
            print(f"  .env existe. Claves faltantes: {', '.join(missing)}")
            answer = _prompt("  Agregar claves faltantes? [s/N] ").strip().lower()
            if answer in ("s", "si", "y", "yes"):
                for key in missing:
                    write_env_key(key, "")
                print(f"  {len(missing)} clave(s) agregada(s).")
            else:
                print("  Sin cambios.")

    ignored = _is_gitignored(ENV_PATH)
    print(f"  .env gitignoreado: {'✓' if ignored else '✗ (revisar .gitignore)'}")


def action_show_status() -> None:
    """Display configuration status with counts and human descriptions."""
    if not ENV_PATH.is_file():
        print("  .env no existe. Usa '1) Inicializar .env' primero.")
        return

    values = read_env_values()
    vars_set = sum(1 for k in VARIABLES if values.get(k))
    secrets_set = sum(1 for k in SECRETS if values.get(k))

    print()
    print(f"  ── Variables operativas ({vars_set}/{len(VARIABLES)} configuradas) ──────────────────")
    for i, key in enumerate(VARIABLES, 1):
        val = values.get(key, "")
        desc = VARIABLE_DESCRIPTIONS.get(key, "")
        display = val if val else "[vacio]"
        print(f"  {i:2}. {key}")
        print(f"      {desc}")
        print(f"      Valor: {display}")

    print()
    print(f"  ── Secrets ({secrets_set}/{len(SECRETS)} configurados) ──────────────────────────────")
    for i, key in enumerate(SECRETS, 1):
        val = values.get(key, "")
        desc = SECRET_DESCRIPTIONS.get(key, "")
        status = "[configurado]" if val else "[vacio]"
        print(f"  {i:2}. {key}")
        print(f"      {desc}")
        print(f"      Estado: {status}")

    print()
    ignored = _is_gitignored(ENV_PATH)
    print(f"  .env gitignoreado: {'✓' if ignored else '✗'}")


def action_edit_variable() -> None:
    """Edit a non-sensitive operational variable (visible input)."""
    if not ENV_PATH.is_file():
        print("  .env no existe. Inicializa primero.")
        return

    print()
    values = read_env_values()
    for i, key in enumerate(VARIABLES, 1):
        current = values.get(key, "")
        desc = VARIABLE_DESCRIPTIONS.get(key, "")
        display = current if current else "[vacio]"
        print(f"  {i:2}) {key} = {display}")
        print(f"       {desc}")

    choice = _prompt("\n  Seleccione el numero del campo a editar (Enter para cancelar): ").strip()
    if not choice:
        return
    try:
        idx = int(choice) - 1
        if idx < 0 or idx >= len(VARIABLES):
            raise ValueError
    except ValueError:
        print("  Numero invalido.")
        return

    key = VARIABLES[idx]
    desc = VARIABLE_DESCRIPTIONS.get(key, "")
    current = values.get(key, "")

    print()
    print(f"  Campo:        {key}")
    print(f"  Descripcion:  {desc}")
    print(f"  Valor actual: {current if current else '[vacio]'}")

    new_val = _prompt("  Nuevo valor (Enter para cancelar): ").strip()
    if not new_val:
        print("  Cancelado. Sin cambios.")
        return

    write_env_key(key, new_val)
    print(f"  ✓ Guardado: {key}={new_val}")


def action_edit_secret() -> None:
    """Edit a secret using hidden terminal input (getpass)."""
    if not ENV_PATH.is_file():
        print("  .env no existe. Inicializa primero.")
        return

    print()
    values = read_env_values()
    for i, key in enumerate(SECRETS, 1):
        status = "[configurado]" if values.get(key) else "[vacio]"
        desc = SECRET_DESCRIPTIONS.get(key, "")
        print(f"  {i:2}) {key}  {status}")
        print(f"       {desc}")

    choice = _prompt("\n  Seleccione el numero del secret a editar (Enter para cancelar): ").strip()
    if not choice:
        return
    try:
        idx = int(choice) - 1
        if idx < 0 or idx >= len(SECRETS):
            raise ValueError
    except ValueError:
        print("  Numero invalido.")
        return

    key = SECRETS[idx]
    desc = SECRET_DESCRIPTIONS.get(key, "")
    was_set = bool(values.get(key))

    print()
    print(f"  Secret:        {key}")
    print(f"  Descripcion:   {desc}")
    print(f"  Estado actual: {'[configurado]' if was_set else '[vacio]'}")

    try:
        new_val = getpass.getpass(f"  Nuevo valor (oculto, Enter para cancelar): ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        print("  Cancelado.")
        return

    if not new_val:
        if was_set:
            print("  Cancelado. Valor anterior conservado.")
        else:
            print("  Cancelado. El secret sigue sin configurar.")
        return

    write_env_key(key, new_val)
    print(f"  ✓ {key} guardado [configurado]")


def action_test_auth() -> None:
    """Test Azure MSA authentication using current .env values."""
    values = read_env_values()
    tenant = values.get("MSA_TENANT") or "consumers"
    client_id = values.get("AZURE_CLIENT_ID", "")
    refresh_token = values.get("MSA_REFRESH_TOKEN", "")

    if not client_id:
        print("  AZURE_CLIENT_ID no configurado.")
        return
    if not refresh_token:
        print("  MSA_REFRESH_TOKEN no configurado.")
        return

    print(f"  Probando autenticacion (tenant={tenant})...")
    token, err = _exchange_token(tenant, client_id, refresh_token)
    if token:
        print("  ✓ Autenticacion exitosa (token obtenido, no se muestra)")
    else:
        print(f"  ✗ Error: {err}")


def action_test_appfolder() -> None:
    """Test OneDrive App Folder access after successful authentication."""
    values = read_env_values()
    tenant = values.get("MSA_TENANT") or "consumers"
    client_id = values.get("AZURE_CLIENT_ID", "")
    refresh_token = values.get("MSA_REFRESH_TOKEN", "")
    root_mode = values.get("ONEDRIVE_ROOT_MODE") or "approot"

    if not client_id or not refresh_token:
        print("  AZURE_CLIENT_ID y/o MSA_REFRESH_TOKEN no configurados.")
        return

    print(f"  Obteniendo token (tenant={tenant})...")
    token, err = _exchange_token(tenant, client_id, refresh_token)
    if not token:
        print(f"  ✗ Error de autenticacion: {err}")
        return

    if root_mode == "drive":
        url = f"{GRAPH_BASE}/me/drive/root"
    else:
        url = f"{GRAPH_BASE}/me/drive/special/approot"

    print(f"  Accediendo a {root_mode} ({url})...")
    try:
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=15) as resp:
            info = json.loads(resp.read())
        name = info.get("name", "?")
        size = info.get("size", "?")
        item_id = info.get("id", "?")[:12] + "..."
        print(f"  ✓ Acceso OK — nombre: {name!r}  size: {size}  id: {item_id}")
    except urllib.error.HTTPError as exc:
        print(f"  ✗ HTTP {exc.code}: {exc.reason}")
    except Exception as exc:
        print(f"  ✗ Error: {exc}")


def _build_mirror_env(sync_dry_run: str) -> dict[str, str]:
    """Build environment for subprocess mirror call, loading .env first."""
    env = os.environ.copy()
    if ENV_PATH.is_file():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key and key not in env:
                env[key] = value.strip()
    env["SYNC_DRY_RUN"] = sync_dry_run
    return env


def action_preview() -> None:
    """Run mirror in dry-run mode (no uploads to OneDrive)."""
    print("  Ejecutando preview (SYNC_DRY_RUN=true — sin subir archivos)...\n", flush=True)
    subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "remote_mirror_out_local.py")],
        cwd=REPO_ROOT,
        env=_build_mirror_env("true"),
    )


def action_sync_manual() -> None:
    """Run mirror in live mode after explicit confirmation."""
    values = read_env_values()
    if not values.get("AZURE_CLIENT_ID"):
        print("  AZURE_CLIENT_ID no configurado. Configura los secrets primero.")
        return
    if not values.get("MSA_REFRESH_TOKEN"):
        print("  MSA_REFRESH_TOKEN no configurado. Configura los secrets primero.")
        return

    print()
    print("  ADVERTENCIA: Esto ejecutara el mirror real a OneDrive.")
    print("  AGENT_DIRECT_CANON_WRITE no aplica aqui — mirror y canon son flujos separados.")
    confirm = _prompt("  Confirmar sync real? [s/N] ").strip().lower()
    if confirm not in ("s", "si", "y", "yes"):
        print("  Cancelado.")
        return

    print(flush=True)
    subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "remote_mirror_out_local.py")],
        cwd=REPO_ROOT,
        env=_build_mirror_env("false"),
    )


def action_reset_key() -> None:
    """Reset a variable or secret to empty without removing it from .env."""
    if not ENV_PATH.is_file():
        print("  .env no existe. Inicializa primero.")
        return

    print()
    values = read_env_values()
    for i, key in enumerate(ALL_KEYS, 1):
        is_secret = key in SECRETS
        if is_secret:
            status = "[configurado]" if values.get(key) else "[vacio]"
            print(f"  {i:2}) {key:<42} [SECRET]  {status}")
        else:
            val = values.get(key, "")
            display = (val[:40] + "...") if len(val) > 40 else (val if val else "[vacio]")
            print(f"  {i:2}) {key:<42} {display}")

    choice = _prompt("\n  Numero del campo a resetear (Enter para cancelar): ").strip()
    if not choice:
        return
    try:
        idx = int(choice) - 1
        if idx < 0 or idx >= len(ALL_KEYS):
            raise ValueError
    except ValueError:
        print("  Numero invalido.")
        return

    key = ALL_KEYS[idx]
    current_val = values.get(key, "")
    if not current_val:
        print(f"  '{key}' ya esta vacio. Sin cambios.")
        return

    confirm = _prompt(f"  Resetear '{key}' a vacio? [s/N] ").strip().lower()
    if confirm not in ("s", "si", "y", "yes"):
        print("  Cancelado.")
        return

    write_env_key(key, "")
    print(f"  ✓ {key} reseteado a [vacio].")


# ---------------------------------------------------------------------------
# Submenu
# ---------------------------------------------------------------------------

_MENU_BODY = (
    "1) Inicializar .env\n"
    "2) Editar variable operativa\n"
    "3) Editar secret (entrada oculta)\n"
    "4) Ver estado de configuracion\n"
    "5) Probar autenticacion Azure\n"
    "6) Probar acceso a App Folder\n"
    "7) Preview mirror local → remoto (dry-run)\n"
    "8) Sync manual (mirror real a OneDrive)\n"
    "9) Resetear variable o secret a vacio\n"
    "0) Volver"
)

_ACTIONS = {
    "1": action_init_env,
    "2": action_edit_variable,
    "3": action_edit_secret,
    "4": action_show_status,
    "5": action_test_auth,
    "6": action_test_appfolder,
    "7": action_preview,
    "8": action_sync_manual,
    "9": action_reset_key,
}


def run_submenu() -> None:
    while True:
        summary = _config_summary()
        print(f"\nConfiguracion MCP / Mirror Remoto")
        print(f"Estado: {summary}\n")
        print(_MENU_BODY)
        choice = _prompt("> ").strip()
        if choice == "0" or (choice == "" and not sys.stdin.isatty()):
            return
        if choice == "":
            continue
        action = _ACTIONS.get(choice)
        if action:
            print()
            action()
        else:
            print("  Opcion invalida.")
        _pause()


def main() -> int:
    try:
        run_submenu()
    except KeyboardInterrupt:
        print("\nInterrumpido.")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
