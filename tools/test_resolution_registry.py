#!/usr/bin/env python3
"""Tests for resolution reuse (deposit → Next-Best-Action → ARM feedback) over the real commons."""
import commons as cm
import resolution_registry as rr


def _resolution(name="resolution-ADR-0001", cat="dependency-swap-percolation", digest="sha256:" + "ab" * 32,
                tags=("nix", "guix", "swap")):
    return {"domain": "governance/migration", "name": name, "version": "v0.1", "category": cat,
            "tags": list(tags), "recommendation": "apply Firewall #1",
            "content": {"root_cause": "swap nix→guix built no graph", "graph_digest": digest}}


def test_deposit_is_a_reproducible_resolution_asset():
    c = cm.Commons()
    rec = rr.deposit_resolution(c, _resolution())
    assert rec["asset_type"] == "resolution" and rec["category"] == "dependency-swap-percolation"
    assert rec["reproducibility"] == "reproducible"  # carries graph_digest
    assert c.search(asset_type="resolution") == [rec]


def test_resolution_without_a_graph_digest_is_only_declared():
    c = cm.Commons()
    r = _resolution(digest=None)
    r["content"]["graph_digest"] = None
    rec = rr.deposit_resolution(c, r)
    assert rec["reproducibility"] == "declared"


def test_next_best_action_finds_the_prior_resolution_for_the_failure_class():
    c = cm.Commons()
    dep = rr.deposit_resolution(c, _resolution())
    nba = rr.next_best_action(c, failure_class="dependency-swap-percolation", from_lang="nix", to_lang="guix")
    assert [r["commons_id"] for r in nba] == [dep["commons_id"]]
    assert nba[0]["semantic_action"]["recommendation"] == "apply Firewall #1"


def test_a_genuinely_new_failure_class_has_no_prior_resolution():
    c = cm.Commons()
    rr.deposit_resolution(c, _resolution())
    assert rr.next_best_action(c, failure_class="some-brand-new-failure") == []


def test_apply_records_reuse_and_ranks_most_reused_first():
    c = cm.Commons()
    a = rr.deposit_resolution(c, _resolution(name="res-a"))
    b = rr.deposit_resolution(c, _resolution(name="res-b"))
    # apply b twice, a once → b should rank first
    rr.apply_resolution(c, a["commons_id"])
    rr.apply_resolution(c, b["commons_id"])
    rr.apply_resolution(c, b["commons_id"])
    ranked = rr.next_best_action(c, failure_class="dependency-swap-percolation", limit=5)
    assert ranked[0]["commons_id"] == b["commons_id"]
    assert ranked[0]["reuse"]["uses"] == 2


def test_lang_filter_excludes_other_swaps():
    c = cm.Commons()
    rr.deposit_resolution(c, _resolution(tags=("python2", "python3", "swap")))
    # a nix→guix case should not match a python2→3 resolution in the same failure class
    nba = rr.next_best_action(c, failure_class="dependency-swap-percolation", from_lang="nix", to_lang="guix")
    assert nba == []


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"ok: {len(fns)} resolution-registry tests passed")
    sys.exit(0)
