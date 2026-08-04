#!/usr/bin/env python3
"""Sovereign inference — run LLMs on OUR mesh, not a cloud provider.

The whole point of a sovereign PaaS: a sensitive prompt must NEVER leave for a vendor LLM
(OpenAI/Anthropic/Gemini/…). The mesh serves its own models — weights are immutable DATA SPHERES
(provenance-tracked, residency ring-fenced), served on a TRUSTED GPU backend behind a Grant — and
inference routing is fail-closed: sensitive inference goes to a sovereign endpoint or it BLOCKS; it
never silently falls back to a cloud connector. That is the difference between "our infrastructure"
and "a cloud provider like Claude."

Where inference runs — the durable **twin** (always-on cloud K3s) or the **box** (direct/LAN when it
is up) — is a placement decision the compute plane already makes; both are sovereign, and the twin
is the default rendezvous because the box sleeps and the twin does not.
"""
from __future__ import annotations

import data_sphere as ds

ENGINES = ("vllm", "llama.cpp", "ollama", "tgi")


def model_sphere(*, name: str, version: str, weights_digest: str, params_b: float,
                 engine: str = "vllm", residency: str = "cluster") -> dict:
    """A model is a data sphere: immutable weights, pinned integrity, provenance, residency-fenced.
    Loading the weights therefore needs a read Grant, and a mutated model is un-citable."""
    s = ds.mint_sphere(name=f"model/{name}", version=version,
                       content={"weights": weights_digest, "params_b": params_b, "engine": engine},
                       residency=residency, direction="ingress",
                       provenance={"kind": "model-weights", "params_b": params_b, "engine": engine})
    s["model_name"] = name
    s["params_b"] = params_b
    s["engine"] = engine
    return s


def inference_service_workload(model: dict, *, replicas: int = 1, sensitivity: str = "sensitive") -> dict:
    """Serving a model = a GPU workload the compute plane places on a TRUSTED backend (the Needs
    firewall keeps a sensitive model off untrusted/volunteer/vendor backends). Dispatch it with the
    executor like any other workload; reading the weights needs a read Grant on the model sphere."""
    return {"name": "infer-" + model["model_name"].replace("/", "-"),
            "kind": "inference-service", "engine": model.get("engine", "vllm"),
            "model_sphere": model["sphere_id"], "needs_gpu": True, "scalable": True,
            "replicas": replicas, "effect": "compute", "sensitivity": sensitivity,
            "needs": {"residency": model.get("residency", "cluster")}}


def route_inference(*, model: dict, sovereign_endpoints: list, prompt_sensitivity: str = "sensitive",
                    allow_vendor: bool = False) -> dict:
    """Fail-closed sovereign-first routing. Returns {route, endpoint, reason}. A sensitive prompt (or
    a residency-fenced model) is sent to a sovereign endpoint or BLOCKED — never a cloud LLM."""
    if sovereign_endpoints:
        return {"route": "sovereign", "endpoint": sovereign_endpoints[0],
                "reason": "served on our own mesh — the prompt never leaves"}
    sovereign_required = (prompt_sensitivity == "sensitive"
                          or model.get("residency") in ("local", "cluster", "eu"))
    if sovereign_required:
        return {"route": "blocked", "endpoint": None,
                "reason": "no sovereign endpoint up; REFUSING to send sensitive inference to a cloud LLM"}
    if allow_vendor:
        return {"route": "vendor", "endpoint": "connector",
                "reason": "non-sensitive, no sovereign endpoint: policy-allowed vendor fallback"}
    return {"route": "blocked", "endpoint": None,
            "reason": "no sovereign endpoint and vendor fallback not permitted"}


if __name__ == "__main__":
    import json
    m = model_sphere(name="llama-3-70b", version="q4", weights_digest="sha256:" + "ab" * 32,
                     params_b=70, engine="vllm", residency="any")
    print(json.dumps({
        "model_sphere": m["sphere_id"],
        "service": inference_service_workload(m)["name"],
        "sensitive_no_endpoint": route_inference(model=m, sovereign_endpoints=[], prompt_sensitivity="sensitive")["route"],
        "sensitive_with_endpoint": route_inference(model=m, sovereign_endpoints=["twin:vllm:8000"])["route"],
        "normal_vendor_fallback": route_inference(model=m, sovereign_endpoints=[],
                                                  prompt_sensitivity="normal", allow_vendor=True)["route"],
    }, indent=2))
