#!/usr/bin/env python3
"""Tests for Data Spheres. Load-bearing: access is fail-closed and integrity-pinned (a mutated
sphere or a wrong-effect grant is denied), the at-most-one-egress invariant holds, and the
intent×link×durability lattice picks reference-mount over reliable links (no reconciliation)."""
import data_sphere as ds


def test_sphere_is_content_addressed_immutable_and_integrity_pinned():
    s = ds.mint_sphere(name="corpus", version="1", content={"n": 10}, direction="ingress")
    assert s["sphere_id"].startswith("sphere:corpus@1+") and s["immutable"] is True
    assert s["root_hash"].startswith("sha256:") and s["integrity"] == "dm-verity"
    # same content -> same id (content-addressed); different content -> different
    assert ds.mint_sphere(name="corpus", version="1", content={"n": 10})["sphere_id"] == s["sphere_id"]
    assert ds.mint_sphere(name="corpus", version="1", content={"n": 11})["sphere_id"] != s["sphere_id"]


def test_tenancy_is_bound_in_the_mount_source_not_the_path():
    s = ds.mint_sphere(name="c", version="1", content={})
    binding = ds.tenancy_binding(s, session="sess_xyz")
    assert binding.startswith("sphere-store:sess_xyz:")  # session in the source ref, unforgeable


def test_access_check_authorizes_a_bound_read_grant():
    s = ds.mint_sphere(name="c", version="1", content={"x": 1})
    grant = {"capability": ds.read_grant_capability(s)}
    assert ds.access_check(s, grant)["authorized"] is True


def test_access_denies_wrong_effect_mutation_and_bad_residency():
    s = ds.mint_sphere(name="c", version="1", content={"x": 1}, residency="eu")
    grant = {"capability": ds.read_grant_capability(s)}
    # wrong effect
    assert ds.access_check(s, grant, requested_effect="write")["authorized"] is False
    # residency not satisfied at this node
    assert ds.access_check(s, grant, residency_ok=False)["authorized"] is False
    # content-digest mismatch = sphere mutated or wrong grant
    tampered = {"capability": {**ds.read_grant_capability(s), "capability_digest": "sha256:" + "0" * 64}}
    assert ds.access_check(s, tampered)["authorized"] is False


def test_access_refuses_a_sphere_without_pinned_integrity():
    s = ds.mint_sphere(name="c", version="1", content={})
    s = {**s, "root_hash": None}  # integrity not pinned
    grant = {"capability": ds.read_grant_capability(s)}
    assert ds.access_check(s, grant)["authorized"] is False


def test_at_most_one_egress_mount_invariant():
    ok = ds.check_egress_invariant([{"name": "out", "direction": "egress"},
                                    {"name": "in", "direction": "ingress"}])
    bad = ds.check_egress_invariant([{"name": "out1", "direction": "egress"},
                                     {"name": "out2", "direction": "egress"}])
    assert ok["ok"] is True and bad["ok"] is False
    assert bad["egress_mounts"] == ["out1", "out2"]


def test_backend_lattice_reference_mounts_over_reliable_links():
    reliable = ds.backend_for(intent="canonical", link_availability="reliable", durability="canonical")
    assert reliable["backend"] == "reference-mount" and reliable["copy"] is False and reliable["reconciliation"] is False
    # intermittent + canonical -> the reconciliation burden appears (not before)
    inter = ds.backend_for(intent="canonical", link_availability="intermittent", durability="canonical")
    assert inter["copy"] is True and inter["reconciliation"] is True
    # intermittent + derived -> copy but no reconciliation
    derived = ds.backend_for(intent="derived", link_availability="intermittent", durability="derived")
    assert derived["copy"] is True and derived["reconciliation"] is False


def test_needs_prune_the_lattice_before_link_availability():
    # a no_egress Need on a REMOTE store: a remote reference-mount IS egress -> forbidden -> local copy
    remote = ds.backend_for(intent="canonical", link_availability="reliable", durability="canonical",
                            needs={"no_egress": True}, store_locality="remote")
    assert remote["backend"] == "local-copy" and remote["copy"] is True
    # but a LOCAL store may still be reference-mounted under no_egress (a local mount is not egress)
    local = ds.backend_for(intent="canonical", link_availability="reliable", durability="canonical",
                           needs={"no_egress": True}, store_locality="local")
    assert local["backend"] == "reference-mount"
    # offline-tolerance forbids reference-mount even over a reliable link (it fails on link loss)
    off = ds.backend_for(intent="canonical", link_availability="reliable", durability="canonical",
                         offline_tolerant=True)
    assert off["backend"] == "local-cache" and off["copy"] is True


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
    print(f"ok: {len(fns)} data-sphere tests passed")
    sys.exit(0)
