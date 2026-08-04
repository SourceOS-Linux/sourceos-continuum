#!/usr/bin/env python3
"""Resolution reuse — deposit RCA Resolution assets into the commons/ARM and find them next time.

Closes the ARM feedback loop for root-cause work (the IBM ARM diagram: Domain → Category → Asset →
Recommendation → Feedback; and "Next Best Action for a Case"): a Resolution asset (produced by the
RCA pipeline — a tagged, content-addressed record carrying the root-cause graph SVG + remediation) is
**deposited into the real continuum commons** as `asset_type="resolution"`, keyed by its failure-class
category. When the same failure class recurs, `next_best_action()` retrieves the prior resolution to
apply — recommendation, not a fresh investigation — and `apply_resolution()` feeds the ARM reuse loop
(`commons.record_use`) so the most-reused, most-successful resolutions rank first.

Thin adapter over `commons.Commons` — no parallel store. stdlib only.
"""
from __future__ import annotations

import commons as cm


def deposit_resolution(commons: cm.Commons, resolution: dict) -> dict:
    """Deposit a Resolution asset record into the commons as a first-class, reusable asset. The record
    is the portable shape the RCA pipeline emits (asset_type='resolution', category=failure-class,
    tags, content{...graph_digest, remediation, svg...})."""
    content = resolution.get("content", resolution)
    graph_digest = content.get("graph_digest")
    provenance = {"source_ref": resolution.get("commons_id", "resolution"),
                  "tags": resolution.get("tags", [])}
    # a resolution is 'reproducible' iff it carries the graph digest that rebuilds its evidence.
    if graph_digest:
        provenance["source_digest"] = graph_digest
        provenance["sbom_digest"] = graph_digest  # the graph IS the reproducible evidence bundle
    return commons.deposit(
        domain=resolution.get("domain", "governance/migration"),
        name=resolution.get("name", "resolution-unknown"),
        version=resolution.get("version", "v0.1"),
        asset_type="resolution",
        category=resolution.get("category", "resolution"),
        content=content,
        provenance=provenance,
        semantic_action={"recommendation": resolution.get("recommendation"),
                         "tags": resolution.get("tags", [])})


def next_best_action(commons: cm.Commons, *, failure_class: str, from_lang: str | None = None,
                     to_lang: str | None = None, limit: int = 3) -> list[dict]:
    """ARM 'Next Best Action for a case': given a NEW failure's class (and optionally the swap langs),
    return the prior Resolution assets to apply, most-reused/most-successful first. Empty = no prior
    resolution — genuinely new failure."""
    pool = commons.search(asset_type="resolution", category=failure_class)
    if from_lang or to_lang:
        def langs_match(r):
            c = r.get("content", {})
            return ((not from_lang or c.get("root_cause", "").find(from_lang) >= 0
                     or from_lang in (r.get("semantic_action", {}).get("tags") or []))
                    and (not to_lang or to_lang in (r.get("semantic_action", {}).get("tags") or [])))
        pool = [r for r in pool if langs_match(r)]
    return sorted(pool, key=lambda r: (r["reuse"]["score"], r["reuse"]["uses"]), reverse=True)[:limit]


def apply_resolution(commons: cm.Commons, commons_id: str, *, outcome: str = "ok") -> dict | None:
    """Record that a resolution was applied to a case — the ARM use/evaluate feedback that raises its
    reuse score, so proven resolutions surface first next time."""
    return commons.record_use(commons_id, outcome=outcome)


if __name__ == "__main__":
    import json

    commons = cm.Commons()
    # a Resolution asset from the RCA pipeline (Nix→Guix percolation).
    resolution = {
        "domain": "governance/migration", "name": "resolution-ADR-0001-nix-to-guix", "version": "v0.1",
        "category": "dependency-swap-percolation", "tags": ["nix", "guix", "swap", "rca"],
        "recommendation": "apply Firewall #1 (adr_swap_gate) before authoring in scope; reuse this plan",
        "content": {"root_cause": "a swap nix→guix built no dependency graph, so no control caught new "
                    "FROM artifacts", "graph_digest": "sha256:" + "ab" * 32, "residual": 63},
    }
    dep = deposit_resolution(commons, resolution)

    # later: a NEW case of the same failure class arrives → Next Best Action finds the prior resolution.
    nba = next_best_action(commons, failure_class="dependency-swap-percolation",
                           from_lang="nix", to_lang="guix")
    for r in nba:
        apply_resolution(commons, r["commons_id"])  # applied to the new case (feedback)
    applied = commons.resolve(dep["commons_id"])

    print(json.dumps({
        "deposited": {"commons_id": dep["commons_id"], "asset_type": dep["asset_type"],
                      "category": dep["category"], "reproducibility": dep["reproducibility"]},
        "next_best_action_found": [r["commons_id"] for r in nba],
        "recommendation": nba[0]["semantic_action"]["recommendation"] if nba else None,
        "reuse_after_apply": applied["reuse"],
    }, indent=2))
