#!/usr/bin/env python3
"""MCP-A2A Policy Authority + fog-node Policy Gate — CONFORMS to the canonical mcp-a2a-zero-trust
schemas (see schemas/a2a/, vendored + hash-pinned from SourceOS-Linux/mcp-a2a-zero-trust, the
estate's zero-trust authority). This module does NOT invent a grant shape; it emits the canonical
`Grant`, consumes the canonical `AttestationBundle`, honours the canonical `QuorumProof`, and returns
a canonical `tool_grant.validate` check result.

The cloud-shell fog flow it implements:

  Policy Authority (issue_grant):  Attest (AttestationBundle.results.tpm_valid & cosign_valid) →
    Decide (a real scheduled compute_plane placement) → Grant (mint a canonical Grant: session-bound
    via `binding`, structured `capability`, `constraints`, `policy_hash`, optional `quorum_proof`,
    `evidence_refs`, signed with `sig{issuer,sig}`). Refuses to mint without attestation, without a
    valid placement, or without a required quorum.

  fog-node Policy Gate (verify_grant):  on attach and on every op, re-check the signature, the
    session binding, expiry, attestation binding, and that the requested effect/op is within the
    Grant's capability + constraints. Returns a canonical tool_grant.validate result
    {valid, expired, revoked, reason}. Fail-closed.

HMAC stands in for the Key Authority (HSM/KMS); the `sig{issuer,sig}` shape is canonical — swap in
ed25519/HSM without touching the flow.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import uuid
from datetime import datetime, timedelta, timezone

ISSUER = "spiffe://sourceos/policyarbiter"
_SHA256_RE = re.compile(r"^sha256:[a-f0-9]{64}$")


def _canon(body: dict) -> bytes:
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(body: dict) -> str:
    return "sha256:" + hashlib.sha256(_canon(body)).hexdigest()


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def hmac_signer(key: bytes):
    """Stand-in for the Key Authority (HSM/KMS) 'sign grant' op. Returns a hex sig (>=16 chars)."""
    return lambda body: hmac.new(key, _canon(body), hashlib.sha256).hexdigest()


def hmac_verifier(key: bytes):
    signer = hmac_signer(key)
    return lambda body, sig: hmac.compare_digest(signer(body), sig)


def attestation_bundle(*, spiffe_id: str, aum_digest: str, tpm_valid: bool, cosign_valid: bool,
                       fido2_valid: bool = False, tpm_quote_ref: str = "worm://quotes/none",
                       cosign_bundle_ref: str = "worm://bundles/none") -> dict:
    """Build a canonical AttestationBundle (schemas/a2a/attestation_bundle.schema.json)."""
    return {"subject": {"spiffe_id": spiffe_id, "aum_digest": aum_digest},
            "results": {"tpm_valid": bool(tpm_valid), "cosign_valid": bool(cosign_valid),
                        "fido2_valid": bool(fido2_valid)},
            "evidence_refs": {"tpm_quote_ref": tpm_quote_ref, "cosign_bundle_ref": cosign_bundle_ref}}


class GrantRefused(Exception):
    """Attest / Decide / quorum precondition failed — no Grant is minted (fail-closed)."""


def issue_grant(*, binding: dict, capability: dict, decision: dict, attestation: dict,
                constraints: dict, signer, issuer: str = ISSUER, ttl_s: float = 900.0,
                quorum_proof: dict | None = None, evidence_refs: dict | None = None,
                now: datetime | None = None) -> dict:
    """Attest → Decide → Grant. Returns a canonical Grant (sig embedded) or raises GrantRefused.

    binding:     {"spiffe_id", "aum_digest" (sha256:...), "session_id"}
    capability:  {"kind" (mcp_tool|a2a_skill|deployment|runner_action), "capability_ref",
                  "capability_digest" (sha256:...), "effect" (read|write|compute|exec|egress), ...}
    decision:    a compute_plane.place() result — must be a real scheduled placement.
    attestation: a canonical AttestationBundle.
    constraints: free-form object; `require_quorum`/`quorum_threshold` are Authority-side directives
                 (stripped from the emitted Grant, which only carries enforceable constraints).
    """
    now = datetime.now(timezone.utc) if now is None else now

    # ── Attest ──────────────────────────────────────────────────────────────────────
    res = attestation.get("results", {})
    if not (res.get("tpm_valid") and res.get("cosign_valid")):
        raise GrantRefused("attestation failed: results.tpm_valid and results.cosign_valid required")

    # ── Decide ──────────────────────────────────────────────────────────────────────
    if decision.get("placement") != "scheduled" or not decision.get("backend"):
        raise GrantRefused(f"no valid placement to grant (placement={decision.get('placement')!r})")

    # ── Quorum (only when the capability demands it) ─────────────────────────────────
    if constraints.get("require_quorum"):
        threshold = int(constraints.get("quorum_threshold", 2))
        sigs = (quorum_proof or {}).get("signatures", [])
        if not quorum_proof or len(sigs) < threshold:
            raise GrantRefused(f"quorum required: need {threshold} validator signatures, got {len(sigs)}")

    cap = dict(capability)
    cap.setdefault("executor_ref", f"node://{decision['backend']}")  # bind the chosen fog node

    enforceable = {k: v for k, v in constraints.items() if k not in ("require_quorum", "quorum_threshold")}
    enforceable.setdefault("ttl_sec", int(ttl_s))

    ev = dict(evidence_refs or {})
    ev.setdefault("attestation_bundle_ref", "worm://attest/inline")
    ev.setdefault("attestation_bundle_hash", _sha256(attestation))
    if decision.get("receipt_digest"):
        ev.setdefault("hdt_decision_ref", "worm://hdt/decision")
        ev.setdefault("hdt_decision_hash", decision["receipt_digest"])

    grant = {
        "grant_id": "grant_" + uuid.uuid4().hex[:16],
        "issued_at": _iso(now),
        "expires_at": _iso(now + timedelta(seconds=float(ttl_s))),
        "binding": {k: binding[k] for k in ("spiffe_id", "aum_digest", "session_id") if k in binding},
        "capability": cap,
        "constraints": enforceable,
        "policy_hash": _sha256({"binding": binding, "capability": cap, "constraints": enforceable,
                                "placement": decision.get("backend"), "attestation": res}),
    }
    if quorum_proof:
        grant["quorum_proof"] = quorum_proof
    if ev:
        grant["evidence_refs"] = ev
    grant["sig"] = {"issuer": issuer, "sig": signer(grant)}  # sign the grant-minus-sig
    return grant


def verify_grant(grant: dict, *, session_id: str, verifier, actor: dict | None = None,
                 requested_effect: str | None = None, requested_op: str | None = None,
                 trust_boundary_id: str | None = None, now: datetime | None = None) -> dict:
    """fog-node Policy Gate → canonical tool_grant.validate result. Fail-closed; re-check on attach
    and on every op. Pass requested_effect/requested_op on an op to enforce it is within the Grant."""
    now = datetime.now(timezone.utc) if now is None else now

    def check(valid, expired, revoked, reason):
        out = {"check_id": "chk_" + uuid.uuid4().hex[:8], "operation": "tool_grant.validate",
               "grant_id": grant.get("grant_id"), "checked_at": _iso(now),
               "actor": actor or {"spiffe_id": ISSUER,
                                  "aum_digest": grant.get("binding", {}).get("aum_digest", "sha256:" + "0" * 64)},
               "result": {"valid": valid, "expired": expired, "revoked": revoked, "reason": reason},
               "policy_hash": grant.get("policy_hash")}
        if trust_boundary_id:
            out["trust_boundary_id"] = trust_boundary_id
        return out

    sig = grant.get("sig", {})
    body = {k: v for k, v in grant.items() if k != "sig"}
    if not (sig.get("sig") and verifier(body, sig["sig"])):
        return check(False, False, False, "signature invalid — Grant tampered or wrong key")
    if grant.get("binding", {}).get("session_id") != session_id:
        return check(False, False, False, "session mismatch — Grant is not bound to this session")
    if now > _parse_iso(grant.get("expires_at", "1970-01-01T00:00:00Z")):
        return check(False, True, False, "Grant expired")
    if not grant.get("evidence_refs", {}).get("attestation_bundle_hash"):
        return check(False, False, False, "no attestation bound in Grant")
    granted_effect = grant.get("capability", {}).get("effect")
    if requested_effect is not None and requested_effect != granted_effect:
        return check(False, False, False, f"effect {requested_effect!r} not granted (granted: {granted_effect!r})")
    ops_allow = grant.get("constraints", {}).get("ops_allow")
    if requested_op is not None and ops_allow is not None and requested_op not in ops_allow:
        return check(False, False, False, f"op {requested_op!r} not in granted constraints ops_allow={ops_allow}")
    return check(True, False, False, "Grant is active and within TTL; session-bound; op permitted")


if __name__ == "__main__":
    # demo: the full canonical attach flow for one session.
    key = b"demo-key-not-for-real-use"
    dec = {"placement": "scheduled", "backend": "hpc-slurm", "backend_trust": "trusted",
           "receipt_digest": "sha256:" + "de" * 32}
    att = attestation_bundle(spiffe_id="spiffe://sourceos/agent/noetica", aum_digest="sha256:" + "ab" * 32,
                             tpm_valid=True, cosign_valid=True)
    grant = issue_grant(
        binding={"spiffe_id": "spiffe://sourceos/agent/noetica", "aum_digest": "sha256:" + "ab" * 32,
                 "session_id": "sess_abc123"},
        capability={"kind": "mcp_tool", "capability_ref": "capd://caps.dev.devspace-inner-loop",
                    "capability_digest": "sha256:" + "cd" * 32, "effect": "exec",
                    "server": "shell.runtime", "tool": "pty"},
        decision=dec, attestation=att, constraints={"ops_allow": ["pty.attach", "fs.read"], "paths_allow": ["$HOME/**"]},
        signer=hmac_signer(key))
    result = verify_grant(grant, session_id="sess_abc123", verifier=hmac_verifier(key),
                          requested_effect="exec", requested_op="pty.attach")
    print(json.dumps({"grant": grant, "check": result}, indent=2))
