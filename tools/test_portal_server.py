#!/usr/bin/env python3
"""Tests for the developer portal's pure router — every endpoint, the 404, and that the two views
the console renders (capabilities incl. DevSpace, and the compute mesh incl. the untrusted volunteer
grid) are actually served."""
import json
import pathlib
import tempfile

import mesh_telemetry as mt
import portal_server as ps


def _seed_fresh(dirpath):
    """A fresh, isolated live mesh so telemetry-backed endpoints are deterministic."""
    mt.write_heartbeat(dirpath, "k8s-x", "k8s", 8)
    mt.write_heartbeat(dirpath, "boinc-x", "volunteer-boinc", 300)
    mt.write_heartbeat(dirpath, "slurm-x", "hpc-slurm", 100)


def test_root_serves_the_console_html():
    status, ctype, body = ps.route("/")
    assert status == 200
    assert "text/html" in ctype
    assert "Developer Console" in body and "Compute mesh" in body


def test_healthz_is_ok():
    assert ps.route("/healthz") == (200, "text/plain", "ok")


def test_api_endpoints_return_json():
    for path, key in (("/api/capabilities", "capabilities"),
                      ("/api/lifecycle", "lifecycle"),
                      ("/api/evidence", "evidence"),
                      ("/api/compute", "backends")):
        status, ctype, body = ps.route(path)
        assert status == 200 and ctype == "application/json"
        assert key in json.loads(body)


def test_query_string_is_ignored_by_router():
    assert ps.route("/healthz?x=1")[0] == 200


def test_unknown_path_is_404():
    status, _, _ = ps.route("/nope")
    assert status == 404


def test_devspace_capability_is_surfaced():
    caps = json.loads(ps.route("/api/capabilities")[2])["capabilities"]
    ids = {c.get("capability_id") for c in caps}
    assert any(str(i).startswith("caps.dev.devspace-inner-loop") for i in ids), ids


def test_compute_mesh_reflects_live_telemetry():
    with tempfile.TemporaryDirectory() as td:
        old, ps._HEARTBEATS = ps._HEARTBEATS, pathlib.Path(td)
        try:
            _seed_fresh(td)
            backends = json.loads(ps.route("/api/compute")[2])["backends"]
            by_id = {b["id"]: b for b in backends}
            assert by_id["volunteer-boinc"]["trust"] == "untrusted"
            assert by_id["volunteer-boinc"]["available"] == 300  # summed from the live heartbeat
            assert by_id["hpc-slurm"]["available"] == 100
        finally:
            ps._HEARTBEATS = old


def test_mesh_endpoint_lists_live_nodes():
    with tempfile.TemporaryDirectory() as td:
        old, ps._HEARTBEATS = ps._HEARTBEATS, pathlib.Path(td)
        try:
            _seed_fresh(td)
            mesh = json.loads(ps.route("/api/mesh")[2])
            assert mesh["summary"]["live_nodes"] == 3
            assert {n["node_id"] for n in mesh["nodes"]} == {"k8s-x", "boinc-x", "slurm-x"}
        finally:
            ps._HEARTBEATS = old


def test_placements_govern_the_suite_over_live_availability():
    with tempfile.TemporaryDirectory() as td:
        old, ps._HEARTBEATS = ps._HEARTBEATS, pathlib.Path(td)
        try:
            _seed_fresh(td)  # k8s + volunteer-boinc + hpc-slurm live
            pl = {p["id"]: p for p in json.loads(ps.route("/api/placements")[2])["placements"]}
            # offensive tooling must never ride the volunteer grid, whatever the scale pressure
            assert pl["bearbrowser.scan"]["backend"] != "volunteer-boinc"
            # sensitive reasoning lands on trusted infra
            assert pl["noetica.reasoning"]["backend_trust"] == "trusted"
        finally:
            ps._HEARTBEATS = old


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
    print(f"ok: {len(fns)} portal tests passed")
    sys.exit(0)
