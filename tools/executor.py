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
        # Always set requests + limits (with small defaults) so pods are admissible under a DevSpace
        # ResourceQuota, which requires them.
        res = workload.get("resource", {})
        requests = {"cpu": str(res.get("cpu", "100m")), "memory": str(res.get("mem", "128Mi"))}
        limits = dict(requests)
        if workload.get("needs_gpu"):
            limits["nvidia.com/gpu"] = "1"
        container = {"name": "workload",
                     "image": workload.get("image") or "busybox:1.36",  # or-default: "" is falsy but present
                     "command": shlex.split(workload["command"]) if workload.get("command") else ["true"],
                     "resources": {"requests": requests, "limits": limits}}
        pod_spec = {"restartPolicy": "Never", "containers": [container]}
        # Mount the agent-machine's persistent inception mount (a TopoLVM-backed PVC) when asked.
        pvc = workload.get("inception_pvc")
        if pvc:
            container["volumeMounts"] = [{"name": "inception", "mountPath": "/var/lib/sourceos/inception"}]
            pod_spec["volumes"] = [{"name": "inception", "persistentVolumeClaim": {"claimName": pvc}}]
        job_spec = {"backoffLimit": 0, "ttlSecondsAfterFinished": 3600,
                    "template": {"metadata": {"labels": {"sourceos.io/grant-id": grant["grant_id"]}},
                                 "spec": pod_spec}}
        # Parallel / MPI job (the IBM Parallel Environment POE pattern): an Indexed Job runs N tasks,
        # each getting JOB_COMPLETION_INDEX as its rank.
        parallelism = int(workload.get("parallelism", 1))
        if parallelism > 1:
            job_spec["parallelism"] = parallelism
            job_spec["completions"] = int(workload.get("completions", parallelism))
            job_spec["completionMode"] = "Indexed"
        return {
            "apiVersion": "batch/v1", "kind": "Job",
            "metadata": {"generateName": f"{workload.get('name', 'wl')}-",
                         "labels": {"sourceos.io/grant-id": grant["grant_id"],
                                    "sourceos.io/session": grant["binding"].get("session_id", ""),
                                    "sourceos.io/backend": "k8s"}},
            "spec": job_spec,
        }

    def dispatch(self, workload, decision, grant, *, apply):
        import os
        context = os.environ.get("SOURCEOS_KUBE_CONTEXT")
        namespace = os.environ.get("SOURCEOS_KUBE_NAMESPACE", "sourceos-mesh")
        manifest = self.manifest(workload, decision, grant)
        manifest["metadata"]["namespace"] = namespace
        if not apply:
            return {"kind": "k8s", "applied": False, "namespace": namespace, "manifest": manifest}
        # Safety: NEVER dispatch to whatever kube-context happens to be current (that could be prod).
        # Applying requires an explicit target context named in SOURCEOS_KUBE_CONTEXT.
        if not context:
            return {"kind": "k8s", "applied": False, "namespace": namespace, "manifest": manifest,
                    "reason": "refusing to apply without SOURCEOS_KUBE_CONTEXT — won't dispatch to the current context"}
        if not shutil.which("kubectl"):
            return {"kind": "k8s", "applied": False, "namespace": namespace, "manifest": manifest,
                    "reason": "kubectl not found"}
        # `create`, not `apply`: a Job is one-shot + immutable, and `apply` rejects generateName.
        cmd = ["kubectl", "--context", context, "create", "-n", namespace, "-f", "-"]
        proc = subprocess.run(cmd, input=json.dumps(manifest), capture_output=True, text=True, timeout=60)
        return {"kind": "k8s", "applied": proc.returncode == 0, "namespace": namespace,
                "context": context, "manifest": manifest,
                "kubectl": proc.stdout.strip() or proc.stderr.strip()}


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


class SlurmAdapter:
    """HPC/SLURM: emits a real sbatch script (the IBM Parallel Environment POE pattern — N tasks via
    --ntasks, launched with srun for MPI ranks) and submits it via `ssh <login> sbatch` when a login
    node is configured (SOURCEOS_SLURM_LOGIN), else emits the script."""
    backend = "hpc-slurm"

    def sbatch_script(self, workload, grant):
        ntasks = int(workload.get("parallelism", 1))
        nodes = int(workload.get("nodes", 1))
        lines = ["#!/bin/bash",
                 f"#SBATCH --job-name={workload.get('name', 'sourceos')}",
                 f"#SBATCH --ntasks={ntasks}",
                 f"#SBATCH --nodes={nodes}",
                 f"#SBATCH --comment=grant:{grant['grant_id']}"]
        if workload.get("needs_gpu"):
            lines.append("#SBATCH --gres=gpu:1")
        cmd = workload.get("command") or "true"
        lines.append(f"srun {cmd}" if ntasks > 1 else cmd)  # srun launches the N MPI ranks
        return "\n".join(lines) + "\n"

    def dispatch(self, workload, decision, grant, *, apply):
        import os
        script = self.sbatch_script(workload, grant)
        login = os.environ.get("SOURCEOS_SLURM_LOGIN")
        if apply and login and shutil.which("ssh"):
            proc = subprocess.run(["ssh", login, "sbatch"], input=script,
                                  capture_output=True, text=True, timeout=60)
            return {"kind": "hpc-slurm", "applied": proc.returncode == 0, "script": script,
                    "login": login, "sbatch": proc.stdout.strip() or proc.stderr.strip()}
        return {"kind": "hpc-slurm", "applied": False, "script": script,
                "note": "set SOURCEOS_SLURM_LOGIN to submit via `ssh <login> sbatch`"}


class ConnectorAdapter:
    """A remote connector call (Gemini/OpenAI/Claude Files API, or an MCP tool) as a GOVERNED
    dispatch — the same materialize->handle->dispatch->result shape as a compute job, gated by the
    same Grant. Emits the connector-call descriptor; the grant-bound connector runtime makes the
    actual call."""
    backend = "connector"

    def dispatch(self, workload, decision, grant, *, apply):
        return {"kind": "connector", "applied": False,
                "call": {"connector": workload.get("connector", "mcp"),
                         "operation": workload.get("operation", "tools/call"),
                         "artifact_ref": workload.get("artifact_ref"),
                         "effect": grant["capability"].get("effect"),
                         "grant_id": grant["grant_id"],
                         "session": grant["binding"].get("session_id")},
                "note": "grant-bound connector call (materialize -> handle -> dispatch -> result)"}


def default_adapters() -> dict:
    ad = {LocalAdapter().backend: LocalAdapter(), K8sAdapter().backend: K8sAdapter(),
          SlurmAdapter().backend: SlurmAdapter(), ConnectorAdapter().backend: ConnectorAdapter()}
    for b in ("wasm-edge", "p2p-mesh", "volunteer-boinc", "blockchain-rlc"):
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
              attestation: dict, constraints: dict, signer, verifier, apply: bool = False,
              admission=None, admission_key: str | None = None, cost: float = 1.0) -> dict:
    """The one call that runs a workload governed across the mesh: admit -> place -> grant -> verify
    -> execute -> charge.

    Returns the full trace. Fail-closed at every stage: over quota -> denied (no Grant minted); the
    plane blocks placement -> blocked; neither issues a Grant nor dispatches anything.
    """
    import compute_plane as cp
    akey = admission_key or binding["spiffe_id"]
    if admission is not None:
        adm = admission.admit(akey, workload, cost=cost)
        if not adm["admitted"]:
            return {"status": "denied", "admission": adm}
    decision = cp.place(workload, policy, registry.availability())
    if not decision.get("backend"):
        return {"status": "blocked", "decision": decision}
    grant = grant_mod.issue_grant(binding=binding, capability=capability, decision=decision,
                                  attestation=attestation, constraints=constraints, signer=signer)
    execution = execute(workload, decision, grant, session_id=binding["session_id"],
                        verifier=verifier, apply=apply)
    result = {"status": "ran", "backend": decision["backend"], "decision": decision,
              "grant_id": grant["grant_id"], "execution": execution}
    if admission is not None:
        result["admission"] = admission.charge(akey, workload, cost=cost)
    return result


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
