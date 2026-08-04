#!/usr/bin/env python3
"""Tests for the execution spine. Two things matter most: (1) dispatch is real — a local subprocess
actually runs, a k8s Job manifest is actually well-formed and Grant-labelled; (2) it is fail-closed
on the Grant — a tampered / mis-sessioned / wrong-effect Grant dispatches NOTHING. Plus the full
place->grant->verify->execute spine end to end."""
import executor as ex
import mcp_a2a_grant as g
import mesh_telemetry as mt

KEY = b"exec-test-key"
SIGNER = g.hmac_signer(KEY)
VERIFIER = g.hmac_verifier(KEY)
AUM = "sha256:" + "ab" * 32
CAPDIG = "sha256:" + "cd" * 32
BINDING = {"spiffe_id": "spiffe://sourceos/agent/x", "aum_digest": AUM, "session_id": "sess_exec1"}
CAP = {"kind": "mcp_tool", "capability_ref": "capd://caps.x", "capability_digest": CAPDIG, "effect": "exec"}
ATT = g.attestation_bundle(spiffe_id="spiffe://sourceos/agent/x", aum_digest=AUM,
                           tpm_valid=True, cosign_valid=True)


def _decision(backend):
    return {"placement": "scheduled", "backend": backend, "backend_trust": "trusted",
            "receipt_digest": "sha256:" + "de" * 32}


def _grant(decision, effect="exec"):
    return g.issue_grant(binding=BINDING, capability={**CAP, "effect": effect}, decision=decision,
                         attestation=ATT, constraints={"ops_allow": ["exec.run"]}, signer=SIGNER)


# ── dispatch is real ─────────────────────────────────────────────────────────────────
def test_local_adapter_runs_a_real_subprocess():
    d = _decision("local")
    res = ex.execute({"command": "echo hello-mesh", "effect": "exec"}, d, _grant(d, "exec"),
                     session_id="sess_exec1", verifier=VERIFIER, apply=True)
    assert res["dispatch"]["applied"] and res["dispatch"]["exit_code"] == 0
    assert "hello-mesh" in res["dispatch"]["stdout"]
    assert res["receipt"]["receipt_digest"].startswith("sha256:")


def test_local_adapter_dry_run_plans_but_does_not_execute():
    d = _decision("local")
    res = ex.execute({"command": "echo x", "effect": "exec"}, d, _grant(d, "exec"),
                     session_id="sess_exec1", verifier=VERIFIER, apply=False)
    assert res["dispatch"]["applied"] is False and res["dispatch"]["planned"] == "echo x"


def test_k8s_adapter_emits_a_valid_grant_labelled_job():
    d = _decision("k8s")
    grant = _grant(d, "compute")
    res = ex.execute({"name": "trainer", "image": "img:1", "command": "python x.py",
                      "needs_gpu": True, "resource": {"cpu": 2, "mem": "4Gi"}, "effect": "compute"},
                     d, grant, session_id="sess_exec1", verifier=VERIFIER, apply=False)
    m = res["dispatch"]["manifest"]
    assert m["apiVersion"] == "batch/v1" and m["kind"] == "Job"
    c = m["spec"]["template"]["spec"]["containers"][0]
    assert c["image"] == "img:1" and c["command"] == ["python", "x.py"]
    assert c["resources"]["limits"]["nvidia.com/gpu"] == "1"
    assert m["metadata"]["labels"]["sourceos.io/grant-id"] == grant["grant_id"]
    assert m["spec"]["template"]["spec"]["restartPolicy"] == "Never"


def test_descriptor_adapter_emits_a_backend_specific_descriptor():
    d = _decision("hpc-slurm")
    res = ex.execute({"command": "srun train", "effect": "compute"}, d, _grant(d, "compute"),
                     session_id="sess_exec1", verifier=VERIFIER)
    assert res["dispatch"]["kind"] == "hpc-slurm"
    assert res["dispatch"]["descriptor"]["backend"] == "hpc-slurm"
    assert res["dispatch"]["descriptor"]["executor_ref"] == "node://hpc-slurm"


# ── fail-closed on the Grant ─────────────────────────────────────────────────────────
def test_dispatch_refused_on_tampered_grant():
    d = _decision("local")
    grant = _grant(d, "exec")
    grant["capability"]["effect"] = "egress"  # tamper -> signature breaks
    try:
        ex.execute({"command": "echo x", "effect": "egress"}, d, grant,
                   session_id="sess_exec1", verifier=VERIFIER, apply=True)
        assert False, "should have refused"
    except ex.DispatchRefused as e:
        assert "tamper" in str(e).lower() or "signature" in str(e).lower()


def test_dispatch_refused_when_effect_not_granted():
    d = _decision("local")
    grant = _grant(d, "read")  # granted read...
    try:
        ex.execute({"command": "echo x", "effect": "exec"}, d, grant,  # ...but asking exec
                   session_id="sess_exec1", verifier=VERIFIER, apply=True)
        assert False
    except ex.DispatchRefused as e:
        assert "effect" in str(e)


def test_dispatch_refused_on_wrong_session():
    d = _decision("local")
    try:
        ex.execute({"command": "echo x", "effect": "exec"}, d, _grant(d, "exec"),
                   session_id="sess_WRONG", verifier=VERIFIER, apply=True)
        assert False
    except ex.DispatchRefused as e:
        assert "session" in str(e)


def test_dispatch_refused_for_unknown_backend():
    d = _decision("quantum-foo")
    try:
        ex.execute({"command": "echo x", "effect": "exec"}, d, _grant(d, "exec"),
                   session_id="sess_exec1", verifier=VERIFIER)
        assert False
    except ex.DispatchRefused as e:
        assert "adapter" in str(e)


# ── the whole spine ──────────────────────────────────────────────────────────────────
def test_run_spine_end_to_end_places_grants_verifies_and_dispatches():
    reg = mt.MeshRegistry()
    reg.heartbeat("slurm", "hpc-slurm", 100)
    reg.heartbeat("boinc", "volunteer-boinc", 500)  # bigger, but untrusted
    out = ex.run_spine(
        {"name": "t", "sensitivity": "sensitive", "scalable": True, "needs_gpu": True,
         "effect": "compute", "command": "python t.py"},
        {"require_attestation": True}, registry=reg, binding=BINDING,
        capability={**CAP, "effect": "compute"}, attestation=ATT,
        constraints={"ops_allow": ["exec.run"]}, signer=SIGNER, verifier=VERIFIER)
    assert out["status"] == "ran"
    assert out["backend"] == "hpc-slurm"  # sensitive+gpu -> trusted HPC, never the volunteer grid
    assert out["execution"]["dispatch"]["kind"] == "hpc-slurm"
    assert out["execution"]["receipt"]["receipt_digest"].startswith("sha256:")


def test_run_spine_blocks_fail_closed_and_dispatches_nothing():
    reg = mt.MeshRegistry()
    reg.heartbeat("boinc", "volunteer-boinc", 500)  # only an untrusted backend is up
    out = ex.run_spine(
        {"sensitivity": "sensitive", "scalable": True, "effect": "compute"},
        {}, registry=reg, binding=BINDING, capability={**CAP, "effect": "compute"},
        attestation=ATT, constraints={}, signer=SIGNER, verifier=VERIFIER)
    assert out["status"] == "blocked" and out["decision"]["backend"] is None
    assert "execution" not in out  # nothing was dispatched


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
    print(f"ok: {len(fns)} executor spine tests passed")
    sys.exit(0)
