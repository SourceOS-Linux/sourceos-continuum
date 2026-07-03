# Local-first PaaS — quickstart

A Vercel/Heroku-style developer loop with GitOps truth underneath, on your own
machine. One command brings up a kind cluster running the whole control plane;
you deploy apps through the `prophet` CLI (or the porter-shim API), and Argo
reconciles from Git.

## One command

```bash
make dev-up
```

Which runs `scripts/dev_up.sh` (idempotent):
1. **preflight** — checks for a container runtime (Docker/Podman) and installs
   `kubectl`/`kind`/`helm` via brew if missing.
2. **kind cluster** `prophet-paas` (ingress-ready, host ports 80/443 → ingress).
3. **ingress-nginx** (kind provider).
4. **Argo CD** (the reconciler).
5. **hardened pack in AUDIT** — the Kyverno signed-image / pod-security / no-latest
   policies, in Audit mode locally (Enforce needs signed local images — that's the
   prod posture, not the dev loop).
6. **Cloud Shell** via Helm with `overlays/values.local.yaml` (no-auth, public
   ttyd image, kind `standard` storage).
7. **porter-shim** (dev posture: unsigned allowed, dry-run PRs).

Then:

```
Cloud Shell   →  http://localhost/
porter-shim   →  kubectl -n porter-system port-forward svc/porter-shim 8081:80
Argo CD UI    →  kubectl -n argocd port-forward svc/argocd-server 8080:443
```

## Deploy an app (Pattern A: Intent → PR → gate → Argo → evidence)

```bash
export PROPHET_API=http://localhost:8081
prophet release publish --service api --env dev --digest ghcr.io/you/api@sha256:<64hex>
# → { "pr_url": "...", "evidence_bundle": { signed, policy_pass, ... } }
```

The shim validates the pinned digest, applies the `signed_images` guard, and
(dry-run locally, or a real `gh` PR when `SHIM_GITOPS_REPO` is set) records the
promotion with an evidence bundle. Argo reconciles the merged PR into the cluster.

## Tear down

```bash
make dev-down
```

## What's local-dev vs production

| Concern | Local (`values.local.yaml` / dev_up) | Production (GitOps) |
|---|---|---|
| Auth | off (ingress → gateway) | oauth2-proxy + OIDC (`auth.enabled: true`) |
| Policies | Kyverno **Audit** | **Enforce** + keyless-signed images |
| Shim PRs | dry-run (`local://…`) | real `gh` PRs (`SHIM_GITOPS_REPO`) |
| Storage | kind `standard` | TopoLVM / cloud PV |

## Notes

- Needs a container runtime; every local-k8s option (kind/k3d/minikube) does.
- `make shim-test` builds + tests the control plane (`CGO_ENABLED=0`).
- The shim's `/compose/kompose/convert` needs `kompose` on the shim host.
