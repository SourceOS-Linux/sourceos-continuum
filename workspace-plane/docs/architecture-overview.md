# Open Workspace Plane v0 — Architecture Overview

This export package freezes the first hard edges of the platform so implementation can proceed without architectural drift.

## Design objective

Build an open, replayable, policy-aware workspace plane that can:

- run locally on rootless Podman,
- attach to or materialize into Kubernetes,
- preserve Dev Container ergonomics for IDEs,
- accept Compose as an authoring model without pretending Compose and Kubernetes are identical,
- and expose sync/debug/promotion behaviors through explicit policy and evidence rather than opaque product logic.

## Canonical inputs and outputs

Authoring inputs:

- `devcontainer.json`: developer-facing environment and IDE/runtime expectations.
- `compose.yaml`: application topology and baseline service graph.
- `workspace.agent.yaml`: platform policy, sync, debug, and promotion intent.

Canonical compiled outputs:

- `WorkspaceGraph`: the normalized, platform-neutral source of truth.
- `WorkspaceSync`: the compiled sync contract with authority and conflict policy.
- realized runtime plans for local Podman, Kubernetes, or hybrid split execution.
- evidence records for normalization decisions, warnings, overrides, and runtime IDs.

## Non-negotiable design rules

1. Compose is authoring input, not runtime truth.
2. Every synchronized path belongs to exactly one authority class.
3. Single-writer sync is the default.
4. Caches, stateful data, and secrets are never treated as ordinary source trees.
5. Agent behavior is typed and capability-scoped; there is no omnipotent bot role.
6. Browser and desktop IDEs are clients, not the orchestrator.

## Authority classes

- `local_authoritative`
- `remote_authoritative`
- `derived`
- `immutable_injected`
- `agent_emulated`

## Runtime modes

- `local`: rootless Podman realization, usually with direct bind mounts for source.
- `cluster`: Kubernetes attach or materialize mode.
- `hybrid`: local editor/session plus remote execution surfaces.

## Security baseline

The default cluster profile is `portable-restricted`. That means non-root execution, no privilege escalation, restricted capability posture, and only storage forms that fit the restricted Kubernetes baseline profile. Local mode assumes rootless Podman and regular-user execution.

## Why this is better than copying a product

We are not rebuilding someone else's hosted control plane. We are pinning the platform to open inputs, a compiled internal graph, typed agent roles, and replayable evidence. That lets us implement a reference runtime today without giving away the architecture tomorrow.
