#!/usr/bin/env python3
"""Git-push deploy flow — build -> deploy -> per-branch preview, one real flow.

The thin ergonomic wrapper that makes the whole stack `git push`-to-deploy. On a push, detect+build
the source (buildpack, no Dockerfile) into a reproducible OCI image, turn it into a workload the
compute plane places + the executor dispatches behind a Grant, and open a per-branch PREVIEW — a
Signadot-style sandbox that shares the baseline (route `x-sandbox-routing-key: <branch>` to the fork).
Promotion of a preview to prod is the fail-closed promotion gate. That is Vercel/Heroku's
"push a branch, get a preview URL," sovereign and governed.
"""
from __future__ import annotations

import buildpack as bp
import devspace as dv


def on_push(*, tenant: str, user: str, repo: str, branch: str, source_files: list,
            sensitivity: str = "normal", app: str | None = None) -> dict:
    """Handle a push: build the source, produce a deployable workload, and open a per-branch preview."""
    build = bp.build_plan(source_files=source_files, app_name=f"{repo}-{branch}")
    if not build.get("ok"):
        return {"status": "build-failed", "reason": build["reason"], "branch": branch}

    workload = bp.deploy_workload(build, kind="service", sensitivity=sensitivity)
    namespace = "ds-" + dv._slug(tenant, user, app or "default")
    preview = dv.sandbox_manifests(baseline=repo, image=build["image"], routing_key=branch,
                                   namespace=namespace)
    return {
        "status": "deployed", "branch": branch, "language": build["language"],
        "image": build["image"], "build_digest": build["image_digest"], "workload": workload,
        "preview": {"namespace": namespace, "baseline": repo, "routing_key": branch,
                    "route_header": f"x-sandbox-routing-key: {branch}", "manifests": preview},
        "promote_via": "fail-closed promotion gate (sealed APPROVE verdict)",
    }


if __name__ == "__main__":
    import json
    out = on_push(tenant="acme", user="alice", repo="productpage", branch="pr-42",
                  source_files=["package.json", "server.js"])
    print(json.dumps({"status": out["status"], "image": out["image"],
                      "preview_route": out["preview"]["route_header"],
                      "preview_fork": out["preview"]["manifests"][0]["metadata"]["name"],
                      "promote_via": out["promote_via"]}, indent=2))
