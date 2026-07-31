# Translation Contract v0

## Purpose

Define a deterministic boundary between Compose authoring, Dev Container authoring, and runtime realization.

## Pipeline

1. **Ingest**
   - Read `devcontainer.json`, one or more Compose files, and `workspace.agent.yaml`.

2. **Normalize**
   - Compile inputs into `WorkspaceGraph`.
   - Resolve service IDs, mounts, endpoints, role bindings, and policies.

3. **Classify**
   - Tag every field as one of:
     - Class A — supported and translated cleanly
     - Class B — supported locally, caution remotely
     - Class C — agent-emulated
     - Class D — rejected in v0

4. **Realize**
   - Emit one runtime plan:
     - local Podman plan
     - Kubernetes attach/materialize plan
     - hybrid split plan

5. **Attach**
   - Broker editor access through standard protocols such as DAP and LSP.

6. **Evidence**
   - Emit a replayable decision log with warnings, overrides, and runtime identifiers.

## Class map

### Class A — Supported and translated cleanly

Cleanly supported baseline fields:
- services
- image
- basic build context / dockerfile
- command
- entrypoint
- environment
- ports
- basic named volumes
- basic named networks
- simple configs
- restart in the supported subset
- depends_on as a startup hint only

### Class B — Supported locally, caution remotely

These compile with explicit parity-loss diagnostics when targeting Kubernetes:
- richer build options
- host-path-heavy bind patterns
- extra_hosts / custom DNS / host shortcuts
- device exposure
- advanced aliasing
- conditional dependency semantics

### Class C — Agent-emulated

These are preserved by our agent plane or Dev Container contract, not by Kubernetes manifests:
- hot sync
- IDE lifecycle hooks
- dev bootstrap helpers
- debug attach surfaces
- workspace memory/indexing
- approval and promotion gates

### Class D — Rejected in v0

- privileged-by-default workloads
- unsafe host mutation
- opaque runtime-specific daemon extensions
- fields that would produce materially misleading Kubernetes semantics

## Diagnostics

- `E_UNSUPPORTED_FIELD`
- `E_SECURITY_POLICY`
- `W_PARITY_LOSS`
- `W_AGENT_EMULATION`
- `I_LOCAL_ONLY`

## Realization boundary

Kompose may be used inside the implementation as a bootstrap/reference converter for the simple subset, but it does not own the platform contract. The platform contract is `WorkspaceGraph`.
