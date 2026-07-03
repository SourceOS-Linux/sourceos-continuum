# SourceOS Continuum

**Tagline:** OS-layer local-first PaaS — a seamless developer *continuum* from onboarding through cloud-native test and rollout.

## About
`sourceos-continuum` is the SourceOS OS-layer Platform-as-a-Service control plane. It owns the
developer **continuum**: onboard a workstation, develop against a local sovereign forge, run and
cloud-native-test workloads on a local cluster (kind/k3s), then roll them out — the same workload,
without seams, from n=1 local up to a composable cluster.

It rehomes the Porter local-PaaS control-plane work as a first-class SourceOS OS integration, and
treats `SourceOS-Linux/sourceos-devtools` (`sourceosctl`) as its first-class operator surface.

## Owned surfaces
- Local PaaS control plane (porter-shim) over kind/k3s.
- PR-driven GitOps: deploy, ephemeral preview/test environments, promotion, rollback.
- Onboard → develop → test → rollout lifecycle orchestration (see `docs/LIFECYCLE.md`).
- CapD interface contracts for agentic deploy/rollout workflows.
- Evidence bundles (signed images, provenance) per action.

## Non-owned surfaces
- Source-control authority — that is **Gitea Sovereign**.
- Workspace manifest + binding — that is **SocioProphet/sociosphere** (the source→workspace controller).
- Runtime tuning + release (RuntimeAssets, SBOM, signing) — that is **SocioProphet/lattice-forge**.
- Cluster scale-up primitives — pinned via **SocioProphet/hyperswarm-agent-composable-cluster-scaleup**.
- Model weights, datasets, training runs.

## The continuum (pipeline)
```
Gitea Sovereign ──▶ sociosphere ──▶ prophet-workspace
 (local forge)   (source→workspace)   (the workspace)

Holmes labs ──▶ lattice-forge ──▶ sourceos-continuum ──▶ hyperswarm
(OOTB models)  (prophet-platform    (local PaaS deploy:     (cluster
               tunes → signed        onboard→test→rollout)   scale-up)
               RuntimeAssets)
```

## Capability
- Capability: `caps.infra.paas.continuum-local@0.1.0` (see `capd/continuum.local-paas.capd.json`)
- Scales up to: `caps.infra.cluster-scaleup.hyperswarm@0.1.0`
- Composes with: `caps.infra.paas.porter-local@0.1.0` (rehomed control-plane primitives)

## Interfaces
- `make validate` — repo hygiene + CapD validity.
- `make onboard` / `make dev-up` / `make test` / `make rollout` — lifecycle entry points (scaffold).

## Truth hierarchy
- Integration target: `SocioProphet/prophet-platform`
- Workspace governance: `SocioProphet/sociosphere`
- Protocol contracts: `SocioProphet/tritrpc`
- Storage/graph standards: `SocioProphet/socioprophet-standards-storage`
- Ontology: `SocioProphet/ontogenesis`

## License
MIT (see `LICENSE`).
