#!/usr/bin/env bash
set -euo pipefail

PORT="${PORT:-7681}"
SHELL_CMD="${SHELL_CMD:-bash}"

mkdir -p "${HOME:-/home/cloud}"

exec /usr/local/bin/ttyd -p "$PORT" -i 0.0.0.0 -W "$SHELL_CMD"
