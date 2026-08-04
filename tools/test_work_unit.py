#!/usr/bin/env python3
"""Tests for the Work Unit + verification plane. The load-bearing property: an untrusted worker's
result is NEVER accepted unless a quorum of independent workers agrees on it — and liars lose
reputation. This is what makes a 400k-node volunteer mesh trustworthy."""
import work_unit as wu


def test_work_unit_is_content_addressed():
    a = wu.mint_work_unit(task="t", params={"k": 1})
    b = wu.mint_work_unit(task="t", params={"k": 1})
    c = wu.mint_work_unit(task="t", params={"k": 2})
    assert a["wu_id"] == b["wu_id"] and a["wu_id"] != c["wu_id"]
    assert a["wu_id"].startswith("wu:")


def test_replication_defaults_by_proof_mode():
    assert wu.mint_work_unit(task="t", proof_mode="redundant")["replication"] == 3
    assert wu.mint_work_unit(task="t", proof_mode="spot_check")["replication"] == 1


def test_quorum_accepts_the_majority_and_flags_the_liar():
    unit = wu.mint_work_unit(task="image.infer", proof_mode="redundant")
    results = [{"worker": "a", "output": {"label": "cat"}},
               {"worker": "b", "output": {"label": "cat"}},
               {"worker": "c", "output": {"label": "GARBAGE"}}]  # the liar
    v = wu.Verifier().redundant_quorum(unit, results)
    assert v["verified"] is True
    assert v["workers_agree"] == ["a", "b"] and v["workers_disagree"] == ["c"]
    assert v["accepted_digest"] == wu.digest({"label": "cat"})


def test_no_quorum_is_fail_closed():
    unit = wu.mint_work_unit(task="t", proof_mode="redundant")  # replication 3, threshold 2
    results = [{"worker": "a", "output": 1}, {"worker": "b", "output": 2}, {"worker": "c", "output": 3}]
    v = wu.Verifier().redundant_quorum(unit, results)
    assert v["verified"] is False and v["accepted_digest"] is None
    assert "no quorum" in v["reason"]


def test_a_tie_below_threshold_does_not_verify():
    unit = wu.mint_work_unit(task="t", proof_mode="redundant", replication=4)  # threshold 3
    results = [{"worker": "a", "output": 1}, {"worker": "b", "output": 1},
               {"worker": "c", "output": 2}, {"worker": "d", "output": 2}]  # 2-2, neither reaches 3
    assert wu.Verifier().redundant_quorum(unit, results)["verified"] is False


def test_spot_check_rejects_a_wrong_canary():
    good = wu.Verifier().spot_check({"worker": "a", "output": {"ans": 42}}, {"ans": 42})
    bad = wu.Verifier().spot_check({"worker": "b", "output": {"ans": 7}}, {"ans": 42})
    assert good["verified"] is True and bad["verified"] is False


def test_reputation_rewards_agreement_and_penalizes_liars():
    rep = wu.Reputation()
    rep.record(agreed=["a", "b"], disagreed=["c"])
    rep.record(agreed=["a", "b"], disagreed=["c"])
    assert rep.score("a") == 1.0 and rep.score("c") == 0.0
    assert rep.trusted("a") is False  # only 2 samples < min_samples 3
    rep.record(agreed=["a"], disagreed=[])
    assert rep.trusted("a") is True   # 3 verified/3 total >= 0.8
    assert rep.trusted("c") is False


def test_verify_and_score_ties_verification_to_reputation():
    unit = wu.mint_work_unit(task="t", proof_mode="redundant")
    rep = wu.Reputation()
    results = [{"worker": "a", "output": "x"}, {"worker": "b", "output": "x"},
               {"worker": "evil", "output": "lie"}]
    verdict = wu.verify_and_score(unit, results, rep)
    assert verdict["verified"] is True
    assert rep.score("a") == 1.0 and rep.score("evil") == 0.0  # the liar earned nothing


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
    print(f"ok: {len(fns)} work-unit tests passed")
    sys.exit(0)
