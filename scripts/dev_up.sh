#!/usr/bin/env bash
# dev_up.sh — one command to stand up the local-first PaaS on kind.
#
#   Vercel/Heroku-style dev loop, GitOps truth underneath:
#   kind cluster → ingress-nginx → Argo CD → hardened pack (AUDIT locally) →
#   Cloud Shell (local profile, no-auth) → porter-shim (the deploy API).
#
# Idempotent; safe to re-run. Requires a container runtime (docker/podman).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLUSTER="${CLUSTER:-prophet-paas}"
NS_DEVTOOLS="${NS_DEVTOOLS:-devtools}"
NS_PORTER="${NS_PORTER:-porter-system}"

log()  { printf '\033[1;36m▶ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m! %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

# ── preflight ────────────────────────────────────────────────────────────────
# HOST_HTTP/HOST_HTTPS are the ports the ingress is published on. They are 80/443
# unless the runtime cannot bind privileged ports, in which case they move up.
HOST_HTTP=80
HOST_HTTPS=443

need_runtime() {
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then return 0; fi
  if command -v podman >/dev/null 2>&1; then
    export KIND_EXPERIMENTAL_PROVIDER=podman
    # ROOTLESS podman cannot bind ports below net.ipv4.ip_unprivileged_port_start
    # (1024 by default), so a cluster mapping 80/443 dies at create time with
    # "rootlessport cannot expose privileged port 80" -- before any workload exists.
    # Rather than ask the operator to edit sysctl for a dev loop, publish the ingress
    # higher up and tell them the URL.
    if [ "$(podman info --format '{{.Host.Security.Rootless}}' 2>/dev/null)" = "true" ]; then
      HOST_HTTP=8080
      HOST_HTTPS=8443
      warn "rootless podman: publishing ingress on ${HOST_HTTP}/${HOST_HTTPS} (cannot bind 80/443)"
    fi
    return 0
  fi
  die "no container runtime — install Docker Desktop or Podman (kind needs one)"
}

ensure_tool() {  # ensure_tool <bin> <brew-formula>
  command -v "$1" >/dev/null 2>&1 && return 0
  if command -v brew >/dev/null 2>&1; then log "installing $1 via brew"; brew install "$2" >/dev/null; else
    die "$1 not found and brew unavailable — install $1 manually"; fi
}

preflight() {
  log "preflight"
  need_runtime
  ensure_tool kubectl kubernetes-cli
  ensure_tool kind kind
  ensure_tool helm helm
}

# ── cluster ──────────────────────────────────────────────────────────────────
cluster_up() {
  if kind get clusters 2>/dev/null | grep -qx "$CLUSTER"; then
    log "kind cluster '$CLUSTER' already exists"
  else
    log "creating kind cluster '$CLUSTER' (ingress on ${HOST_HTTP}/${HOST_HTTPS})"
    # The committed config carries the canonical shape; the host ports are substituted
    # so the same file serves docker (80/443) and rootless podman (8080/8443).
    sed -e "s/hostPort: 80$/hostPort: ${HOST_HTTP}/" \
        -e "s/hostPort: 443$/hostPort: ${HOST_HTTPS}/" \
        "$ROOT/local/kind-cluster.yaml" | kind create cluster --config -
  fi
  kubectl cluster-info --context "kind-$CLUSTER" >/dev/null
}

ingress_up() {
  log "installing ingress-nginx"
  kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml
  kubectl -n ingress-nginx wait --for=condition=available deploy/ingress-nginx-controller --timeout=180s || \
    warn "ingress-nginx not ready yet; continuing"
}

argo_up() {
  log "installing Argo CD"
  kubectl create ns argocd --dry-run=client -o yaml | kubectl apply -f -
  # Server-side apply: the ApplicationSet CRD exceeds the 262144-byte
  # last-applied-configuration annotation limit of client-side apply.
  kubectl apply --server-side --force-conflicts -n argocd \
    -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
  kubectl -n argocd rollout status deploy/argocd-repo-server --timeout=240s || warn "argocd still settling"
}

# Hardened pack in AUDIT locally — keyless signing isn't wired for local images,
# so Enforce would (correctly) block everything. Audit surfaces violations first.
policies_audit() {
  local pack="$ROOT/artifacts/cloudshell-hardened-pack/policies/kyverno"
  [ -d "$pack" ] || { warn "no kyverno pack; skipping"; return 0; }
  log "applying hardened pack (Audit mode)"
  # Install Kyverno if the CRDs aren't present.
  kubectl get crd clusterpolicies.kyverno.io >/dev/null 2>&1 || \
    helm upgrade --install kyverno kyverno --repo https://kyverno.github.io/kyverno -n kyverno --create-namespace >/dev/null
  for f in "$pack"/*.yaml; do
    [ -e "$f" ] || continue
    sed 's/validationFailureAction: Enforce/validationFailureAction: Audit/' "$f" | kubectl apply -f - || \
      warn "policy $f not applied (CRDs may still be settling)"
  done
}

cloudshell_up() {
  log "installing Cloud Shell (local profile, no-auth)"
  kubectl create ns "$NS_DEVTOOLS" --dry-run=client -o yaml | kubectl apply -f -
  helm upgrade --install cloudshell "$ROOT/charts/cloudshell" -n "$NS_DEVTOOLS" \
    -f "$ROOT/charts/cloudshell/overlays/values.local.yaml"
}

# Build the shim image locally and load it into the kind cluster (no registry
# needed for the dev loop). Supports docker or podman.
shim_build_load() {
  local img="localhost/porter-shim:dev"
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    log "building porter-shim (docker)"
    docker build -t "$img" -f "$ROOT/artifacts/porter-shim/Dockerfile" "$ROOT"
    kind load docker-image "$img" --name "$CLUSTER"
  elif command -v podman >/dev/null 2>&1; then
    log "building porter-shim (podman)"
    podman build -t "$img" -f "$ROOT/artifacts/porter-shim/Dockerfile" "$ROOT"
    podman save --format docker-archive -o /tmp/porter-shim.tar "$img"
    kind load image-archive /tmp/porter-shim.tar --name "$CLUSTER"
  else
    warn "no image builder; porter-shim will not have an image"; return 0
  fi
  SHIM_IMG="$img"
}

shim_up() {
  log "deploying porter-shim (dev: unsigned allowed, dry-run PRs)"
  kubectl create ns "$NS_PORTER" --dry-run=client -o yaml | kubectl apply -f -
  kubectl -n "$NS_PORTER" apply -f "$ROOT/artifacts/porter-shim/deploy/shim.yaml"
  if [ -n "${SHIM_IMG:-}" ]; then
    kubectl -n "$NS_PORTER" set image deploy/porter-shim shim="$SHIM_IMG" >/dev/null
    kubectl -n "$NS_PORTER" patch deploy porter-shim --type=json \
      -p='[{"op":"add","path":"/spec/template/spec/containers/0/imagePullPolicy","value":"Never"}]' >/dev/null 2>&1 || true
  fi
  # Local dev posture for the shim.
  kubectl -n "$NS_PORTER" set env deploy/porter-shim SHIM_ALLOW_UNSIGNED=true SHIM_SHELL_BASE=http://localhost:${HOST_HTTP} >/dev/null 2>&1 || true
  kubectl -n "$NS_PORTER" rollout status deploy/porter-shim --timeout=120s || warn "porter-shim still settling"
}

summary() {
  cat <<EOF

$(printf '\033[1;32m✓ local-first PaaS is up\033[0m')

  Cloud Shell   →  http://localhost/           (browser terminal, no-auth local)
  porter-shim   →  kubectl -n $NS_PORTER port-forward svc/porter-shim 8081:80
  Argo CD UI    →  kubectl -n argocd port-forward svc/argocd-server 8080:443

  Deploy an app (Heroku/Vercel-style):
    export PROPHET_API=http://localhost:8081
    prophet release publish --service api --env dev --digest ghcr.io/you/api@sha256:...

  Tear down:  make dev-down   (or: kind delete cluster --name $CLUSTER)
EOF
}

main() {
  preflight
  cluster_up
  ingress_up
  argo_up
  policies_audit
  cloudshell_up
  shim_build_load
  shim_up
  summary
}
main "$@"
