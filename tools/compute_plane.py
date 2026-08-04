#!/usr/bin/env python3
"""The compute plane — one governed door to any execution substrate.

A user develops on a low-mem box (this M2) and the SAME workload scales out, seamlessly, over
whatever compute the mesh offers: a k8s service, an HPC/SLURM supercomputer, WASM at the edge, a
p2p/hyperswarm mesh, volunteer compute (BOINC / Folding@home / open-HEP-style), or an RLC-style
blockchain compute market. The substrate does not matter — the plane routes by PER-PROJECT /
PER-ACCOUNT policy and live mesh availability, scaling out where it can and where volunteer compute
is offered.

It is GOVERNED, which is the whole point and the differentiator: a sensitive workload NEVER lands
on an untrusted volunteer/p2p/blockchain backend (fail-closed), every placement is sealed into a
tamper-evident receipt, and if no allowed+available backend exists it falls back to local or blocks
— it never silently ships work somewhere the policy forbids. Configured in the portal dashboard,
by project and by account.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

# The mesh of substrates the plane can target. `trust: untrusted` = volunteer / third-party nodes
# (BOINC, Folding@home, p2p mesh, blockchain market) — never given sensitive data. `elasticity` is
# a coarse scale-out capacity rank (1 = a single laptop, 10 = a global volunteer grid).
BACKENDS = {
    "local":          {"kind": "local",        "trust": "trusted",   "elasticity": 1,  "gpu": False},
    "k8s":            {"kind": "container",     "trust": "trusted",   "elasticity": 6,  "gpu": True},
    "hpc-slurm":      {"kind": "hpc",           "trust": "trusted",   "elasticity": 9,  "gpu": True},
    "wasm-edge":      {"kind": "wasm",          "trust": "trusted",   "elasticity": 7,  "gpu": False},
    "p2p-mesh":       {"kind": "hyperswarm",    "trust": "untrusted", "elasticity": 8,  "gpu": False},
    "volunteer-boinc": {"kind": "volunteer",    "trust": "untrusted", "elasticity": 10, "gpu": False},
    "blockchain-rlc": {"kind": "compute-market", "trust": "untrusted", "elasticity": 8, "gpu": True},
    # A vendor connector (Gemini/OpenAI/Claude Files API, or an MCP tool) is external/untrusted —
    # sensitive data does not auto-route here without explicit policy.
    "connector":      {"kind": "connector",     "trust": "untrusted", "elasticity": 9,  "gpu": True},
}

# ATTESTED capabilities each backend can PROVABLY provide. The Needs/Wants firewall: a hard Need may
# only be satisfied by a backend that provably provides it — a soft Want never masquerades as a Need.
BACKEND_CAPS = {
    "local":           {"residency": "local", "no_egress": True},
    "k8s":             {"residency": "cluster", "fips": True},
    "hpc-slurm":       {"residency": "cluster", "fips": True, "tee": True},
    "wasm-edge":       {"residency": "edge", "deterministic": True},
    "p2p-mesh":        {},
    "volunteer-boinc": {},
    "blockchain-rlc":  {},
    "connector":       {"residency": "vendor"},
}


def _needs_met(needs: dict, caps: dict) -> tuple[bool, list]:
    """A backend meets a Need only if it provably provides it. `needs` is {capability: requirement}:
    True = must be present/truthy; a string = must equal; a list = must be one of."""
    unmet = []
    for k, req in needs.items():
        have = caps.get(k)
        ok = (bool(have) if req is True
              else have in req if isinstance(req, (list, tuple, set))
              else have == req)
        if not ok:
            unmet.append(k)
    return (not unmet, unmet)


def _seal(body: dict) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def place(workload: dict, policy: dict, availability: dict) -> dict:
    """Route one workload to a backend under per-project/per-account policy and live availability.

    workload:     {sensitivity: 'sensitive'|'normal', scalable: bool, needs_gpu: bool}
    policy:       {allowed_backends: [...], forbid_untrusted_for_sensitive: bool (default True),
                   prefer: [...], require_attestation: bool}
    availability: {backend_id: capacity_units}  — which backends are up right now, and how big.

    Returns a sealed placement decision. Fail-closed: sensitive work never goes untrusted; no
    allowed+available candidate -> fall back to local if permitted, else block.
    """
    sensitive = workload.get("sensitivity") == "sensitive"
    needs_gpu = bool(workload.get("needs_gpu"))
    scalable = bool(workload.get("scalable"))
    needs = workload.get("needs") or {}  # hard, attested requirements (Needs/Wants firewall)
    allowed = set(policy.get("allowed_backends") or BACKENDS.keys())
    forbid_untrusted = policy.get("forbid_untrusted_for_sensitive", True)

    excluded: dict[str, str] = {}
    candidates = []
    for bid, spec in BACKENDS.items():
        met, unmet = _needs_met(needs, BACKEND_CAPS.get(bid, {})) if needs else (True, [])
        if bid not in allowed:
            excluded[bid] = "not in project policy allowed_backends"
        elif availability.get(bid, 0) <= 0:
            excluded[bid] = "not available in the mesh right now"
        elif needs_gpu and not spec["gpu"]:
            excluded[bid] = "no GPU"
        elif sensitive and forbid_untrusted and spec["trust"] == "untrusted":
            excluded[bid] = "GOVERNANCE: sensitive workload may not run on an untrusted backend"
        elif not met:
            excluded[bid] = f"NEEDS firewall: does not provably provide {', '.join(unmet)}"
        else:
            candidates.append(bid)

    decision = {"plane": "sourceos-continuum.compute_plane.v1",
                "workload": workload, "excluded": excluded,
                "decided_at": datetime.now(timezone.utc).isoformat()}

    if not candidates:
        # fail-closed: nothing allowed+available satisfies the workload's constraints. We do NOT
        # silently degrade (e.g. run GPU work on a non-GPU local box) — we block. `local`, when it
        # is genuinely usable, is always already a candidate, so there is nothing to fall back to.
        decision.update({"backend": None, "placement": "blocked",
                         "reason": "no allowed+available backend satisfies the workload — blocked, not shipped anywhere (fail-closed)"})
        decision["receipt_digest"] = _seal({k: v for k, v in decision.items() if k != "receipt_digest"})
        return decision

    # honour explicit preference order, then scale out where we can (highest elasticity) for
    # scalable work, else keep it cheap/local (lowest elasticity).
    prefer = [b for b in (policy.get("prefer") or []) if b in candidates]
    if prefer:
        chosen = prefer[0]
        why = "project preference"
    elif scalable:
        chosen = max(candidates, key=lambda b: (BACKENDS[b]["elasticity"], availability.get(b, 0)))
        why = ("scale-out: highest available elasticity in the mesh"
               if BACKENDS[chosen]["elasticity"] > 1
               else "mesh had no scale-out capacity available; ran locally")
    else:
        chosen = min(candidates, key=lambda b: BACKENDS[b]["elasticity"])
        why = "kept small: lowest-cost candidate (non-scalable workload)"

    decision.update({
        "backend": chosen,
        "backend_kind": BACKENDS[chosen]["kind"],
        "backend_trust": BACKENDS[chosen]["trust"],
        "placement": "scheduled",
        "reason": why,
        "alternatives": sorted(b for b in candidates if b != chosen),
        "attestation_required": bool(policy.get("require_attestation")) or BACKENDS[chosen]["trust"] == "untrusted",
    })
    decision["receipt_digest"] = _seal({k: v for k, v in decision.items() if k != "receipt_digest"})
    return decision


def backends_view(availability: dict | None = None) -> dict:
    """The dashboard view of the mesh: every substrate, its trust/elasticity, and live availability."""
    availability = availability or {}
    return {"backends": [
        {"id": bid, **spec, "available": availability.get(bid, 0)} for bid, spec in BACKENDS.items()]}


if __name__ == "__main__":
    # demo: a sensitive, scalable, GPU workload against a full mesh — untrusted backends are refused.
    demo = place({"sensitivity": "sensitive", "scalable": True, "needs_gpu": True},
                 {"forbid_untrusted_for_sensitive": True},
                 {b: 100 for b in BACKENDS})
    print(json.dumps(demo, indent=2, sort_keys=True))
