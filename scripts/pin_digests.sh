#!/usr/bin/env bash
set -euo pipefail

# Requires: crane, yq
# Purpose: resolve image digests for a TAG and write them into an overlay values file for GitOps.

REGISTRY="${REGISTRY:-ghcr.io}"
ORG="${ORG:-your-org}"
TAG="${TAG:-$(git rev-parse --short HEAD 2>/dev/null || echo dev)}"
OUT="${OUT:-charts/cloudshell/overlays/values.pinned.yaml}"

img() { echo "$REGISTRY/$ORG/$1:$TAG"; }

CLOUDSHELL="$(img cloud-shell)"
SPAWNER="$(img cloudshell-spawner)"
CULLER="$(img cloudshell-culler)"
SHIM="$(img porter-shim)"

digest_ref() {
  local ref="$1"
  local d
  d="$(crane digest "$ref")"
  echo "${ref%:*}@sha256:$d"
}

mkdir -p "$(dirname "$OUT")"

CLOUDSHELL_D="$(digest_ref "$CLOUDSHELL")"
SPAWNER_D="$(digest_ref "$SPAWNER")"
CULLER_D="$(digest_ref "$CULLER")"
SHIM_D="$(digest_ref "$SHIM")"

cat > "$OUT" <<EOF
image:
  cloudShell: "$CLOUDSHELL_D"
  spawner: "$SPAWNER_D"
  culler: "$CULLER_D"
EOF

echo "[+] wrote pinned images to $OUT"
echo "    $CLOUDSHELL_D"
echo "    $SPAWNER_D"
echo "    $CULLER_D"
echo "    (porter-shim digest computed but not used by cloudshell chart): $SHIM_D"
