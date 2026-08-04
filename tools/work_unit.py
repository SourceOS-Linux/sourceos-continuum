#!/usr/bin/env python3
"""Work Unit + verification plane — how an UNTRUSTED volunteer mesh becomes trustworthy.

A Grant proves WHO ran a Work Unit; it cannot prove the RESULT is correct. On a Folding@home-scale
grid (hundreds of thousands of anonymous volunteers) some workers are broken, slow, or malicious —
they return garbage or lie. Volunteer computing solves this by VERIFYING results, and that is the
piece our compute plane was missing.

This implements the Dual-Orchestration `PROOF_MODE` verification, fail-closed:

  * redundant quorum — run the same Work Unit on N independent workers; accept only a result a
    quorum agrees on (identical output digest). No quorum -> rejected, never accepted unverified.
  * spot-check — embed a canary sub-task with a known answer; a worker that gets the canary wrong is
    rejected and loses reputation (for stochastic tasks where bit-exact quorum doesn't apply).
  * a reliable backend (a cluster, per CluBORun) can stand in as a reference verifier.

Reputation is a per-worker moving record of verified successes; it weights future allocation and is
how the mesh routes around bad actors without trusting any single node.

Dispatch of Work Units to workers is pull/lease (see `lease_scheduler.py`): verification here is the
optional overlay layered on top, keyed on stakes x reputation.
"""
from __future__ import annotations

import hashlib
import json

# Default replication (independent runs) required to VERIFY a result, per proof mode.
REPLICATION = {"redundant": 3, "spot_check": 1, "tee": 1, "zk": 1, "optimistic": 1}


def _canon(obj) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def digest(output) -> str:
    """Content digest of a worker's output — what quorum agreement is computed over."""
    return _canon(output)


def mint_work_unit(*, task: str, inputs: list | None = None, params: dict | None = None,
                   proof_mode: str = "redundant", sandbox: str = "wasm", ttl_s: int = 60,
                   replication: int | None = None) -> dict:
    """A content-addressed Work Unit. `wu_id` is derived from the task definition, so the same work
    has the same id (dedup + reproducibility)."""
    body = {"task": task, "inputs": inputs or [], "params": params or {},
            "proof_mode": proof_mode, "sandbox": sandbox}
    return {"wu_id": "wu:" + digest(body).split(":", 1)[1][:16],
            **body, "ttl_s": ttl_s,
            "replication": replication or REPLICATION.get(proof_mode, 1)}


class Verifier:
    """Fail-closed result verification for untrusted workers."""

    def redundant_quorum(self, wu: dict, results: list, *, threshold: int | None = None) -> dict:
        """results: [{worker, output}] from independent runs. Accept the output a majority agrees on
        (by digest). threshold defaults to a strict majority of the WU's replication factor."""
        n = wu.get("replication", len(results))
        threshold = threshold or (n // 2 + 1)
        groups: dict[str, list] = {}
        for r in results:
            groups.setdefault(digest(r["output"]), []).append(r["worker"])
        if not groups:
            return {"verified": False, "accepted_digest": None, "reason": "no results", "threshold": threshold}
        winner, agree = max(groups.items(), key=lambda kv: len(kv[1]))
        verified = len(agree) >= threshold
        disagree = [w for d, ws in groups.items() if d != winner for w in ws]
        return {"verified": verified,
                "accepted_digest": winner if verified else None,
                "workers_agree": sorted(agree),
                "workers_disagree": sorted(disagree),
                "threshold": threshold, "received": len(results),
                "reason": ("quorum reached" if verified
                           else f"no quorum: best {len(agree)}/{threshold} agreed")}

    def spot_check(self, result: dict, expected_output) -> dict:
        """A canary with a known answer — for stochastic tasks. Wrong canary -> rejected."""
        ok = digest(result.get("output")) == digest(expected_output)
        return {"verified": ok, "worker": result.get("worker"),
                "reason": "canary matched" if ok else "canary FAILED — worker output rejected"}


class Reputation:
    """Per-worker verified-success record; weights allocation and routes around bad actors."""

    def __init__(self):
        self._rep: dict[str, dict] = {}

    def _r(self, worker: str) -> dict:
        return self._rep.setdefault(worker, {"verified": 0, "total": 0})

    def record(self, *, agreed: list, disagreed: list) -> None:
        for w in agreed:
            r = self._r(w)
            r["verified"] += 1
            r["total"] += 1
        for w in disagreed:
            self._r(w)["total"] += 1

    def score(self, worker: str) -> float:
        r = self._r(worker)
        return round(r["verified"] / r["total"], 3) if r["total"] else 0.0

    def trusted(self, worker: str, *, minimum: float = 0.8, min_samples: int = 3) -> bool:
        r = self._r(worker)
        return r["total"] >= min_samples and self.score(worker) >= minimum


def verify_and_score(wu: dict, results: list, reputation: Reputation | None = None,
                     verifier: Verifier | None = None) -> dict:
    """Convenience: quorum-verify a WU's results and update reputation. Returns the verdict."""
    verifier = verifier or Verifier()
    verdict = verifier.redundant_quorum(wu, results)
    if reputation is not None and verdict.get("workers_agree") is not None:
        reputation.record(agreed=verdict.get("workers_agree", []),
                          disagreed=verdict.get("workers_disagree", []))
    return verdict


if __name__ == "__main__":
    wu = mint_work_unit(task="image.infer@v3", params={"top_k": 3}, proof_mode="redundant")
    # 3 workers: two agree, one lies.
    results = [{"worker": "vol-a", "output": {"label": "cat", "score": 0.9}},
               {"worker": "vol-b", "output": {"label": "cat", "score": 0.9}},
               {"worker": "vol-c", "output": {"label": "GARBAGE"}}]
    rep = Reputation()
    verdict = verify_and_score(wu, results, rep)
    print(json.dumps({"wu": wu["wu_id"], "verified": verdict["verified"],
                      "agree": verdict["workers_agree"], "disagree": verdict["workers_disagree"],
                      "rep_vol_a": rep.score("vol-a"), "rep_vol_c": rep.score("vol-c")}, indent=2))
