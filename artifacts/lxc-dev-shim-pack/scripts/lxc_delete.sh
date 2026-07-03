#!/usr/bin/env bash
set -euo pipefail
WS=${1:?workspace_id}
lxc stop -f "$WS" || true
lxc delete "$WS" || true
echo "[+] deleted $WS"
