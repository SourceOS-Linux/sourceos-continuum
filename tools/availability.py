#!/usr/bin/env python3
"""Availability maturity grade — the BlueMix / DW-DevOps Zero-Downtime legend as a governance artifact.

Every capability carries an honest availability GRADE (like the commons' reproducible/declared grade).
The ladder is the continuous-availability legend from the Gen4 diagram:

    non-managed  ->  needs-work  ->  almost-zd  ->  zero-downtime

A CapD declares its grade in `policy.availability` (default: non-managed). This reports the estate's
availability posture at a glance and gives promotion a hook — a capability shouldn't claim a grade it
can't back. Sovereign + light: a legend, not an IBM stack.
"""
from __future__ import annotations

import json
from pathlib import Path

GRADES = ("non-managed", "needs-work", "almost-zd", "zero-downtime")
_ROOT = Path(__file__).resolve().parent.parent


def grade_rank(grade: str) -> int:
    return GRADES.index(grade) if grade in GRADES else 0


def estate_availability(root=None) -> dict:
    """Read every CapD's declared availability grade. Returns per-capability grades + a histogram."""
    root = Path(root or _ROOT)
    caps = []
    d = root / "capd"
    for f in sorted(d.glob("*.capd.json")) if d.is_dir() else []:
        try:
            data = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        grade = data.get("policy", {}).get("availability", "non-managed")
        if grade not in GRADES:
            grade = "non-managed"
        caps.append({"capability_id": data.get("capability_id", f.stem), "availability": grade})
    hist = {g: sum(1 for c in caps if c["availability"] == g) for g in GRADES}
    return {"capabilities": sorted(caps, key=lambda c: -grade_rank(c["availability"])),
            "histogram": hist, "total": len(caps)}


if __name__ == "__main__":
    report = estate_availability()
    print(json.dumps({"histogram": report["histogram"], "total": report["total"],
                      "top": [c for c in report["capabilities"] if c["availability"] != "non-managed"]},
                     indent=2))
