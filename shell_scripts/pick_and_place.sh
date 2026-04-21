#!/usr/bin/env bash
set -euo pipefail

# pick_and_place.sh
# Interactive helper to pick files from a Windows-mounted folder (e.g. Downloads)
# and copy them into selected destinations inside the repository.
# Usage (interactive): bash shell_scripts/pick_and_place.sh
# Usage (batch):       bash shell_scripts/pick_and_place.sh -n "/mnt/c/Users/Ohana/Downloads/foo.json,/mnt/c/Users/Ohana/Downloads/bar.json" -d docs/tiddlers_esp

REPO_ROOT="/repositorios/tiddly-data-converter"
DEFAULT_SRC="/mnt/c/Users/Ohana/Downloads"

print_usage() {
  cat <<EOF
Usage: $0 [options]

Interactive mode (default):
  $0

Batch / non-interactive:
  $0 -n "<file1>[,<file2>,...]" -d <dest-relative-to-repo>

Options:
  -s, --source DIR       Source directory (default: $DEFAULT_SRC)
  -n, --non-interactive  Comma-separated full paths of files to copy
  -d, --dest DIR         Destination path (relative to repo root) for non-interactive mode
  -h, --help             Show this help
  -a, --all              Show hidden / temp files (don't filter)

Examples:
  $0                       # run interactive selector against Downloads
  $0 -n "/mnt/c/.../a.json,/mnt/c/.../b.json" -d docs/tiddlers_esp
EOF
}

# Helpers
join_by() { local IFS="$1"; shift; echo "$*"; }

ensure_inside_repo() {
  local p="$1"
  # normalize
  p="$(realpath -m "$p")"
  case "$p" in
    "$REPO_ROOT"* ) echo "$p" ;;
    *) return 1 ;;
  esac
}

suggest_dest_for_file() {
  local f="$1"
  case "${f##*.}" in
    json) echo "docs/tiddlers_esp" ;;
    md|markdown) echo "docs" ;;
    py|sh) echo "scripts" ;;
    html) echo "docs" ;;
    *) echo "docs" ;;
  esac
}

# Build a numeric menu of destinations inside the repo and return the chosen relative path
show_dest_menu() {
  local suggested="$1"
  local -a dests
  dests=(.)
  for d in "$REPO_ROOT"/*; do
    if [[ -d "$d" ]]; then
      base="$(basename "$d")"
      # skip .git and hidden dirs
      if [[ "$base" == ".git" ]]; then
        continue
      fi
      dests+=("$base")
    fi
  done
  # include suggested if not already present
  if [[ -n "$suggested" && "$suggested" != "." ]]; then
    local found=false
    for x in "${dests[@]}"; do [[ "$x" == "$suggested" ]] && found=true; done
    if ! $found; then dests+=("$suggested"); fi
  fi

  echo "Choose destination (relative to repo):"
  for i in "${!dests[@]}"; do
    idx=$((i+1))
    printf "  [%2d] %s\n" "$idx" "${dests[i]}"
  done
  printf "  [ 0] Other (type relative path)\n"

  read -r -p "Select destination index: " sel
  if [[ "$sel" == "0" ]]; then
    read -r -p "Enter relative path (e.g. docs/tiddlers_esp or . for repo root): " dest_in
    dest_in="${dest_in:-.}"
  else
    if ! [[ "$sel" =~ ^[0-9]+$ ]]; then
      echo ""; return 1
    fi
    selidx=$((sel-1))
    if (( selidx < 0 || selidx >= ${#dests[@]} )); then
      echo ""; return 1
    fi
    dest_in="${dests[selidx]}"
  fi
  echo "$dest_in"
}

# Parse args
SRC="$DEFAULT_SRC"
NON_INTERACTIVE=false
MOVE=false
SHOW_ALL=false
FILES_ARG=""
DEST_ARG=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -s|--source) SRC="$2"; shift 2 ;;
    -n|--non-interactive) NON_INTERACTIVE=true; FILES_ARG="$2"; shift 2 ;;
    -m|--move) MOVE=true; shift 1 ;;
    -a|--all) SHOW_ALL=true; shift 1 ;;
    -d|--dest) DEST_ARG="$2"; shift 2 ;;
    -h|--help) print_usage; exit 0 ;;
    *) echo "Unknown arg: $1"; print_usage; exit 2 ;;
  esac
done

if $NON_INTERACTIVE; then
  # Batch mode
  if [[ -z "$FILES_ARG" ]]; then
    echo "No files provided for non-interactive mode." >&2
    exit 2
  fi
  IFS=',' read -r -a srcs <<< "$FILES_ARG"
  if [[ -n "$DEST_ARG" ]]; then
    dest_rel="$DEST_ARG"
  else
    # if single file, suggest; otherwise default to docs
    if [[ ${#srcs[@]} -eq 1 ]]; then
      dest_rel="$(suggest_dest_for_file "${srcs[0]##*/}")"
    else
      dest_rel="docs"
    fi
  fi
  dest_abs="$REPO_ROOT/$dest_rel"
  if ! ensure_inside_repo "$dest_abs" >/dev/null 2>&1 ; then
    echo "Destination must be inside repo root ($REPO_ROOT)." >&2
    exit 2
  fi
  mkdir -p "$dest_abs"
  for f in "${srcs[@]}"; do
    f="$(realpath -m "$f")"
    if [[ ! -e "$f" ]]; then
      echo "Skipping missing path: $f" >&2
      continue
    fi
    if $MOVE; then
      echo "Moving: $f -> $dest_abs/"
      mv -v "$f" "$dest_abs/" || { echo "Failed to move $f" >&2; continue; }
    else
      echo "Copying: $f -> $dest_abs/"
      rsync -a --progress --chmod=ugo=rwX "$f" "$dest_abs/"
    fi
  done
  echo "Done."
  exit 0
fi

# Interactive mode
if [[ ! -d "$SRC" ]]; then
  echo "Source directory not found: $SRC" >&2
  exit 1
fi

# Build items list (top-level files and directories)
if $SHOW_ALL; then
  mapfile -d $'\0' -t files < <(find "$SRC" -maxdepth 1 -mindepth 1 \( -type f -o -type d \) -print0)
else
  mapfile -d $'\0' -t files < <(find "$SRC" -maxdepth 1 -mindepth 1 \( -type f -o -type d \) ! -name 'desktop.ini' ! -name '~*' ! -name '*.tmp' ! -name 'Thumbs.db' -print0)
fi
if [[ ${#files[@]} -eq 0 ]]; then
  echo "No files or directories found in $SRC (filtered). Use -a to show hidden/temp files." >&2
  exit 0
fi

echo "Found ${#files[@]} items in $SRC:"
for i in "${!files[@]}"; do
  idx=$((i+1))
  path_i="${files[i]}"
  bas=$(basename "$path_i")
  if [[ -d "$path_i" ]]; then
    type_label="[DIR]"
  else
    type_label="[FILE]"
  fi
  printf "  [%2d] %s %s\n" "$idx" "$type_label" "$bas"
done

echo
read -r -p "Enter numbers to copy (e.g. 1 3 5-7), 'all' to select all, or 'q' to quit: " sel_raw
if [[ "$sel_raw" == "q" ]]; then
  echo "Aborted."; exit 0
fi
sel_raw="${sel_raw//,/ }"

declare -a selected_indices=()
if [[ "$sel_raw" == "all" ]]; then
  for ((i=1;i<=${#files[@]};i++)); do selected_indices+=("$i"); done
else
  for token in $sel_raw; do
    if [[ "$token" =~ ^[0-9]+-[0-9]+$ ]]; then
      IFS='-' read -r a b <<< "$token"
      for ((j=a;j<=b;j++)); do selected_indices+=("$j"); done
    elif [[ "$token" =~ ^[0-9]+$ ]]; then
      selected_indices+=("$token")
    else
      echo "Ignored token: $token" >&2
    fi
  done
fi

# Normalize unique and valid
declare -A seen=()
declare -a final_indices=()
for v in "${selected_indices[@]}"; do
  [[ -z "$v" ]] && continue
  if (( v < 1 || v > ${#files[@]} )); then
    echo "Index out of range: $v" >&2
    continue
  fi
  if [[ -z "${seen[$v]:-}" ]]; then
    final_indices+=("$v")
    seen[$v]=1
  fi
done

if [[ ${#final_indices[@]} -eq 0 ]]; then
  echo "No valid selections."; exit 0
fi

read -r -p "Use same destination for all selected items? (y/N): " same_dest_ans
same_dest_ans=${same_dest_ans,,}
use_common_dest=false
common_dest_abs=""
if [[ "$same_dest_ans" == "y" || "$same_dest_ans" == "yes" ]]; then
  use_common_dest=true
  # Suggest dest based on first file
  first_file="${files[${final_indices[0]}-1]}"
  suggested="$(suggest_dest_for_file "$(basename "$first_file")")"
  dest_in="$(show_dest_menu "$suggested")"
  if [[ -z "$dest_in" ]]; then
    echo "No valid destination selected." >&2
    exit 2
  fi
  common_dest_abs="$REPO_ROOT/$dest_in"
  if ! ensure_inside_repo "$common_dest_abs" >/dev/null 2>&1 ; then
    echo "Destination must be inside repo root ($REPO_ROOT)." >&2
    exit 2
  fi
  mkdir -p "$common_dest_abs"
fi

copied=0
# Ask if user wants to move instead of copy
read -r -p "Copy or move selected items? (c=copy, m=move) [c]: " action
action=${action:-c}
for idx in "${final_indices[@]}"; do
  srcfile="${files[idx-1]}"
  base="$(basename "$srcfile")"
  if $use_common_dest; then
    dest="$common_dest_abs"
  else
    suggested="$(suggest_dest_for_file "$base")"
    dest_in="$(show_dest_menu "$suggested")"
    if [[ -z "$dest_in" ]]; then
      echo "No valid destination selected. Skipping $base" >&2
      continue
    fi
    dest="$REPO_ROOT/$dest_in"
    if ! ensure_inside_repo "$dest" >/dev/null 2>&1 ; then
      echo "Destination must be inside repo root ($REPO_ROOT). Skipping $base" >&2
      continue
    fi
    mkdir -p "$dest"
  fi
  if [[ "$action" == "m" || "$action" == "M" ]]; then
    echo "Moving: $srcfile -> $dest/"
    mv -v "$srcfile" "$dest/" || { echo "Failed to move $srcfile" >&2; continue; }
  else
    echo "Copying: $srcfile -> $dest/"
    rsync -a --progress --chmod=ugo=rwX "$srcfile" "$dest/"
  fi
  copied=$((copied+1))
done

echo "Copied $copied file(s)."
if [[ "$common_dest_abs" == "$REPO_ROOT/docs/tiddlers_esp" || "$dest" == "$REPO_ROOT/docs/tiddlers_esp" ]]; then
  echo "Nota: /docs/tiddlers_esp está listado en .gitignore por defecto; los archivos no serán seguidos por git a menos que fuerces el add."
fi

exit 0
