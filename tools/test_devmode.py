#!/usr/bin/env python3
"""Tests for dev-mode manifest/command generation (the pure core of the inner loop)."""
import devmode as dm


def test_devmode_patch_swaps_in_a_dev_runner_with_a_workspace():
    p = dm.devmode_patch(workload="productpage", run_cmd="python -m http.server 8080", grant_id="g1")
    c = p["spec"]["template"]["spec"]["containers"][0]
    assert c["name"] == "dev" and c["workingDir"] == "/workspace"
    assert c["command"] == ["sh", "-c", "python -m http.server 8080"]
    assert c["volumeMounts"][0]["mountPath"] == "/workspace"
    assert p["spec"]["template"]["spec"]["volumes"][0]["emptyDir"] == {}
    assert p["metadata"]["labels"]["sourceos.io/devmode"] == "on"
    assert p["metadata"]["labels"]["sourceos.io/grant-id"] == "g1"


def test_sync_command_is_kubectl_cp_into_the_workspace():
    cmd = dm.sync_command(local_dir="./app", namespace="ds-x", pod="pp-abc", context="kind-x")
    assert cmd == ["kubectl", "--context", "kind-x", "cp", "./app", "ds-x/pp-abc:/workspace", "-c", "dev"]


def test_port_forward_maps_local_to_remote():
    cmd = dm.port_forward_command(namespace="ds-x", pod="pp-abc", ports=[(8080, 8080), (5678, 5678)])
    assert cmd == ["kubectl", "port-forward", "-n", "ds-x", "pod/pp-abc", "8080:8080", "5678:5678"]


def test_plan_ties_patch_sync_and_forward():
    plan = dm.devmode_plan(workload="pp", namespace="ds-x", local_dir="./app",
                           ports=[(8080, 8080)], run_cmd="python -m http.server 8080")
    assert plan["workspace"] == "/workspace"
    assert "cp" in plan["sync"] and "port-forward" in plan["forward"]
    assert plan["patch"]["spec"]["template"]["spec"]["containers"][0]["name"] == "dev"


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
    print(f"ok: {len(fns)} devmode tests passed")
    sys.exit(0)
