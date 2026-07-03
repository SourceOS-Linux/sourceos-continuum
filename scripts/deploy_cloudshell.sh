#!/usr/bin/env bash
set -euo pipefail

NS="${NS:-devtools}"
RELEASE="${RELEASE:-cloudshell}"
CHART="${CHART:-./charts/cloudshell}"
HOST="${HOST:-shell.example.com}"
ISSUER="${ISSUER:-https://dex.example.com}"
CLIENT_ID="${CLIENT_ID:-cloudshell}"
CLIENT_SECRET="${CLIENT_SECRET:?set CLIENT_SECRET}"
COOKIE_SECRET="${COOKIE_SECRET:-$(head -c 32 /dev/urandom | base64)}"

kubectl create ns "$NS" >/dev/null 2>&1 || true

kubectl -n "$NS" create secret generic cloudshell-oauth2-proxy   --from-literal=client-id="$CLIENT_ID"   --from-literal=client-secret="$CLIENT_SECRET"   --from-literal=cookie-secret="$COOKIE_SECRET"   --dry-run=client -o yaml | kubectl apply -f -

helm upgrade --install "$RELEASE" "$CHART" -n "$NS"   --set ingress.host="$HOST"   --set auth.oidcIssuerURL="$ISSUER"

echo ""
echo "Cloud Shell installed."
echo "Open: https://$HOST/"
echo "Spawn per-user: POST https://$HOST/launch  (oauth2-proxy protected)"
