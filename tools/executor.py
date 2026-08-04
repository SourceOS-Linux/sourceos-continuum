#!/usr/bin/env python3
"""The execution spine — turns a governed placement decision + a verified Grant into an ACTUAL
dispatch. This is what makes the compute plane a *platform* and not a planner.

The whole flow, closed:

    heartbeat -> place() [Decide] -> issue_grant() [Grant] -> verify_grant() [Gate] -> DISPATCH
    -> sealed execution receipt

Dispatch is pluggable per substrate: run it locally as a subprocess, emit a real k8s Job manifest
(and apply it when a cluster is reachable), or emit the substrate-specific descriptor you'd hand to
an HPC/SLURM queue, a WASM edge, a p2p/hyperswarm peer, a volunteer grid, or a blockchain compute
market. Every dispatch is **fail-closed on the Grant**: the fog-node Policy Gate re-verifies the
Grant (signature, session binding, expiry, attestation, effect) before anything runs — no valid
Grant, no dispatch — and every dispatch is sealed into a tamper-evident receipt.
"""
from __future__ import annotations

import hashlib
import json
import shlex
import shutil
import subprocess
from datetime import datetime, timezone

import mcp_a2a_grant as grant_mod


def _seal(body: dict) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class DispatchRefused(Exception):
    """The Grant did not verify at the node — nothing is dispatched (fail-closed)."""


# ── backend adapters ─────────────────────────────────────────────────────────────────
class LocalAdapter:
    """Runs the workload as a local subprocess (the dev's own box)."""
    backend = "local"

    def dispatch(self, workload, decision, grant, *, apply):
        cmd = workload.get("command")
        if not cmd:
            return {"kind": "local", "applied": False, "reason": "no command to run"}
        if not apply:
            return {"kind": "local", "applied": False, "planned": cmd}
        proc = subprocess.run(shlex.split(cmd), capture_output=True, text=True, timeout=120)
        return {"kind": "local", "applied": True, "exit_code": proc.returncode,
                "stdout": proc.stdout[-2000:], "stderr": proc.stderr[-2000:]}


class K8sAdapter:
    """Emits a real batch/v1 Job manifest, Grant-labelled; applies it when a cluster is reachable."""
    backend = "k8s"

    def manifest(self, workload, decision, grant):
        res = workload.get("resource", {})
        requests = {}
        if res.get("cpu"):
            requests["cpu"] = str(res["cpu"])
        if res.get("mem"):
            requests["memory"] = str(res["mem"])
        limits = dict(requests)
        if workload.get("needs_gpu"):
            limits["nvidia.com/gpu"] = "1"
        container = {"name": "workload",
                     "image": workload.get("image", "busybox:1.36"),
                     "command": shlex.split(workload["command"]) if workload.get("command") else ["true"]}
        if requests or limits:
            container["resources"] = {k: v for k, v in (("requests", requests), ("limits", limits)) if v}
        return {
            "apiVersion": "batch/v1", "kind": "Job",
            "metadata": {"generateName": f"{workload.get('name', 'wl')}-",
                         "labels": {"sourceos.io/grant-id": grant["grant_id"],
                                    "sourceos.io/session": grant["binding"].get("session_id", ""),
                                    "sourceos.io/backend": "k8s"}},
            "spec": {"backoffLimit": 0, "ttlSecondsAfterFinished": 3600,
                     "template": {"metadata": {"labels": {"sourceos.io/grant-id": grant["grant_id"]}},
                                  "spec": {"restartPolicy": "Never", "containers": [container]}}},
        }

    def dispatch(self, workload, decision, grant, *, apply):
        manifest = self.manifest(workload, decision, grant)
        if apply and shutil.which("kubectl"):
            proc = subprocess.run(["kubectl", "apply", "-f", "-"], input=json.dumps(manifest),
                                  capture_output=True, text=True, timeout=60)
            return {"kind": "k8s", "applied": proc.returncode == 0, "manifest": manifest,
                    "kubectl": proc.stdout.strip() or proc.stderr.strip()}
        return {"kind": "k8s", "applied": False, "manifest": manifest}


class DescriptorAdapter:
    """For substrates dispatched by handing a descriptor to their own scheduler/mesh: HPC/SLURM,
    WASM edge, p2p/hyperswarm, volunteer grid, blockchain compute market."""
    def __init__(self, backend: str):
        self.backend = backend

    def dispatch(self, workload, decision, grant, *, apply):
        return {"kind": self.backend, "applied": False,
                "descriptor": {"backend": self.backend, "executor_ref": grant["capability"].get("executor_ref"),
                               "command": workload.get("command"), "image": workload.get("image"),
                               "resource": workload.get("resource", {}), "needs_gpu": workload.get("needs_gpu", False),
                               "grant_id": grant["grant_id"], "session": grant["binding"].get("session_id")},
                "note": f"hand this descriptor to the {self.backend} scheduler over a Grant-bound channel"}


def default_adapters() -> dict:
    ad = {LocalAdapter().backend: LocalAdapter(), K8sAdapter().backend: K8sAdapter()}
    for b in ("hpc-slurm", "wasm-edge", "p2p-mesh", "volunteer-boinc", "blockchain-rlc"):
        ad[b] = DescriptorAdapter(b)
    return ad


def execute(workload: dict, decision: dict, grant: dict, *, session_id: str, verifier,
            adapters: dict | None = None, apply: bool = False) -> dict:
    """Enforce the Grant at the node, then dispatch to the decided backend, then seal a receipt.

    Fail-closed: if verify_grant denies (bad sig / wrong session / expired / attestation / effect),
    raise DispatchRefused — nothing runs.
    """
    adapters = adapters or default_adapters()
    check = grant_mod.verify_grant(grant, session_id=session_id, verifier=verifier,
                                   requested_effect=workload.get("effect"))
    if not check["result"]["valid"]:
        raise DispatchRefused(check["result"]["reason"])

    backend = decision.get("backend")
    adapter = adapters.get(backend)
    if adapter is None:
        raise DispatchRefused(f"no execution adapter for backend {backend!r}")

    dispatch = adapter.dispatch(workload, decision, grant, apply=apply)
    receipt = {"spine": "sourceos-continuum.executor.v1", "backend": backend,
               "grant_id": grant["grant_id"], "session": session_id,
               "applied": dispatch.get("applied", False), "dispatch_kind": dispatch.get("kind"),
               "grant_check": check["check_id"], "at": _now_iso()}
    receipt["receipt_digest"] = _seal(receipt)
    return {"status": "dispatched", "backend": backend, "dispatch": dispatch,
            "grant_check": check, "receipt": receipt}


def run_spine(workload: dict, policy: dict, *, registry, binding: dict, capability: dict,
              attestation: dict, constraints: dict, signer, verifier, apply: bool = False) -> dict:
    """The one call that runs a workload governed across the mesh: place -> grant -> verify -> execute.

    Returns the full trace. If the plane blocks placement (fail-closed), no Grant is issued and
    nothing is dispatched.
    """
    import compute_plane as cp
    decision = cp.place(workload, policy, registry.availability())
    if not decision.get("backend"):
        return {"status": "blocked", "decision": decision}
    grant = grant_mod.issue_grant(binding=binding, capability=capability, decision=decision,
                                  attestation=attestation, constraints=constraints, signer=signer)
    execution = execute(workload, decision, grant, session_id=binding["session_id"],
                        verifier=verifier, apply=apply)
    return {"status": "ran", "backend": decision["backend"], "decision": decision,
            "grant_id": grant["grant_id"], "execution": execution}


if __name__ == "__main__":
    # demo: run the full spine for a sensitive GPU workload against a live mesh (dry-run dispatch).
    import mesh_telemetry as mt
    key = b"demo-executor-key"
    reg = mt.MeshRegistry()
    reg.heartbeat("slurm-1", "hpc-slurm", 100)
    reg.heartbeat("boinc-1", "volunteer-boinc", 500)
    att = grant_mod.attestation_bundle(spiffe_id="spiffe://sourceos/agent/demo",
                                       aum_digest="sha256:" + "ab" * 32, tpm_valid=True, cosign_valid=True)
    out = run_spine(
        {"name": "train", "sensitivity": "sensitive", "scalable": True, "needs_gpu": True,
         "effect": "compute", "image": "ghcr.io/sourceos/trainer:1", "command": "python train.py"},
        {"require_attestation": True}, registry=reg,
        binding={"spiffe_id": "spiffe://sourceos/agent/demo", "aum_digest": "sha256:" + "ab" * 32,
                 "session_id": "sess_demo1"},
        capability={"kind": "mcp_tool", "capability_ref": "capd://caps.compute.mesh-plane",
                    "capability_digest": "sha256:" + "cd" * 32, "effect": "compute"},
        attestation=att, constraints={"ops_allow": ["exec.run"]},
        signer=grant_mod.hmac_signer(key), verifier=grant_mod.hmac_verifier(key))
    print(json.dumps({"status": out["status"], "backend": out["backend"],
                      "grant_id": out["grant_id"],
                      "dispatch": out["execution"]["dispatch"]["kind"],
                      "receipt": out["execution"]["receipt"]["receipt_digest"]}, indent=2))
