# Sovereign Agentic Cloud-Shell — fog deployment, made first-class

This witnesses the cloud-shell fog spec (*Zero-Trust MCP-A2A + TriRPC transport + HyperSwarm
placement*) against its implementation in this repo. Every box in the diagram points at real code —
no box is decoration.

## Planes → implementation

| Spec plane / box | Implementation | Status |
|---|---|---|
| **Capability Build / Packaging** — OCI image (digest+SBOM+sig), publish CapD + tool schema | estate build + `attest.py` (SLSA/in-toto/DSSE), `capd/*.capd.json` | estate |
| **Capability Registry** (CapDs + MCP tool catalog) | `capd/` + `tools/mcp_ops_server.py` | ✅ |
| **Control Plane Agent** (placement + quotas + admission; session lifecycle) | `tools/compute_plane.py` — `place()` is the *Decide* | ✅ |
| **HyperSwarm Mesh** (discovery + gossip + rendezvous) / *find candidate nodes* | `tools/mesh_telemetry.py` — live liveness registry | ✅ |
| **Supply-chain Gate** (OCI digest + SBOM + signatures) | `prophet-platform/tools/advisory_check.py` + `attest.py` | estate |
| **MCP-A2A Policy Authority** (Attest → Decide → Grant, +QuorumProof) | `tools/mcp_a2a_grant.py` — `issue_grant()` | ✅ |
| **Key Authority** (HSM/KMS — sign grants / derive session keys) | `hmac_signer` interface in `mcp_a2a_grant.py` (swap in HSM/ed25519) | ✅ iface |
| **fog-node MCP-A2A Policy Gate** (verify Grant + bind to session + streams) | `tools/mcp_a2a_grant.py` — `verify_grant()` | ✅ |
| **Shell Runtime Container/Pod** (PTY + FS sandbox) — enforce constraints | gate returns per-op authorization + redactions; runtime sandbox = estate | ✅ policy |
| **Attestation Verifier / Node Attestor** (TPM/TEE + cosign) | attestation inputs consumed fail-closed by `issue_grant` | ✅ iface |
| **Observability Sink** (OTEL) | estate OTel collector (`prophet-platform/deploy/superiority-march/observability`) | estate |
| **Ledger / Audit** (append-only evidence) | sealed receipts → `artifacts/{gate-decisions,mcp-receipts}` | ✅ |
| **Browser Terminal UI / Console API** | portal (read-only view) `tools/portal_server.py`; mutations via MCP surface | ✅ view |

## The numbered flow (0–11)

`0` login/refresh (IdP) → `1` start session (UI) → `2` SessionRequest {capability, agent} →
`3` resolve CapD + tool schemas (registry) → `4` verify artifact digest/SBOM/sig (supply-chain gate) →
`5` **find candidate nodes** (HyperSwarm / `mesh_telemetry`) → `6` route to selected node →
`7` **policy eval** user+node+capability (`place()` Decide) → `8` **issue Grant** session-bound,
+QuorumProof when required (`issue_grant`) → `9` TriRPC attach over the Grant-bound channel →
`10` **authorize attach** (`verify_grant`) → `11` **allow PTY/FS ops**, enforce constraints
(`verify_grant(requested_op=...)`).

## Why this is zero-trust, not just RBAC

A placement decision is **not** permission to run. The node re-verifies the Grant itself — signature,
session binding, expiry, attestation, and that the *specific* op is inside the granted constraints —
on attach **and on every PTY/FS op**. A missing, stale, tampered, or over-reaching Grant is denied,
fail-closed. Sensitive workloads never even get a Grant for an untrusted (volunteer/p2p/blockchain)
node — the Decide stage refuses them first (`compute_plane`), and the Authority refuses to mint a
Grant against a blocked or unattested decision.

See `tools/test_mcp_a2a_grant.py` (Authority + Gate) and `tools/test_compute_plane.py` (Decide).

## Shape conformance — we consume the canonical spec, we do not fork it

The Grant, AttestationBundle, and QuorumProof that `tools/mcp_a2a_grant.py` emits/consumes are the
**canonical** shapes owned by `SourceOS-Linux/mcp-a2a-zero-trust` (the estate's zero-trust authority
repo — "owns the zero-trust authority model … grant request, grant decision, and grant ledger
contracts"). Those schemas are vendored here under `schemas/a2a/`, **hash-pinned** to the authority's
`schemas/index.json` (see `schemas/a2a/PROVENANCE.md`), and `test_mcp_a2a_grant.py` validates every
emitted Grant / QuorumProof / AttestationBundle against them. So `issue_grant()` produces a `Grant`
with the canonical `binding` / `capability` / `constraints` / `policy_hash` / `quorum_proof` /
`evidence_refs` / `sig{issuer,sig}`, and `verify_grant()` returns a canonical `tool_grant.validate`
result `{valid, expired, revoked, reason}` — identical to `examples/grant.example.json` and
`examples/tool_grant_check.example.json` in the authority repo. If the authority updates a schema,
re-vendor and re-pin; the authority stays the source of truth for the shape.
