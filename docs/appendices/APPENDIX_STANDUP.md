# Appendix — Stand-up & build/push playbook

Generated: 2026-01-14 17:02:38Z

## 0) Assumptions
- We have a container registry (GHCR/GitLab/Harbor/etc.).
- We have a cluster (k3s/k8s/OpenShift) with an ingress/route configured.
- We have an OIDC issuer (Dex/Keycloak/etc.).

## 1) Build & push images
Local Docker build+push:
```bash
make push-all REGISTRY=ghcr.io ORG=your-org TAG=$(git rev-parse --short HEAD) PLATFORMS=linux/amd64
```

Sign images:
```bash
cosign sign --yes ghcr.io/your-org/cloud-shell:TAG
cosign sign --yes ghcr.io/your-org/cloudshell-spawner:TAG
cosign sign --yes ghcr.io/your-org/cloudshell-culler:TAG
cosign sign --yes ghcr.io/your-org/porter-shim:TAG
```

CI:
- GitHub Actions: `.github/workflows/images.yml`
- GitLab CI: `templates/ci/gitlab-ci.yml`

## 2) Bootstrap install Cloud Shell (non-GitOps)
```bash
export CLIENT_SECRET='...'
export HOST='shell.example.com'
export ISSUER='https://dex.example.com'
./scripts/deploy_cloudshell.sh
```

## 3) GitOps install (Pattern A)
- Put `charts/cloudshell` into your GitOps repo.
- Pin images by digest in values overlays.
- Store secrets using ExternalSecrets/SealedSecrets.
- Let Argo reconcile into the `devtools` namespace.

## 4) Lock-in checklist
- pin image digests
- enforce Kyverno policy after signatures are live (Audit→Enforce)
- pick k3s CNI that enforces NetworkPolicy if we require default-deny


## Multi-arch note
- For ARM64 Twins (common on edge hardware), set `PLATFORMS=linux/amd64,linux/arm64`.
- The cloud-shell image Dockerfile is TARGETARCH-aware (ttyd/kubectl/helm/yq/jq download the correct arch).
