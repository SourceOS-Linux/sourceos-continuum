#!/usr/bin/env python3
"""SSO front door — real OIDC + WebAuthn/FIDO2 verification, fail-closed, stdlib-only.

`login.py` is the session core (issue/verify an HMAC-bound session). This is the thing that decides
*who is this* before a session is minted: the two real SSO mechanisms the cloud-shell-fog spec names,
OIDC and WebAuthn/FIDO2 — done honestly with only the standard library.

An honest boundary, stated up front: verifying an **asymmetric** signature (RS256/ES256 JWTs, WebAuthn
credential public keys) needs asymmetric crypto the stdlib does not ship, and hand-rolling RSA/ECDSA
is exactly what you must not do. So the asymmetric signature check is a single, clearly-marked
**injection point** (`verify_signature=...`), wired in production to a JWKS/`cryptography` verifier.
Everything *else* — and it is the majority of what these protocols get wrong in the wild — is real
here and stdlib-doable:

  * **OIDC ID-token**: strict claim validation (iss, aud/azp, exp/iat/nbf, nonce), `alg:none` refused,
    HS256 verified with hmac; asymmetric algs require the injected verifier (never silently accepted).
  * **PKCE (S256)**: challenge/verifier binding + state (CSRF) + nonce (replay) — all stdlib.
  * **WebAuthn assertion**: type, challenge, origin, rpIdHash, user-present/verified flags, and
    signature-counter clone detection — all stdlib; the credential signature is the injected step.

Every check is fail-closed: any failure returns `{"valid": False, "reason": ...}` and no identity is
asserted. Verified identity → `session_from_identity()` mints a `login.py` session.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timezone
from urllib.parse import urlencode


# --- base64url + hashing helpers -----------------------------------------------------------------

def _b64url_decode(s) -> bytes:
    if isinstance(s, str):
        s = s.encode("ascii")
    return base64.urlsafe_b64decode(s + b"=" * (-len(s) % 4))


def _b64url_encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _sha256(b: bytes) -> bytes:
    return hashlib.sha256(b).digest()


def _fail(reason: str) -> dict:
    return {"valid": False, "reason": reason}


# --- PKCE + authorization-code flow (all stdlib) -------------------------------------------------

def pkce_pair(code_verifier: str | None = None) -> dict:
    """A PKCE S256 pair. `code_verifier` is a high-entropy secret the client keeps; `code_challenge`
    is base64url(sha256(verifier)) sent on the authorize request. Proves the client that started the
    flow is the one redeeming the code (defeats code interception)."""
    code_verifier = code_verifier or _b64url_encode(secrets.token_bytes(48))
    return {"code_verifier": code_verifier,
            "code_challenge": _b64url_encode(_sha256(code_verifier.encode("ascii"))),
            "code_challenge_method": "S256"}


def verify_pkce(*, code_verifier: str, code_challenge: str, method: str = "S256") -> bool:
    """Recompute the challenge from the verifier and constant-time compare (fail-closed)."""
    if method == "S256":
        expected = _b64url_encode(_sha256(code_verifier.encode("ascii")))
    elif method == "plain":
        expected = code_verifier
    else:
        return False
    return hmac.compare_digest(expected, code_challenge)


def build_authorization_request(*, authorize_url: str, client_id: str, redirect_uri: str,
                                scope: str = "openid profile", state: str | None = None,
                                nonce: str | None = None, code_challenge: str) -> dict:
    """Build the /authorize redirect (with state + nonce + PKCE challenge). Keep `state`/`nonce` to
    check on the callback."""
    state = state or _b64url_encode(secrets.token_bytes(16))
    nonce = nonce or _b64url_encode(secrets.token_bytes(16))
    params = {"response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri,
              "scope": scope, "state": state, "nonce": nonce,
              "code_challenge": code_challenge, "code_challenge_method": "S256"}
    return {"url": authorize_url + "?" + urlencode(params), "state": state, "nonce": nonce}


def verify_callback(*, returned_state: str, expected_state: str, error: str | None = None) -> dict:
    """Fail-closed callback check: an IdP-reported error, or a state mismatch (CSRF), aborts."""
    if error:
        return _fail(f"authorization error from IdP: {error}")
    if not returned_state or not hmac.compare_digest(str(returned_state), str(expected_state)):
        return _fail("state mismatch — possible CSRF; authorization rejected")
    return {"valid": True}


def build_token_exchange(*, token_url: str, code: str, redirect_uri: str, client_id: str,
                         code_verifier: str, client_secret: str | None = None) -> dict:
    """The token-endpoint POST body redeeming the code (sends `code_verifier` — the PKCE proof). No
    network I/O here; the caller POSTs `body` to `token_url` over TLS."""
    body = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
            "client_id": client_id, "code_verifier": code_verifier}
    if client_secret is not None:
        body["client_secret"] = client_secret
    return {"token_url": token_url, "body": body}


# --- OIDC ID-token verification ------------------------------------------------------------------

def encode_jwt_hs256(payload: dict, secret: str, *, header: dict | None = None) -> str:
    """Mint an HS256 JWT (for symmetric clients + tests). Real IdPs usually sign RS256."""
    h = {"alg": "HS256", "typ": "JWT", **(header or {})}
    seg = _b64url_encode(json.dumps(h, separators=(",", ":")).encode()) + "." + \
        _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(secret.encode(), seg.encode("ascii"), hashlib.sha256).digest()
    return seg + "." + _b64url_encode(sig)


def decode_jwt(token: str) -> dict:
    """Split a compact JWT into header/payload/signature without verifying. Raises ValueError if
    malformed. `signing_input` is the exact bytes the signature covers (never re-serialized)."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("not a compact JWS (need 3 dot-separated segments)")
    header = json.loads(_b64url_decode(parts[0]))
    payload = json.loads(_b64url_decode(parts[1]))
    if not isinstance(header, dict) or not isinstance(payload, dict):
        raise ValueError("JWT header/payload are not JSON objects")
    return {"header": header, "payload": payload,
            "signing_input": (parts[0] + "." + parts[1]).encode("ascii"),
            "signature": _b64url_decode(parts[2])}


def verify_id_token(token: str, *, issuer: str, audience: str, nonce: str | None = None,
                    now: datetime | None = None, hs256_secret: str | None = None,
                    verify_signature=None, leeway_s: int = 60) -> dict:
    """Verify an OIDC ID token, fail-closed. Signature FIRST, then every required claim.

    hs256_secret     — verify HS256 tokens with this shared secret (hmac, stdlib).
    verify_signature — (signing_input: bytes, signature: bytes, header: dict) -> bool, for asymmetric
                       algs (RS256/ES256/…). Required for those; without it they are rejected, never
                       silently trusted. This is the one crypto step delegated out of stdlib.
    Returns {valid, sub, claims} or {valid, reason}.
    """
    now = now or datetime.now(timezone.utc)
    try:
        jwt = decode_jwt(token)
    except (ValueError, json.JSONDecodeError, base64.binascii.Error) as exc:
        return _fail(f"malformed ID token: {exc}")

    alg = jwt["header"].get("alg")
    # 1. signature — the load-bearing check. `none` is always refused.
    if alg == "none" or not alg:
        return _fail("alg 'none' (or missing) is refused — an unsigned ID token is never trusted")
    if alg == "HS256":
        if not hs256_secret:
            return _fail("HS256 token but no shared secret configured")
        expected = hmac.new(hs256_secret.encode(), jwt["signing_input"], hashlib.sha256).digest()
        if not hmac.compare_digest(expected, jwt["signature"]):
            return _fail("HS256 signature invalid")
    else:
        if verify_signature is None:
            return _fail(f"alg {alg} needs an asymmetric verifier (inject verify_signature=…); refused")
        if not verify_signature(jwt["signing_input"], jwt["signature"], jwt["header"]):
            return _fail(f"{alg} signature invalid")

    c = jwt["payload"]
    # 2. issuer — exact match.
    if c.get("iss") != issuer:
        return _fail(f"iss mismatch (want {issuer!r})")
    # 3. audience — client_id must be in aud; with multiple audiences, azp must be us.
    aud = c.get("aud")
    auds = aud if isinstance(aud, list) else [aud]
    if audience not in auds:
        return _fail("aud does not include this client")
    if len(auds) > 1 and c.get("azp") != audience:
        return _fail("multiple audiences but azp is not this client")
    # 4. expiry / not-before / issued-at.
    ts = now.timestamp()
    if "exp" not in c or ts > float(c["exp"]) + leeway_s:
        return _fail("token expired")
    if "nbf" in c and ts + leeway_s < float(c["nbf"]):
        return _fail("token not yet valid (nbf)")
    if "iat" not in c:
        return _fail("missing iat")
    # 5. nonce — binds the token to this login attempt (replay/CSRF).
    if nonce is not None and not hmac.compare_digest(str(c.get("nonce", "")), str(nonce)):
        return _fail("nonce mismatch — token not bound to this login")
    return {"valid": True, "sub": c.get("sub"), "claims": c}


# --- WebAuthn / FIDO2 assertion verification -----------------------------------------------------

def verify_assertion(*, client_data_json: bytes, authenticator_data: bytes, signature: bytes,
                     expected_challenge: bytes, expected_origin: str, rp_id: str,
                     prev_sign_count: int = 0, require_user_verification: bool = False,
                     verify_signature) -> dict:
    """Verify a WebAuthn assertion (navigator.credentials.get), fail-closed, per WebAuthn §7.2. Every
    non-crypto check is here; the credential signature is the injected `verify_signature(signed_data,
    signature) -> bool` (ES256/RS256/EdDSA over the public key — the one out-of-stdlib step).

    Returns {valid, sign_count} or {valid, reason}.
    """
    try:
        cd = json.loads(client_data_json.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return _fail(f"clientDataJSON not valid JSON: {exc}")
    if not isinstance(cd, dict):
        return _fail("clientDataJSON is not an object")

    # 1. ceremony type.
    if cd.get("type") != "webauthn.get":
        return _fail("clientData.type is not webauthn.get")
    # 2. challenge — must equal the one we issued (defeats replay). clientData carries it base64url.
    try:
        got_challenge = _b64url_decode(cd.get("challenge", ""))
    except base64.binascii.Error:
        return _fail("clientData.challenge is not valid base64url")
    if not hmac.compare_digest(got_challenge, expected_challenge):
        return _fail("challenge mismatch — assertion not for this login")
    # 3. origin — must be exactly the RP's origin (defeats cross-origin/phishing).
    if cd.get("origin") != expected_origin:
        return _fail(f"origin mismatch (want {expected_origin!r})")

    # 4. authenticatorData: rpIdHash + flags + signCount.
    if len(authenticator_data) < 37:
        return _fail("authenticatorData too short")
    if not hmac.compare_digest(authenticator_data[:32], _sha256(rp_id.encode())):
        return _fail("rpIdHash mismatch — assertion is for a different Relying Party")
    flags = authenticator_data[32]
    if not (flags & 0x01):  # UP (user present)
        return _fail("user-present (UP) flag not set")
    if require_user_verification and not (flags & 0x04):  # UV (user verified)
        return _fail("user-verification required but UV flag not set")
    sign_count = int.from_bytes(authenticator_data[33:37], "big")
    # 5. signature-counter clone detection: a stored or reported counter of 0 disables the check
    #    (some authenticators don't implement it); otherwise it MUST strictly increase.
    if (sign_count != 0 or prev_sign_count != 0) and sign_count <= prev_sign_count:
        return _fail(f"signature counter did not increase ({sign_count} <= {prev_sign_count}) — "
                     "possible cloned authenticator")
    # 6. the credential signature over authenticatorData || sha256(clientDataJSON) — injected crypto.
    signed_data = authenticator_data + _sha256(client_data_json)
    if not verify_signature(signed_data, signature):
        return _fail("assertion signature invalid")
    return {"valid": True, "sign_count": sign_count}


# --- bridge to the session core ------------------------------------------------------------------

def session_from_identity(verify_result: dict, *, key: bytes, tier: str = "pro",
                          ttl_s: float = 3600.0, now: datetime | None = None,
                          user: str | None = None) -> dict | None:
    """Turn a VALID OIDC/WebAuthn verification into a login.py session. Fail-closed: an invalid
    verification never yields a session."""
    if not verify_result.get("valid"):
        return None
    import login
    subject = user or verify_result.get("sub") or (verify_result.get("claims") or {}).get("sub")
    if not subject:
        return None
    return login.issue_session(user=subject, tier=tier, key=key, ttl_s=ttl_s, now=now)


if __name__ == "__main__":
    import login

    key = b"sso-demo-session-key"
    now = datetime.now(timezone.utc)

    # PKCE
    p = pkce_pair()
    pkce_ok = verify_pkce(code_verifier=p["code_verifier"], code_challenge=p["code_challenge"])
    pkce_bad = verify_pkce(code_verifier="tampered", code_challenge=p["code_challenge"])

    # OIDC (HS256 for the demo; real IdPs sign RS256 → inject verify_signature)
    secret = "oidc-client-secret"
    claims = {"iss": "https://idp.sovereign", "aud": "continuum", "sub": "alice",
              "nonce": "n-123", "iat": int(now.timestamp()), "exp": int(now.timestamp()) + 300}
    tok = encode_jwt_hs256(claims, secret)
    oidc_ok = verify_id_token(tok, issuer="https://idp.sovereign", audience="continuum",
                              nonce="n-123", now=now, hs256_secret=secret)
    unsigned = encode_jwt_hs256({**claims}, secret).rsplit(".", 1)[0] + "."  # strip sig
    none_tok = _b64url_encode(json.dumps({"alg": "none"}).encode()) + "." + \
        _b64url_encode(json.dumps(claims).encode()) + "."
    oidc_none = verify_id_token(none_tok, issuer="https://idp.sovereign", audience="continuum", now=now)
    oidc_badnonce = verify_id_token(tok, issuer="https://idp.sovereign", audience="continuum",
                                    nonce="wrong", now=now, hs256_secret=secret)

    # WebAuthn (inject the credential-signature step)
    rp_id, origin, chal = "continuum.sovereign", "https://continuum.sovereign", secrets.token_bytes(32)
    client_data = json.dumps({"type": "webauthn.get", "challenge": _b64url_encode(chal),
                              "origin": origin}).encode()
    auth_data = _sha256(rp_id.encode()) + bytes([0x05]) + (7).to_bytes(4, "big")  # UP+UV, counter 7
    wa_ok = verify_assertion(client_data_json=client_data, authenticator_data=auth_data,
                             signature=b"sig", expected_challenge=chal, expected_origin=origin,
                             rp_id=rp_id, prev_sign_count=6, verify_signature=lambda d, s: True)
    wa_clone = verify_assertion(client_data_json=client_data, authenticator_data=auth_data,
                                signature=b"sig", expected_challenge=chal, expected_origin=origin,
                                rp_id=rp_id, prev_sign_count=7, verify_signature=lambda d, s: True)

    sess = session_from_identity(oidc_ok, key=key, tier="pro", now=now)
    print(json.dumps({
        "pkce": {"ok": pkce_ok, "tampered_rejected": not pkce_bad},
        "oidc": {"valid": oidc_ok["valid"], "sub": oidc_ok.get("sub"),
                 "alg_none_refused": not oidc_none["valid"],
                 "bad_nonce_refused": not oidc_badnonce["valid"]},
        "webauthn": {"valid": wa_ok["valid"], "clone_refused": not wa_clone["valid"],
                     "clone_reason": wa_clone.get("reason", "")[:40]},
        "session_after_oidc": login.verify_session(sess, key=key, now=now)["valid"],
    }, indent=2))
