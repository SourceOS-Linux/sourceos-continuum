#!/usr/bin/env python3
"""Tests for sovereign inference. Load-bearing: a model is an immutable data sphere, serving it is a
trusted-GPU workload, and routing NEVER sends sensitive inference to a cloud LLM (fail-closed)."""
import inference as inf


def test_model_is_an_immutable_integrity_pinned_data_sphere():
    m = inf.model_sphere(name="llama", version="q4", weights_digest="sha256:" + "ab" * 32,
                         params_b=8, engine="vllm")
    assert m["sphere_id"].startswith("sphere:model/llama@q4+")
    assert m["immutable"] is True and m["root_hash"].startswith("sha256:")
    assert m["engine"] == "vllm" and m["params_b"] == 8


def test_serving_a_model_is_a_trusted_gpu_workload_referencing_the_sphere():
    m = inf.model_sphere(name="llama", version="q4", weights_digest="sha256:" + "ab" * 32, params_b=8)
    wl = inf.inference_service_workload(m, sensitivity="sensitive")
    assert wl["needs_gpu"] is True and wl["sensitivity"] == "sensitive"
    assert wl["model_sphere"] == m["sphere_id"]
    assert wl["needs"]["residency"] == "cluster"


def test_routing_prefers_a_sovereign_endpoint():
    m = inf.model_sphere(name="x", version="1", weights_digest="sha256:" + "cd" * 32, params_b=1)
    r = inf.route_inference(model=m, sovereign_endpoints=["twin:vllm:8000"])
    assert r["route"] == "sovereign" and r["endpoint"] == "twin:vllm:8000"


def test_sensitive_inference_blocks_rather_than_leaking_to_a_cloud_llm():
    m = inf.model_sphere(name="x", version="1", weights_digest="sha256:" + "cd" * 32, params_b=1)
    r = inf.route_inference(model=m, sovereign_endpoints=[], prompt_sensitivity="sensitive")
    assert r["route"] == "blocked" and r["endpoint"] is None
    assert "REFUSING" in r["reason"]


def test_residency_fenced_model_forces_sovereign_even_for_normal_prompts():
    m = inf.model_sphere(name="x", version="1", weights_digest="sha256:" + "cd" * 32, params_b=1,
                         residency="eu")
    r = inf.route_inference(model=m, sovereign_endpoints=[], prompt_sensitivity="normal")
    assert r["route"] == "blocked"  # residency ring-fence overrides "normal"


def test_non_sensitive_may_fall_back_to_a_vendor_only_when_allowed():
    m = inf.model_sphere(name="x", version="1", weights_digest="sha256:" + "cd" * 32, params_b=1,
                         residency="any")
    assert inf.route_inference(model=m, sovereign_endpoints=[], prompt_sensitivity="normal",
                               allow_vendor=True)["route"] == "vendor"
    assert inf.route_inference(model=m, sovereign_endpoints=[], prompt_sensitivity="normal",
                               allow_vendor=False)["route"] == "blocked"


def test_inference_service_places_on_a_trusted_gpu_backend():
    import compute_plane as cp
    m = inf.model_sphere(name="x", version="1", weights_digest="sha256:" + "cd" * 32, params_b=70,
                         residency="cluster")
    wl = inf.inference_service_workload(m)
    d = cp.place(wl, {}, {b: 100 for b in cp.BACKENDS})
    assert d["backend"] in ("hpc-slurm", "k8s") and d["backend_trust"] == "trusted"  # never volunteer/vendor


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
    print(f"ok: {len(fns)} inference tests passed")
    sys.exit(0)
