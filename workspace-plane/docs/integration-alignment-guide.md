# Integration and Alignment Guide

This guide aligns the owning teams and the handoff surfaces.

## Ownership model

### App team
Owns:
- `devcontainer.json`
- `compose.yaml`
- language profile selection
- repository-specific include/exclude patterns

### Platform team
Owns:
- compiler
- schemas
- runtime adapters
- sync engine
- attach broker
- evidence emitter

### Security team
Owns:
- `portable-restricted` profile
- secret scopes
- policy defaults
- exception review

### IDE team
Owns:
- extension / client integration
- DAP/LSP wiring
- preview and port-forward UX

### Release / operations team
Owns:
- promotion approvals
- manifest patch controls
- runtime cataloging
- evidence retention policy

## Integration checkpoints

1. Schema freeze
2. Example validation in CI
3. Compiler/generator conformance tests
4. Podman adapter conformance
5. Kubernetes adapter conformance
6. Sync conflict simulation
7. IDE attach and debug smoke tests

## Required repository conventions

- a checked-in `.devcontainer/`
- at least one Compose file or an explicit statement that the repo is single-service
- a checked-in `workspace.agent.yaml`
- language-profile declaration in repo metadata or workspace catalog entry
- generated outputs separated from canonical source where possible

## Rollout recommendation

Phase 1:
- local Podman only
- single repo
- single dev service plus one dependency

Phase 2:
- hybrid attach
- Kubernetes materialize mode
- evidence in CI

Phase 3:
- multi-service repos
- catalog publication
- policy exceptions workflow
