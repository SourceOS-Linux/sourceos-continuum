#!/usr/bin/env python3
"""Tests for the live mesh telemetry registry. The load-bearing behavior is fail-closed liveness:
a node that stops beating must stop counting toward availability. Time is injected so expiry is
deterministic."""
import json

import mesh_telemetry as mt


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def test_heartbeats_sum_capacity_per_backend():
    reg = mt.MeshRegistry(ttl_seconds=30, clock=Clock())
    reg.heartbeat("n1", "k8s", 4)
    reg.heartbeat("n2", "k8s", 6)
    reg.heartbeat("n3", "hpc-slurm", 100)
    assert reg.availability() == {"k8s": 10, "hpc-slurm": 100}


def test_stale_node_stops_counting_after_ttl():
    clk = Clock(1000.0)
    reg = mt.MeshRegistry(ttl_seconds=30, clock=clk)
    reg.heartbeat("n1", "volunteer-boinc", 200)  # beat at t=1000
    assert reg.availability() == {"volunteer-boinc": 200}
    clk.t = 1031.0  # 31s later, past the 30s TTL
    assert reg.availability() == {}  # fail-closed: no longer available


def test_a_fresh_beat_revives_a_node():
    clk = Clock(1000.0)
    reg = mt.MeshRegistry(ttl_seconds=30, clock=clk)
    reg.heartbeat("n1", "k8s", 8)
    clk.t = 1040.0
    assert reg.availability() == {}          # expired
    reg.heartbeat("n1", "k8s", 8)            # beats again at t=1040
    assert reg.availability() == {"k8s": 8}  # live again


def test_nodes_view_reports_liveness_and_age():
    clk = Clock(1000.0)
    reg = mt.MeshRegistry(ttl_seconds=30, clock=clk)
    reg.heartbeat("live1", "k8s", 4, ts=990.0)     # 10s old -> live
    reg.heartbeat("dead1", "p2p-mesh", 9, ts=900.0)  # 100s old -> dead
    rows = {r["node_id"]: r for r in reg.nodes()}
    assert rows["live1"]["live"] is True and rows["live1"]["age_s"] == 10.0
    assert rows["dead1"]["live"] is False


def test_summary_counts_live_vs_total():
    clk = Clock(1000.0)
    reg = mt.MeshRegistry(ttl_seconds=30, clock=clk)
    reg.heartbeat("a", "k8s", 1, ts=1000.0)
    reg.heartbeat("b", "hpc-slurm", 1, ts=800.0)  # stale
    s = reg.summary()
    assert s["total_nodes"] == 2 and s["live_nodes"] == 1 and s["backends_up"] == ["k8s"]


def test_from_dir_loads_heartbeat_files_and_skips_malformed(tmp_path):
    mt.write_heartbeat(tmp_path, "good", "wasm-edge", 20, ts=1000.0)
    (tmp_path / "broken.json").write_text("{not json")
    (tmp_path / "incomplete.json").write_text(json.dumps({"node_id": "x"}))  # missing keys
    reg = mt.MeshRegistry.from_dir(tmp_path, ttl_seconds=30, clock=Clock(1005.0))
    assert reg.availability() == {"wasm-edge": 20}  # only the good one; malformed = dead, no crash


def test_empty_dir_is_fail_closed_not_error(tmp_path):
    reg = mt.MeshRegistry.from_dir(tmp_path, ttl_seconds=30, clock=Clock())
    assert reg.availability() == {} and reg.summary()["live_nodes"] == 0


def test_telemetry_feeds_the_compute_plane_end_to_end():
    import compute_plane as cp
    clk = Clock(1000.0)
    reg = mt.MeshRegistry(ttl_seconds=30, clock=clk)
    reg.heartbeat("gpu1", "hpc-slurm", 50)        # both beat at t=1000
    reg.heartbeat("vol1", "volunteer-boinc", 500)
    # a normal scalable workload scales out to the biggest live backend...
    d = cp.place({"sensitivity": "normal", "scalable": True}, {}, reg.availability())
    assert d["backend"] == "volunteer-boinc"
    # the volunteer node goes silent; the gpu node keeps beating.
    clk.t = 1031.0
    reg.heartbeat("gpu1", "hpc-slurm", 50)         # fresh beat at t=1031
    d2 = cp.place({"sensitivity": "normal", "scalable": True}, {}, reg.availability())
    assert d2["backend"] == "hpc-slurm"            # volunteer expired -> re-placed onto live HPC


if __name__ == "__main__":
    import sys
    import tempfile
    fns = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_")]
    for name, fn in fns:
        if "tmp_path" in fn.__code__.co_varnames:
            import pathlib
            with tempfile.TemporaryDirectory() as td:
                fn(pathlib.Path(td))
        else:
            fn()
    print(f"ok: {len(fns)} mesh-telemetry tests passed")
    sys.exit(0)
