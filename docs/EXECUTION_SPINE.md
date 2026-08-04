# The execution spine — from a low-mem box to anywhere, governed

This is what makes the compute plane a *platform* and not a planner. One command from a low-mem box
places a workload, mints and verifies a zero-trust Grant, and **actually dispatches** it — to
whatever substrate the mesh offers — sealing a receipt. Fail-closed at every step.

```
sourceosctl run --command "python train.py" --gpu --sensitivity sensitive
```
```
ran on: hpc-slurm  (trusted)  via grant grant_caed7e42fff04099
dispatch: hpc-slurm (applied=False)
sealed receipt: sha256:3d504bec…
```

## The flow (`tools/executor.py` · `tools/sourceosctl.py`)

```
mesh_telemetry           compute_plane        mcp_a2a_grant           mcp_a2a_grant        executor
  (live avail.)   ──►   place() [Decide]  ──►  issue_grant() [Grant] ─► verify_grant() ─►  dispatch ─► sealed receipt
   heartbeats            per-policy,            attest→decide→grant      [Policy Gate]      per-backend adapter
   TTL fail-closed       per-availability       session-bound, signed    fail-closed         + receipt
```

1. **Telemetry** — the live mesh (`sourceosctl mesh`); stale nodes count zero.
2. **Decide** — `place()` picks a backend under per-project/per-account policy. A sensitive workload
   never lands on an untrusted (volunteer/p2p/blockchain) backend; if nothing compliant is live it
   **blocks**, it doesn't degrade.
3. **Grant** — `issue_grant()` attests, then mints a canonical session-bound Grant (see
   `docs/CLOUDSHELL_FOG.md` and the vendored `schemas/a2a/`).
4. **Gate** — `verify_grant()` re-checks the Grant at the node: signature, session, expiry,
   attestation, effect. No valid Grant → **`DispatchRefused`**, nothing runs.
5. **Dispatch** — a per-backend adapter runs it:
   - **local** — a real subprocess (`--apply`).
   - **k8s** — a real, Grant-labelled `batch/v1` Job manifest (applied via `kubectl` when a cluster
     is reachable, else emitted).
   - **hpc-slurm · wasm-edge · p2p-mesh · volunteer-boinc · blockchain-rlc** — the substrate-specific
     descriptor to hand that scheduler over a Grant-bound channel.
6. **Receipt** — every dispatch is hash-sealed.

## CLI

| command | does |
|---|---|
| `sourceosctl mesh` | what's live in the mesh right now |
| `sourceosctl place --gpu --sensitivity sensitive` | where would this land? (dry, no dispatch) |
| `sourceosctl run … [--apply]` | place → grant → verify → dispatch; `--apply` actually executes |
| `sourceosctl commons` | the reproducible knowledge commons |

**Production vs dev.** In production the Grant is signed by the Key Authority (HSM/KMS) and the
`AttestationBundle` comes from the node's TPM/TEE + cosign. Without `SOURCEOS_SIGNING_KEY` set, the
CLI runs in **DEV MODE** — it synthesizes a dev attestation + HMAC key and says so loudly on stderr.

See `tools/test_executor.py` (adapters + fail-closed + full spine) and `tools/test_sourceosctl.py`.
