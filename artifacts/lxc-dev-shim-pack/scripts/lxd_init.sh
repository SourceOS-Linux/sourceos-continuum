#!/usr/bin/env bash
set -euo pipefail
if ! command -v lxd >/dev/null 2>&1; then
  echo "Installing LXD via snap (dev shim)."
  snap install lxd --channel=5.21/stable || true
fi
echo "Initializing LXD with defaults (override as needed)."
lxd init --auto || true
echo "LXD ready."
