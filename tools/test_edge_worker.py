#!/usr/bin/env python3
"""Tests for edge-worker registration + evolvable topology (Giant Swarm, reversed)."""
import tempfile

import compute_plane as cp
import edge_worker as ew
import mesh_telemetry as mt


def test_register_worker_joins_a_pool_and_becomes_visible_to_placement():
    with tempfile.TemporaryDirectory() as td:
        reg = ew.register_worker(node_id="m2", pool="cloud-pool-a", cpu=8, mem_gb=16,
                                 storage_gb=200, distro="k3s-edge", heartbeats_dir=td)
        assert reg["backend"] == "k3s-edge" and reg["role"] == "worker" and reg["registered"]
        # the edge node's capacity is now real, placeable mesh availability (registered UP into the pool)
        assert mt.MeshRegistry.from_dir(td).availability().get("k3s-edge") == 8


def test_shared_storage_is_the_topolvm_inception_mount():
    m = ew.shared_storage_mount(node_id="m2")
    assert m["storage_class"] == "topolvm-provisioner" and m["path"] == "/var/lib/sourceos/inception"
    assert "container mount" in m["shared_via"]


def test_evolve_migrates_up_and_down_the_ladder_carrying_state():
    wl = {"name": "svc", "inception_pvc": "inception-mount"}
    up = ew.evolve(workload=wl, from_backend="k3s-edge", to_backend="k8s-cloud")
    assert up["ok"] and up["direction"] == "up" and up["carries_inception_mount"] is True
    down = ew.evolve(workload=wl, from_backend="k8s-cloud", to_backend="k3s-edge")
    assert down["direction"] == "down"


def test_evolve_rejects_a_backend_off_the_ladder():
    assert ew.evolve(workload={}, from_backend="k3s-edge", to_backend="volunteer-boinc")["ok"] is False


def test_k3s_edge_is_trusted_and_placeable():
    # the sovereign edge is a trusted backend — a sensitive workload may run there.
    d = cp.place({"sensitivity": "sensitive", "scalable": False},
                 {"allowed_backends": ["k3s-edge"]}, {"k3s-edge": 8})
    assert d["backend"] == "k3s-edge" and d["backend_trust"] == "trusted"


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
    print(f"ok: {len(fns)} edge-worker tests passed")
    sys.exit(0)
