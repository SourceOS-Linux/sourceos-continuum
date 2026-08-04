#!/usr/bin/env python3
"""Tests for the Reproducible Knowledge Commons. Load-bearing: (1) the reproducibility gate — a
record may only claim `reproducible` if its provenance actually carries the digests; (2) the ARM
use/evaluate feedback loop; (3) the estate ingests itself, so the compute-mesh/fog work is a
first-class citable record."""
import pathlib

import commons as cm

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_mint_id_is_content_addressed_and_deterministic():
    a, da = cm.mint_id("compute", "mesh-plane", "0.1.0", {"x": 1})
    b, db = cm.mint_id("compute", "mesh-plane", "0.1.0", {"x": 1})
    c, _ = cm.mint_id("compute", "mesh-plane", "0.1.0", {"x": 2})
    assert a == b and da == db and a.startswith("commons:compute/mesh-plane@0.1.0+")
    assert c != a  # different content -> different citable id (reproducible versioning)


def test_reproducibility_gate_requires_real_provenance():
    c = cm.Commons()
    weak = c.deposit(domain="ml", name="model", version="1", asset_type="model", content={"w": 1})
    strong = c.deposit(domain="ml", name="model", version="2", asset_type="model", content={"w": 2},
                       provenance={"source_digest": "sha256:" + "a" * 64, "attestation_ref": "worm://a1"})
    half = c.deposit(domain="ml", name="model", version="3", asset_type="model", content={"w": 3},
                     provenance={"source_digest": "sha256:" + "b" * 64})  # no attestation/sbom
    assert weak["reproducibility"] == "declared"
    assert strong["reproducibility"] == "reproducible"
    assert half["reproducibility"] == "declared"  # source alone is not enough


def test_deposit_is_citable():
    c = cm.Commons()
    rec = c.deposit(domain="data", name="corpus", version="0.2.0", asset_type="dataset", content={"n": 10})
    assert rec["cite"].startswith("corpus 0.2.0. Commons commons:data/corpus@0.2.0+")


def test_arm_use_evaluate_feedback_raises_score():
    c = cm.Commons()
    rec = c.deposit(domain="d", name="a", version="1", asset_type="capability", content={})
    cid = rec["commons_id"]
    c.record_use(cid, "ok")
    c.record_use(cid, "ok")
    c.record_use(cid, "fail")
    r = c.resolve(cid)
    assert r["reuse"]["uses"] == 3 and r["reuse"]["evaluations"] == 2 and r["reuse"]["score"] == 0.667


def test_recommend_orders_by_reuse():
    c = cm.Commons()
    lo = c.deposit(domain="d", name="lo", version="1", asset_type="capability", content={"a": 1})
    hi = c.deposit(domain="d", name="hi", version="1", asset_type="capability", content={"a": 2})
    for _ in range(3):
        c.record_use(hi["commons_id"], "ok")
    top = c.recommend(domain="d")
    assert top[0]["name"] == "hi" and top[-1]["name"] == "lo"


def test_estate_ingests_itself_including_the_fog_work():
    c = cm.estate_commons(ROOT)
    caps = c.search(asset_type="capability")
    ids = {r["commons_id"].split("+")[0] for r in caps}
    # the compute-mesh + cloud-shell fog capabilities are first-class citable records
    assert any("caps.compute.mesh-plane" in i for i in ids), ids
    assert any("caps.compute.cloudshell-fog" in i for i in ids), ids
    # the cloudshell-fog CapD references a ledger/shape-authority, so it ingests as reproducible
    fog = next(r for r in caps if "cloudshell-fog" in r["commons_id"])
    assert fog["reproducibility"] == "reproducible"


def test_estate_ingests_the_suite_workloads_with_semantic_actions():
    c = cm.estate_commons(ROOT)
    workloads = c.search(asset_type="workload")
    assert len(workloads) >= 5
    bear = next((r for r in workloads if "bearbrowser" in r["name"]), None)
    assert bear is not None and bear["semantic_action"]["policy"]  # policy carried as the semantic action


def test_search_filters_by_domain_and_reproducibility():
    c = cm.estate_commons(ROOT)
    assert all(r["domain"] == "compute" for r in c.search(domain="compute"))
    assert all(r["reproducibility"] == "reproducible" for r in c.search(reproducible=True))


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
    print(f"ok: {len(fns)} commons tests passed")
    sys.exit(0)
