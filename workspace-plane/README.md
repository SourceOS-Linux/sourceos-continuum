# Open Workspace Plane v0 Export Package

This package integrates the frozen v0 decisions into a concrete handoff bundle for implementation, review, and alignment.

## What is inside

- human-readable architecture and integration docs
- JSON Schemas for:
  - `workspace.agent.yaml`
  - `WorkspaceGraph`
  - `WorkspaceSync`
  - `WorkspaceEvidence`
- machine-readable profiles:
  - Compose support profile
  - `portable-restricted` security profile
  - language defaults for Node, Python, Go, and Java
- validated examples:
  - Node + Postgres
  - Python/FastAPI + Postgres
- an implementation-facing adapter contract
- an alignment matrix
- file checksums and a validation report

## Package intent

Use this bundle to:
- align platform, IDE, security, and app teams
- begin implementing the compiler and adapters
- keep runtime semantics honest when crossing Compose, Dev Containers, and Kubernetes
- validate examples before writing the first adapter

## Recommended implementation order

1. schema loading and validation
2. authoring input parser
3. `WorkspaceGraph` compiler
4. `WorkspaceSync` compiler
5. Podman local adapter
6. Kubernetes attach/materialize adapter
7. sync engine
8. attach broker
9. evidence emitter

## Key package files

- `docs/architecture-overview.md`
- `docs/translation-contract.md`
- `docs/integration-alignment-guide.md`
- `schemas/workspace.agent.schema.json`
- `schemas/workspace-graph.schema.json`
- `schemas/workspace-sync.schema.json`
- `profiles/compose-support-profile.v0.yaml`
- `profiles/security-profile-portable-restricted.yaml`
- `matrices/integration-alignment-matrix.csv`
- `manifest/validation-report.json`
