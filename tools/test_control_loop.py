#!/usr/bin/env python3
"""Tests for the governed autonomous control loop. The safety properties are what matter: it acts
through the governed spine, decides each condition once per cooldown, records fail-closed
block/deny without acting ungoverned, and never lets one bad condition kill the loop."""
import control_loop as cl
import mcp_a2a_grant as g
import mesh_telemetry as mt

KEY = b"loop-test-key"
AUM = "sha256:" + "ab" * 32


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def _spine(reg, admission=None):
    kw = dict(
        registry=reg,
        binding={"spiffe_id": "spiffe://sourceos/agent/healer", "aum_digest": AUM, "session_id": "sess_loop1"},
        capability={"kind": "mcp_tool", "capability_ref": "capd://caps.x",
                    "capability_digest": "sha256:" + "cd" * 32, "effect": "exec"},
        attestation=g.attestation_bundle(spiffe_id="spiffe://sourceos/agent/healer", aum_digest=AUM,
                                         tpm_valid=True, cosign_valid=True),
        constraints={"ops_allow": ["exec.run"]},
        signer=g.hmac_signer(KEY), verifier=g.hmac_verifier(KEY))
    if admission is not None:
        kw["admission"] = admission
    return kw


def _wl(effect="exec", gpu=False, sensitivity="normal"):
    return {"name": "probe", "sensitivity": sensitivity, "scalable": gpu, "needs_gpu": gpu,
            "effect": effect, "command": "echo hi"}


def test_tick_remediates_a_firing_condition_through_the_governed_spine():
    reg = mt.MeshRegistry()
    reg.heartbeat("k", "k8s", 8)
    loop = cl.ControlLoop(sense=lambda: [{"key": "unhealthy:svc"}],
                          to_workload=lambda c: (_wl(), {}, 1.0), spine_kwargs=_spine(reg), clock=Clock())
    out = loop.tick()
    assert len(out) == 1 and out[0]["outcome"] == "ran" and out[0]["grant_id"]
    assert out[0]["receipt_digest"].startswith("sha256:")


def test_a_condition_is_decided_once_per_cooldown():
    reg = mt.MeshRegistry()
    reg.heartbeat("k", "k8s", 8)
    clk = Clock(1000.0)
    loop = cl.ControlLoop(sense=lambda: [{"key": "unhealthy:svc"}],
                          to_workload=lambda c: (_wl(), {}, 1.0), spine_kwargs=_spine(reg),
                          cooldown_s=300, clock=clk)
    assert loop.tick()[0]["outcome"] == "ran"
    clk.t = 1100.0                                  # within cooldown
    assert loop.tick()[0]["outcome"] == "suppressed"
    clk.t = 1400.0                                  # past the 300s cooldown
    assert loop.tick()[0]["outcome"] == "ran"
    assert len([r for r in loop.ledger() if r["outcome"] == "ran"]) == 2  # suppressed not ledgered


def test_fail_closed_block_is_recorded_and_the_loop_continues():
    reg = mt.MeshRegistry()
    reg.heartbeat("v", "volunteer-boinc", 500)      # only an untrusted backend is up
    loop = cl.ControlLoop(sense=lambda: [{"key": "c1"}, {"key": "c2"}],
                          to_workload=lambda c: (_wl(sensitivity="sensitive"), {}, 1.0),
                          spine_kwargs=_spine(reg), clock=Clock())
    out = loop.tick()
    assert [r["outcome"] for r in out] == ["blocked", "blocked"]  # both blocked, neither crashed
    assert all(r["grant_id"] is None for r in out)                # nothing was granted


def test_fail_closed_quota_denies_the_second_gpu_remediation():
    import admission as adm
    reg = mt.MeshRegistry()
    reg.heartbeat("s", "hpc-slurm", 100)
    ac = adm.AdmissionController({"spiffe://sourceos/agent/healer": {"gpu_max": 1}})
    loop = cl.ControlLoop(sense=lambda: [{"key": "g1"}, {"key": "g2"}],
                          to_workload=lambda c: (_wl(effect="exec", gpu=True), {}, 1.0),
                          spine_kwargs=_spine(reg, admission=ac), clock=Clock())
    assert [r["outcome"] for r in loop.tick()] == ["ran", "denied"]


def test_a_raising_remediation_does_not_kill_the_loop():
    reg = mt.MeshRegistry()
    reg.heartbeat("k", "k8s", 8)

    def to_wl(c):
        if c["key"] == "bad":
            raise ValueError("boom")
        return (_wl(), {}, 1.0)

    loop = cl.ControlLoop(sense=lambda: [{"key": "bad"}, {"key": "good"}],
                          to_workload=to_wl, spine_kwargs=_spine(reg), clock=Clock())
    out = loop.tick()
    assert out[0]["outcome"] == "error" and "boom" in out[0]["error"]
    assert out[1]["outcome"] == "ran"               # loop carried on to the next condition


def test_run_executes_multiple_ticks():
    reg = mt.MeshRegistry()
    reg.heartbeat("k", "k8s", 8)
    seen = [0]

    def sense():
        seen[0] += 1
        return [{"key": f"c{seen[0]}"}]              # a fresh condition each tick

    loop = cl.ControlLoop(sense=sense, to_workload=lambda c: (_wl(), {}, 1.0),
                          spine_kwargs=_spine(reg), clock=Clock())
    ledger = loop.run(max_ticks=3)
    assert len([r for r in ledger if r["outcome"] == "ran"]) == 3


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
    print(f"ok: {len(fns)} control-loop tests passed")
    sys.exit(0)
