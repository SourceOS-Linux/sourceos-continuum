# Continuum Scope — Owned and Non-Owned Surfaces

`sourceos-continuum` is the OS-layer local-first PaaS control plane. It owns deployment/runtime
orchestration on the workstation and the local→cluster promotion path. It does not own source,
workspace, runtime-release, or scale-up primitives — those are consumed from their canonical repos.

## Owned
- Local PaaS control plane (porter-shim) over kind/k3s.
- Deploy / run / preview-test / promote / rollback (PR-driven GitOps).
- Lifecycle orchestration across onboard, develop, cloud-native test, rollout.
- CapD interface contracts for agentic deploy/rollout.
- Per-action evidence bundles (signed images, provenance).

## Non-owned (consumed)
| Concern | Canonical owner |
| --- | --- |
| Source-control authority | Gitea Sovereign |
| Workspace manifest + source→workspace binding | `SocioProphet/sociosphere` |
| Governed runtime tuning + release (RuntimeAssets, SBOM, signing) | `SocioProphet/lattice-forge` |
| Cluster scale-up primitives (kubespray/krew/Cluster-API) | `SocioProphet/hyperswarm-agent-composable-cluster-scaleup` |
| Operator CLI surface | `SourceOS-Linux/sourceos-devtools` (`sourceosctl`) |
| Canonical schemas | `SourceOS-Linux/sourceos-spec` |
| Model weights, datasets, training | Holmes labs + `prophet-platform` |

## Boundary rule
When a concern above appears in-scope, bind to the canonical owner rather than reimplement it.
Provisioning, signing, and workspace binding are consumed, never forked.
