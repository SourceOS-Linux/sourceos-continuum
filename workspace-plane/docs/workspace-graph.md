# WorkspaceGraph v0alpha1

`WorkspaceGraph` is the canonical, platform-neutral representation of the workspace plane.

## Object families

- `metadata`: provenance and source inputs
- `compiler`: unsupported-field posture and profile
- `sources`: logical content roots
- `storages`: backing media abstractions
- `mounts`: edges from storages into services
- `services`: dev/app/dependency/agent workloads
- `endpoints`: application, debug, preview, or forwarding surfaces
- `artifacts`: OCI images and non-image outputs
- `roles`: human and agent capabilities
- `policies`: security, network, secret, git, and promotion constraints

## Modeling rules

- Sources are not mounts.
- Storages are not sources.
- Mounts are the only thing that binds a storage to a service path.
- The same storage can be mounted into multiple services.
- Authority belongs to the storage or source classification, not to an ad hoc file watcher.
- Service kind and agent role are separate concerns.

## Required invariants

- `apiVersion` must be `workspaces.dev/v0alpha1`.
- `kind` must be `WorkspaceGraph`.
- `metadata.workspaceId` is stable for a compiled session root.
- every mount references an existing storage and service.
- every endpoint references an existing service.
- every artifact identifies the producing service.
- every path class and authority class must be explicit.
