#!/bin/sh
# Compares a machine's .env with .env.example, by variable names and values.
# Run by `make check-env` in a container with no network; it reads both files
# from stdin, as one bundle, so neither ever needs mounting:
#
#   ### FILE <path>
#   <that file's lines>
#   ### FILE <path>
#   ...
#
#   check-env.sh <reference> <env file>
#
# Errors, which fail:
#   missing  a name in the reference that .env lacks
#   blank    a name blank in .env, unless the reference's `# may-be-blank:`
#            line lists it
# Reports, which do not:
#   differs  a value the reference sets that .env sets otherwise — a setting
#            chosen for this place, or a new default this .env has not taken
#   extra    a name in .env the reference does not declare: no longer read, or,
#            since ADR 0062, a machine's shape still in .env (delete it; the
#            machine's compose files hold it now)
# Values are printed only where the reference sets one, so a secret, which
# .env.example leaves blank, is never printed.
set -eu

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# One file per bundle entry, its path flattened into a name, in a directory of
# their own so no entry can be mistaken for a scratch file.
mkdir "$work/bundle"
awk -v dir="$work/bundle" '
  /^### FILE / { path = substr($0, 10); gsub("/", "__", path); file = dir "/" path; printf "" > file; next }
  file != "" { print > file }
'

stored() { echo "$work/bundle/$(echo "$1" | sed 's|/|__|g')"; }

# NAME=value pairs, the last one winning as in compose, one per line, sorted.
pairs() {
  awk '
    /^[A-Za-z_][A-Za-z0-9_]*=/ { i = index($0, "="); value[substr($0, 1, i - 1)] = substr($0, i + 1) }
    END { for (name in value) print name "=" value[name] }
  ' "$1" | sort
}
may_be_blank() { sed -n 's/^# may-be-blank://p' "$1" | tr ' ' '\n' | grep -v '^$' | sort -u || true; }

reference_path="${1:-}"; env_path="${2:-}"
[ -n "$reference_path" ] && [ -n "$env_path" ] || { echo "usage: check-env.sh <reference> <env file>"; exit 2; }
reference="$(stored "$reference_path")"; env="$(stored "$env_path")"
[ -f "$reference" ] || { echo "ERROR: the bundle holds no $reference_path."; exit 1; }
[ -f "$env" ] || { echo "ERROR: the bundle holds no $env_path."; exit 1; }
pairs "$reference" > "$work/.reference"
pairs "$env" > "$work/.env"
may_be_blank "$reference" > "$work/.may_be_blank"
cut -d= -f1 "$work/.reference" > "$work/.reference_names"
cut -d= -f1 "$work/.env" > "$work/.env_names"

missing="$(comm -23 "$work/.reference_names" "$work/.env_names")"
extra="$(comm -13 "$work/.reference_names" "$work/.env_names")"
blank="$(grep -E '^[A-Za-z0-9_]+=("")?$' "$work/.env" | cut -d= -f1 \
         | comm -12 - "$work/.reference_names" | comm -23 - "$work/.may_be_blank" || true)"
# Only where the reference sets a value: a blank there is a secret's place.
differs="$(awk -F= '
  NR == FNR { if (substr($0, index($0, "=") + 1) != "") want[$1] = substr($0, index($0, "=") + 1); next }
  ($1 in want) && substr($0, index($0, "=") + 1) != want[$1] {
    printf "  %s: %s, here %s\n", $1, want[$1], substr($0, index($0, "=") + 1)
  }
' "$work/.reference" "$work/.env")"

failed=0
if [ -n "$missing" ]; then
  echo "ERROR: $env_path lacks what $reference_path declares:"; echo "$missing" | sed 's/^/  /'; failed=1
fi
if [ -n "$blank" ]; then
  echo "ERROR: $env_path leaves these blank, and $reference_path needs them set:"; echo "$blank" | sed 's/^/  /'; failed=1
fi
if [ -n "$differs" ]; then
  echo "Differs from $reference_path (fine if meant for this place):"; echo "$differs"
fi
if [ -n "$extra" ]; then
  echo "In $env_path but not in $reference_path (no longer read, or a machine's shape: delete it):"
  echo "$extra" | sed 's/^/  /'
fi
[ "$failed" -eq 0 ] || exit 1
echo "$env_path has everything $reference_path declares, and nothing required is blank"
