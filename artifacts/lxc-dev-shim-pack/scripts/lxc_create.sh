#!/usr/bin/env bash
set -euo pipefail
OWNER=${1:?owner}
REPO=${2:?repo_url}
REF=${3:?ref}
IMAGE=${4:-images:ubuntu/22.04}
SIZE=${5:-s}
TTL=${6:-180}
FEATURES=${7:-"kubectl,helm,node,go,python,code-server"}

WS="ws-$(date +%s)-$RANDOM"
echo "[+] create $WS owner=$OWNER repo=$REPO ref=$REF size=$SIZE ttl=$TTL"
lxc launch "$IMAGE" "$WS"
lxc exec "$WS" -- bash -lc "apt-get update && apt-get install -y git curl ca-certificates"
lxc exec "$WS" -- bash -lc "mkdir -p /workspace && cd /workspace && git clone --depth=1 $REPO app && cd app && git fetch origin $REF || true && git checkout $REF || true"
IP=$(lxc list "$WS" -c 4 --format csv | awk '{print $1}' | head -n1)
echo "WORKSPACE=$WS"
echo "IP=$IP"
