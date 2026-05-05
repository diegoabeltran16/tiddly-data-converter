"""
tdc_cat.py — Cat States UI v0.1
Terminal identity for tiddly-data-converter.

States: open, loading, success, warning, error, blink
Rule: the cat signals state; operational output remains the source of evidence.
      Never replace stdout/stderr/cwd/exit with visual summaries.

Architecture note (v0.1): static display only. Natural-blink animation
(open → blink → open) is reserved for safe zones. The threading loader
(tdc_cat_loading_start / tdc_cat_loading_stop) implements it with a daemon
thread that only activates in TTY contexts and stops before any output prints.
"""
from __future__ import annotations

import sys
import threading
import time

# ---------------------------------------------------------------------------
# ASCII art constants
# Each art block is exactly 3 lines, no trailing newline.
# ---------------------------------------------------------------------------
_OPEN    = " /\\_/\\\n( o_o )\n > ^ <"
_BLINK   = " /\\_/\\\n( -_- )\n > ^ <"
_SUCCESS = " /\\_/\\\n( ^_^ )\n > ^ <"
_WARNING = " /\\_/\\\n( o_o )\n > ! <"
_ERROR   = " /\\_/\\\n( x_x )\n > ^ <"

_CAT_LINES = 3  # lines in every art block

# ---------------------------------------------------------------------------
# Static state displays
# ---------------------------------------------------------------------------

def tdc_cat_open(label: str | None = None) -> None:
    """Show cat in open/idle state. Use at menu header or safe pauses."""
    print(_OPEN)
    if label:
        print(f"Estado: open — {label}")


def tdc_cat_loading(action: str) -> None:
    """Show cat in loading state (static). Use before operations."""
    print(_OPEN)
    print(f"\nEstado: loading")
    print(f"Accion: {action}")


def tdc_cat_success(message: str = "") -> None:
    """Show cat in success state. Use after operation with exit 0."""
    print(_SUCCESS)
    print("\nEstado: success")
    if message:
        print(message)


def tdc_cat_warning(message: str = "") -> None:
    """Show cat in warning state. Use for non-blocking issues or findings."""
    print(_WARNING)
    print("\nEstado: warning")
    if message:
        print(message)


def tdc_cat_error(message: str = "Revisar stderr / salida anterior.") -> None:
    """Show cat in error state. Use after operation with exit != 0."""
    print(_ERROR)
    print("\nEstado: error")
    print(message)


# ---------------------------------------------------------------------------
# Natural-blink loader (threading, TTY only)
# Safe contract:
#   stop_event = tdc_cat_loading_start("Accion")
#   result = run_command(...)         # main thread free to run subprocess
#   tdc_cat_loading_stop(stop_event)  # waits for thread, then clears cat
#   print_command_result(result)      # full output visible after cat clears
# ---------------------------------------------------------------------------

_BLINK_OPEN_SECS  = 3.0   # ojos abiertos
_BLINK_CLOSE_SECS = 0.16  # ojos cerrados


def tdc_cat_loading_start(action: str) -> threading.Event:
    """
    Display a blinking loading cat while a command runs.
    Only animates in TTY; degrades to static display otherwise.
    Returns a stop_event — call tdc_cat_loading_stop(stop_event) when done.
    """
    stop = threading.Event()

    if not sys.stdout.isatty():
        tdc_cat_loading(action)
        return stop

    label = f"\nEstado: loading\nAccion: {action}"
    total_lines = _CAT_LINES + 3  # cat (3) + blank (1) + "Estado:" (1) + "Accion:" (1)
    move_up = f"\033[{total_lines}A"

    def _blink() -> None:
        print(_OPEN + label, flush=True)
        while not stop.is_set():
            if stop.wait(_BLINK_OPEN_SECS):
                break
            if stop.is_set():
                break
            sys.stdout.write(move_up)
            print(_BLINK + label, flush=True)
            if stop.wait(_BLINK_CLOSE_SECS):
                break
            if stop.is_set():
                break
            sys.stdout.write(move_up)
            print(_OPEN + label, flush=True)

    t = threading.Thread(target=_blink, daemon=True, name="tdc-cat-blink")
    t.start()
    return stop


def tdc_cat_loading_stop(stop_event: threading.Event) -> None:
    """
    Signal the blink thread to stop and wait briefly for it to finish.
    Call before printing command output to ensure clean output order.
    """
    stop_event.set()
    # Allow the daemon thread up to 0.5s to finish its current iteration
    time.sleep(0.05)
    # Print a blank line to separate cat block from command output
    if sys.stdout.isatty():
        print()
