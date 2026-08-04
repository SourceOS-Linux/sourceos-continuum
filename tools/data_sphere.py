#!/usr/bin/env python3
"""Data Spheres — ring-fenced, immutable, provenance-tracked data as a first-class governed unit.

A data sphere is the "trusted data sphere" (immutable + persistent + token-gated + provenance) fused
with our commons record + grant + Needs-firewall — and hardened by four lessons read straight off
the sandbox's own live mount table:

  * INTEGRITY by construction, not by flag. `readOnly: true` is a mount-flag assertion — the inode
    stays writable through any other view (a second mount, the host, an rw sidecar). A squashfs/erofs
    image + dm-verity with the root hash PINNED in the manifest makes immutability a signature check,
    not a trust assertion.
  * TENANCY by construction, not by policy. The isolation key lives in the mount SOURCE reference
    (session-scoped, unforgeable from inside the guest) — not a path prefix or an admission rule a
    bad manifest can get wrong.
  * DIRECTION is a first-class axis: ingress | egress | bidirectional | none. Invariant: AT MOST ONE
    egress mount per workload, named — the single durable-write chokepoint where egress attestation
    lives, and the only mount whose contents survive the workload.
  * BACKEND is a function of intent x link_availability x durability, not of the data. Over a reliable
    link a sphere is REFERENCE-mounted (no copy, no divergence, no reconciliation); only an
    intermittent link forces copy + divergence + conflict-resolution.
"""
from __future__ import annotations

import hashlib
import json

DIRECTIONS = ("ingress", "egress", "bidirectional", "none")


def _digest(content) -> str:
    return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def mint_sphere(*, name: str, version: str, content, residency: str = "any",
                direction: str = "ingress", provenance: dict | None = None,
                integrity: str = "dm-verity") -> dict:
    """A content-addressed, immutable data sphere. `root_hash` is the pinned dm-verity root — integrity
    becomes a signature check, not a `readOnly` assertion."""
    assert direction in DIRECTIONS, f"direction must be one of {DIRECTIONS}"
    d = _digest(content)
    return {"sphere_id": f"sphere:{name}@{version}+{d[:12]}",
            "content_digest": "sha256:" + d,
            "residency": residency, "direction": direction,
            "integrity": integrity, "root_hash": "sha256:" + d,  # dm-verity root, pinned
            "immutable": True, "provenance": provenance or {}}


def tenancy_binding(sphere: dict, *, session: str) -> str:
    """Construction-enforced tenancy: the isolation key is in the mount SOURCE ref, session-scoped and
    unforgeable from inside the guest (cf. `rclone-filestore:<session>:/path`)."""
    return f"sphere-store:{session}:{sphere['sphere_id']}"


def read_grant_capability(sphere: dict) -> dict:
    """The Grant capability required to read this sphere (the 'read token'): effect=read, ref bound to
    the sphere id + its content digest."""
    return {"kind": "mcp_tool", "capability_ref": "capd://" + sphere["sphere_id"],
            "capability_digest": sphere["content_digest"], "effect": "read"}


def access_check(sphere: dict, grant: dict, *, requested_effect: str = "read",
                 residency_ok: bool = True) -> dict:
    """Fail-closed access: the Grant must be for THIS sphere, the right effect, integrity pinned, and
    residency satisfied. Returns {authorized, reason}."""
    cap = grant.get("capability", {})
    if not sphere.get("root_hash"):
        return {"authorized": False, "reason": "sphere has no pinned integrity root — refuse"}
    if cap.get("capability_ref") != "capd://" + sphere["sphere_id"]:
        return {"authorized": False, "reason": "grant is not bound to this sphere"}
    if cap.get("capability_digest") != sphere["content_digest"]:
        return {"authorized": False, "reason": "content digest mismatch — sphere mutated or wrong grant"}
    if cap.get("effect") != requested_effect:
        return {"authorized": False, "reason": f"effect {requested_effect!r} not granted (granted {cap.get('effect')!r})"}
    if not residency_ok:
        return {"authorized": False, "reason": f"residency {sphere['residency']!r} not satisfied at this node"}
    return {"authorized": True, "reason": "grant bound, integrity pinned, effect + residency satisfied"}


def check_egress_invariant(mounts: list) -> dict:
    """At most ONE egress mount per workload (the single durable-write chokepoint). mounts:
    [{name, direction}]. Fail-closed on >1."""
    egress = [m["name"] for m in mounts if m.get("direction") == "egress"]
    return {"ok": len(egress) <= 1, "egress_mounts": egress,
            "reason": ("ok" if len(egress) <= 1
                       else f"{len(egress)} egress mounts ({egress}); the invariant is at most one, named")}


def backend_for(*, intent: str, link_availability: str, durability: str, needs: dict | None = None,
                offline_tolerant: bool = False, store_locality: str = "remote") -> dict:
    """intent x link_availability x durability x NEEDS -> backend. The reconciliation burden is a
    function of this product, not a property of the data.

    The Needs firewall prunes the lattice BEFORE link availability, because two Needs forbid the
    cheap reference-mount outright:
      * a `no_egress` Need on a REMOTE store — a remote reference-mount *is* egress, so it's
        forbidden; the data must be copied local.
      * offline-tolerance — a reference-mount has zero offline capability (cut the link, it fails),
        so a workload that must survive link loss has to cache locally even over a reliable link.
    Only after those prunes does link availability pick reference-mount vs copy+reconcile.
    """
    needs = needs or {}
    if needs.get("no_egress") and store_locality == "remote":
        return {"backend": "local-copy", "copy": True, "reconciliation": durability == "canonical",
                "note": "no_egress Need forbids a remote reference-mount (which IS egress) -> local copy"}
    if offline_tolerant:
        return {"backend": "local-cache", "copy": True, "reconciliation": durability == "canonical",
                "note": "offline-tolerant: a reference-mount fails on link loss -> local cache"}
    if link_availability == "reliable":
        return {"backend": "reference-mount", "copy": False, "reconciliation": False,
                "note": "mount it, don't sync it — no second copy, no divergence, no CRF machinery"}
    if durability == "canonical":
        return {"backend": "copy+reconcile", "copy": True, "reconciliation": True,
                "note": "intermittent + canonical: copy forces divergence -> conflict-resolution (SP-EVAL-CRF-001)"}
    return {"backend": "copy", "copy": True, "reconciliation": False,
            "note": "snapshot/export; derived/scratch does not need reconciliation"}


if __name__ == "__main__":
    sphere = mint_sphere(name="crawl-corpus", version="2026.08", content={"docs": 1_000_000},
                         residency="eu", direction="ingress",
                         provenance={"crawl": "SP-SCOPE-CRAWL-001"})
    grant = {"capability": read_grant_capability(sphere)}
    print(json.dumps({
        "sphere_id": sphere["sphere_id"],
        "integrity": f"{sphere['integrity']} root {sphere['root_hash'][:20]}…",
        "tenancy": tenancy_binding(sphere, session="sess_abc"),
        "access": access_check(sphere, grant)["authorized"],
        "reliable_link": backend_for(intent="canonical", link_availability="reliable", durability="canonical")["backend"],
        "intermittent_link": backend_for(intent="canonical", link_availability="intermittent", durability="canonical")["backend"],
        "egress_invariant_2": check_egress_invariant([{"name": "a", "direction": "egress"},
                                                      {"name": "b", "direction": "egress"}])["ok"],
    }, indent=2))
