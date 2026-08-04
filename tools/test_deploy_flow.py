#!/usr/bin/env python3
"""Tests for the git-push deploy flow (build -> deploy -> per-branch preview)."""
import deploy_flow as df


def test_push_builds_deploys_and_opens_a_per_branch_preview():
    out = df.on_push(tenant="acme", user="alice", repo="productpage", branch="pr-42",
                     source_files=["package.json", "server.js"])
    assert out["status"] == "deployed" and out["language"] == "node"
    assert out["workload"]["image"] == out["image"]
    # the preview is a Signadot-style sandbox routed by the branch
    assert out["preview"]["routing_key"] == "pr-42"
    assert out["preview"]["route_header"] == "x-sandbox-routing-key: pr-42"
    fork = out["preview"]["manifests"][0]
    assert fork["kind"] == "Deployment" and "sbx-pr-42" in fork["metadata"]["name"]


def test_push_with_unbuildable_source_fails_closed():
    out = df.on_push(tenant="acme", user="alice", repo="x", branch="main",
                     source_files=["notes.txt"])
    assert out["status"] == "build-failed" and "no buildpack matched" in out["reason"]


def test_preview_namespace_is_the_tenant_devspace():
    out = df.on_push(tenant="acme", user="bob", repo="api", branch="feat", source_files=["go.mod"])
    assert out["preview"]["namespace"] == "ds-acme-bob-default"


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
    print(f"ok: {len(fns)} deploy-flow tests passed")
    sys.exit(0)
