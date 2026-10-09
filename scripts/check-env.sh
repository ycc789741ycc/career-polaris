#!/bin/sh
# Compares env files by their variable names and values. It reads every file
# it compares from stdin, as one bundle, and is run by `make` in a container
# with no network, so neither a template nor a .env ever needs mounting:
#
#   ### FILE <path>
#   <that file's lines>
#   ### FILE <path>
#   ...
#
# Two checks:
#
#   check-env.sh templates
#     `make lint`. Every infra/env/*.env.example in the bundle declares exactly
#     the names .env.example does, and its may-be-blank line names only those.
#     A variable added to one template and not the others fails here, not on a
#     machine at startup.
#
#   check-env.sh place <template> <env file>
#     `make check-env TEMPLATE=`. Compares this machine's .env with the
#     template it was copied from. Errors, which fail:
#       missing  a name in the template that .env lacks
#       blank    a name blank in .env, unless the template's `# may-be-blank:`
#                line lists it
#     Reports, which do not:
#       differs  a value the template sets that .env sets otherwise — a limit
#                raised by hand, or a template change this .env has not taken
#       extra    a name in .env the template does not declare
#     Values are printed only where the template sets one, so a secret, which
#     templates leave blank, is never printed.
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
names() { pairs "$1" | cut -d= -f1; }
may_be_blank() { sed -n 's/^# may-be-blank://p' "$1" | tr ' ' '\n' | grep -v '^$' | sort -u || true; }

mode="${1:-}"
case "$mode" in
  templates)
    reference="$(stored .env.example)"
    [ -f "$reference" ] || { echo "ERROR: the bundle holds no .env.example."; exit 1; }
    names "$reference" > "$work/.reference"
    failed=0
    count=0
    for template in "$work"/bundle/infra__env__*.env.example; do
      [ -f "$template" ] || continue
      count=$((count + 1))
      shown="$(basename "$template" | sed 's|__|/|g')"
      names "$template" > "$work/.names"
      lacking="$(comm -23 "$work/.reference" "$work/.names")"
      surplus="$(comm -13 "$work/.reference" "$work/.names")"
      unknown="$(may_be_blank "$template" | comm -23 - "$work/.names")"
      if [ -n "$lacking" ]; then
        echo "ERROR: $shown lacks what .env.example declares:"; echo "$lacking" | sed 's/^/  /'; failed=1
      fi
      if [ -n "$surplus" ]; then
        echo "ERROR: $shown declares what .env.example does not:"; echo "$surplus" | sed 's/^/  /'; failed=1
      fi
      if [ -n "$unknown" ]; then
        echo "ERROR: $shown lets a name it does not declare be blank:"; echo "$unknown" | sed 's/^/  /'; failed=1
      fi
    done
    [ "$failed" -eq 0 ] || exit 1
    echo "env templates: $count, each declaring exactly what .env.example does"
    ;;

  place)
    template_path="${2:-}"; env_path="${3:-}"
    template="$(stored "$template_path")"; env="$(stored "$env_path")"
    [ -f "$template" ] || { echo "ERROR: the bundle holds no $template_path."; exit 1; }
    [ -f "$env" ] || { echo "ERROR: the bundle holds no $env_path."; exit 1; }
    pairs "$template" > "$work/.template"
    pairs "$env" > "$work/.env"
    may_be_blank "$template" > "$work/.may_be_blank"
    cut -d= -f1 "$work/.template" > "$work/.template_names"
    cut -d= -f1 "$work/.env" > "$work/.env_names"

    missing="$(comm -23 "$work/.template_names" "$work/.env_names")"
    extra="$(comm -13 "$work/.template_names" "$work/.env_names")"
    blank="$(grep -E '^[A-Za-z0-9_]+=("")?$' "$work/.env" | cut -d= -f1 \
             | comm -12 - "$work/.template_names" | comm -23 - "$work/.may_be_blank" || true)"
    # Only where the template sets a value: a blank there is a secret's place.
    differs="$(awk -F= '
      NR == FNR { if (substr($0, index($0, "=") + 1) != "") want[$1] = substr($0, index($0, "=") + 1); next }
      ($1 in want) && substr($0, index($0, "=") + 1) != want[$1] {
        printf "  %s: template %s, here %s\n", $1, want[$1], substr($0, index($0, "=") + 1)
      }
    ' "$work/.template" "$work/.env")"

    failed=0
    if [ -n "$missing" ]; then
      echo "ERROR: $env_path lacks what $template_path declares:"; echo "$missing" | sed 's/^/  /'; failed=1
    fi
    if [ -n "$blank" ]; then
      echo "ERROR: $env_path leaves these blank, and $template_path needs them set:"; echo "$blank" | sed 's/^/  /'; failed=1
    fi
    if [ -n "$differs" ]; then
      echo "Differs from $template_path (fine if meant; otherwise take the template's):"; echo "$differs"
    fi
    if [ -n "$extra" ]; then
      echo "In $env_path but not in $template_path (no longer read?):"; echo "$extra" | sed 's/^/  /'
    fi
    [ "$failed" -eq 0 ] || exit 1
    echo "$env_path has everything $template_path declares, and nothing required is blank"
    ;;

  *)
    echo "usage: check-env.sh templates | check-env.sh place <template> <env file>"; exit 2 ;;
esac
