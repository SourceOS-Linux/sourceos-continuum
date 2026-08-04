#!/usr/bin/env python3
"""Tests for the pull/lease scheduler. Load-bearing: conservative single-copy dispatch (one WU to
one worker), crash-stop re-lending (a dead worker's unit is not lost), ordered re-merge, and the
per-worker Limiter. Time is injected so crash detection is deterministic."""
import lease_scheduler as ls


class Clock:
    def __init__(self, t=0.0):
        self.t = t

    def __call__(self):
        return self.t


def test_limiter_caps_in_flight_per_worker():
    s = ls.LeaseScheduler(range(10), max_in_flight=3, clock=Clock())
    assert len(s.lease("w", n=10)) == 3


def test_conservative_single_copy_no_double_lease():
    s = ls.LeaseScheduler(["a", "b"], max_in_flight=4, clock=Clock())
    w1 = s.lease("w1", 2)
    assert len(w1) == 2 and s.lease("w2", 2) == []  # both held by w1; nothing for w2


def test_results_re_merge_in_index_order():
    s = ls.LeaseScheduler(["a", "b", "c"], max_in_flight=4, clock=Clock())
    got = s.lease("w", 3)
    s.complete(got[2]["lease_id"], "C")  # complete out of order
    s.complete(got[0]["lease_id"], "A")
    s.complete(got[1]["lease_id"], "B")
    assert s.results_in_order() == ["A", "B", "C"]


def test_crashed_worker_unit_is_relent_and_late_result_dropped():
    clk = Clock()
    s = ls.LeaseScheduler(["only"], max_in_flight=4, lease_ttl_s=10, clock=clk)
    a = s.lease("A", 1)[0]
    assert s.lease("B", 1) == []          # conservative: B gets nothing while A holds it
    clk.t = 20                            # A missed its deadline -> crashed
    b = s.lease("B", 1)
    assert len(b) == 1 and b[0]["wu"] == "only"   # re-lent to B
    assert s.complete(a["lease_id"], "stale") is False   # A's late result is dropped
    assert s.complete(b[0]["lease_id"], "fresh") is True
    assert s.results_in_order() == ["fresh"]      # the unit ran exactly once, authoritative copy


def test_heartbeat_prevents_reclaim():
    clk = Clock()
    s = ls.LeaseScheduler(["x"], lease_ttl_s=10, clock=clk)
    s.lease("A", 1)
    clk.t = 8
    s.heartbeat("A")          # extends deadline to 18
    clk.t = 15
    assert s.lease("B", 1) == []   # still alive; not reclaimed


def test_adaptive_a_fast_worker_drains_more():
    s = ls.LeaseScheduler(range(6), max_in_flight=2, clock=Clock())
    a_total = 0
    while not s.drained():
        got = s.lease("A", 2)   # A keeps pulling; B never does
        for lz in got:
            s.complete(lz["lease_id"], lz["index"])
            a_total += 1
    assert a_total == 6


def test_end_to_end_two_workers_one_crash_each_wu_once():
    clk = Clock()
    s = ls.LeaseScheduler([f"wu{i}" for i in range(4)], max_in_flight=1, lease_ttl_s=10, clock=clk)
    a = s.lease("A", 1)[0]
    s.lease("B", 1)                    # B takes one then crashes (never completes)
    s.complete(a["lease_id"], a["wu"])
    clk.t = 20                         # B reclaimed
    while not s.drained():
        for lz in s.lease("A", 4):
            s.complete(lz["lease_id"], lz["wu"])
    assert sorted(s.results_in_order()) == ["wu0", "wu1", "wu2", "wu3"]  # every WU exactly once


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
    print(f"ok: {len(fns)} lease-scheduler tests passed")
    sys.exit(0)
