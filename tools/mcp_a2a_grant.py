#!/usr/bin/env python3
"""MCP-A2A Policy Authority + fog-node Policy Gate — the zero-trust heart of the cloud-shell fog spec.

The compute plane's `place()` is the Control-Plane Agent's *Decide*: it picks a node. But a placement
decision is not permission to run. The Sovereign Agentic Cloud-Shell spec routes every attach through
**Attest → Decide → Grant**, and then the *fog node itself* re-verifies before it lets anything touch
a PTY or the filesystem. This module is both ends of that:

  Policy Authority (issue_grant):  Attest (TPM/TEE + cosign must be valid) → Decide (a real scheduled
    placement, not a block) → Grant (mint a signed, session-bound capability carrying its constraints
    and expiry; require a quorum proof when the capability demands one).

  fog-node Policy Gate (verify_grant):  on attach (step 10) and on every PTY/FS op (step 11),
    re-check the signature, the session binding, expiry, attestation, and that the specific op is in
    the granted constraints. Fail-closed at every step — a missing or stale or tampered Grant denies.

The signer/verifier here is HMAC (stdlib) standing in for the spec's Key Authority (HSM/KMS); the
interface is what matters — swap in ed25519/HSM without touching the flow.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid


def _canon(body: dict) -> bytes:
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def hmac_signer(key: bytes):
    """Stand-in for the Key Authority (HSM/KMS) 'sign grant' operation."""
    return lambda body: hmac.new(key, _canon(body), hashlib.sha256).hexdigest()


def hmac_verifier(key: bytes):
    signer = hmac_signer(key)
    return lambda body, sig: hmac.compare_digest(signer(body), sig)


class GrantRefused(Exception):
    """Attest/Decide/quorum precondition failed — no Grant is minted (fail-closed)."""


def issue_grant(*, session_id: str, subject: str, capability: str, decision: dict,
                attestation: dict, constraints: dict, signer, ttl_s: float = 900.0,
                quorum_proof: list | None = None, now=None) -> dict:
    """Attest → Decide → Grant. Returns {"grant": {...}, "signature": "..."} or raises GrantRefused.

    attestation: {"tpm_valid": bool, "cosign_valid": bool, "artifact_digest": "sha256:..."}
    decision:    a compute_plane.place() result — must be a real scheduled placement.
    constraints: {"allowed_ops": [...], "redactions": [...], "require_quorum": bool,
                  "quorum_threshold": int}
    """
    now = time.time() if now is None else now

    # ── Attest ──────────────────────────────────────────────────────────────────────
    if not (attestation.get("tpm_valid") and attestation.get("cosign_valid")):
        raise GrantRefused("attestation failed: tpm_valid and cosign_valid are both required")

    # ── Decide ──────────────────────────────────────────────────────────────────────
    if decision.get("placement") != "scheduled" or not decision.get("backend"):
        raise GrantRefused(f"no valid placement to grant (placement={decision.get('placement')!r})")

    # ── Quorum (only when the capability demands it) ─────────────────────────────────
    if constraints.get("require_quorum"):
        threshold = int(constraints.get("quorum_threshold", 2))
        if len(quorum_proof or []) < threshold:
            raise GrantRefused(f"quorum required: need {threshold} validator signatures, "
                               f"got {len(quorum_proof or [])}")

    grant = {
        "grant_id": str(uuid.uuid4()),
        "session_id": session_id,
        "subject": subject,
        "capability": capability,
        "placement": {"node": decision.get("backend"), "trust": decision.get("backend_trust")},
        "constraints": {"allowed_ops": list(constraints.get("allowed_ops", [])),
                        "redactions": list(constraints.get("redactions", []))},
        "attestation": {"tpm_valid": True, "cosign_valid": True,
                        "artifact_digest": attestation.get("artifact_digest")},
        "quorum_proof": list(quorum_proof or []),
        "issued_at": now,
        "expires_at": now + float(ttl_s),
        "decision_receipt": decision.get("receipt_digest"),
    }
    return {"grant": grant, "signature": signer(grant)}


def verify_grant(grant: dict, signature: str, *, session_id: str, verifier,
                 requested_op: str | None = None, now=None) -> dict:
    """fog-node Policy Gate. Re-verify on attach (step 10) and on each PTY/FS op (step 11).

    Returns {"authorized": bool, "reason": str, "redactions": [...]}. Fail-closed: any failed check
    denies. Pass requested_op on step 11 to enforce that the op is within the granted constraints.
    """
    def deny(reason):
        return {"authorized": False, "reason": reason, "redactions": []}

    now = time.time() if now is None else now
    if not verifier(grant, signature):
        return deny("signature invalid — Grant tampered or wrong key")
    if grant.get("session_id") != session_id:
        return deny("session mismatch — Grant is not bound to this session")
    if now > grant.get("expires_at", 0):
        return deny("Grant expired")
    att = grant.get("attestation", {})
    if not (att.get("tpm_valid") and att.get("cosign_valid")):
        return deny("attestation not satisfied in Grant")
    allowed = grant.get("constraints", {}).get("allowed_ops", [])
    if requested_op is not None and requested_op not in allowed:
        return deny(f"op {requested_op!r} not in granted constraints {allowed}")
    return {"authorized": True, "reason": "attest+decide+grant verified; session-bound; op permitted",
            "redactions": grant.get("constraints", {}).get("redactions", [])}


if __name__ == "__main__":
    # demo: the full attach flow for one session.
    key = b"demo-key-not-for-real-use"
    dec = {"placement": "scheduled", "backend": "k8s", "backend_trust": "trusted",
           "receipt_digest": "sha256:deadbeef"}
    issued = issue_grant(session_id="sess-1", subject="agent:noetica", capability="caps.dev.devspace-inner-loop@0.1.0",
                         decision=dec, attestation={"tpm_valid": True, "cosign_valid": True,
                         "artifact_digest": "sha256:abc"},
                         constraints={"allowed_ops": ["pty.attach", "fs.read"]}, signer=hmac_signer(key))
    gate = verify_grant(issued["grant"], issued["signature"], session_id="sess-1",
                        verifier=hmac_verifier(key), requested_op="pty.attach")
    print(json.dumps({"grant_id": issued["grant"]["grant_id"], "gate": gate}, indent=2))
