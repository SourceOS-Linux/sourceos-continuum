#!/usr/bin/env python3
"""Provisioning plane — the server/control-plane seam the diagrams have and we lacked.

Nocalhost calls it Web+API+Dep; BlueMix calls it SSO+Entitlement+Broker+Token+BSS. It is the same
server, and a developer/admin actually touches it: log in -> provision my tenant -> get my namespace
+ quota + endpoint -> see my usage -> be billed. This builds the governed core, composing what we
already have (devspace + admission tiers + grants), fail-closed and evidence-emitting — and, unlike
BlueMix's Cloud-Foundry stack, k8s-native and open.

An Open-Service-Broker-shaped surface:
  * provision  — create a tenant = an isolated DevSpace + an entitlement tier (quota + backend
                 allowlist), sealed.
  * bind       — issue access: namespace + endpoint (twin default / box) + a session.
  * deprovision— teardown.
  * meter      — BSS: turn the admission usage ledger into a billable metering record.
  * me         — the tenant profile (tier, namespace, quota, usage, endpoint).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import admission as adm
import devspace as dv


def _seal(body: dict) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ServiceBroker:
    """The governed provisioning/entitlement broker. `admission` (an AdmissionController) supplies the
    live usage ledger for metering + /me."""

    def __init__(self, *, admission=None):
        self._tenants: dict[str, dict] = {}
        self._admission = admission or adm.AdmissionController()

    def provision(self, *, tenant: str, user: str, tier: str = "pro", app: str | None = None,
                  grant_id: str | None = None) -> dict:
        """Create a tenant: an isolated DevSpace + the tier's entitlement (quota + backend allowlist)."""
        tier_spec = adm.TIERS.get(tier, adm.TIERS["pro"])
        quota = {k: v for k, v in tier_spec.items() if k != "allowed_backends"}
        manifests = dv.devspace_manifests(tenant=tenant, user=user, space=app or "default",
                                          grant_id=grant_id)
        rec = {"tenant": tenant, "user": user, "tier": tier,
               "namespace": manifests[0]["metadata"]["name"],
               "quota": quota, "allowed_backends": tier_spec.get("allowed_backends"),
               "manifests": manifests, "state": "provisioned", "provisioned_at": _iso()}
        rec["receipt"] = _seal({k: v for k, v in rec.items() if k != "manifests"})
        self._tenants[tenant] = rec
        return rec

    def bind(self, tenant: str, *, endpoint: str = "twin") -> dict | None:
        """Issue access: the connection info (namespace + endpoint + session). twin is the default
        rendezvous (always-on); box is the opt-in direct/LAN path."""
        t = self._tenants.get(tenant)
        if t is None:
            return None
        session = "sess_" + hashlib.sha256(f"{tenant}:{_iso()}".encode()).hexdigest()[:10]
        return {"tenant": tenant, "namespace": t["namespace"], "endpoint": endpoint,
                "session_id": session, "quota": t["quota"], "allowed_backends": t["allowed_backends"],
                "bound_at": _iso()}

    def deprovision(self, tenant: str) -> bool:
        return self._tenants.pop(tenant, None) is not None

    def me(self, tenant: str) -> dict | None:
        """The tenant profile (Watson '/me'): tier, namespace, quota, live usage, endpoint."""
        t = self._tenants.get(tenant)
        if t is None:
            return None
        return {"tenant": tenant, "tier": t["tier"], "namespace": t["namespace"],
                "quota": t["quota"], "allowed_backends": t["allowed_backends"],
                "usage": self._admission.usage(tenant), "endpoint": "twin"}

    def meter(self, tenant: str, *, cost_rate: float = 1.0) -> dict | None:
        """BSS: the admission usage ledger -> a billable metering record."""
        t = self._tenants.get(tenant)
        if t is None:
            return None
        usage = self._admission.usage(tenant)
        return {"tenant": tenant, "tier": t["tier"], "usage": dict(usage),
                "billable_units": round(usage.get("cost", 0.0) * cost_rate, 4), "period": _iso()}

    def tenants(self) -> list:
        return [{k: v for k, v in t.items() if k != "manifests"} for t in self._tenants.values()]


if __name__ == "__main__":
    ac = adm.AdmissionController(tiers={"acme": "free"})
    ac.charge("acme", {"needs_gpu": False}, cost=3.0)  # some usage
    b = ServiceBroker(admission=ac)
    prov = b.provision(tenant="acme", user="alice", tier="free", app="feature-x")
    print(json.dumps({
        "provisioned": {"namespace": prov["namespace"], "tier": prov["tier"],
                        "allowed_backends": prov["allowed_backends"], "receipt": prov["receipt"][:20] + "…"},
        "bind": b.bind("acme"),
        "me": b.me("acme"),
        "meter": b.meter("acme"),
    }, indent=2))
