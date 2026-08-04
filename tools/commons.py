#!/usr/bin/env python3
"""Reproducible Knowledge Commons — a Zenodo-style, citable, reproducible, reusable layer over the
whole estate.

Every capability, workload, model, dataset, or semantic action becomes a **commons record**: a
content-addressed, citable deposit (a DOI-like `commons:<domain>/<name>@<version>+<digest>`), carrying
its reproducibility provenance and its reuse history. Three demonstrated systems, folded into one:

  * Zenodo / reproducible-fusion commons: content-addressed + citable + versioned; a record is only
    marked `reproducible` if its provenance actually carries the digests to reproduce it — otherwise
    it is honestly `declared`. Fail-closed on the reproducibility claim.
  * ARM (Asset Reuse Manager): Domain → Category → Asset, with recommendation + a use/evaluate
    feedback loop that raises a record's reuse score.
  * Semantic API / ontology: a record may carry a declarative `semantic_action` (signature +
    ontology constraints + executor), so the commons is also the semantic-action catalog.

The commons ingests the estate's own CapDs and suite workloads, so the compute-mesh / cloud-shell
fog work we built is itself first-class here — citable and reusable — not a thing off to the side.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def _canon(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def mint_id(domain: str, name: str, version: str, content) -> tuple[str, str]:
    """Content-addressed, citable id. Same inputs -> same id (reproducible; Zenodo-style versioning)."""
    digest = hashlib.sha256(_canon({"domain": domain, "name": name, "version": version,
                                     "content": content})).hexdigest()
    return f"commons:{domain}/{name}@{version}+{digest[:12]}", "sha256:" + digest


def _domain_of(capability_id: str) -> str:
    # caps.compute.mesh-plane@0.1.0 -> "compute"; caps.dev.x -> "dev"; caps.infra.y -> "infra"
    parts = capability_id.split("@")[0].split(".")
    return parts[1] if len(parts) > 1 else "misc"


class Commons:
    """The deposit store + ARM reuse graph + semantic-action catalog."""

    def __init__(self):
        self._records: dict[str, dict] = {}

    # ── deposit (Zenodo) + reproducibility gate (MLOps provenance) ───────────────────
    def deposit(self, *, domain: str, name: str, version: str, asset_type: str, content,
                category: str | None = None, provenance: dict | None = None,
                semantic_action: dict | None = None, reuse: dict | None = None) -> dict:
        provenance = provenance or {}
        cid, content_digest = mint_id(domain, name, version, content)
        # a record may only claim `reproducible` if it carries what you'd need to reproduce it:
        # a source digest AND either an attestation reference or an SBOM digest. Else: `declared`.
        reproducible = bool(provenance.get("source_digest")) and \
            bool(provenance.get("attestation_ref") or provenance.get("sbom_digest"))
        rec = {
            "commons_id": cid,
            "content_digest": content_digest,
            "domain": domain, "name": name, "version": version,
            "asset_type": asset_type, "category": category or asset_type,
            "provenance": provenance,
            "reproducibility": "reproducible" if reproducible else "declared",
            "semantic_action": semantic_action,
            "reuse": reuse or {"uses": 0, "evaluations": 0, "score": 0.0},
            "cite": f"{name} {version}. Commons {cid}.",
        }
        self._records[cid] = rec
        return rec

    # ── ingest the estate: its own CapDs and suite workloads become first-class records ──
    def ingest_capds(self, capd_dir) -> int:
        d = Path(capd_dir)
        n = 0
        for f in sorted(d.glob("*.capd.json")) if d.is_dir() else []:
            try:
                data = json.loads(f.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            cap_id = data.get("capability_id", f.stem)
            name, _, version = cap_id.partition("@")
            links = data.get("links", {})
            # reproducible iff the CapD points at a supply-chain/attestation provenance
            provenance = {"source_ref": f"capd://{f.name}", "kind": data.get("kind"),
                          "links": links}
            if any(k in links for k in ("supply_chain_gate", "shape_authority", "ledger")):
                provenance["attestation_ref"] = links.get("supply_chain_gate") or links.get("ledger")
                provenance["source_digest"] = "sha256:" + hashlib.sha256(f.read_bytes()).hexdigest()
            self.deposit(domain=_domain_of(cap_id), name=name or f.stem,
                         version=version or "0.0.0", asset_type="capability",
                         category=data.get("kind", "capability"), content=data,
                         provenance=provenance)
            n += 1
        return n

    def ingest_workloads(self, path) -> int:
        try:
            profiles = json.loads(Path(path).read_text())["workloads"]
        except (OSError, json.JSONDecodeError, KeyError):
            return 0
        for p in profiles:
            self.deposit(domain="workload", name=p.get("id", "unknown"), version="0.1.0",
                         asset_type="workload", category=p.get("product", "workload"),
                         content=p, provenance={"source_ref": "mesh/suite-workloads.json"},
                         semantic_action={"policy": p.get("policy", {}), "workload": p.get("workload", {})})
        return len(profiles)

    # ── resolve / search / ARM recommend / feedback ──────────────────────────────────
    def resolve(self, commons_id: str) -> dict | None:
        return self._records.get(commons_id)

    def records(self) -> list[dict]:
        return list(self._records.values())

    def search(self, *, domain=None, category=None, asset_type=None, reproducible=None) -> list[dict]:
        out = []
        for r in self._records.values():
            if domain and r["domain"] != domain:
                continue
            if category and r["category"] != category:
                continue
            if asset_type and r["asset_type"] != asset_type:
                continue
            if reproducible is not None and (r["reproducibility"] == "reproducible") != reproducible:
                continue
            out.append(r)
        return out

    def recommend(self, *, domain=None, asset_type=None, limit=5) -> list[dict]:
        """ARM recommendation: most-reused, most-evaluated records first (optionally within a domain)."""
        pool = self.search(domain=domain, asset_type=asset_type)
        return sorted(pool, key=lambda r: (r["reuse"]["score"], r["reuse"]["uses"]), reverse=True)[:limit]

    def record_use(self, commons_id: str, outcome: str = "ok") -> dict | None:
        """ARM use/evaluate feedback loop — raises the record's reuse score."""
        rec = self._records.get(commons_id)
        if rec is None:
            return None
        rec["reuse"]["uses"] += 1
        if outcome == "ok":
            rec["reuse"]["evaluations"] += 1
        rec["reuse"]["score"] = round(rec["reuse"]["evaluations"] / max(rec["reuse"]["uses"], 1), 3)
        return rec


def estate_commons(root) -> Commons:
    """A Commons populated from the estate: this repo's CapDs + the suite workloads."""
    root = Path(root)
    c = Commons()
    c.ingest_capds(root / "capd")
    c.ingest_workloads(root / "mesh" / "suite-workloads.json")
    return c


if __name__ == "__main__":
    import sys
    root = Path(__file__).resolve().parent.parent
    c = estate_commons(root)
    recs = c.records()
    print(json.dumps({
        "total": len(recs),
        "by_asset_type": {t: len(c.search(asset_type=t)) for t in {r["asset_type"] for r in recs}},
        "reproducible": len(c.search(reproducible=True)),
        "sample": [{"commons_id": r["commons_id"], "reproducibility": r["reproducibility"],
                    "cite": r["cite"]} for r in recs[:6]],
    }, indent=2))
    sys.exit(0)
