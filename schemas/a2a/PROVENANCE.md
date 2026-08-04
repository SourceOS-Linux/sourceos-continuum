# A2A zero-trust schemas — vendored, pinned by hash

These are the **canonical** MCP-A2A zero-trust contracts, owned by
`SourceOS-Linux/mcp-a2a-zero-trust` (the estate's zero-trust authority repo). They are vendored here
so continuum's `tools/mcp_a2a_grant.py` conforms to the canonical shape and its conformance is
testable in-repo, without a cross-repo build dependency.

Pinned by sha256 (matches the authority's `schemas/index.json` — verified on vendor):

| file | title | sha256 |
|---|---|---|
| `grant.schema.json` | Grant | `sha256:2aac20b5fc9ce2ef72c0609bc1687f2b4b17a2167ef3148fa8ad3c4c1494f0b1` |
| `quorum_proof.schema.json` | QuorumProof | `sha256:d3ceec20d3268c30c1f0fda17f0981654a850ad39073ac5b1ff4aff62a0b2bb2` |
| `attestation_bundle.schema.json` | AttestationBundle | `sha256:485d0ed689cc1b3184a18d555bb3eba75c4110f7087d0c3c6c54c575447a4272` |
| `runtime_evidence_refs.schema.json` | RuntimeEvidenceRefs | (governance/) |

**Do not hand-edit.** If the authority updates a schema, re-vendor and update the pins. `mcp-a2a-zero-trust`
remains the source of truth for the shape; continuum consumes it, it does not fork it.
