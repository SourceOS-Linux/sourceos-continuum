#!/usr/bin/env python3
"""Tests for the buildpack build (the Vercel/Heroku 'git push, no Dockerfile' ergonomic via CNB)."""
import buildpack as bp


def test_detect_matches_manifests_and_none_for_unknown():
    assert bp.detect(["requirements.txt"]) == "python"
    assert bp.detect(["package.json"]) == "node"
    assert bp.detect(["go.mod"]) == "go"
    assert bp.detect(["Cargo.toml"]) == "rust"
    assert bp.detect(["index.html"]) == "static"
    assert bp.detect(["README.md"]) is None


def test_build_plan_is_reproducible_and_carries_a_process():
    a = bp.build_plan(source_files=["package.json", "index.js"], app_name="app")
    b = bp.build_plan(source_files=["index.js", "package.json"], app_name="app")  # order-insensitive
    assert a["ok"] and a["language"] == "node" and a["buildpack"] == "paketo/nodejs"
    assert a["image_digest"] == b["image_digest"]        # same source -> same image (reproducible)
    assert a["process"] == "npm start" and a["pack_command"][0] == "pack"


def test_procfile_web_overrides_the_default_process():
    p = bp.build_plan(source_files=["package.json"], app_name="app",
                      procfile={"web": "node server.js", "worker": "node w.js"})
    assert p["process"] == "node server.js" and p["process_types"]["worker"] == "node w.js"


def test_no_buildpack_match_is_fail_closed():
    p = bp.build_plan(source_files=["random.txt"], app_name="app")
    assert p["ok"] is False and "no buildpack matched" in p["reason"]
    assert bp.deploy_workload(p) is None


def test_built_image_flows_into_an_executor_dispatch():
    import executor as ex
    import mcp_a2a_grant as g
    plan = bp.build_plan(source_files=["go.mod", "main.go"], app_name="svc")
    wl = bp.deploy_workload(plan, kind="service")
    assert wl["image"] == plan["image"] and wl["build_digest"] == plan["image_digest"]
    assert wl["provenance"]["buildpack"] == "paketo/go"
    d = {"placement": "scheduled", "backend": "k8s", "backend_trust": "trusted"}
    grant = g.issue_grant(
        binding={"spiffe_id": "s", "aum_digest": "sha256:" + "ab" * 32, "session_id": "sess_bp1"},
        capability={"kind": "mcp_tool", "capability_ref": "c", "capability_digest": "sha256:" + "cd" * 32, "effect": "compute"},
        decision=d, attestation=g.attestation_bundle(spiffe_id="s", aum_digest="sha256:" + "ab" * 32, tpm_valid=True, cosign_valid=True),
        constraints={"ops_allow": ["x"]}, signer=g.hmac_signer(b"k"))
    m = ex.K8sAdapter().manifest(wl, d, grant)
    assert m["spec"]["template"]["spec"]["containers"][0]["image"] == plan["image"]  # runs the built artifact


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
    print(f"ok: {len(fns)} buildpack tests passed")
    sys.exit(0)
