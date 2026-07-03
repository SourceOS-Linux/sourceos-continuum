\
#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MAN="$ROOT/tools/manifest.yaml"
BIN="${BIN:-/usr/local/bin}"
RUNTIME="${RUNTIME:-podman}"          # podman|toolbox
TOOLBOX_BIN="${TOOLBOX_BIN:-toolbox}" # toolbx command (containers/toolbox)

need() { command -v "$1" >/dev/null 2>&1 || { echo "Missing $1"; exit 1; }; }

need python3
need jq

yqjson() { python3 - <<'PY'
import sys, yaml, json
print(json.dumps(yaml.safe_load(sys.stdin.read())))
PY
}

cfg_json="$(cat "$MAN" | yqjson)"

mkdir -p "$BIN"

wrap_podman() {
  local name="$1" image="$2" cmd="${3:-$1}"
  cat > "$BIN/$name" <<EOF
#!/usr/bin/env bash
set -e
exec podman run --rm -it \
  -v "\$HOME:/home/user:Z" \
  -v "\$PWD:/work:Z" -w /work \
  --security-opt label=disable \
  "$image" "$cmd" "\$@"
EOF
  chmod +x "$BIN/$name"
  echo "[podman] $name -> $image"
}

wrap_toolbox() {
  local name="$1"
  need "$TOOLBOX_BIN"
  # Ensure toolbx container exists
  if ! $TOOLBOX_BIN list 2>/dev/null | grep -q genesys; then
    $TOOLBOX_BIN create -c genesys >/dev/null
  fi
  cat > "$BIN/$name" <<EOF
#!/usr/bin/env bash
set -e
exec $TOOLBOX_BIN run -c genesys $name "\$@"
EOF
  chmod +x "$BIN/$name"
  echo "[toolbx] $name -> toolbx container 'genesys'"
}

install_cat() {
  local cat="$1"
  echo "$cfg_json" | jq -c --arg cat "$cat" '.categories[$cat][]' | while read -r item; do
    name="$(echo "$item" | jq -r '.name')"
    image="$(echo "$item" | jq -r '.image // ""')"
    cmd="$(echo "$item" | jq -r '.cmd // ""')"
    if [[ "$RUNTIME" == "podman" && -n "$image" ]]; then
      wrap_podman "$name" "$image" "$([[ -n "$cmd" ]] && echo "$cmd" || echo "$name")"
    else
      wrap_toolbox "$name"
    fi
  done
}

need podman || true

for cat in $(echo "$cfg_json" | jq -r '.categories | keys[]'); do
  install_cat "$cat"
done

echo "Done. Ensure $BIN is in PATH."
