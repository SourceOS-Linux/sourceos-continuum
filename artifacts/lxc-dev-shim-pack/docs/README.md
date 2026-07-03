# LXC Dev Shim Pack

Purpose: Gitpod-like workspaces via LXD/LXC without turning local dev into a cluster orchestrator.

Modes:
- Devcontainer-local (privileged) for single-user dev only.
- Genesys gateway to a hardened LXD host for multi-user workspaces.

Integrates via CapDs: porter.devshim.*
