#!/usr/bin/env python3
"""Tests for the git-push webhook — the fail-closed trigger that turns a push into a deploy."""
import hashlib
import hmac
import json
import tempfile

import push_webhook as pw
import release_ledger as rl

_SECRET = "s3cr3t-per-tenant"
_PROJECT = {"tenant": "acme", "user": "alice", "app": "shop", "sensitivity": "normal"}


def _payload(ref="refs/heads/pr-42", after="a" * 40, added=("package.json",), modified=("server.js",),
             repo="productpage", deleted=False):
    return {"ref": ref, "after": after, "deleted": deleted,
            "repository": {"name": repo}, "pusher": {"name": "alice"},
            "commits": [{"added": list(added), "modified": list(modified)}]}


def _raw(payload):
    return json.dumps(payload).encode("utf-8")


def _sign(raw, secret=_SECRET, prefix="sha256="):
    return prefix + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def test_valid_signed_push_builds_and_deploys():
    raw = _raw(_payload())
    d = pw.handle_push(secret=_SECRET, sig_header=_sign(raw), raw_body=raw, project=_PROJECT)
    assert d["status"] == "deployed" and d["accepted"] is True
    assert d["deploy"]["language"] == "node" and d["deploy"]["image"].startswith("productpage-pr-42@")
    assert d["event"]["branch"] == "pr-42" and d["receipt_digest"].startswith("sha256:")


def test_unsigned_push_is_rejected_and_never_builds():
    raw = _raw(_payload())
    d = pw.handle_push(secret=_SECRET, sig_header="", raw_body=raw, project=_PROJECT)
    assert d["status"] == "rejected" and d["accepted"] is False
    assert "deploy" not in d  # THE point: no build was ever started


def test_tampered_signature_is_rejected():
    raw = _raw(_payload())
    forged = _sign(raw, secret="wrong-secret")  # correct shape, wrong key
    d = pw.handle_push(secret=_SECRET, sig_header=forged, raw_body=raw, project=_PROJECT)
    assert d["status"] == "rejected" and "deploy" not in d


def test_body_tampered_after_signing_is_rejected():
    raw = _raw(_payload())
    sig = _sign(raw)
    tampered = _raw(_payload(repo="attacker-owned"))  # different body, old signature
    d = pw.handle_push(secret=_SECRET, sig_header=sig, raw_body=tampered, project=_PROJECT)
    assert d["status"] == "rejected" and "deploy" not in d


def test_gitea_bare_hex_signature_form_is_accepted():
    raw = _raw(_payload())
    d = pw.handle_push(secret=_SECRET, sig_header=_sign(raw, prefix=""), raw_body=raw, project=_PROJECT)
    assert d["status"] == "deployed"


def test_tag_push_is_ignored():
    raw = _raw(_payload(ref="refs/tags/v1.0.0"))
    d = pw.handle_push(secret=_SECRET, sig_header=_sign(raw), raw_body=raw, project=_PROJECT)
    assert d["status"] == "ignored" and "deploy" not in d


def test_branch_delete_is_ignored():
    raw = _raw(_payload(after="0" * 40, deleted=True))
    d = pw.handle_push(secret=_SECRET, sig_header=_sign(raw), raw_body=raw, project=_PROJECT)
    assert d["status"] == "ignored"


def test_valid_signature_but_non_json_body_is_rejected():
    raw = b"\x00\x01 not json"
    d = pw.handle_push(secret=_SECRET, sig_header=_sign(raw), raw_body=raw, project=_PROJECT)
    assert d["status"] == "rejected" and "malformed" in d["reason"]


def test_valid_signature_but_non_object_json_is_rejected_not_crashed():
    # a validly-signed but non-object body ([], 123, "x") must reject cleanly, never raise (no 500).
    for raw in (b"[]", b"123", b'"a string"', b"null"):
        d = pw.handle_push(secret=_SECRET, sig_header=_sign(raw), raw_body=raw, project=_PROJECT)
        assert d["status"] == "rejected" and "deploy" not in d, raw


def test_no_matching_buildpack_is_build_failed_not_deployed():
    raw = _raw(_payload(added=("README.md",), modified=("LICENSE",)))
    d = pw.handle_push(secret=_SECRET, sig_header=_sign(raw), raw_body=raw, project=_PROJECT)
    assert d["status"] == "build-failed" and d["accepted"] is False


def test_resolve_files_supplies_the_full_tree_at_the_pushed_commit():
    # the payload's changed files wouldn't detect Go, but a checkout of the pushed SHA does.
    raw = _raw(_payload(added=("main.go",), modified=("go.sum",)))
    d = pw.handle_push(secret=_SECRET, sig_header=_sign(raw), raw_body=raw, project=_PROJECT,
                       resolve_files=lambda repo, ref, after: ["go.mod", "main.go", "go.sum"])
    assert d["status"] == "deployed" and d["deploy"]["language"] == "go"
    assert d["files_source"] == "checkout"


def test_receipt_is_sealed_and_persisted():
    raw = _raw(_payload())
    with tempfile.TemporaryDirectory() as td:
        d = pw.handle_push(secret=_SECRET, sig_header=_sign(raw), raw_body=raw, project=_PROJECT,
                           receipts_dir=td)
        import pathlib
        files = list(pathlib.Path(td).glob("push-*.json"))
        assert len(files) == 1
        written = json.loads(files[0].read_text())
        assert written["receipt_digest"] == d["receipt_digest"]
        # the receipt is bound to the exact request body
        assert written["body_digest"] == pw._digest(raw)


def test_deployed_push_records_a_rollbackable_release():
    raw = _raw(_payload())
    with tempfile.TemporaryDirectory() as td:
        d = pw.handle_push(secret=_SECRET, sig_header=_sign(raw), raw_body=raw, project=_PROJECT,
                           ledger_dir=td)
        assert d["status"] == "deployed" and "release_id" in d
        hist = rl.history(td, "acme", "shop")
        assert len(hist) == 1 and hist[0]["release_id"] == d["release_id"]


def test_build_failed_push_records_no_release():
    raw = _raw(_payload(added=("README.md",), modified=("LICENSE",)))  # no buildpack match
    with tempfile.TemporaryDirectory() as td:
        d = pw.handle_push(secret=_SECRET, sig_header=_sign(raw), raw_body=raw, project=_PROJECT,
                           ledger_dir=td)
        assert d["status"] == "build-failed" and "release_id" not in d
        assert rl.history(td, "acme", "shop") == []


def test_secret_never_appears_in_decision_or_receipt():
    raw = _raw(_payload())
    d = pw.handle_push(secret=_SECRET, sig_header=_sign(raw), raw_body=raw, project=_PROJECT)
    assert _SECRET not in json.dumps(d)


def test_project_for_path_parses_tenant_and_app():
    p = pw.project_for_path("/hooks/acme/shop?x=1")
    assert p["tenant"] == "acme" and p["app"] == "shop"
    p2 = pw.project_for_path("/hooks/acme")
    assert p2["tenant"] == "acme" and p2["app"] == "default"


def test_verify_signature_rejects_empties():
    assert pw.verify_signature("", b"body", "sha256=x") is False
    assert pw.verify_signature("s", b"", "sha256=x") is False
    assert pw.verify_signature("s", b"body", "") is False


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"ok: {len(fns)} push-webhook tests passed")
    sys.exit(0)
