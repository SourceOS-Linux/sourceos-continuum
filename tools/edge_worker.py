#!/usr/bin/env python3
"""Edge-worker registration + evolvable topology — Giant Swarm, reversed.

Giant Swarm runs a cloud MANAGEMENT cluster that provisions workload clusters top-down (k8s-on-k8s /
Cluster API). We invert it: the edge agent-machine — a lightweight, SINGLE-MASTER **k3s** (k3s-in-
docker on the box, or k3s on a server) — is sovereign and local-first, and REGISTERS UP into a cloud
pool as a **worker**. The cloud twin is a rendezvous, not a master.

Two consequences the user called out:
  * an ephemeral dev node doesn't need HA redundancy, so single-master k3s is right at the edge; the
    topology is EVOLVABLE — the same workload climbs `k3s-edge -> k3s-server -> k8s-cloud` as needs
    grow, and it shouldn't matter which rung it's on.
  * the agent-machine's local **TopoLVM flash** is exposed to the cluster as a shared container mount,
    so the registered worker contributes both compute AND storage to the pool.
"""
from __future__ import annotations

import mesh_telemetry as mt

# The evolvable topology ladder. A workload/node climbs it as needs grow; migration up or down is
# allowed — the topology is not pinned to any rung.
TOPOLOGY_LADDER = ["k3s-edge", "k3s-server", "k8s-cloud"]


def shared_storage_mount(*, node_id: str, pvc: str = "inception-mount",
                         path: str = "/var/lib/sourceos/inception") -> dict:
    """The agent-machine's local TopoLVM flash, exposed to the cluster as a shared container mount."""
    return {"pvc": pvc, "path": path, "storage_class": "topolvm-provisioner", "node": node_id,
            "access": "ReadWriteOnce", "shared_via": "container mount on the registered worker node"}


def register_worker(*, node_id: str, pool: str, cpu: int, mem_gb: int, storage_gb: int,
                    gpu: bool = False, distro: str = "k3s-edge", heartbeats_dir=None) -> dict:
    """The agent-machine joins a cloud POOL as a worker (Giant Swarm, reversed). Emits a mesh heartbeat
    so placement sees its capacity, and advertises its TopoLVM storage. Returns the registration."""
    backend = "k3s-edge" if distro.startswith("k3s") else "k8s"
    rec = {"node_id": node_id, "pool": pool, "distro": distro, "backend": backend, "role": "worker",
           "cpu": cpu, "mem_gb": mem_gb, "storage_gb": storage_gb, "gpu": gpu, "registered": True,
           "shared_storage": shared_storage_mount(node_id=node_id)}
    if heartbeats_dir is not None:
        mt.write_heartbeat(heartbeats_dir, node_id, backend, cpu)  # now visible to compute_plane.place()
    return rec


def evolve(*, workload: dict, from_backend: str, to_backend: str) -> dict:
    """Migrate a workload across the topology ladder (evolvable topology). Data follows via the
    inception mount; the direction is just an index move on the ladder — no rung is special."""
    if from_backend not in TOPOLOGY_LADDER or to_backend not in TOPOLOGY_LADDER:
        return {"ok": False, "reason": f"backend not on the topology ladder {TOPOLOGY_LADDER}"}
    i, j = TOPOLOGY_LADDER.index(from_backend), TOPOLOGY_LADDER.index(to_backend)
    return {"ok": True, "workload": workload.get("name"), "from": from_backend, "to": to_backend,
            "direction": "up" if j > i else "down" if j < i else "same",
            "carries_inception_mount": bool(workload.get("inception_pvc")),
            "note": f"migrate {from_backend} -> {to_backend}; state follows via the TopoLVM inception mount"}


if __name__ == "__main__":
    import json
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        reg = register_worker(node_id="m2-agent", pool="cloud-pool-a", cpu=8, mem_gb=16,
                              storage_gb=200, gpu=False, distro="k3s-edge", heartbeats_dir=td)
        avail = mt.MeshRegistry.from_dir(td).availability()
        wl = {"name": "trainer", "inception_pvc": "inception-mount"}
        print(json.dumps({
            "registered": {"node": reg["node_id"], "pool": reg["pool"], "backend": reg["backend"],
                           "storage": reg["shared_storage"]["storage_class"]},
            "mesh_sees": avail,
            "evolve": evolve(workload=wl, from_backend="k3s-edge", to_backend="k8s-cloud"),
        }, indent=2))
