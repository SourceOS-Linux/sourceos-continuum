#!/usr/bin/env python3
"""Tests for the SSO front door — OIDC + PKCE + WebAuthn, every check fail-closed."""
import json
from datetime import datetime, timezone

import login
import sso

_NOW = datetime(2026, 8, 4, 12, 0, 0, tzinfo=timezone.utc)
_ISS = "https://idp.sovereign"
_AUD = "continuum"
_SECRET = "oidc-client-secret"


def _claims(**over):
    base = {"iss": _ISS, "aud": _AUD, "sub": "alice", "nonce": "n-1",
            "iat": int(_NOW.timestamp()), "exp": int(_NOW.timestamp()) + 300}
    base.update(over)
    return base


def _mint(alg, claims, sig=b"x"):
    h = sso._b64url_encode(json.dumps({"alg": alg, "typ": "JWT"}).encode())
    p = sso._b64url_encode(json.dumps(claims).encode())
    return h + "." + p + "." + sso._b64url_encode(sig)


# --- PKCE ---------------------------------------------------------------------------------------

def test_pkce_pair_verifies_and_tampered_verifier_fails():
    p = sso.pkce_pair()
    assert p["code_challenge_method"] == "S256"
    assert sso.verify_pkce(code_verifier=p["code_verifier"], code_challenge=p["code_challenge"])
    assert not sso.verify_pkce(code_verifier="tampered", code_challenge=p["code_challenge"])


def test_pkce_unknown_method_is_rejected():
    assert sso.verify_pkce(code_verifier="v", code_challenge="v", method="MD5") is False


def test_authorization_request_carries_state_nonce_and_challenge():
    p = sso.pkce_pair()
    req = sso.build_authorization_request(authorize_url="https://idp/authorize", client_id="c",
                                          redirect_uri="https://app/cb", code_challenge=p["code_challenge"])
    assert "code_challenge_method=S256" in req["url"] and req["state"] and req["nonce"]
    assert "response_type=code" in req["url"]


def test_callback_state_mismatch_is_csrf_rejected():
    assert sso.verify_callback(returned_state="a", expected_state="a")["valid"] is True
    assert sso.verify_callback(returned_state="a", expected_state="b")["valid"] is False
    assert sso.verify_callback(returned_state="a", expected_state="a", error="access_denied")["valid"] is False


def test_token_exchange_sends_the_pkce_verifier():
    tx = sso.build_token_exchange(token_url="https://idp/token", code="abc", redirect_uri="https://app/cb",
                                  client_id="c", code_verifier="the-verifier")
    assert tx["body"]["code_verifier"] == "the-verifier" and tx["body"]["grant_type"] == "authorization_code"


# --- OIDC ID token --------------------------------------------------------------------------------

def test_valid_hs256_id_token_verifies_with_subject():
    tok = sso.encode_jwt_hs256(_claims(), _SECRET)
    r = sso.verify_id_token(tok, issuer=_ISS, audience=_AUD, nonce="n-1", now=_NOW, hs256_secret=_SECRET)
    assert r["valid"] and r["sub"] == "alice"


def test_alg_none_is_always_refused():
    r = sso.verify_id_token(_mint("none", _claims(), sig=b""), issuer=_ISS, audience=_AUD, now=_NOW)
    assert r["valid"] is False and "none" in r["reason"]


def test_hs256_wrong_secret_is_refused():
    tok = sso.encode_jwt_hs256(_claims(), _SECRET)
    r = sso.verify_id_token(tok, issuer=_ISS, audience=_AUD, now=_NOW, hs256_secret="wrong")
    assert r["valid"] is False and "signature" in r["reason"]


def test_asymmetric_alg_without_verifier_is_refused_never_trusted():
    r = sso.verify_id_token(_mint("RS256", _claims()), issuer=_ISS, audience=_AUD, now=_NOW)
    assert r["valid"] is False and "asymmetric verifier" in r["reason"]


def test_asymmetric_alg_uses_the_injected_verifier():
    tok = _mint("RS256", _claims())
    ok = sso.verify_id_token(tok, issuer=_ISS, audience=_AUD, nonce="n-1", now=_NOW,
                             verify_signature=lambda si, sig, h: True)
    bad = sso.verify_id_token(tok, issuer=_ISS, audience=_AUD, now=_NOW,
                              verify_signature=lambda si, sig, h: False)
    assert ok["valid"] is True and bad["valid"] is False


def test_issuer_and_audience_are_enforced():
    tok = sso.encode_jwt_hs256(_claims(), _SECRET)
    assert not sso.verify_id_token(tok, issuer="https://evil", audience=_AUD, now=_NOW, hs256_secret=_SECRET)["valid"]
    assert not sso.verify_id_token(tok, issuer=_ISS, audience="other-app", now=_NOW, hs256_secret=_SECRET)["valid"]


def test_multiple_audiences_require_azp_to_be_us():
    tok = sso.encode_jwt_hs256(_claims(aud=[_AUD, "other"], azp="other"), _SECRET)
    assert not sso.verify_id_token(tok, issuer=_ISS, audience=_AUD, now=_NOW, hs256_secret=_SECRET)["valid"]
    ok = sso.encode_jwt_hs256(_claims(aud=[_AUD, "other"], azp=_AUD), _SECRET)
    assert sso.verify_id_token(ok, issuer=_ISS, audience=_AUD, nonce="n-1", now=_NOW, hs256_secret=_SECRET)["valid"]


def test_expired_token_is_refused():
    tok = sso.encode_jwt_hs256(_claims(exp=int(_NOW.timestamp()) - 3600), _SECRET)
    r = sso.verify_id_token(tok, issuer=_ISS, audience=_AUD, now=_NOW, hs256_secret=_SECRET)
    assert r["valid"] is False and "expired" in r["reason"]


def test_missing_iat_is_refused():
    c = _claims()
    del c["iat"]
    tok = sso.encode_jwt_hs256(c, _SECRET)
    assert not sso.verify_id_token(tok, issuer=_ISS, audience=_AUD, now=_NOW, hs256_secret=_SECRET)["valid"]


def test_nonce_mismatch_is_refused():
    tok = sso.encode_jwt_hs256(_claims(nonce="n-1"), _SECRET)
    r = sso.verify_id_token(tok, issuer=_ISS, audience=_AUD, nonce="n-DIFFERENT", now=_NOW, hs256_secret=_SECRET)
    assert r["valid"] is False and "nonce" in r["reason"]


def test_malformed_token_is_refused():
    assert not sso.verify_id_token("not.a.jwt.at.all", issuer=_ISS, audience=_AUD, now=_NOW)["valid"]
    assert not sso.verify_id_token("garbage", issuer=_ISS, audience=_AUD, now=_NOW)["valid"]


# --- WebAuthn assertion --------------------------------------------------------------------------

_RP = "continuum.sovereign"
_ORIGIN = "https://continuum.sovereign"
_CHAL = b"\x11" * 32


def _assertion(*, challenge_b64=None, origin=_ORIGIN, rp_id=_RP, flags=0x05, count=7,
               ctype="webauthn.get"):
    cd = {"type": ctype, "challenge": challenge_b64 or sso._b64url_encode(_CHAL), "origin": origin}
    client_data = json.dumps(cd).encode()
    auth_data = sso._sha256(rp_id.encode()) + bytes([flags]) + count.to_bytes(4, "big")
    return client_data, auth_data


def test_valid_assertion_passes_with_injected_signature():
    cd, ad = _assertion()
    r = sso.verify_assertion(client_data_json=cd, authenticator_data=ad, signature=b"s",
                             expected_challenge=_CHAL, expected_origin=_ORIGIN, rp_id=_RP,
                             prev_sign_count=6, verify_signature=lambda d, s: True)
    assert r["valid"] and r["sign_count"] == 7


def test_wrong_type_challenge_or_origin_are_refused():
    for over in ({"ctype": "webauthn.create"},
                 {"challenge_b64": sso._b64url_encode(b"\x22" * 32)},
                 {"origin": "https://evil.example"}):
        cd, ad = _assertion(**over)
        r = sso.verify_assertion(client_data_json=cd, authenticator_data=ad, signature=b"s",
                                 expected_challenge=_CHAL, expected_origin=_ORIGIN, rp_id=_RP,
                                 prev_sign_count=0, verify_signature=lambda d, s: True)
        assert r["valid"] is False, over


def test_wrong_rp_id_is_refused():
    cd, ad = _assertion(rp_id="attacker.example")
    r = sso.verify_assertion(client_data_json=cd, authenticator_data=ad, signature=b"s",
                             expected_challenge=_CHAL, expected_origin=_ORIGIN, rp_id=_RP,
                             prev_sign_count=0, verify_signature=lambda d, s: True)
    assert r["valid"] is False and "rpIdHash" in r["reason"]


def test_user_present_flag_required():
    cd, ad = _assertion(flags=0x00)  # UP not set
    r = sso.verify_assertion(client_data_json=cd, authenticator_data=ad, signature=b"s",
                             expected_challenge=_CHAL, expected_origin=_ORIGIN, rp_id=_RP,
                             prev_sign_count=0, verify_signature=lambda d, s: True)
    assert r["valid"] is False and "UP" in r["reason"]


def test_user_verification_enforced_when_required():
    cd, ad = _assertion(flags=0x01)  # UP set, UV not
    r = sso.verify_assertion(client_data_json=cd, authenticator_data=ad, signature=b"s",
                             expected_challenge=_CHAL, expected_origin=_ORIGIN, rp_id=_RP,
                             prev_sign_count=0, require_user_verification=True,
                             verify_signature=lambda d, s: True)
    assert r["valid"] is False and "UV" in r["reason"]


def test_signature_counter_clone_is_refused():
    cd, ad = _assertion(count=5)
    r = sso.verify_assertion(client_data_json=cd, authenticator_data=ad, signature=b"s",
                             expected_challenge=_CHAL, expected_origin=_ORIGIN, rp_id=_RP,
                             prev_sign_count=5, verify_signature=lambda d, s: True)
    assert r["valid"] is False and "cloned" in r["reason"]


def test_bad_credential_signature_is_refused():
    cd, ad = _assertion()
    r = sso.verify_assertion(client_data_json=cd, authenticator_data=ad, signature=b"s",
                             expected_challenge=_CHAL, expected_origin=_ORIGIN, rp_id=_RP,
                             prev_sign_count=6, verify_signature=lambda d, s: False)
    assert r["valid"] is False and "signature" in r["reason"]


def test_counter_zero_disables_clone_check():
    # some authenticators never implement the counter; 0/0 must not trip clone detection.
    cd, ad = _assertion(count=0)
    r = sso.verify_assertion(client_data_json=cd, authenticator_data=ad, signature=b"s",
                             expected_challenge=_CHAL, expected_origin=_ORIGIN, rp_id=_RP,
                             prev_sign_count=0, verify_signature=lambda d, s: True)
    assert r["valid"] is True


# --- bridge to the session core ------------------------------------------------------------------

def test_verified_identity_mints_a_session_and_invalid_does_not():
    key = b"k"
    tok = sso.encode_jwt_hs256(_claims(), _SECRET)
    ok = sso.verify_id_token(tok, issuer=_ISS, audience=_AUD, nonce="n-1", now=_NOW, hs256_secret=_SECRET)
    sess = sso.session_from_identity(ok, key=key, tier="pro", now=_NOW)
    assert sess is not None and login.verify_session(sess, key=key, now=_NOW)["valid"]
    assert sso.session_from_identity({"valid": False}, key=key, now=_NOW) is None


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"ok: {len(fns)} sso tests passed")
    sys.exit(0)
