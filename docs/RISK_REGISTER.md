# Risk Register

Generated: 2026-01-14 14:16:53Z

## R1 — Drift (imperative apply)
Mitigation:
- PR-only by default
- admission restrictions on privileged verbs
- reconcile selfHeal

## R2 — False security from NetworkPolicy on k3s
Mitigation:
- standardize on policy-capable CNI OR treat netpol as documentation and compensate with host firewalling

## R3 — Cloud Shell identity leak (shared ServiceAccount)
Mitigation:
- per-user spawner model
- bound tokens + short TTL

## R4 — Storage death spirals (local PV)
Mitigation:
- quotas, watermarks, SRE promotion gates

## R5 — Supply chain brittleness
Mitigation:
- staged Audit→Enforce rollout
- conformance tests and breakglass procedure with evidence
