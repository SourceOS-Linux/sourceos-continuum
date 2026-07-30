# The SourceOS Continuum — Developer Lifecycle

The continuum is one seamless path with four stages. The same workload flows through all four
without re-plumbing, from n=1 local to a composable cluster.

## 1. Onboard
Bring a developer from zero to a working local platform in one move.
- Local sovereign forge up (Gitea Sovereign) and reachable.
- Local cluster up (kind/k3s).
- Operator surface installed: `sourceos-devtools` / `sourceosctl`.
- Identity + local governance bound.

Targets: `SourceOS-Linux/sourceos-devtools`, Gitea Sovereign.

## 2. Develop
Work against local source and run it locally.
- A repo on the workstation is imported into Gitea (the local→Gitea seam).
- `sociosphere` binds the source into a governed workspace (canonical manifest + lock).
- The local PaaS control plane (porter-shim) deploys and runs it over kind/k3s.

Targets: Gitea Sovereign, `SocioProphet/sociosphere`, porter control-plane primitives.

## 3. Cloud-native test
Prove the workload the way it will run in production, still locally.
- PR-driven GitOps: an ephemeral preview environment per change.
- Governed RuntimeAssets (models/images) pulled from `lattice-forge` — signed, SBOM, provenance.
- Evidence bundle emitted per run.

Targets: `SocioProphet/lattice-forge`, GitOps checks.

## 4. Rollout
Promote the proven workload up and out.
- Promotion gate: promotion requires an `APPROVE` review verdict from the review gate consumed
  from `prophet-platform` (this repo's CapD `links.integration_target`; pin-not-vendor).
  `tools/promotion_gate.py` verifies the verdict's seal and, fail-closed, blocks on anything but
  APPROVE. Every decision — allow or block — is emitted to the per-action evidence bundle under
  `artifacts/gate-decisions/` (policy `evidence_emitting`).
- Promote local → composable cluster via the pinned scale-up wrapper
  (`caps.infra.cluster-scaleup.hyperswarm`).
- Signed images, drain/rollback gates, promotion evidence.

Targets: `SocioProphet/hyperswarm-agent-composable-cluster-scaleup`.

## Model path (parallel track)
Out-of-the-box models from the Holmes labs (embedding / time-series / translation / video / ocr)
are tuned by `prophet-platform` inside `lattice-forge` into governed, signed RuntimeAssets, then
delivered on-device by `sourceos-model-carry` and deployed through stages 3–4 above.
