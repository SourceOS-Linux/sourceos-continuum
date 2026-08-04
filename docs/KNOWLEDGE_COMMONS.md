# Reproducible Knowledge Commons — three demonstrated systems, one governed plane

The commons folds the three systems those diagrams show — IBM's **Asset Reuse Manager**, the 3-phase
**MLOps** reproducible pipeline, and the **Semantic API / ontology** — into one content-addressed,
citable, reproducibility-graded plane (`tools/commons.py`). It ingests the estate's own CapDs and
suite workloads, so the compute-mesh / cloud-shell fog work is itself first-class and citable here.

## System → implementation

| Demonstrated system (diagram) | In the commons |
|---|---|
| **Zenodo / reproducible-fusion commons** — versioned, citable, DOI-like, reproducible | `mint_id()` → content-addressed `commons:<domain>/<name>@<version>+<digest>`; every record carries a `cite` string |
| **ARM: Domain → Category → Asset** | every record has `domain` / `category` / `asset_type`; `search()` navigates them |
| **ARM: Recommendation** | `recommend()` ranks by reuse score, within a domain |
| **ARM: Use / Evaluate → Feedback** | `record_use(id, outcome)` raises `reuse.score = evaluations / uses` |
| **MLOps: reproducible pipeline + model registry + monitoring** | the **reproducibility gate**: a record is `reproducible` only if `provenance` carries a `source_digest` **and** an `attestation_ref` or `sbom_digest` — else honestly `declared` |
| **Semantic API: declarative action + ontology constraints + executor** | a record may carry a `semantic_action` (signature + policy/ontology constraints); the suite workloads ingest with their governing policy as the semantic action |

## The reproducibility gate is fail-closed on the *claim*

This is the point that makes it a *reproducible* commons and not just a catalog: you cannot mint a
record that claims `reproducible` unless the provenance actually carries what you would need to
reproduce it. A model deposited with only weights is `declared`; a model deposited with its
`source_digest` + a cosign/SLSA `attestation_ref` is `reproducible`. The portal shows the split
honestly (`N reproducible` of the total), so the dashboard never overstates.

## The estate ingests itself

`estate_commons(root)` deposits every `capd/*.capd.json` and every `mesh/suite-workloads.json` entry.
So `caps.compute.mesh-plane`, `caps.compute.cloudshell-fog`, `caps.dev.devspace-inner-loop`, and the
five app-suite workloads (Noetica, memory-mesh, TurtleTern, Goose Notes, BearBrowser) are all citable
commons records. The cloud-shell fog capability ingests as `reproducible` because its CapD references
the sealed ledger + the mcp-a2a-zero-trust shape authority — provenance enough to reproduce the claim.

See `tools/test_commons.py`. Surfaced read-only at the portal's `/api/commons`.
