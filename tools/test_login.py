#!/usr/bin/env python3
"""Tests for login/session — fail-closed authentication of the front door."""
from datetime import datetime, timedelta, timezone

import login as lg

KEY = b"login-test-key"
CREDS = {"alice": "s3cret"}


def _check(user, credential):
    return CREDS.get(user) == credential


def test_authenticate_issues_a_session_for_good_credentials():
    s = lg.authenticate(user="alice", credential="s3cret", key=KEY, tier="pro", credential_check=_check)
    assert s and s["user"] == "alice" and s["tier"] == "pro" and s["session_id"].startswith("sess_")
    assert lg.verify_session(s, key=KEY)["valid"] is True


def test_bad_credentials_are_rejected_fail_closed():
    assert lg.authenticate(user="alice", credential="wrong", key=KEY, credential_check=_check) is None
    assert lg.authenticate(user="mallory", credential="x", key=KEY, credential_check=_check) is None


def test_verify_denies_a_tampered_session():
    s = lg.authenticate(user="alice", credential="s3cret", key=KEY, credential_check=_check)
    s = {**s, "tier": "enterprise"}  # privilege-escalation attempt
    r = lg.verify_session(s, key=KEY)
    assert r["valid"] is False and "tamper" in r["reason"].lower()


def test_verify_denies_an_expired_session():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    s = lg.issue_session(user="alice", tier="pro", key=KEY, ttl_s=60, now=now)
    ok = lg.verify_session(s, key=KEY, now=now + timedelta(seconds=30))
    late = lg.verify_session(s, key=KEY, now=now + timedelta(seconds=120))
    assert ok["valid"] is True and late["valid"] is False and "expired" in late["reason"]


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
    print(f"ok: {len(fns)} login tests passed")
    sys.exit(0)
