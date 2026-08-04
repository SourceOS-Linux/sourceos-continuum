#!/usr/bin/env python3
"""Tests for the provisioning plane (the Nocalhost-API + BlueMix-Broker + Entitlement + BSS + /me seam)."""
import admission as adm
import provisioning as pv


def test_provision_creates_an_isolated_tenant_with_its_tier_entitlement():
    b = pv.ServiceBroker()
    rec = b.provision(tenant="acme", user="alice", tier="free", app="feat")
    assert rec["namespace"] == "ds-acme-alice-feat" and rec["tier"] == "free"
    assert rec["quota"]["gpu_max"] == 0                       # free tier
    assert rec["allowed_backends"] == ["local", "wasm-edge"]  # free entitlement
    assert rec["receipt"].startswith("sha256:") and rec["state"] == "provisioned"


def test_bind_issues_access_defaulting_to_the_twin():
    b = pv.ServiceBroker()
    b.provision(tenant="acme", user="alice", tier="pro")
    acc = b.bind("acme")
    assert acc["endpoint"] == "twin" and acc["session_id"].startswith("sess_")
    assert acc["namespace"] == "ds-acme-alice-default"
    assert b.bind("nobody") is None                           # fail-closed on unknown tenant


def test_me_surfaces_the_profile_with_live_usage():
    ac = adm.AdmissionController(tiers={"acme": "pro"})
    ac.charge("acme", {"needs_gpu": True}, cost=2.0)
    b = pv.ServiceBroker(admission=ac)
    b.provision(tenant="acme", user="alice", tier="pro")
    me = b.me("acme")
    assert me["tier"] == "pro" and me["endpoint"] == "twin"
    assert me["usage"]["cost"] == 2.0 and me["usage"]["gpu"] == 1
    assert b.me("nobody") is None


def test_meter_turns_usage_into_a_billable_record():
    ac = adm.AdmissionController()
    ac.charge("acme", {}, cost=5.0)
    b = pv.ServiceBroker(admission=ac)
    b.provision(tenant="acme", user="alice", tier="enterprise")
    m = b.meter("acme", cost_rate=2.0)
    assert m["billable_units"] == 10.0 and m["tier"] == "enterprise"


def test_deprovision_removes_the_tenant():
    b = pv.ServiceBroker()
    b.provision(tenant="acme", user="alice")
    assert b.deprovision("acme") is True and b.me("acme") is None
    assert b.deprovision("acme") is False


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
    print(f"ok: {len(fns)} provisioning tests passed")
    sys.exit(0)
