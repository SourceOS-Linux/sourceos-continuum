"""Coverage for tools/promotion_gate.py — continuum's rollout promotion gate.

The gate consumes a sealed review verdict (produced by the prophet-platform reviewer) and
decides promotion. Fail-closed: only APPROVE with an intact seal promotes; REJECT,
NEEDS_HUMAN, and a tampered verdict all block — and every decision, allow or block, is
written to the per-action evidence bundle.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("promotion_gate", ROOT / "tools" / "promotion_gate.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["promotion_gate"] = mod
    spec.loader.exec_module(mod)
    return mod


pg = _load()


def _sealed(verdict_value: str, key: str = "engine-at-0.4.45") -> dict:
    v = {
        "tool": "prophet-platform.review_gate.v1",
        "reviewed": {"idempotency_key": key, "to_version": "0.4.45"},
        "verdict": verdict_value,
        "checks": [],
    }
    v["review_digest"] = pg._recompute_seal(v)
    return v


def test_approve_promotes_and_writes_evidence(tmp_path):
    promote, dec = pg.gate(_sealed("APPROVE"), tmp_path)
    assert promote is True and dec["promotion"] == "allow"
    written = list(tmp_path.glob("*.json"))
    assert len(written) == 1
    assert json.loads(written[0].read_text())["promotion"] == "allow"


def test_reject_blocks(tmp_path):
    promote, dec = pg.gate(_sealed("REJECT"), tmp_path)
    assert promote is False and dec["promotion"] == "block"
    assert "requires APPROVE" in dec["reason"]


def test_needs_human_blocks(tmp_path):
    promote, _ = pg.gate(_sealed("NEEDS_HUMAN"), tmp_path)
    assert promote is False


def test_tampered_verdict_blocks_even_when_it_says_approve(tmp_path):
    v = _sealed("REJECT")          # seal is computed over REJECT
    v["verdict"] = "APPROVE"       # flip to APPROVE without re-sealing
    promote, dec = pg.gate(v, tmp_path)
    assert promote is False and dec["seal_ok"] is False
    assert "seal did not recompute" in dec["reason"]


def test_missing_seal_blocks(tmp_path):
    promote, dec = pg.gate({"tool": "x", "reviewed": {}, "verdict": "APPROVE"}, tmp_path)
    assert promote is False and dec["seal_ok"] is False


def test_block_is_also_evidenced(tmp_path):
    pg.gate(_sealed("REJECT"), tmp_path)
    written = list(tmp_path.glob("*.json"))
    assert len(written) == 1 and json.loads(written[0].read_text())["promotion"] == "block"


def test_main_exit_codes(tmp_path):
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_sealed("APPROVE")))
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(_sealed("REJECT")))
    assert pg.main(["--verdict", str(good), "--evidence-dir", str(tmp_path / "ev")]) == 0
    assert pg.main(["--verdict", str(bad), "--evidence-dir", str(tmp_path / "ev")]) == 1
