# SSO front door — real OIDC + WebAuthn/FIDO2, fail-closed, stdlib-only

`login.py` is the **session core** — it issues and verifies an HMAC-bound, expiring session. But a
session should only be minted once you actually know *who is this*. That decision is SSO, and
`tools/sso.py` does it with the two real mechanisms the cloud-shell-fog spec names — **OIDC** and
**WebAuthn/FIDO2** — using only the standard library.

It is the human analogue of the push webhook: the webhook is the **machine** door (an HMAC-verified
`git push`); this is the **human** door (an OIDC/WebAuthn-verified login). Same posture — a
zero-trust, fail-closed gate, not an open one.

## The honest boundary

Verifying an **asymmetric** signature — RS256/ES256 ID tokens, WebAuthn credential public keys —
needs public-key crypto the Python stdlib does not ship, and hand-rolling RSA/ECDSA is exactly the
thing you must never do. So that one step is a **clearly-marked injection point**
(`verify_signature=…`), wired in production to a JWKS / `cryptography` verifier. Without it,
asymmetric algorithms are **refused, never silently trusted**.

Everything *else* — and it is the majority of what these protocols get wrong in the field — is real
here and stdlib-doable. That's the point: we build the security-critical validation honestly and
delegate exactly one crypto primitive, rather than fake the whole thing or pull a heavy dep into a
dependency-free stack.

## What's verified (all fail-closed)

**OIDC ID-token** (`verify_id_token`) — signature first, then every required claim:
- `alg: none` (or missing) is **always refused** — an unsigned token is never trusted.
- `HS256` verified with `hmac` (stdlib); asymmetric algs require the injected verifier.
- `iss` exact match · `aud` contains us (and `azp` is us when there are multiple audiences) ·
  `exp`/`nbf`/`iat` with small leeway · `nonce` binds the token to *this* login (replay/CSRF).

**PKCE + auth-code** (`pkce_pair` / `build_authorization_request` / `verify_callback` /
`build_token_exchange`) — S256 challenge/verifier binding, `state` (CSRF) and `nonce` (replay) checks,
and the token-exchange body that sends the `code_verifier` as proof. All stdlib, no network I/O.

**WebAuthn assertion** (`verify_assertion`) — per WebAuthn §7.2:
- ceremony `type == webauthn.get` · `challenge` equals the one we issued (constant-time) ·
  `origin` exact (anti-phishing) · `rpIdHash == sha256(rp_id)` · **UP** (user-present) required,
  **UV** enforced when asked · **signature-counter clone detection** (a stored/reported 0 disables it,
  else it must strictly increase). The credential signature over
  `authenticatorData ‖ sha256(clientDataJSON)` is the injected step.

A valid verification → `session_from_identity()` mints a `login.py` session. An invalid one mints
nothing.

## Try it

```bash
make sso        # PKCE ok/tampered · OIDC valid/alg-none-refused/bad-nonce-refused · WebAuthn valid/clone-refused · session
```

`sso.py` is a pure verification core (25 unit tests, every rejection path covered). Production wires
`verify_signature` to a JWKS fetcher for the real IdP; the claim/ceremony logic does not change.
