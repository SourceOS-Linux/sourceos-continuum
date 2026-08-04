#!/usr/bin/env python3
"""Quota + admission — the other two thirds of the Control Plane Agent (placement + quotas +
admission).

`compute_plane.place()` decides WHERE a workload runs. Admission decides WHETHER a subject may run
it at all *right now*, under per-account / per-project budgets: how many jobs concurrently, how many
GPUs, how much spend. This is what makes the platform multi-tenant and cost-governed rather than a
free-for-all scheduler.

Fail-closed: over budget -> denied, and nothing is placed, granted, or dispatched. Admission is
checked BEFORE the Grant is minted, so an over-quota subject never even receives a capability. On a
successful dispatch the consumption is charged; when a job finishes it is released (spend is
cumulative and not released — you don't get money back).
"""
from __future__ import annotations

import json
from pathlib import Path

DEFAULT_QUOTA = {"max_concurrent": 4, "gpu_max": 2, "cost_budget": 100.0}


class AdmissionController:
    """Per-subject (or per-project) quotas + a live consumption ledger.

    With a `ledger_path`, consumption persists across processes (so a CLI enforces a real running
    budget, not a fresh one each invocation)."""

    def __init__(self, quotas: dict[str, dict] | None = None, ledger_path=None):
        self._quotas = quotas or {}
        self._ledger_path = Path(ledger_path) if ledger_path else None
        self._usage: dict[str, dict] = self._load()

    def _load(self) -> dict:
        if self._ledger_path and self._ledger_path.exists():
            try:
                return json.loads(self._ledger_path.read_text())
            except (OSError, json.JSONDecodeError):
                return {}
        return {}

    def _save(self) -> None:
        if self._ledger_path:
            self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
            self._ledger_path.write_text(json.dumps(self._usage, sort_keys=True))

    def quota_for(self, key: str) -> dict:
        return {**DEFAULT_QUOTA, **self._quotas.get(key, {})}

    def usage(self, key: str) -> dict:
        return self._usage.setdefault(key, {"concurrent": 0, "gpu": 0, "cost": 0.0})

    def admit(self, key: str, workload: dict, *, cost: float = 1.0) -> dict:
        """Fail-closed admission check. Returns {admitted, reason, quota, usage, exceeded}."""
        q = self.quota_for(key)
        u = self.usage(key)
        gpu = 1 if workload.get("needs_gpu") else 0
        checks = {
            "max_concurrent": u["concurrent"] + 1 <= q["max_concurrent"],
            "gpu_max": u["gpu"] + gpu <= q["gpu_max"],
            "cost_budget": round(u["cost"] + cost, 6) <= q["cost_budget"],
        }
        exceeded = sorted(name for name, ok in checks.items() if not ok)
        return {"admitted": not exceeded,
                "reason": "within budget" if not exceeded else f"quota exceeded: {', '.join(exceeded)}",
                "quota": q, "usage": dict(u), "exceeded": exceeded}

    def charge(self, key: str, workload: dict, *, cost: float = 1.0) -> dict:
        """Record a dispatch against the subject's budget."""
        u = self.usage(key)
        u["concurrent"] += 1
        u["gpu"] += 1 if workload.get("needs_gpu") else 0
        u["cost"] = round(u["cost"] + cost, 6)
        self._save()
        return dict(u)

    def release(self, key: str, workload: dict) -> dict:
        """A job finished: free the concurrency + GPU it held. Spend stays spent."""
        u = self.usage(key)
        u["concurrent"] = max(0, u["concurrent"] - 1)
        u["gpu"] = max(0, u["gpu"] - (1 if workload.get("needs_gpu") else 0))
        self._save()
        return dict(u)


if __name__ == "__main__":
    import json
    ac = AdmissionController({"spiffe://sourceos/agent/dev": {"gpu_max": 1, "max_concurrent": 2}})
    key = "spiffe://sourceos/agent/dev"
    gpu_wl = {"needs_gpu": True}
    print(json.dumps(ac.admit(key, gpu_wl), indent=2))
    ac.charge(key, gpu_wl)
    # a second GPU job now exceeds gpu_max=1
    print(json.dumps(ac.admit(key, gpu_wl), indent=2))
