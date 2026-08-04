#!/usr/bin/env python3
"""Nocalhost-style dev-mode — the tight modify->result inner loop against a real cluster.

The whole point of a local-first PaaS: edit on the low-mem box, see it running in a real DevSpace
pod in seconds, without rebuilding an image. Dev-mode does the three things Nocalhost's Dev Mode
does, governed and in the user's own DevSpace namespace:

  1. put a workload into DEV MODE — swap its container for a dev-runner with an in-pod workspace, so
     synced code runs live (no image rebuild);
  2. SYNC local files into the running pod (hot reload) — `kubectl cp`;
  3. PORT-FORWARD the remote service (+ a debug port) to localhost (local access + remote debug).

The manifest patch and the kubectl command lines are pure functions (unit-tested); a driver wraps
them for a live cluster.
"""
from __future__ import annotations

DEV_WORKSPACE = "/workspace"


def devmode_patch(*, workload: str, dev_image: str = "python:3.12-alpine",
                  run_cmd: str | None = None, grant_id: str | None = None) -> dict:
    """A strategic-merge patch that puts a Deployment into dev mode: a dev-runner container with an
    emptyDir workspace at /workspace, running the synced code (or idling until synced)."""
    labels = {"sourceos.io/devmode": "on", "sourceos.io/workload": workload}
    if grant_id:
        labels["sourceos.io/grant-id"] = grant_id
    container = {"name": "dev", "image": dev_image, "workingDir": DEV_WORKSPACE,
                 "command": ["sh", "-c", run_cmd or "sleep infinity"],
                 "volumeMounts": [{"name": "workspace", "mountPath": DEV_WORKSPACE}]}
    return {"metadata": {"labels": labels},
            "spec": {"template": {"metadata": {"labels": labels},
                                  "spec": {"containers": [container],
                                           "volumes": [{"name": "workspace", "emptyDir": {}}]}}}}


def _ctx(context):
    return ["--context", context] if context else []


def sync_command(*, local_dir: str, namespace: str, pod: str, container: str = "dev",
                 remote: str = DEV_WORKSPACE, context: str | None = None) -> list:
    """`kubectl cp` local -> pod: the file-sync / hot-reload step (no image rebuild)."""
    return ["kubectl", *_ctx(context), "cp", local_dir, f"{namespace}/{pod}:{remote}", "-c", container]


def port_forward_command(*, namespace: str, pod: str, ports: list, context: str | None = None) -> list:
    """`kubectl port-forward` local:remote — local access + a debug port. ports = [(local, remote)]."""
    maps = [f"{lo}:{re}" for lo, re in ports]
    return ["kubectl", *_ctx(context), "port-forward", "-n", namespace, f"pod/{pod}", *maps]


def attach_command(*, namespace: str, pod: str, grant: dict, verifier, session_id: str,
                   container: str = "dev", context: str | None = None) -> dict:
    """Grant-bound remote terminal (Nocalhost AppA-terminal / cloud-shell attach). The fog-node Policy
    Gate re-verifies the Grant (effect exec + op pty.attach, session-bound) BEFORE any PTY is opened —
    fail-closed. Returns {authorized, command|reason, redactions}."""
    import mcp_a2a_grant as g
    check = g.verify_grant(grant, session_id=session_id, verifier=verifier,
                           requested_effect="exec", requested_op="pty.attach")
    if not check["result"]["valid"]:
        return {"authorized": False, "reason": check["result"]["reason"]}
    return {"authorized": True,
            "command": ["kubectl", *_ctx(context), "exec", "-it", "-n", namespace,
                        f"pod/{pod}", "-c", container, "--", "/bin/sh"],
            "redactions": check.get("redactions", [])}


def devmode_plan(*, workload: str, namespace: str, local_dir: str, ports: list,
                 dev_image: str = "python:3.12-alpine", run_cmd: str | None = None,
                 context: str | None = None, grant_id: str | None = None) -> dict:
    """The full inner-loop plan: patch the workload into dev-mode, sync files, forward ports."""
    return {
        "workspace": DEV_WORKSPACE,
        "patch": devmode_patch(workload=workload, dev_image=dev_image, run_cmd=run_cmd, grant_id=grant_id),
        "patch_command": ["kubectl", *_ctx(context), "-n", namespace, "patch", "deployment", workload,
                          "--type", "strategic", "-p", "<patch-json>"],
        "sync": sync_command(local_dir=local_dir, namespace=namespace, pod=f"<{workload}-pod>",
                             context=context),
        "forward": port_forward_command(namespace=namespace, pod=f"<{workload}-pod>", ports=ports,
                                        context=context),
    }


if __name__ == "__main__":
    import json
    plan = devmode_plan(workload="productpage", namespace="ds-acme-alice-feat",
                        local_dir="./app", ports=[(8080, 8080), (5678, 5678)],
                        run_cmd="python -m http.server 8080")
    print(json.dumps({"workspace": plan["workspace"],
                      "dev_container": plan["patch"]["spec"]["template"]["spec"]["containers"][0]["name"],
                      "sync": " ".join(plan["sync"]),
                      "forward": " ".join(plan["forward"])}, indent=2))
