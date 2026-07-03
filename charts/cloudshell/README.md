# cloudshell Helm chart

Generated: 2026-01-14 17:02:38Z

Installs:
- oauth2-proxy (OIDC)
- nginx gateway (routes `/launch` and `/u/<hash>/` to per-user services)
- spawner (creates per-user SA/PVC/Deployment/Service)
- culler (optional)
- shared shell (fallback / bootstrap)

Install (quick, non-GitOps bootstrap):
```bash
kubectl create ns devtools || true
kubectl -n devtools create secret generic cloudshell-oauth2-proxy \
  --from-literal=client-id='cloudshell' \
  --from-literal=client-secret='REDACTED' \
  --from-literal=cookie-secret='BASE64_32_BYTES'

helm upgrade --install cloudshell ./charts/cloudshell -n devtools \
  --set ingress.host=shell.example.com \
  --set auth.oidcIssuerURL=https://dex.example.com \
  --set image.cloudShell=ghcr.io/your-org/cloud-shell@sha256:... \
  --set image.spawner=ghcr.io/your-org/cloudshell-spawner@sha256:... \
  --set image.culler=ghcr.io/your-org/cloudshell-culler@sha256:...
```

In GitOps:
- Store secrets using ExternalSecrets/SealedSecrets.
- Reference images by digest and enable Kyverno verifyImages (Audit → Enforce).


k3s overlay example:
```bash
helm upgrade --install cloudshell ./charts/cloudshell -n devtools \
  -f charts/cloudshell/overlays/values.k3s.yaml
```
