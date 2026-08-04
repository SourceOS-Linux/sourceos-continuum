#!/usr/bin/env python3
"""Live mesh telemetry — the fail-closed liveness registry the compute plane places against.

"Per mesh availability" has to be *live*, not a static snapshot. Every node in the mesh — a k8s
worker, an HPC login node, a WASM edge, a volunteer BOINC/Folding@home box, a p2p peer — emits a
heartbeat carrying its backend kind and free capacity. This registry turns those heartbeats into
the availability dict `compute_plane.place()` consumes.

Staleness is the signal; TTL is the enforcement. A node that stops beating stops counting: once its
last heartbeat ages past the TTL it contributes zero capacity, so the plane will not schedule there.
Fail-closed by construction — no heartbeat means unavailable, never "assume it's still up." The
read-only portal never ingests; nodes write heartbeat files (sovereign, no broker), the registry
reads them.
"""
from __future__ import annotations

import json
import time
from pathlib import Path


class MeshRegistry:
    """Aggregates node heartbeats into live per-backend availability, expiring stale nodes by TTL."""

    def __init__(self, ttl_seconds: float = 30.0, clock=time.time):
        self.ttl = float(ttl_seconds)
        self._clock = clock
        self._nodes: dict[str, dict] = {}  # node_id -> {backend, capacity, ts}

    def heartbeat(self, node_id: str, backend: str, capacity: float, *, ts: float | None = None) -> None:
        self._nodes[node_id] = {"backend": backend, "capacity": float(capacity),
                                "ts": float(ts if ts is not None else self._clock())}

    @classmethod
    def from_dir(cls, path, ttl_seconds: float = 30.0, clock=time.time) -> "MeshRegistry":
        """Load heartbeat files (<node>.json = {node_id, backend, capacity, ts}) written by nodes."""
        reg = cls(ttl_seconds=ttl_seconds, clock=clock)
        p = Path(path)
        if p.is_dir():
            for f in p.glob("*.json"):
                try:
                    hb = json.loads(f.read_text())
                    reg.heartbeat(hb["node_id"], hb["backend"], hb["capacity"], ts=hb.get("ts"))
                except (OSError, json.JSONDecodeError, KeyError, TypeError):
                    continue  # a malformed heartbeat is a dead node, not a crash — fail-closed
        return reg

    def _live(self, now: float | None = None) -> dict[str, dict]:
        now = self._clock() if now is None else now
        return {nid: n for nid, n in self._nodes.items() if now - n["ts"] <= self.ttl}

    def availability(self, now: float | None = None) -> dict[str, float]:
        """Live free capacity summed per backend. Backends with no live node are simply absent (0)."""
        out: dict[str, float] = {}
        for n in self._live(now).values():
            out[n["backend"]] = out.get(n["backend"], 0.0) + n["capacity"]
        return out

    def nodes(self, now: float | None = None) -> list[dict]:
        """Per-node view for the dashboard: which nodes are live, their age, and capacity."""
        now = self._clock() if now is None else now
        rows = []
        for nid, n in sorted(self._nodes.items()):
            age = round(now - n["ts"], 1)
            rows.append({"node_id": nid, "backend": n["backend"], "capacity": n["capacity"],
                         "age_s": age, "live": age <= self.ttl})
        return rows

    def summary(self, now: float | None = None) -> dict:
        live = self._live(now)
        return {"ttl_s": self.ttl, "total_nodes": len(self._nodes), "live_nodes": len(live),
                "backends_up": sorted({n["backend"] for n in live.values()})}


def write_heartbeat(dir_path, node_id: str, backend: str, capacity: float, *, ts: float | None = None) -> Path:
    """Emit one heartbeat file — what a mesh node (or the demo agent) calls to announce itself."""
    d = Path(dir_path)
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{node_id}.json"
    f.write_text(json.dumps({"node_id": node_id, "backend": backend,
                             "capacity": float(capacity),
                             "ts": float(ts if ts is not None else time.time())}))
    return f


if __name__ == "__main__":
    # `mesh_telemetry.py heartbeat <dir> <node> <backend> <capacity>` — announce a node.
    # `mesh_telemetry.py view <dir>` — show live availability + per-node liveness.
    import sys
    if len(sys.argv) >= 6 and sys.argv[1] == "heartbeat":
        p = write_heartbeat(sys.argv[2], sys.argv[3], sys.argv[4], float(sys.argv[5]))
        print(f"wrote {p}")
    elif len(sys.argv) >= 3 and sys.argv[1] == "view":
        reg = MeshRegistry.from_dir(sys.argv[2])
        print(json.dumps({"summary": reg.summary(), "availability": reg.availability(),
                          "nodes": reg.nodes()}, indent=2, sort_keys=True))
    else:
        print("usage: mesh_telemetry.py heartbeat <dir> <node> <backend> <capacity> | view <dir>")
        sys.exit(2)
