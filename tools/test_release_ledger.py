#!/usr/bin/env python3
"""Tests for the release ledger + instant rollback."""
import tempfile

import release_ledger as rl


def _seed(td, digests, tenant="acme", app="shop"):
    for dig in digests:
        rl.record(td, rl.make_release(tenant=tenant, app=app, branch="main",
                                      image=f"{app}@sha256:{dig[:12]}",
                                      image_digest="sha256:" + dig, workload_name=app))


def test_history_is_newest_first_and_current_is_the_head():
    with tempfile.TemporaryDirectory() as td:
        _seed(td, ["aa" * 32, "bb" * 32, "cc" * 32])
        hist = rl.history(td, "acme", "shop")
        assert [r["image_digest"][-2:] for r in hist] == ["cc"[-2:], "bb"[-2:], "aa"[-2:]]
        assert rl.current(td, "acme", "shop")["image_digest"] == "sha256:" + "cc" * 32


def test_rollback_one_step_repoints_to_previous_image_no_rebuild():
    with tempfile.TemporaryDirectory() as td:
        _seed(td, ["aa" * 32, "bb" * 32, "cc" * 32])
        d = rl.rollback(td, tenant="acme", app="shop")  # cc -> bb
        assert d["ok"] and d["placement"] == "rolled-back"
        assert d["instant"] is True and d["no_rebuild"] is True
        assert d["to"]["image_digest"] == "sha256:" + "bb" * 32
        assert rl.current(td, "acme", "shop")["image_digest"] == "sha256:" + "bb" * 32


def test_rollback_to_a_specific_prior_digest():
    with tempfile.TemporaryDirectory() as td:
        _seed(td, ["aa" * 32, "bb" * 32, "cc" * 32])
        d = rl.rollback(td, tenant="acme", app="shop", to_digest="sha256:" + "aa" * 32)
        assert d["ok"] and d["to"]["image_digest"] == "sha256:" + "aa" * 32
        assert rl.current(td, "acme", "shop")["image_digest"] == "sha256:" + "aa" * 32


def test_rollback_creates_a_new_auditable_head_linking_from_and_to():
    with tempfile.TemporaryDirectory() as td:
        _seed(td, ["aa" * 32, "bb" * 32])
        before = rl.history(td, "acme", "shop")
        d = rl.rollback(td, tenant="acme", app="shop")
        head = rl.current(td, "acme", "shop")
        assert len(rl.history(td, "acme", "shop")) == len(before) + 1  # rollback is itself a release
        assert head["kind"] == "rollback" and head["status"] == "rolled-back"
        assert head["rolled_back_from"] == d["from"]["release_id"]
        assert head["rolled_back_to"] == d["to"]["release_id"]


def test_rollback_to_an_image_that_never_ran_is_blocked_failclosed():
    with tempfile.TemporaryDirectory() as td:
        _seed(td, ["aa" * 32, "bb" * 32])
        d = rl.rollback(td, tenant="acme", app="shop", to_digest="sha256:" + "99" * 32)
        assert d["ok"] is False and d["placement"] == "blocked"
        # nothing served: current is unchanged
        assert rl.current(td, "acme", "shop")["image_digest"] == "sha256:" + "bb" * 32


def test_rollback_with_no_history_is_blocked():
    with tempfile.TemporaryDirectory() as td:
        d = rl.rollback(td, tenant="acme", app="shop")
        assert d["ok"] is False and d["placement"] == "blocked"


def test_rollback_to_the_current_release_is_a_noop():
    with tempfile.TemporaryDirectory() as td:
        _seed(td, ["aa" * 32, "bb" * 32])
        head_id = rl.current(td, "acme", "shop")["release_id"]  # bb is serving
        d = rl.rollback(td, tenant="acme", app="shop", to_release_id=head_id)
        assert d["ok"] and d["placement"] == "no-op"
        # a no-op does not append a new head
        assert len(rl.history(td, "acme", "shop")) == 2


def test_rollback_to_currently_serving_digest_finds_no_prior_release():
    # to_digest looks only at PRIOR releases; the serving digest isn't a prior one, so it's blocked.
    with tempfile.TemporaryDirectory() as td:
        _seed(td, ["aa" * 32, "bb" * 32])
        d = rl.rollback(td, tenant="acme", app="shop", to_digest="sha256:" + "bb" * 32)
        assert d["ok"] is False and d["placement"] == "blocked"


def test_record_deploy_records_only_successful_deploys():
    with tempfile.TemporaryDirectory() as td:
        ok = {"status": "deployed", "branch": "pr-1", "image": "shop@sha256:abc",
              "build_digest": "sha256:" + "ab" * 32, "workload": {"name": "shop"}}
        failed = {"status": "build-failed", "reason": "no buildpack"}
        assert rl.record_deploy(td, tenant="acme", app="shop", deploy_result=ok) is not None
        assert rl.record_deploy(td, tenant="acme", app="shop", deploy_result=failed) is None
        assert len(rl.history(td, "acme", "shop")) == 1  # only the successful one is a release


def test_release_and_rollback_records_are_sealed():
    with tempfile.TemporaryDirectory() as td:
        _seed(td, ["aa" * 32, "bb" * 32])
        assert rl.current(td, "acme", "shop")["receipt_digest"].startswith("sha256:")
        d = rl.rollback(td, tenant="acme", app="shop")
        assert d["receipt_digest"].startswith("sha256:")


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"ok: {len(fns)} release-ledger tests passed")
    sys.exit(0)
