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
]
CAPD_KEYS = ("capability_id", "kind", "status", "links", "composes_with", "policy")

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
