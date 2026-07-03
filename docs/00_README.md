# Porter-first PaaS + Agentic GitOps — Master Bundle

Generated: 2026-01-14 14:05:30Z

This bundle contains:
- Canonical design doc (`docs/DESIGN.md`) + appendices
- Ledger of all repos/links mentioned (`ledger/ledger.csv`)
- Hardened Cloud Shell pack (Twin devtools)
- Genesys CLI pack (operator parity, open tooling)
- LXC Dev Shim pack (Gitpod-like workspaces without K8s tenancy)
- Canonical CapD set (Prophet contracts)

Quick start:
1) Read `docs/DESIGN.md`
2) Apply Cloud Shell hardenings from `artifacts/cloudshell-hardened-pack`
3) Install Genesys CLI pack on Genesys
4) Use CapDs as the interface contract for agentic workflows


New in this revision:
- `charts/cloudshell`: Helm chart to stand up Cloud Shell + oauth2-proxy + gateway + spawner/culler.
- `artifacts/cloud-shell-image`: Dockerfile for the ttyd-based shell image.
- CI templates for building/pushing/signing images.
