#!/usr/bin/env python3
"""Minimal repo-hygiene validator for sourceos-continuum.

Mirrors the scale-up wrapper's validate posture: required files exist, the CapD is valid and
non-drifting, and core docs carry no placeholder ellipses. Exit non-zero on any failure.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
REQUIRED = [
    "README.md",
    "repo.maturity.yaml",
    "Makefile",
    "AGENTS.md",
    "LICENSE",
    "docs/LIFECYCLE.md",
    "docs/CONTINUUM_SCOPE.md",
    "capd/continuum.local-paas.capd.json",
    "capd/compute-plane.mesh.capd.json",
    "capd/devspace.local-dev.capd.json",
    "capd/cloudshell-fog.capd.json",
    "capd/knowledge-commons.mesh.capd.json",
    "capd/self-healing-loop.mesh.capd.json",
    "capd/volunteer-mesh-verification.mesh.capd.json",
    "capd/data-spheres.mesh.capd.json",
    "capd/sovereign-inference.mesh.capd.json",
    "capd/git-push-deploy.mesh.capd.json",
    "capd/git-push-webhook.mesh.capd.json",
    "capd/instant-rollback.mesh.capd.json",
    "capd/sso-front-door.mesh.capd.json",
    "capd/provisioning-plane.mesh.capd.json",
    "tools/promotion_gate.py",
    "tools/portal_server.py",
    "tools/compute_plane.py",
    "tools/mesh_telemetry.py",
    "tools/mcp_a2a_grant.py",
    "tools/commons.py",
    "tools/mcp_ops_server.py",
    "tools/executor.py",
    "tools/sourceosctl.py",
    "tools/admission.py",
    "tools/control_loop.py",
    "tools/devspace.py",
    "tools/work_unit.py",
    "tools/lease_scheduler.py",
    "tools/devmode.py",
    "tools/data_sphere.py",
    "tools/availability.py",
    "tools/inference.py",
    "tools/buildpack.py",
    "tools/provisioning.py",
    "tools/deploy_flow.py",
    "tools/push_webhook.py",
    "tools/release_ledger.py",
    "tools/login.py",
    "tools/sso.py",
    "tools/edge_worker.py",
]
CAPD_KEYS = ("capability_id", "kind", "status", "links", "composes_with", "policy")
# Every CapD in capd/ must carry the core keys and parse — not just the flagship control-plane one.
EXTRA_CAPD_IDS = {
    "capd/compute-plane.mesh.capd.json": "caps.compute.mesh-plane",
    "capd/devspace.local-dev.capd.json": "caps.dev.devspace-inner-loop",
    "capd/cloudshell-fog.capd.json": "caps.compute.cloudshell-fog",
    "capd/knowledge-commons.mesh.capd.json": "caps.knowledge.commons",
    "capd/self-healing-loop.mesh.capd.json": "caps.compute.self-healing-loop",
    "capd/volunteer-mesh-verification.mesh.capd.json": "caps.compute.volunteer-mesh-verification",
    "capd/data-spheres.mesh.capd.json": "caps.data.spheres",
    "capd/sovereign-inference.mesh.capd.json": "caps.inference.sovereign",
    "capd/git-push-deploy.mesh.capd.json": "caps.dev.git-push-deploy",
    "capd/git-push-webhook.mesh.capd.json": "caps.dev.git-push-webhook",
    "capd/instant-rollback.mesh.capd.json": "caps.dev.instant-rollback",
    "capd/sso-front-door.mesh.capd.json": "caps.dev.sso-front-door",
    "capd/provisioning-plane.mesh.capd.json": "caps.dev.provisioning",
}

errors: list[str] = []

for rel in REQUIRED:
    if not (ROOT / rel).exists():
        errors.append(f"missing required file: {rel}")

capd = ROOT / "capd/continuum.local-paas.capd.json"
if capd.exists():
    try:
        data = json.loads(capd.read_text())
        for key in CAPD_KEYS:
            if key not in data:
                errors.append(f"capd missing key: {key}")
        if data.get("capability_id", "").split("@")[0] != "caps.infra.paas.continuum-local":
            errors.append("capd capability_id drift")
        if data.get("composes_with", {}).get("scales_up_to", "").split("@")[0] != "caps.infra.cluster-scaleup.hyperswarm":
            errors.append("capd scales_up_to must point at the hyperswarm scale-up capability")
    except json.JSONDecodeError as exc:
        errors.append(f"capd invalid json: {exc}")

for rel, want_id in EXTRA_CAPD_IDS.items():
    path = ROOT / rel
    if not path.exists():
        continue
    try:
        data = json.loads(path.read_text())
        for key in CAPD_KEYS:
            if key not in data:
                errors.append(f"{rel} missing key: {key}")
        if data.get("capability_id", "").split("@")[0] != want_id:
            errors.append(f"{rel} capability_id drift (want {want_id})")
    except json.JSONDecodeError as exc:
        errors.append(f"{rel} invalid json: {exc}")

for rel in ("README.md", "docs/LIFECYCLE.md", "docs/CONTINUUM_SCOPE.md"):
    path = ROOT / rel
    if path.exists() and "…" in path.read_text():
        errors.append(f"placeholder ellipsis in {rel}")

if errors:
    print("VALIDATION FAILED:")
    for err in errors:
        print(f"  - {err}")
    sys.exit(1)

print("ok: sourceos-continuum validation passed")
