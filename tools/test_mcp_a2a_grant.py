#!/usr/bin/env python3
"""Tests for the MCP-A2A Policy Authority (issue_grant) + fog-node Policy Gate (verify_grant).

Two things are proven: (1) the emitted Grant / QuorumProof / AttestationBundle CONFORM to the
canonical mcp-a2a-zero-trust schemas (validated against the vendored schemas/a2a/*.schema.json — so
this is real conformance, not a shape I made up); (2) every fail-closed edge holds — no Grant without
attestation / a real placement / a required quorum, and at the node a tampered / mis-sessioned /
expired / over-reaching Grant is denied."""
import json
import pathlib
import re
from datetime import datetime, timezone

import mcp_a2a_grant as g

KEY = b"unit-test-key"
SIGNER = g.hmac_signer(KEY)
VERIFIER = g.hmac_verifier(KEY)
NOW = datetime(2026, 1, 7, 0, 0, 0, tzinfo=timezone.utc)
AUM = "sha256:" + "ab" * 32
CAPDIG = "sha256:" + "cd" * 32
SCHED = {"placement": "scheduled", "backend": "hpc-slurm", "backend_trust": "trusted",
         "receipt_digest": "sha256:" + "de" * 32}

BINDING = {"spiffe_id": "spiffe://sourceos/agent/x", "aum_digest": AUM, "session_id": "sess_unit1"}
CAPABILITY = {"kind": "mcp_tool", "capability_ref": "capd://caps.dev.devspace-inner-loop",
              "capability_digest": CAPDIG, "effect": "exec", "server": "shell.runtime", "tool": "pty"}


def _att():
    return g.attestation_bundle(spiffe_id="spiffe://sourceos/agent/x", aum_digest=AUM,
                                tpm_valid=True, cosign_valid=True)


def _quorum(nsigs):
    return {"rule": "2of3-human",
            "validators": ["spiffe://validators/h1", "spiffe://validators/h2", "spiffe://validators/h3"],
            "signed_payload_hash": "sha256:" + "11" * 32,
            "signatures": [{"kind": "human", "spiffe_id": f"spiffe://validators/h{i + 1}",
                            "sig": "MEUCIQD" + "fake" * 4} for i in range(nsigs)]}


def _issue(**over):
    kw = dict(binding=BINDING, capability=CAPABILITY, decision=SCHED, attestation=_att(),
              constraints={"ops_allow": ["pty.attach", "fs.read"], "paths_allow": ["$HOME/**"]},
              signer=SIGNER, now=NOW)
    kw.update(over)
    return g.issue_grant(**kw)


# ── canonical-schema conformance (dependency-free JSON-Schema subset validator) ───────────
def _load_schema(name):
    p = pathlib.Path(__file__).resolve().parent.parent / "schemas" / "a2a" / name
    return json.loads(p.read_text())


def _conformance_errors(node, schema, path="$"):
    errs = []
    t = schema.get("type")
    if t == "object":
        if not isinstance(node, dict):
            return [f"{path}: expected object"]
        for r in schema.get("required", []):
            if r not in node:
                errs.append(f"{path}: missing required '{r}'")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for k in node:
                if k not in props:
                    errs.append(f"{path}: unexpected property '{k}'")
        for k, v in node.items():
            if k in props and "$ref" not in props[k]:  # $ref'd subschemas validated on their own
                errs += _conformance_errors(v, props[k], f"{path}.{k}")
    elif t == "array":
        if not isinstance(node, list):
            return [f"{path}: expected array"]
        if schema.get("items"):
            for i, e in enumerate(node):
                errs += _conformance_errors(e, schema["items"], f"{path}[{i}]")
    if "enum" in schema and node not in schema["enum"]:
        errs.append(f"{path}: {node!r} not in enum {schema['enum']}")
    if "pattern" in schema and isinstance(node, str) and not re.search(schema["pattern"], node):
        errs.append(f"{path}: {node!r} does not match {schema['pattern']}")
    return errs


def test_emitted_grant_conforms_to_canonical_grant_schema():
    errs = _conformance_errors(_issue(), _load_schema("grant.schema.json"))
    assert errs == [], errs


def test_grant_with_quorum_still_conforms_and_quorum_matches_its_schema():
    grant = _issue(constraints={"ops_allow": ["deploy"], "require_quorum": True, "quorum_threshold": 2},
                   quorum_proof=_quorum(2))
    assert _conformance_errors(grant, _load_schema("grant.schema.json")) == []
    assert _conformance_errors(grant["quorum_proof"], _load_schema("quorum_proof.schema.json")) == []


def test_attestation_bundle_conforms_to_canonical_schema():
    assert _conformance_errors(_att(), _load_schema("attestation_bundle.schema.json")) == []


# ── Policy Authority: Attest → Decide → Grant, fail-closed ────────────────────────────────
def test_issue_mints_a_session_bound_signed_grant():
    grant = _issue()
    assert grant["binding"]["session_id"] == "sess_unit1"
    assert grant["capability"]["executor_ref"] == "node://hpc-slurm"  # bound the chosen fog node
    assert grant["issued_at"] == "2026-01-07T00:00:00Z" and grant["expires_at"] == "2026-01-07T00:15:00Z"
    body = {k: v for k, v in grant.items() if k != "sig"}
    assert VERIFIER(body, grant["sig"]["sig"]) and grant["sig"]["issuer"] == g.ISSUER


def test_issue_refused_without_attestation():
    bad = g.attestation_bundle(spiffe_id="s", aum_digest=AUM, tpm_valid=True, cosign_valid=False)
    try:
        _issue(attestation=bad)
        assert False
    except g.GrantRefused as e:
        assert "attestation" in str(e)


def test_issue_refused_on_blocked_placement():
    try:
        _issue(decision={"placement": "blocked", "backend": None})
        assert False
    except g.GrantRefused as e:
        assert "placement" in str(e)


def test_issue_refused_when_quorum_required_but_insufficient():
    try:
        _issue(constraints={"ops_allow": ["deploy"], "require_quorum": True, "quorum_threshold": 2},
               quorum_proof=_quorum(1))
        assert False
    except g.GrantRefused as e:
        assert "quorum" in str(e)


# ── fog-node Policy Gate: canonical tool_grant.validate, fail-closed ──────────────────────
def _at(minute):
    return datetime(2026, 1, 7, 0, minute, 0, tzinfo=timezone.utc)


def test_gate_authorizes_a_valid_grant_for_a_permitted_effect_and_op():
    res = g.verify_grant(_issue(), session_id="sess_unit1", verifier=VERIFIER,
                         requested_effect="exec", requested_op="pty.attach", now=_at(5))
    assert res["operation"] == "tool_grant.validate"
    assert res["result"] == {"valid": True, "expired": False, "revoked": False,
                             "reason": "Grant is active and within TTL; session-bound; op permitted"}


def test_gate_denies_a_tampered_grant():
    grant = _issue()
    grant["capability"]["executor_ref"] = "node://volunteer-boinc"  # redirect to an untrusted node
    res = g.verify_grant(grant, session_id="sess_unit1", verifier=VERIFIER, now=_at(5))
    assert res["result"]["valid"] is False and "tamper" in res["result"]["reason"].lower()


def test_gate_denies_wrong_session():
    res = g.verify_grant(_issue(), session_id="sess_other", verifier=VERIFIER, now=_at(5))
    assert res["result"]["valid"] is False and "session" in res["result"]["reason"]


def test_gate_denies_expired_grant():
    res = g.verify_grant(_issue(), session_id="sess_unit1", verifier=VERIFIER, now=_at(20))
    assert res["result"]["valid"] is False and res["result"]["expired"] is True


def test_gate_denies_effect_outside_grant():
    res = g.verify_grant(_issue(), session_id="sess_unit1", verifier=VERIFIER,
                         requested_effect="write", now=_at(5))
    assert res["result"]["valid"] is False and "write" in res["result"]["reason"]


def test_gate_denies_op_outside_constraints():
    res = g.verify_grant(_issue(), session_id="sess_unit1", verifier=VERIFIER,
                         requested_op="fs.write", now=_at(5))
    assert res["result"]["valid"] is False and "fs.write" in res["result"]["reason"]


def test_end_to_end_place_then_grant_then_gate():
    import compute_plane as cp
    decision = cp.place({"sensitivity": "sensitive", "scalable": True, "needs_gpu": True},
                        {"require_attestation": True}, {"hpc-slurm": 100})
    assert decision["backend"] == "hpc-slurm"
    grant = g.issue_grant(binding=BINDING, capability={**CAPABILITY, "effect": "compute"},
                          decision=decision, attestation=_att(),
                          constraints={"ops_allow": ["exec.run"]}, signer=SIGNER, now=NOW)
    assert _conformance_errors(grant, _load_schema("grant.schema.json")) == []
    res = g.verify_grant(grant, session_id="sess_unit1", verifier=VERIFIER,
                         requested_effect="compute", requested_op="exec.run", now=_at(1))
    assert res["result"]["valid"] is True


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
    print(f"ok: {len(fns)} mcp-a2a-grant conformance+gate tests passed")
    sys.exit(0)
