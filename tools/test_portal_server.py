#!/usr/bin/env python3
"""Tests for the developer portal's pure router — every endpoint, the 404, and that the two views
the console renders (capabilities incl. DevSpace, and the compute mesh incl. the untrusted volunteer
grid) are actually served."""
import json

import portal_server as ps


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


def test_compute_mesh_includes_the_untrusted_volunteer_grid():
    backends = json.loads(ps.route("/api/compute")[2])["backends"]
    by_id = {b["id"]: b for b in backends}
    assert "volunteer-boinc" in by_id and by_id["volunteer-boinc"]["trust"] == "untrusted"
    assert "hpc-slurm" in by_id and by_id["hpc-slurm"]["trust"] == "trusted"
    assert by_id["volunteer-boinc"]["available"] > 0  # snapshot shows live availability


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
    print(f"ok: {len(fns)} portal tests passed")
    sys.exit(0)
