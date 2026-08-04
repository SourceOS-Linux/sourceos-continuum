#!/usr/bin/env python3
"""Tests for the MCP-A2A Policy Authority (issue_grant) and fog-node Policy Gate (verify_grant).
Every fail-closed edge is exercised: no Grant without attestation or a real placement or a required
quorum; and at the node, a tampered / mis-sessioned / expired / over-reaching Grant is denied."""
import copy

import mcp_a2a_grant as g

KEY = b"unit-test-key"
SIGNER = g.hmac_signer(KEY)
VERIFIER = g.hmac_verifier(KEY)
GOOD_ATT = {"tpm_valid": True, "cosign_valid": True, "artifact_digest": "sha256:abc"}
SCHED = {"placement": "scheduled", "backend": "hpc-slurm", "backend_trust": "trusted",
         "receipt_digest": "sha256:feed"}


def _issue(**over):
    kw = dict(session_id="s1", subject="agent:noetica", capability="cap@0.1.0",
              decision=SCHED, attestation=GOOD_ATT,
              constraints={"allowed_ops": ["pty.attach", "fs.read"]}, signer=SIGNER, now=1000.0)
    kw.update(over)
    return g.issue_grant(**kw)


def test_issue_mints_a_signed_session_bound_grant():
    out = _issue()
    grant = out["grant"]
    assert grant["session_id"] == "s1" and grant["placement"]["node"] == "hpc-slurm"
    assert grant["expires_at"] == 1000.0 + 900.0
    assert VERIFIER(grant, out["signature"])  # signature checks out


def test_issue_refused_without_attestation():
    for bad in ({"tpm_valid": False, "cosign_valid": True}, {"tpm_valid": True, "cosign_valid": False}):
        try:
            _issue(attestation=bad)
            assert False, "should have refused"
        except g.GrantRefused as e:
            assert "attestation" in str(e)


def test_issue_refused_on_a_blocked_placement():
    try:
        _issue(decision={"placement": "blocked", "backend": None})
        assert False
    except g.GrantRefused as e:
        assert "placement" in str(e)


def test_issue_refused_when_quorum_required_but_insufficient():
    try:
        _issue(constraints={"allowed_ops": ["pty.attach"], "require_quorum": True, "quorum_threshold": 2},
               quorum_proof=["validator-A"])  # only 1 of 2
        assert False
    except g.GrantRefused as e:
        assert "quorum" in str(e)


def test_issue_succeeds_with_sufficient_quorum():
    out = _issue(constraints={"allowed_ops": ["pty.attach"], "require_quorum": True, "quorum_threshold": 2},
                 quorum_proof=["validator-A", "validator-B"])
    assert len(out["grant"]["quorum_proof"]) == 2


def test_gate_authorizes_a_valid_grant_for_a_permitted_op():
    out = _issue()
    res = g.verify_grant(out["grant"], out["signature"], session_id="s1",
                         verifier=VERIFIER, requested_op="pty.attach", now=1100.0)
    assert res["authorized"] is True


def test_gate_denies_a_tampered_grant():
    out = _issue()
    tampered = copy.deepcopy(out["grant"])
    tampered["placement"]["node"] = "volunteer-boinc"  # try to redirect to an untrusted node
    res = g.verify_grant(tampered, out["signature"], session_id="s1", verifier=VERIFIER, now=1100.0)
    assert res["authorized"] is False and "tamper" in res["reason"].lower()


def test_gate_denies_wrong_session():
    out = _issue()
    res = g.verify_grant(out["grant"], out["signature"], session_id="s2", verifier=VERIFIER, now=1100.0)
    assert res["authorized"] is False and "session" in res["reason"]


def test_gate_denies_expired_grant():
    out = _issue()  # expires at 1900
    res = g.verify_grant(out["grant"], out["signature"], session_id="s1", verifier=VERIFIER, now=2000.0)
    assert res["authorized"] is False and "expired" in res["reason"]


def test_gate_denies_op_outside_constraints():
    out = _issue()  # allows pty.attach, fs.read
    res = g.verify_grant(out["grant"], out["signature"], session_id="s1",
                         verifier=VERIFIER, requested_op="fs.write", now=1100.0)
    assert res["authorized"] is False and "fs.write" in res["reason"]


def test_gate_carries_redactions_through_to_the_node():
    out = _issue(constraints={"allowed_ops": ["pty.attach"], "redactions": ["env.SECRET"]})
    res = g.verify_grant(out["grant"], out["signature"], session_id="s1",
                         verifier=VERIFIER, requested_op="pty.attach", now=1100.0)
    assert res["authorized"] is True and res["redactions"] == ["env.SECRET"]


def test_end_to_end_place_then_grant_then_gate():
    import compute_plane as cp
    decision = cp.place({"sensitivity": "sensitive", "scalable": True, "needs_gpu": True},
                        {"require_attestation": True}, {"hpc-slurm": 100})
    assert decision["backend"] == "hpc-slurm"  # sensitive -> trusted HPC
    out = g.issue_grant(session_id="s9", subject="agent:memory-mesh", capability="caps.compute.mesh-plane@0.1.0",
                        decision=decision, attestation=GOOD_ATT,
                        constraints={"allowed_ops": ["exec.run"]}, signer=SIGNER, now=5000.0)
    res = g.verify_grant(out["grant"], out["signature"], session_id="s9",
                         verifier=VERIFIER, requested_op="exec.run", now=5001.0)
    assert res["authorized"] is True


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
    print(f"ok: {len(fns)} mcp-a2a-grant tests passed")
    sys.exit(0)
