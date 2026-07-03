# Security Model (Baseline)

Generated: 2026-01-14 14:16:53Z

## 1) Default posture
- least privilege RBAC
- signed artifacts (images + OS) with verifiable provenance
- drift is blocked or reversed (GitOps truth)
- network segmentation where enforceable

## 2) Identity
- OIDC everywhere (Dex/Keycloak)
- Map groups → Roles/RoleBindings (namespace-scoped by default)
- Cloud Shell uses per-user ServiceAccounts created by spawner

## 3) Supply chain
- images are digest-pinned
- images are signed (Cosign)
- SBOM generated and attached (Syft)
- admission verifies signatures (Kyverno verifyImages) once pipeline is operational

## 4) Pod security baseline
- runAsNonRoot, allowPrivilegeEscalation=false, drop ALL caps
- seccomp RuntimeDefault
- readOnlyRootFilesystem enforced after images comply

## 5) Network
- default-deny in devtools
- allow ingress from ingress controller only
- allow DNS egress
- note: k3s CNI choice determines enforcement

## 6) Evidence and audit
- Every CapD produces an evidence bundle:
  - PR link, policy outcomes, artifact signatures, rollout status
- Optional session logging for Cloud Shell (tlog/script) for forensics

