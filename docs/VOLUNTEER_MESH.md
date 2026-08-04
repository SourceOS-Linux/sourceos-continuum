# The volunteer mesh — superset design & SOTA integration

North star: during COVID, Folding@home crossed **top-5 supercomputer** scale on ~400k volunteers.
The binding constraint was never silicon — it was **participation and trust**. This is the design
for a governed, agent-first volunteer-compute mesh that plugs into the continuum compute plane,
distilled from the corpus (Dual-Orchestration Model, Agent-First Node, Urbit+CoreOS, BOINC OOBE,
CluBORun; plus the 2019 State-of-VC, CMS@home DataBridge, SETI@home motivation study, Pando, the
Radicle/Wikipedia governance essay, Science United UX goals, and the Needs/Wants firewall).

## Two planes, one contract

- **Governed plane** — the continuum compute plane (`compute_plane` + `mcp_a2a_grant` + `admission`
  + `executor`): authoritative placement, zero-trust grants, quotas, sealed receipts.
- **Volunteer mesh** — opportunistic, untrusted, churny capacity (BOINC/Folding@home-style),
  speaking the **same Work Unit** contract so semantics never drift.

They interoperate: the governed plane publishes Work Units to the mesh and collects **verified**
results back.

## The seven moves (why the mesh is more elegant than a scheduler)

1. **Participation is the system, the scheduler is secondary.** Compute is abundant; active
   volunteers are scarce (2019: ~100k PCs ≈ a top-10 super, against 2B PCs — conversion is a
   rounding error). Center the design on the human on-ramp and retention:
   - **Intent-based enrollment** — the volunteer states *values/topics*, the orchestrator
     auto-places cycles. They never pick a Work Unit or a tier. (Science United; = our agent-first
     model.) Jargon-free ("computer"/"job", never FLOPS/GPU); **3 presets** green/standard/max
     mapping to battery/thermal/CPU quotas; SSO one-click / join-by-URL.
   - **Close the Enhancement loop** — the *only* empirically significant motivator (SETI@home study,
     β=0.18) is seeing your contribution produce a visible real-world outcome. Wire the
     evidence/commons provenance so a volunteer sees "your WUs → this result / this science news."
   - **Cooperative teams + personal progress by default; competition opt-in** — teams measurably
     slow tenure-decay; leaderboards repel the mission-motivated majority. Stated≠revealed
     motivation — instrument behavior, don't trust surveys.

2. **Pull/lease streaming dispatch, not push WU-assignment.** (Pando.) Workers *pull* work when
   idle → automatic backpressure and heterogeneity handling with **no speed estimation** (lazy +
   adaptive; a bag of old devices ≈ one modern laptop). A **StreamLender + Limiter** primitive
   bounds in-flight leases per worker, admits workers dynamically, re-lends a crashed worker's
   borrowed unit **by index** (work-stealing), and re-merges in order for determinism. Dispatch is
   **conservative** (one copy to one device) to maximize *distinct* WUs in flight; **redundant
   quorum is an optional overlay** keyed on (result-stakes × worker-reputation), not an always-on
   byzantine tax.

3. **Split control plane from data plane; "done" = data durably landed.** (CMS@home DataBridge +
   Pando.) For data-heavy work the limiter is **output egress**, not CPU. Tiny coordination over
   WebRTC/WebSocket; bulk over P2P (WebTorrent/IPFS) for input and a **signed-URL nearest-endpoint
   DataBridge** for output (volunteer PUTs to the closest bucket via a short-lived signed URL —
   never sees project creds — then async eventually-consistent replication migrates it home).
   Transfers are **resumable** (interruption ≠ restart) with a **durability barrier** (a WU is
   complete only after its output is verify-downloaded; resubmit on partial). **Data gravity + RTT
   are first-class placement signals** — this is what makes the fog tier real.

4. **Trust by earned reputation + soft security + cooperative games — not default byzantine crypto.**
   (Wikipedia/Radicle.) Sybil resistance from **accreted verified-WU history ("human proof-of-work")**
   — sticky pseudonyms, no KYC, no stake. **Match PROOF_MODE to each tier's real failure model**:
   crash-stop + heartbeat-timeout for volunteers, escalate to spot-check → quorum → TEE → ZK only
   when results are load-bearing or reputation is thin. Overlay **soft security** (bots auto-reject
   pattern-anomalous results, sampled spot-audits, reputation-gated human adjudication) and
   **iteration-over-finality** (provisional-accept, upgrade to final as corroboration accrues).
   **Credits are additive-only, never slashable** — loss aversion repels, and crypto rewards were
   empirically marginal (~$3M total market cap across all VC coins). The social lever (teams,
   prizes) beat the monetary one.

5. **Every signal is an instrument; every policy an executable, logged gate.** (Needs/Wants
   firewall.) Reputation, credit, result-confidence, device-trust, placement-fit each ship as
   `{value, uncertainty, provenance, validity, refusal_threshold}`. Below threshold the mesh
   **refuses and logs** rather than silently defaulting. "If you can't say when a score should be
   refused, you're guessing loudly."

6. **A Needs/Wants firewall for placement.** Separate hard **Needs** (TEE, FIPS, data-residency,
   latency SLO, no-egress — must be *attested*) from soft **Wants** (prefer-GPU, nearby, cheap —
   best-effort). A want-grade match may **never** masquerade as a need-grade guarantee. This is the
   crisp primitive that makes governed placement real and guards against semantic laundering.
   **→ shipped:** `compute_plane.place(..., needs=...)` (see below).

7. **Gate the incentive loop against Goodhart; scope reputation to domains.** Any score that feeds
   auto-dispatch or payout is an optimization loop that *will* be gamed — gate the signals entering
   automation; forbid high-stakes grants driven by gameable proxies. Reputation is
   **domain-scoped**: earned rendering-WU trust does not transfer to medical-WU verification without
   recalibration (a per-`(worker, domain)` capability card — our purpose-bound-consent / grant shape
   applied to workers).

## Implementation status in continuum

| Move | Mechanism | Status |
|---|---|---|
| Result verification (move 4) | `work_unit.py` — redundant quorum + spot-check + reputation, fail-closed | ✅ |
| **Needs/Wants firewall (move 6)** | `compute_plane.place(needs=...)` + `BACKEND_CAPS` — a backend must *provably* provide every Need | ✅ (this change) |
| Governed dispatch of a WU | `executor` adapters (local/k8s/slurm/wasm/descriptor/connector) | ✅ |
| Identity/attestation (move 4) | `mcp_a2a_grant` (SPIFFE binding + TPM/cosign attestation) | ✅ |
| Quotas/admission | `admission.py` (additive; make credits additive-only per move 4) | ✅ |
| Pull/lease streaming dispatch (move 2) | StreamLender + Limiter; heartbeat liveness (`mesh_telemetry` is the base) | ○ next |
| Split data plane + DataBridge (move 3) | signed-URL nearest-endpoint upload + async replication + verify-download barrier | ○ next |
| Instrumented signals + refusal (move 5) | wrap reputation/confidence as `{value,uncertainty,provenance,validity,refusal}` | ○ next |
| Domain-scoped reputation (move 7) | per-`(worker,domain)` card on `work_unit.Reputation` | ○ next |
| Participation on-ramp (move 1) | intent enrollment, 3 presets, teams, Enhancement loop in the portal | ○ next |

## The elegant default

Crash-stop + heartbeat + earned reputation + soft security handles the common case cheaply;
redundant-quorum/TEE/ZK are overlays paid only when `stakes × (1 − reputation)` warrants it; the
Needs/Wants firewall keeps hard requirements honest; credits are additive; participation and the
visible-outcome loop are the primary system. That is the superset — human-first, instrument-governed,
and strictly lighter than always-on byzantine trust.
