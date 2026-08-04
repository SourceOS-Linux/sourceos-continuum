#!/usr/bin/env python3
"""Tests for the governed compute plane — the placement broker is the differentiator, so its
governance (sensitive work never goes untrusted; fail-closed when nothing is allowed) is nailed
down hard, alongside the scale-out and preference logic."""
import compute_plane as cp

FULL = {b: 100 for b in cp.BACKENDS}  # whole mesh up, plenty of capacity


def test_sensitive_workload_refuses_every_untrusted_backend():
    d = cp.place({"sensitivity": "sensitive", "scalable": True}, {}, FULL)
    assert d["backend_trust"] == "trusted"
    for bid in ("p2p-mesh", "volunteer-boinc", "blockchain-rlc"):
        assert "untrusted" in d["excluded"][bid]


def test_sensitive_scalable_gpu_lands_on_hpc_not_volunteer():
    # highest-elasticity *trusted* GPU backend is hpc-slurm; volunteer-boinc (elasticity 10) is barred.
    d = cp.place({"sensitivity": "sensitive", "scalable": True, "needs_gpu": True}, {}, FULL)
    assert d["backend"] == "hpc-slurm"


def test_normal_scalable_scales_out_to_the_biggest_grid():
    # no sensitivity bar -> the global volunteer grid (elasticity 10) wins.
    d = cp.place({"sensitivity": "normal", "scalable": True}, {}, FULL)
    assert d["backend"] == "volunteer-boinc"
    assert d["attestation_required"] is True  # untrusted backend always demands attestation


def test_nonscalable_workload_stays_small():
    d = cp.place({"sensitivity": "normal", "scalable": False}, {}, FULL)
    assert d["backend"] == "local"


def test_project_policy_restricts_allowed_backends():
    d = cp.place({"sensitivity": "normal", "scalable": True},
                 {"allowed_backends": ["local", "k8s"]}, FULL)
    assert d["backend"] == "k8s"
    assert "hpc-slurm" in d["excluded"]


def test_explicit_preference_wins_over_scale_out():
    d = cp.place({"sensitivity": "normal", "scalable": True},
                 {"prefer": ["wasm-edge"]}, FULL)
    assert d["backend"] == "wasm-edge"
    assert d["reason"] == "project preference"


def test_needs_gpu_excludes_non_gpu_backends():
    d = cp.place({"sensitivity": "normal", "scalable": True, "needs_gpu": True},
                 {"allowed_backends": ["local", "wasm-edge", "k8s"]}, FULL)
    assert d["backend"] == "k8s"  # only GPU-capable candidate
    assert "no GPU" in d["excluded"]["wasm-edge"]


def test_scale_out_wanted_but_only_local_up_runs_local_and_says_so():
    d = cp.place({"sensitivity": "normal", "scalable": True}, {}, {"local": 1})
    assert d["backend"] == "local"
    assert d["placement"] == "scheduled"
    assert "locally" in d["reason"]  # honest: we couldn't actually scale out


def test_fail_closed_blocks_when_no_candidate_and_no_local():
    # sensitive workload, only untrusted backends up, local not available -> blocked, shipped nowhere.
    d = cp.place({"sensitivity": "sensitive", "scalable": True}, {},
                 {"volunteer-boinc": 500})
    assert d["backend"] is None
    assert d["placement"] == "blocked"


def test_fail_closed_blocks_gpu_work_rather_than_degrade_to_nongpu_local():
    # only a non-GPU local box is up; we must NOT silently run GPU work on it.
    d = cp.place({"sensitivity": "normal", "scalable": True, "needs_gpu": True}, {}, {"local": 1})
    assert d["backend"] is None and d["placement"] == "blocked"


def test_receipt_seal_is_deterministic_and_covers_the_decision():
    d = cp.place({"sensitivity": "normal", "scalable": True}, {"prefer": ["k8s"]}, FULL)
    assert d["receipt_digest"].startswith("sha256:")
    reseal = cp._seal({k: v for k, v in d.items() if k != "receipt_digest"})
    assert reseal == d["receipt_digest"]


def test_needs_firewall_only_a_backend_that_provably_provides_the_need_qualifies():
    # NEEDS a TEE -> only hpc-slurm (provably tee) qualifies, even though k8s is preferred + available.
    d = cp.place({"sensitivity": "normal", "scalable": True, "needs": {"tee": True}},
                 {"prefer": ["k8s"]}, {b: 100 for b in cp.BACKENDS})
    assert d["backend"] == "hpc-slurm"
    assert "NEEDS firewall" in d["excluded"]["k8s"]  # a Want (prefer) can't satisfy a Need


def test_needs_firewall_blocks_when_no_backend_provably_provides_the_need():
    d = cp.place({"sensitivity": "normal", "scalable": True, "needs": {"residency": "eu"}},
                 {}, {b: 100 for b in cp.BACKENDS})
    assert d["backend"] is None  # fail-closed: nothing provably provides residency:eu


def test_needs_no_egress_selects_only_local():
    d = cp.place({"sensitivity": "normal", "scalable": False, "needs": {"no_egress": True}},
                 {}, {b: 100 for b in cp.BACKENDS})
    assert d["backend"] == "local"


def test_no_needs_is_backward_compatible():
    d = cp.place({"sensitivity": "normal", "scalable": True}, {}, {b: 100 for b in cp.BACKENDS})
    assert d["backend"] == "volunteer-boinc"  # unchanged


def test_connector_backend_is_external_barred_for_sensitive_but_open_to_normal():
    # a vendor connector is untrusted: sensitive work refuses it (blocks); normal work may use it.
    blocked = cp.place({"sensitivity": "sensitive", "scalable": True},
                       {"allowed_backends": ["connector"]}, {"connector": 100})
    assert blocked["backend"] is None
    ok = cp.place({"sensitivity": "normal", "scalable": True},
                  {"allowed_backends": ["connector"]}, {"connector": 100})
    assert ok["backend"] == "connector"


def test_backends_view_exposes_the_whole_mesh_with_availability():
    view = cp.backends_view({"volunteer-boinc": 200})
    ids = {b["id"] for b in view["backends"]}
    assert {"local", "hpc-slurm", "wasm-edge", "p2p-mesh", "volunteer-boinc", "blockchain-rlc"} <= ids
    boinc = next(b for b in view["backends"] if b["id"] == "volunteer-boinc")
    assert boinc["trust"] == "untrusted" and boinc["available"] == 200


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
    print(f"ok: {len(fns)} compute-plane tests passed")
    sys.exit(0)
