# Porter Shim (Genesys/Inception/Twin)

Generated: 2026-01-14 14:11:00Z

Purpose:
- Provide a stable **capability backend** for Prophet CapDs.
- Translate high-level verbs into:
  - **Git PRs** (preferred) against the GitOps repo(s)
  - calls to **Porter API** for app lifecycle metadata (as a PaaS interface)
  - calls to **Argo CD API** only for reconciliation observability (never as the source of truth)

Key design rule:
- The shim does *not* apply to clusters directly. It writes to Git and relies on Argo to reconcile.
- Any imperative action must be treated as an exception and produce evidence.

Where it runs:
- **Genesys**: primary location (governance + credentials + PR keys)
- **Inception**: may call the shim from CI to open PRs containing signed digests and SBOM refs
- **Twin**: should not host the shim as an authority, but can call it for user actions via OIDC

Interfaces:
- REST API (OpenAPI provided)
- Emits: PR URLs + evidence bundles
