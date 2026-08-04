#!/usr/bin/env python3
"""Pull/lease streaming dispatch — Pando's StreamLender + Limiter, governed.

Push WU-assignment is brittle on a churny volunteer mesh: you'd estimate each worker's speed and
re-push on every crash. The elegant alternative is PULL: a worker LEASES work when it is idle, so
faster/idler devices simply pull more (adaptive, no speed estimation) and slow ones pull less
(automatic backpressure). Properties:

  * conservative — one copy of a Work Unit to at most one worker at a time, maximizing DISTINCT
    units in flight (redundant-quorum is an optional overlay layered on top, not the default).
  * crash-stop work-stealing — a worker that misses its lease deadline (crashed/left) has its
    borrowed unit RE-LENT by index to someone else; nothing is lost.
  * ordered — results re-merge by index for determinism.
  * bounded — a Limiter caps in-flight leases per worker.

Heartbeat extends a lease's deadline (progress signal); silence past the deadline reclaims it.
"""
from __future__ import annotations

import time


class LeaseScheduler:
    def __init__(self, work_units, *, max_in_flight: int = 4, lease_ttl_s: float = 30.0,
                 clock=time.time):
        self._pending: list[tuple[int, object]] = list(enumerate(work_units))  # ordered by index
        self._leased: dict[str, dict] = {}
        self._done: dict[int, object] = {}
        self._inflight: dict[str, set] = {}
        self._max = int(max_in_flight)
        self._ttl = float(lease_ttl_s)
        self._clock = clock
        self._seq = 0

    def _reclaim(self, now: float) -> list[str]:
        """Return WUs whose lease deadline passed (worker crashed/left) to the pool — re-lent by
        index. A unit already completed is not re-lent."""
        expired = [lid for lid, l in self._leased.items() if now > l["deadline"]]
        for lid in expired:
            l = self._leased.pop(lid)
            self._inflight.get(l["worker"], set()).discard(lid)
            if l["index"] not in self._done:
                self._pending.append((l["index"], l["wu"]))
        if expired:
            self._pending.sort(key=lambda t: t[0])  # keep ordered for deterministic re-merge
        return expired

    def lease(self, worker: str, n: int = 1) -> list[dict]:
        """A worker pulls up to n Work Units (idle workers call this more → adaptive). Respects the
        per-worker Limiter."""
        now = self._clock()
        self._reclaim(now)
        held = self._inflight.setdefault(worker, set())
        out = []
        while self._pending and len(held) < self._max and len(out) < n:
            index, wu = self._pending.pop(0)
            self._seq += 1
            lid = f"lease-{self._seq}"
            self._leased[lid] = {"index": index, "wu": wu, "worker": worker, "deadline": now + self._ttl}
            held.add(lid)
            out.append({"lease_id": lid, "index": index, "wu": wu})
        return out

    def complete(self, lease_id: str, output) -> bool:
        """Return a result. False if the lease was already reclaimed (a slow/crashed worker whose
        unit was re-lent) — its late result is dropped, the re-lent copy is authoritative."""
        l = self._leased.pop(lease_id, None)
        if l is None:
            return False
        self._inflight.get(l["worker"], set()).discard(lease_id)
        self._done.setdefault(l["index"], output)
        return True

    def heartbeat(self, worker: str, lease_id: str | None = None) -> None:
        """Extend the deadline of a worker's lease(s) — a progress signal that keeps it from being
        reclaimed."""
        now = self._clock()
        for lid, l in self._leased.items():
            if l["worker"] == worker and (lease_id is None or lid == lease_id):
                l["deadline"] = now + self._ttl

    def progress(self) -> dict:
        return {"pending": len(self._pending), "leased": len(self._leased), "done": len(self._done)}

    def drained(self) -> bool:
        self._reclaim(self._clock())
        return not self._pending and not self._leased

    def results_in_order(self) -> list:
        return [self._done[i] for i in sorted(self._done)]


if __name__ == "__main__":
    import json

    class Clock:
        def __init__(self, t=0.0):
            self.t = t

        def __call__(self):
            return self.t

    clk = Clock()
    sched = LeaseScheduler([f"wu{i}" for i in range(5)], max_in_flight=2, lease_ttl_s=10, clock=clk)
    # fast worker A pulls + completes; worker B leases one then "crashes" (never completes).
    a1 = sched.lease("A", 1)[0]
    b1 = sched.lease("B", 1)[0]
    sched.complete(a1["lease_id"], a1["wu"] + "-done-by-A")
    clk.t = 20  # B missed its deadline -> its unit is re-lent
    a2 = sched.lease("A", 1)  # picks up B's abandoned unit + more
    for lz in a2:
        sched.complete(lz["lease_id"], lz["wu"] + "-done-by-A")
    while not sched.drained():
        for lz in sched.lease("A", 4):
            sched.complete(lz["lease_id"], lz["wu"] + "-done-by-A")
    print(json.dumps({"drained": sched.drained(), "results": sched.results_in_order()}, indent=2))
