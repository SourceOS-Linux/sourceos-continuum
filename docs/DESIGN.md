# Canonical Design — Porter-first PaaS + Agentic GitOps (Pattern A)

Generated: 2026-01-14 14:05:30Z

## 1. Goals (what we are building)
We are building an open, local-first PaaS that:
- Treats **Porter** as a first-class PaaS interface.
- Treats **GitOps** as the truth (Pattern A): intent becomes PRs; Argo reconciles.
- Treats **agentic workflows** as first-class, but only via CapDs and PRs (no imperative drift).
- Runs across three machines:
  - **Inception**: build/attest/publish artifacts (OS + containers + charts + schemas).
  - **Genesys**: governance + policy + operator UX (the “adult supervision” node).
  - **K3 Twin**: runtime cluster (apps + devtools + storage + observability).

Non-goals:
- We are not building a “kubectl wrapper” system.
- We are not allowing local dev machines to become cluster orchestrators by default.

## 2. Pattern A (the invariant)
**Intent → PR → Policy/SRE gates → Argo reconcile → runtime evidence**

Everything (apps, OS upgrades, Cloud Shell installs, templates, ontology updates) is represented as:
- a PR
- a policy evaluation
- an observable reconciliation event

## 3. Major planes and responsibilities
### 3.1 Inception (artifact birth plane)
- Builds and signs:
  - container images (OCI)
  - SBOMs and attestations
  - OS images (rpm-ostree style)
- Outputs PRs that update desired state repos (chart versions, image digests, OS channels).

### 3.2 Genesys (governance plane)
- Enforces:
  - admission policies (Kyverno/Gatekeeper class)
  - promotion gates (SRE burn rate, storage pressure, rollout health)
  - multi-tenant RBAC patterns
- Provides first-class operator UX:
  - Podman rootless
  - toolbx/toolbox patterns for immutable hosts
  - Slack + lynx + modern terminal experience
  - Prophet CLI as the universal verb surface

### 3.3 K3 Digital Twin (runtime plane)
- Runs workloads and devtools:
  - Cloud Shell (per-user)
  - PaaS workloads deployed via Argo
  - storage profile (TopoLVM optional)
  - observability profile

## 4. Dev experience surfaces (three lanes, one truth)
### 4.1 Cloud Shell (Google-style, Twin-hosted)
Cloud Shell is a browser terminal, OIDC-authenticated, with persistent $HOME, hardened policies, and least privilege.

Key correctness rule:
- Shared ServiceAccounts are identity-incorrect.
- We use a **Spawner** (per-user SA/PVC/Deployment/Service) keyed off OIDC identity headers.

### 4.2 LXC Dev Shim (Gitpod-like without K8s tenancy)
A workspace system using LXD/LXC:
- Dev-only local mode (privileged devcontainer).
- Multi-user mode via Genesys gateway to a hardened LXD host.
CapDs: porter.devshim.*

### 4.3 Compose → K8s (Kompose bridge)
We support single-node non-K8 deployments with Compose, then convert to K8s manifests via Kompose and promote via PR/Argo.

## 5. Security model (baseline)
- Supply chain: signed images, pinned digests, SBOMs.
- Pod security: non-root, drop caps, no priv-esc, RuntimeDefault seccomp.
- Network: default-deny where enforceable (CNI matters on k3s).
- RBAC: namespace-scoped by default; elevation is explicit and audited.
- Audit: logs/metrics/traces shipped centrally; session logging optional.

## 6. Scale strategy (local-first)
- Scale down: single-node, minimal addons; Compose allowed but converts to K8s via PR.
- Scale up: same GitOps/policy semantics; multi-node and multi-cluster via declarative lifecycle tooling.

## 7. Component alignment (what goes where)
- Genesys CLI pack: operator parity and Prophet interface.
- Cloud Shell hardened pack: Twin devtools + identity-correct shells.
- LXC dev shim: heavy dev workspaces outside the cluster.
- Porter: PaaS interface; Argo: reconciler; Prophet: capability router.


## 7.1 Porter Shim (CapD backend)
We run a **Porter Shim** on Genesys as the primary CapD backend:
- Receives Prophet CapD requests (from humans or agents).
- Writes PRs against GitOps repos (preferred).
- Optionally consults Porter APIs for PaaS metadata and Argo APIs for reconciliation observability.
- Never becomes a drift engine: it does not apply directly to clusters except as a last-resort breakglass workflow that produces evidence.

See: `artifacts/porter-shim/`.

## 8. Known hard dependencies
- If we require NetworkPolicy enforcement on k3s, we must standardize on a policy-capable CNI (e.g., Cilium/Calico).
- If we require signed-image enforcement, we must operate a signing pipeline and distribute public keys.

## 9. Next two steps (to avoid rework)
1) Build and ship spawner/culler images + route per-user shells behind ingress.
2) Turn Kyverno policies from Audit scaffolds into Enforce with conformance tests.

