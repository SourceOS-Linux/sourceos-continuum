#!/usr/bin/env python3
"""Tests for the availability maturity grade (the ZD legend over CapDs)."""
import availability as av


def test_grade_ladder_is_ordered():
    assert av.GRADES == ("non-managed", "needs-work", "almost-zd", "zero-downtime")
    assert av.grade_rank("almost-zd") > av.grade_rank("needs-work") > av.grade_rank("non-managed")
    assert av.grade_rank("bogus") == 0  # unknown -> lowest


def test_estate_reports_declared_grades_and_defaults_the_rest():
    r = av.estate_availability()
    assert r["total"] >= 5
    grades = {c["capability_id"]: c["availability"] for c in r["capabilities"]}
    assert all(g in av.GRADES for g in grades.values())          # every grade is valid (default applied)
    assert r["histogram"]["almost-zd"] >= 3                       # commons, verification, data-spheres
    assert any(g == "needs-work" for g in grades.values())        # compute-plane


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
    print(f"ok: {len(fns)} availability tests passed")
    sys.exit(0)
