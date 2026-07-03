# Full Synthesis — Porter-first PaaS + Agentic GitOps (Reaggregated)

Generated: 2026-01-14 14:16:53Z

This document reaggregates the *entire* chat record into a single coherent architecture, including:
- the three-machine control plane model (Inception, Genesys, K3 Twin)
- Porter as first-class PaaS
- Prophet + CapDs as the agentic GitOps interface
- Cloud Shell (Google-style) with identity-correct RBAC
- local-first scale down/up strategy
- domain layers (smart home, ontology, volunteer compute, digital twin mesh)
- omissions and corrections (including tool deprecations)

---

## 1) The invariant spine: Pattern A

We enforce one grammar everywhere:

**Intent → PR → Policy/SRE gates → Argo reconcile → Runtime evidence**

Agents can propose changes; they do not “apply” changes. Any breakglass imperative action produces an evidence bundle and is treated as a controlled exception.

---

## 2) Three machines, one time-shifted control plane

### 2.1 Inception Host — artifact birth plane
What Inception does:
- Build container images, SBOMs, attestations, signatures
- Build OS images (rpm-ostree family patterns), signed promotion channels
- Produce PRs that update the GitOps repo (image digests, chart versions, OS channels)

What Inception does *not* do:
- It does not become a “kubectl apply” node.
- It does not hold broad cluster admin credentials unless absolutely required.

### 2.2 Genesys Host — governance + operator plane
What Genesys does:
- Runs policies, promotion gates, SRE guardrails
- Provides the operator workstation UX (open tooling; Podman rootless; modern terminal)
- Hosts Prophet CLI + the primary CapD backend (Porter Shim)

What Genesys does *not* do:
- It does not tolerate drift; it prefers PRs and Argo reconcile.

### 2.3 K3 Digital Twin — runtime plane
What the Twin does:
- Runs workloads and devtools (Cloud Shell), storage (TopoLVM), observability, etc.
- Is the place where “state exists.”
- Is locally runnable but also scales up to multi-node and multi-cluster.

---

## 3) Porter as first-class PaaS

Porter’s role:
- App lifecycle semantics: environments, releases, previews, templates
- Developer-facing interface layer

Argo’s role:
- The reconciler and truth engine (Git → cluster)
- Drift detection and rollback mechanism

We keep a hard boundary:
- **Porter** may emit PRs or call Prophet/Porter Shim to emit PRs.
- **Argo** applies state from Git.
- **No tool becomes a hidden state database** outside Git.

---

## 4) Prophet + CapDs: full agentic GitOps

We introduced CapDs (Capability Descriptors) so every operation is:
- explicitly defined (inputs, outputs, guards, evidence)
- automatable by agents without permitting drift
- consistent across Genesys/Inception/Twin

Example CapDs:
- `porter.release.publish`
- `twin.cloudshell.install`
- `tools.compose.kompose.convert`
- `porter.devshim.create`
- `inception.os.publish`
- `genesys.os.promote`

---

## 5) Dev experience surfaces (three lanes, one truth)

### 5.1 Cloud Shell on the Twin (Google-style)
We ship Cloud Shell as a devtools service:
- browser terminal (ttyd/Wetty)
- OIDC auth (oauth2-proxy + Dex/Keycloak)
- persistent $HOME via PVC
- policies and quotas by default

Correctness rule:
- oauth2-proxy identity headers ≠ Kubernetes RBAC.
- We need identity-correct per-user shells.

So:
- a **Spawner** creates per-user SA/PVC/Deployment/Service
- a **Culler** reclaims idle shells using an activity signal (initially an annotation; later an auth_request heartbeat/metrics)

### 5.2 LXC Dev Shim (Gitpod-like without K8s tenancy)
We want Gitpod-like reproducible workspaces, but:
- local dev should not orchestrate clusters unless doing software dev.

So we use LXD/LXC:
- devcontainer-local mode (single user)
- Genesys-hosted gateway mode (multi user)

### 5.3 Compose → K8s bridge
We support single-node Compose where appropriate, but maintain k8s compatibility via Kompose conversion and GitOps promotion.

---

## 6) OS image updates + container builds

We treat OS updates as a rollout problem, not a package-manager problem.
- Inception builds signed OS artifacts (rpm-ostree style).
- Genesys promotes versions with drain/rollback gates.

---

## 7) Storage profile: TopoLVM (local-first)
TopoLVM provides local PVs backed by LVM. It’s a strong fit for Twins/edge.
We must gate it with:
- quotas
- watermarks
- promotion checks (storage pressure affects rollout approvals)

---

## 8) Scheduling: topology/cost-aware as advisory PR patches
Firmament/Poseidon are inspiration inputs.
We prefer an “advisor” model first:
- scores and suggests placements
- opens PR patches (affinity/spread/requests/limits)
- stays auditable and reversible

---

## 9) Domain layers we explicitly want (not optional in the long run)

### 9.1 Smart home
Homebase + home-assistant CLI are first-class platform features.
They plug into the same identity and capability surfaces.

### 9.2 Ontology + knowledge
WebProtégé and ontologies become Git-managed artifacts:
- schemas validated in CI
- promoted via PRs
- edited in UI with audit trails

### 9.3 Digital twin mesh / federation
Cloudland/federated/mesh-for-data etc. are tracked as the “twin mesh” plane.
We will triage and extract primitives before committing to any dependency.

### 9.4 Volunteer compute / distributed AI
BOINC-policy, PyBossa, Singularity, JPPF are “pool profiles.”
They’re optional add-on profiles until we fully specify contract/proof/governance.

---

## 10) Corrections and hard truths

1) **NetworkPolicy on k3s is not automatically enforced** (depends on CNI).  
2) **coreos/toolbox is deprecated**; prefer containers/toolbox.  
3) “Spawner/culler” were initially scaffolds; we now include concrete code stubs, but module fetching is blocked in this sandbox environment.

---

## 11) Backlog (next two steps)
1) Build and sign spawner/culler images; wire ingress routing and per-user activity heartbeat.
2) Upgrade policies from Audit→Enforce with conformance tests (signed images, no latest, PSS baseline).

