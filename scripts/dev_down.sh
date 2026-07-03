#!/usr/bin/env bash
# dev_down.sh — tear down the local-first PaaS cluster.
set -euo pipefail
CLUSTER="${CLUSTER:-prophet-paas}"
if command -v kind >/dev/null 2>&1 && kind get clusters 2>/dev/null | grep -qx "$CLUSTER"; then
  echo "▶ deleting kind cluster '$CLUSTER'"
  kind delete cluster --name "$CLUSTER"
else
  echo "! kind cluster '$CLUSTER' not found; nothing to do"
fi
