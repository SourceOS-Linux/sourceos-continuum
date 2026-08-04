#!/usr/bin/env python3
"""Tests for quota + admission. Load-bearing: fail-closed over budget (concurrent / gpu / cost),
correct charge/release accounting, per-subject isolation, and that the spine actually refuses to
place/grant/dispatch an over-quota subject."""
import admission as adm
import executor as ex
import mcp_a2a_grant as g
import mesh_telemetry as mt

KEY = b"adm-test-key"
DEV = "spiffe://sourceos/agent/dev"


def test_admits_within_budget():
    ac = adm.AdmissionController()
    r = ac.admit(DEV, {"needs_gpu": True}, cost=1.0)
    assert r["admitted"] and r["exceeded"] == []


def test_denies_over_concurrency():
    ac = adm.AdmissionController({DEV: {"max_concurrent": 1}})
    ac.charge(DEV, {})
    r = ac.admit(DEV, {})
    assert not r["admitted"] and "max_concurrent" in r["exceeded"]


def test_denies_over_gpu():
    ac = adm.AdmissionController({DEV: {"gpu_max": 1}})
    ac.charge(DEV, {"needs_gpu": True})
    r = ac.admit(DEV, {"needs_gpu": True})
    assert not r["admitted"] and "gpu_max" in r["exceeded"]


def test_denies_over_cost_budget():
    ac = adm.AdmissionController({DEV: {"cost_budget": 5.0}})
    ac.charge(DEV, {}, cost=4.5)
    r = ac.admit(DEV, {}, cost=1.0)  # 4.5 + 1.0 = 5.5 > 5.0
    assert not r["admitted"] and "cost_budget" in r["exceeded"]


def test_release_frees_concurrency_and_gpu_but_not_spend():
    ac = adm.AdmissionController()
    ac.charge(DEV, {"needs_gpu": True}, cost=3.0)
    ac.release(DEV, {"needs_gpu": True})
    u = ac.usage(DEV)
    assert u["concurrent"] == 0 and u["gpu"] == 0 and u["cost"] == 3.0  # spend stays spent


def test_subjects_have_isolated_budgets():
    ac = adm.AdmissionController({DEV: {"max_concurrent": 1}})
    ac.charge(DEV, {})
    other = "spiffe://sourceos/agent/other"
    assert ac.admit(DEV, {})["admitted"] is False       # dev is full
    assert ac.admit(other, {})["admitted"] is True       # other is independent


def test_default_quota_applies_to_unknown_subject():
    ac = adm.AdmissionController()
    assert ac.quota_for("spiffe://who/dis") == adm.DEFAULT_QUOTA


def test_ledger_persists_consumption_across_controllers():
    import pathlib
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / "usage.json"
        ac1 = adm.AdmissionController({DEV: {"max_concurrent": 1}}, ledger_path=p)
        ac1.charge(DEV, {})
        ac2 = adm.AdmissionController({DEV: {"max_concurrent": 1}}, ledger_path=p)  # fresh process
        assert ac2.admit(DEV, {})["admitted"] is False  # sees ac1's charge on disk


# ── integration with the spine ───────────────────────────────────────────────────────
def _spine_args(gpu):
    aum = "sha256:" + "ab" * 32
    reg = mt.MeshRegistry()
    reg.heartbeat("slurm", "hpc-slurm", 100)
    return dict(
        workload={"name": "t", "sensitivity": "normal", "scalable": True, "needs_gpu": gpu,
                  "effect": "compute", "command": "echo hi"},
        policy={}, registry=reg,
        binding={"spiffe_id": DEV, "aum_digest": aum, "session_id": "sess_adm01"},
        capability={"kind": "mcp_tool", "capability_ref": "capd://caps.x",
                    "capability_digest": "sha256:" + "cd" * 32, "effect": "compute"},
        attestation=g.attestation_bundle(spiffe_id=DEV, aum_digest=aum, tpm_valid=True, cosign_valid=True),
        constraints={"ops_allow": ["exec.run"]},
        signer=g.hmac_signer(KEY), verifier=g.hmac_verifier(KEY))


def test_spine_denies_over_quota_before_granting():
    ac = adm.AdmissionController({DEV: {"gpu_max": 1}})
    args = _spine_args(gpu=True)
    first = ex.run_spine(**args, admission=ac, cost=1.0)
    assert first["status"] == "ran" and first["admission"]["gpu"] == 1
    second = ex.run_spine(**_spine_args(gpu=True), admission=ac, cost=1.0)
    assert second["status"] == "denied"          # over gpu_max
    assert "grant_id" not in second               # no Grant minted, nothing dispatched
    assert "gpu_max" in second["admission"]["exceeded"]


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
    print(f"ok: {len(fns)} admission tests passed")
    sys.exit(0)
