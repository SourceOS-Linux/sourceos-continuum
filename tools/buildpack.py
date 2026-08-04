#!/usr/bin/env python3
"""Buildpack build — the Vercel/Heroku "git push, no Dockerfile, it deploys" ergonomic, sovereign.

Vercel and Heroku are the same move: detect the app's language/framework from source, build it into a
runnable image WITHOUT a Dockerfile, and deploy it — with a preview environment per branch. The open,
sovereign way to do the build half is **Cloud Native Buildpacks** (buildpacks.io / Paketo): `pack
build` runs detect + build phases over source and produces a reproducible, SBOM'd OCI image. No
Docker daemon, no hand-written Dockerfile.

This models the build and wires it into the stack we already have:

    source ──detect──> buildpack ──build──> OCI image (reproducible, SBOM/SLSA-attestable)
           ──> a data sphere / commons record (immutable, provenance)
           ──> a workload the executor dispatches into a DevSpace
           ──> a Signadot-style sandbox = the per-branch PREVIEW deployment
           ──> the promotion gate = the dev->prod pipeline

So Heroku's slug+Procfile+dyno, Vercel's build+preview+rollback, become: CNB image + workload spec +
DevSpace/sandbox — governed, and the preview-env we already ship.
"""
from __future__ import annotations

import hashlib
import json

# detect signal -> Paketo buildpack builder + a default process (Procfile-style "web:" command).
BUILDPACKS = {
    "python": {"detect": ["requirements.txt", "pyproject.toml", "Pipfile"],
               "builder": "paketobuildpacks/builder-jammy-base", "buildpack": "paketo/python", "web": "python app.py"},
    "node":   {"detect": ["package.json"], "builder": "paketobuildpacks/builder-jammy-base",
               "buildpack": "paketo/nodejs", "web": "npm start"},
    "go":     {"detect": ["go.mod"], "builder": "paketobuildpacks/builder-jammy-base",
               "buildpack": "paketo/go", "web": "./app"},
    "rust":   {"detect": ["Cargo.toml"], "builder": "paketobuildpacks/builder-jammy-base",
               "buildpack": "paketo-community/rust", "web": "./target/release/app"},
    "static": {"detect": ["index.html", "public/index.html"], "builder": "paketobuildpacks/builder-jammy-base",
               "buildpack": "paketo/web-servers", "web": "serve"},
}


def detect(files: list) -> str | None:
    """Which buildpack matches this source? (No Dockerfile needed.)"""
    fs = set(files)
    for lang, spec in BUILDPACKS.items():
        if any(sig in fs for sig in spec["detect"]):
            return lang
    return None


def build_plan(*, source_files: list, app_name: str, process: str | None = None,
               procfile: dict | None = None) -> dict:
    """CNB-style: detect -> build -> a reproducible OCI image + a Procfile-style process type. The
    image digest is content-addressed over the source + buildpack, so the same source builds the same
    image (reproducible). The real build is `pack build` with the returned command."""
    lang = detect(source_files)
    if lang is None:
        return {"ok": False, "reason": "no buildpack matched — add a Dockerfile or a known manifest "
                "(requirements.txt / package.json / go.mod / Cargo.toml / index.html)"}
    spec = BUILDPACKS[lang]
    digest = hashlib.sha256(json.dumps({"src": sorted(source_files), "bp": spec["buildpack"]},
                                       sort_keys=True).encode()).hexdigest()
    web = (procfile or {}).get("web") or process or spec["web"]
    return {"ok": True, "language": lang, "buildpack": spec["buildpack"], "builder": spec["builder"],
            "image": f"{app_name}@sha256:{digest[:12]}", "image_digest": "sha256:" + digest,
            "process": web, "process_types": procfile or {"web": web},
            "pack_command": ["pack", "build", app_name, "--builder", spec["builder"], "--buildpack", spec["buildpack"]]}


def deploy_workload(build: dict, *, kind: str = "service", sensitivity: str = "normal") -> dict | None:
    """The built image -> a workload the executor dispatches (service = long-lived Deployment; worker
    = Job). The sandbox is the per-branch preview; the promotion gate is dev->prod."""
    if not build.get("ok"):
        return None
    return {"name": build["image"].split("@")[0], "image": build["image"], "command": build["process"],
            "kind": kind, "effect": "compute", "sensitivity": sensitivity, "scalable": True,
            "build_digest": build["image_digest"], "provenance": {"buildpack": build["buildpack"]}}


if __name__ == "__main__":
    plan = build_plan(source_files=["package.json", "index.js", "README.md"], app_name="my-web-app",
                      procfile={"web": "node server.js", "worker": "node worker.js"})
    print(json.dumps({"language": plan["language"], "image": plan["image"],
                      "pack": " ".join(plan["pack_command"]),
                      "workload": deploy_workload(plan)["name"],
                      "process_types": plan["process_types"]}, indent=2))
