#!/usr/bin/env python3
"""Governed autonomous control loop — detect ≠ heal, until now.

Most platforms detect a problem and page a human. This closes the loop: it senses conditions, and
for each one it may act on, it runs the SAME governed spine a developer runs
(admission → place → grant → verify → execute), sealing every action.

Three properties make it safe enough to run unattended:

  * It never acts ungoverned — every remediation goes through the grant + quota path. No valid
    Grant, or over quota, means nothing runs; the loop records that and carries on.
  * It decides a persistent condition ONCE per cooldown — no remediation storms (the same
    escalation-suppression discipline the estate uses elsewhere: decide a standing condition once,
    not every tick).
  * One bad condition never kills the loop — a remediation that blocks, is denied, or even raises is
    caught, recorded, and the loop moves to the next condition.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone

import executor as ex


def _seal(body: dict) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ControlLoop:
    """Senses conditions and remediates them through the governed spine, once per cooldown.

    sense() -> list[condition]; each condition is a dict with a stable "key".
    to_workload(condition) -> (workload, policy, cost) for the remediation.
    spine_kwargs: the run_spine keyword args held constant across ticks — registry, binding,
      capability, attestation, constraints, signer, verifier, and optionally admission / apply.
    """

    def __init__(self, *, sense, to_workload, spine_kwargs: dict, cooldown_s: float = 300.0,
                 clock=time.time):
        self._sense = sense
        self._to_workload = to_workload
        self._spine = spine_kwargs
        self._cooldown = float(cooldown_s)
        self._clock = clock
        self._acted: dict[str, float] = {}
        self._ledger: list[dict] = []

    def tick(self) -> list[dict]:
        """One sense→act pass. Returns the per-condition outcomes for this tick."""
        now = self._clock()
        out = []
        for cond in self._sense():
            key = cond.get("key")
            last = self._acted.get(key)
            if last is not None and now - last < self._cooldown:
                out.append({"key": key, "outcome": "suppressed",
                            "reason": "within cooldown", "at": _iso(now)})
                continue
            try:
                workload, policy, cost = self._to_workload(cond)
                result = ex.run_spine(workload, policy, cost=cost, **self._spine)
                status = result.get("status", "unknown")
            except Exception as exc:  # a bad remediation must not kill the loop
                result, status = {}, "error"
                err = str(exc)
            else:
                err = None
            self._acted[key] = now
            rec = {"key": key, "outcome": status, "backend": result.get("backend"),
                   "grant_id": result.get("grant_id"), "condition": cond, "at": _iso(now)}
            if err is not None:
                rec["error"] = err
            rec["receipt_digest"] = _seal({k: v for k, v in rec.items() if k != "receipt_digest"})
            self._ledger.append(rec)
            out.append(rec)
        return out

    def run(self, *, max_ticks: int, interval_s: float = 0.0) -> list[dict]:
        for _ in range(max_ticks):
            self.tick()
            if interval_s:
                time.sleep(interval_s)
        return self._ledger

    def ledger(self) -> list[dict]:
        return list(self._ledger)


if __name__ == "__main__":
    # demo: a sensor that flags a backend as unhealthy; the loop remediates via a probe workload,
    # then suppresses the same condition on the next tick (cooldown).
    import mcp_a2a_grant as g
    import mesh_telemetry as mt

    key = b"loop-demo-key"
    reg = mt.MeshRegistry()
    reg.heartbeat("k8s-a", "k8s", 8)
    aum = "sha256:" + "ab" * 32

    loop = ControlLoop(
        sense=lambda: [{"key": "unhealthy:paymentsvc", "target": "paymentsvc"}],
        to_workload=lambda c: ({"name": "probe", "sensitivity": "normal", "scalable": False,
                                "needs_gpu": False, "effect": "exec", "command": "echo probing"},
                               {}, 1.0),
        spine_kwargs=dict(
            registry=reg,
            binding={"spiffe_id": "spiffe://sourceos/agent/healer", "aum_digest": aum, "session_id": "sess_loop01"},
            capability={"kind": "mcp_tool", "capability_ref": "capd://caps.compute.mesh-plane",
                        "capability_digest": "sha256:" + "cd" * 32, "effect": "exec"},
            attestation=g.attestation_bundle(spiffe_id="spiffe://sourceos/agent/healer", aum_digest=aum,
                                             tpm_valid=True, cosign_valid=True),
            constraints={"ops_allow": ["exec.run"]},
            signer=g.hmac_signer(key), verifier=g.hmac_verifier(key)),
        cooldown_s=300.0)
    print("tick 1:", [(r["key"], r["outcome"]) for r in loop.tick()])
    print("tick 2:", [(r["key"], r["outcome"]) for r in loop.tick()])
