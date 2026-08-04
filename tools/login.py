#!/usr/bin/env python3
"""Login / session — authenticate the twin/box front door.

A governed session surface. Real SSO is OIDC/FIDO2 (the production swap — the same IdP the cloud-shell
fog spec already names); this is the session core: authenticate a user against a credential verifier,
issue a signed, expiring session bound to the user + tier, and verify it fail-closed. The session is
the bearer the portal, provisioning, and grant issuance trust as "who is this" — so the phone hitting
the twin is authenticated, not open.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone


def _canon(body: dict) -> bytes:
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sign(key: bytes, body: dict) -> str:
    return hmac.new(key, _canon(body), hashlib.sha256).hexdigest()


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def issue_session(*, user: str, tier: str, key: bytes, ttl_s: float = 3600.0,
                  now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    body = {"user": user, "tier": tier, "issued_at": _iso(now),
            "expires_at": _iso(now + timedelta(seconds=float(ttl_s))),
            "session_id": "sess_" + hashlib.sha256(f"{user}:{_iso(now)}".encode()).hexdigest()[:10]}
    return {**body, "sig": _sign(key, body)}


def authenticate(*, user: str, credential: str, credential_check, key: bytes, tier: str = "pro",
                 ttl_s: float = 3600.0, now: datetime | None = None) -> dict | None:
    """Fail-closed: `credential_check(user, credential) -> bool`. Bad credentials -> no session.
    Swap credential_check for an OIDC/FIDO2 verifier in production."""
    if not credential_check(user, credential):
        return None
    return issue_session(user=user, tier=tier, key=key, ttl_s=ttl_s, now=now)


def verify_session(session: dict, *, key: bytes, now: datetime | None = None) -> dict:
    """Fail-closed session verification. Returns {valid, reason?, user?, tier?}."""
    now = now or datetime.now(timezone.utc)
    body = {k: v for k, v in session.items() if k != "sig"}
    if not hmac.compare_digest(_sign(key, body), session.get("sig", "")):
        return {"valid": False, "reason": "signature invalid — session tampered or wrong key"}
    if now > _parse(session.get("expires_at", "1970-01-01T00:00:00Z")):
        return {"valid": False, "reason": "session expired"}
    return {"valid": True, "user": session["user"], "tier": session["tier"]}


if __name__ == "__main__":
    key = b"login-demo-key"
    # a trivial credential check for the demo; production swaps in OIDC/FIDO2.
    creds = {"alice": "s3cret"}
    ok = authenticate(user="alice", credential="s3cret", key=key, tier="pro",
                      credential_check=lambda u, c: creds.get(u) == c)
    bad = authenticate(user="alice", credential="wrong", key=key,
                       credential_check=lambda u, c: creds.get(u) == c)
    print(json.dumps({"authenticated": bool(ok), "bad_creds_rejected": bad is None,
                      "verify": verify_session(ok, key=key)}, indent=2))
