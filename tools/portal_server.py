#!/usr/bin/env python3
"""Developer portal — the human view of continuum's governed surface (superiority-march move #8).

A dependency-free, self-hosted, read-only web console over the SAME data the MCP ops surface (move
#1) exposes to agents: CapD capabilities, the lifecycle, and the sealed evidence bundle. One
governed source, two views — agent via MCP, human via this portal. Fully open: stdlib only, no
external CDN (inline HTML/CSS/JS), scale-to-zero (a plain HTTP server, spawned on demand).

Read-only by construction: mutating actions flow through the governed MCP surface + the fail-closed
promotion gate, never the portal. `route(path) -> (status, content_type, body)` is the pure core
(unit-tested); serve() wraps it in http.server.
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_TOOLS = Path(__file__).resolve().parent
_HEARTBEATS = _ROOT / "artifacts" / "mesh-heartbeats"


def _sib(name: str):
    """Load a sibling tool module by path (keeps the portal import-light and relocatable)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, _TOOLS / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _registry():
    return _sib("mesh_telemetry").MeshRegistry.from_dir(_HEARTBEATS)


def _capabilities() -> dict:
    caps = []
    d = _ROOT / "capd"
    for f in sorted(d.glob("*.capd.json")) if d.is_dir() else []:
        try:
            data = json.loads(f.read_text())
            caps.append({"file": f.name, "capability_id": data.get("capability_id"),
                         "kind": data.get("kind"), "status": data.get("status"),
                         "name": data.get("name"), "policy": data.get("policy", {})})
        except (OSError, json.JSONDecodeError):
            continue
    return {"capabilities": caps}


def _lifecycle() -> dict:
    return {"lifecycle": [
        {"stage": "onboard", "note": "local sovereign forge + cluster + sourceosctl"},
        {"stage": "develop", "note": "inner-loop dev-environments (see caps.dev.devspace)"},
        {"stage": "cloud-native-test", "note": "ephemeral preview env + evidence bundle"},
        {"stage": "rollout", "note": "fail-closed promotion gate on a sealed APPROVE verdict"},
    ]}


def _evidence(limit: int = 20) -> dict:
    bundles = []
    for name in ("gate-decisions", "mcp-receipts"):
        p = _ROOT / "artifacts" / name
        if p.is_dir():
            for f in sorted(p.glob("*.json"), reverse=True)[:limit]:
                bundles.append({"bundle": name, "name": f.name})
    return {"evidence": bundles[:limit]}


def _compute() -> dict:
    """The compute-mesh view: every substrate the plane can target, with trust and LIVE availability
    summed from mesh telemetry (the HyperSwarm discovery/liveness substrate; stale nodes count 0)."""
    cp = _sib("compute_plane")
    reg = _registry()
    view = cp.backends_view(reg.availability())
    view["telemetry"] = reg.summary()
    return view


def _mesh() -> dict:
    """Per-node liveness: which fog nodes are beating, their backend, capacity, and age
    (the spec's HyperSwarm Mesh + Node Identity 'find candidate nodes')."""
    reg = _registry()
    return {"summary": reg.summary(), "nodes": reg.nodes()}


def _placements() -> dict:
    """The app suite on the mesh: run place() (the Control-Plane-Agent Decide) for each product's
    declared workload against LIVE availability, so the dashboard shows where every product's work
    would land right now."""
    cp = _sib("compute_plane")
    avail = _registry().availability()
    try:
        profiles = json.loads((_ROOT / "mesh" / "suite-workloads.json").read_text())["workloads"]
    except (OSError, json.JSONDecodeError, KeyError):
        profiles = []
    out = []
    for p in profiles:
        d = cp.place(p.get("workload", {}), p.get("policy", {}), avail)
        out.append({"product": p.get("product"), "id": p.get("id"),
                    "backend": d.get("backend"), "placement": d.get("placement"),
                    "backend_trust": d.get("backend_trust"), "reason": d.get("reason")})
    return {"placements": out, "availability": avail}


def _commons() -> dict:
    """The Reproducible Knowledge Commons: every estate capability + workload as a citable,
    content-addressed record, honestly graded reproducible vs. declared."""
    c = _sib("commons").estate_commons(_ROOT)
    recs = c.records()
    return {"total": len(recs), "reproducible": len(c.search(reproducible=True)),
            "records": [{"commons_id": r["commons_id"], "domain": r["domain"],
                         "asset_type": r["asset_type"], "reproducibility": r["reproducibility"],
                         "cite": r["cite"]} for r in recs]}


def _endpoint() -> str:
    """Which surface this portal is — the always-on cloud 'twin' or the 'box' (direct/LAN). Set
    SOURCEOS_ENDPOINT=twin on the twin; defaults to box."""
    import os
    return os.environ.get("SOURCEOS_ENDPOINT", "box")


def _inference() -> dict:
    """Sovereign-inference posture: our own models, and where a sensitive prompt would route (never a
    cloud LLM). Sovereign endpoints = live trusted GPU backends."""
    inf = _sib("inference")
    reg = _registry()
    avail = reg.availability()
    sovereign_up = [b for b in ("hpc-slurm", "k8s") if avail.get(b, 0) > 0]
    models = [inf.model_sphere(name=n, version=v, weights_digest="sha256:" + "ab" * 32,
                               params_b=p, engine="vllm")
              for (n, v, p) in [("llama-3-8b", "q4", 8), ("mixtral-8x7b", "q4", 47), ("nomic-embed", "f16", 0.1)]]
    return {"endpoint": _endpoint(),
            "posture": "sovereign-first — sensitive inference never leaves for a cloud LLM",
            "sovereign_endpoints": sovereign_up,
            "models": [{"model": m["model_name"], "params_b": m["params_b"],
                        "route": inf.route_inference(model=m, sovereign_endpoints=sovereign_up,
                                                     prompt_sensitivity="sensitive")["route"]}
                       for m in models]}


def _me() -> dict:
    """The tenant profile (Watson '/me'-style): tier, namespace, quota, live usage, endpoint."""
    pv = _sib("provisioning")
    adm = _sib("admission")
    ac = adm.AdmissionController(ledger_path=_ROOT / "artifacts" / "admission-usage.json",
                                tiers={"you": "pro"})
    b = pv.ServiceBroker(admission=ac)
    b.provision(tenant="you", user="dev", tier="pro", app="default")
    return b.me("you") or {}


_MANIFEST = json.dumps({
    "name": "SourceOS Continuum", "short_name": "Continuum", "start_url": "/", "scope": "/",
    "display": "standalone", "background_color": "#0b0d12", "theme_color": "#0b0d12",
    "description": "See and reach your infrastructure — twin or box.",
    "icons": [{"src": "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'>"
               "<rect width='100' height='100' rx='20' fill='%230b0d12'/><circle cx='50' cy='50' r='28' fill='%237ee2a8'/>"
               "<circle cx='24' cy='30' r='7' fill='%238fb8ff'/><circle cx='76' cy='30' r='7' fill='%238fb8ff'/></svg>",
               "sizes": "any", "type": "image/svg+xml", "purpose": "any maskable"}]})

# cache-first service worker so the console still loads on a flaky mobile link (offline-ish shell).
_SW = ("const C='continuum-v1';"
       "self.addEventListener('install',e=>{self.skipWaiting();e.waitUntil(caches.open(C).then(c=>c.add('/')))});"
       "self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));"
       "self.addEventListener('fetch',e=>{if(e.request.method!=='GET')return;"
       "e.respondWith(fetch(e.request).then(r=>{const cp=r.clone();caches.open(C).then(c=>c.put(e.request,cp));return r})"
       ".catch(()=>caches.match(e.request)))});")


_CONSOLE = """<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover"><title>SourceOS Continuum — Console</title>
<meta name=theme-color content=#0b0d12><link rel=manifest href=/manifest.webmanifest>
<meta name=apple-mobile-web-app-capable content=yes><meta name=apple-mobile-web-app-status-bar-style content=black-translucent>
<meta name=apple-mobile-web-app-title content=Continuum>
<style>
:root{color-scheme:light dark}body{font:15px/1.5 system-ui,sans-serif;margin:0;background:#0b0d12;color:#e8ecf4}
header{padding:20px 28px;border-bottom:1px solid #232838;background:#11141d}
h1{margin:0;font-size:19px}.sub{color:#8a93a6;font-size:13px;margin-top:4px}
main{max-width:960px;margin:0 auto;padding:24px 28px;display:grid;gap:20px}
section{background:#11141d;border:1px solid #232838;border-radius:10px;padding:16px 20px}
h2{margin:0 0 10px;font-size:14px;letter-spacing:.04em;text-transform:uppercase;color:#9aa4bb}
.row{display:flex;justify-content:space-between;gap:12px;padding:8px 0;border-top:1px solid #1b2030}
.row:first-of-type{border-top:0}.pill{font-size:12px;padding:2px 9px;border-radius:20px;background:#1a2f22;color:#7ee2a8}
.pill.exp{background:#2f2a1a;color:#e2c77e}code{color:#8fb8ff}.muted{color:#6b7488;font-size:13px}
.gov{color:#7ee2a8;font-size:12px}
</style></head><body>
<header><h1>SourceOS Continuum — Developer Console <span id=epbadge class=pill>…</span></h1>
<div class=sub>Read-only view of the governed surface. Actions run through the MCP surface + fail-closed promotion gate. Installable on mobile; reaches the twin (always-on) or the box (direct/LAN).</div></header>
<main>
<section id=caps><h2>Capabilities</h2><div class=muted>loading…</div></section>
<section id=life><h2>Lifecycle</h2><div class=muted>loading…</div></section>
<section id=comp><h2>Compute mesh &mdash; scale out anywhere, governed</h2>
<div class=muted>Develop local; the compute plane routes each workload by per-project policy + <b>live mesh telemetry</b>. Untrusted (volunteer/p2p/blockchain) backends never receive sensitive work.</div>
<div id=meshsum class=muted style="margin-top:8px;color:#7ee2a8"></div>
<div id=compbody class=muted style=margin-top:10px>loading…</div></section>
<section id=suite><h2>App suite on the mesh &mdash; live placement</h2>
<div class=muted>Where each product's workload lands right now, under its policy and current availability. <span class=gov>BLOCKED</span> = fail-closed, no compliant node live.</div>
<div id=suitebody class=muted style=margin-top:10px>loading…</div></section>
<section id=commons><h2>Reproducible Knowledge Commons</h2>
<div class=muted>Every capability + workload as a citable, content-addressed record (Zenodo-style). <span class=gov>reproducible</span> = provenance carries the digests to reproduce it; <span class=muted>declared</span> = registered but not yet reproducibility-backed.</div>
<div id=commonssum class=muted style=margin-top:8px></div>
<div id=commonsbody class=muted style=margin-top:10px>loading…</div></section>
<section id=infer><h2>Sovereign inference &mdash; our own LLMs</h2>
<div class=muted>Models are immutable data spheres served on trusted GPU nodes. A <b>sensitive</b> prompt routes to a sovereign endpoint or <span class=gov>blocks</span> &mdash; it never leaves for a cloud LLM.</div>
<div id=inferbody class=muted style=margin-top:10px>loading…</div></section>
<section id=evi><h2>Sealed evidence (latest)</h2><div class=muted>loading…</div></section>
</main>
<script>
async function j(p){return (await fetch(p)).json()}
function esc(s){return String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}
j('/api/capabilities').then(d=>{document.getElementById('caps').innerHTML='<h2>Capabilities</h2>'+
 (d.capabilities.map(c=>`<div class=row><span><code>${esc(c.capability_id)}</code> <span class=muted>${esc(c.name||'')}</span>`+
 (c.policy&&c.policy.evidence_emitting?` <span class=gov>&#9679; evidence-emitting</span>`:'')+
 `</span><span class="pill ${c.status==='experimental'?'exp':''}">${esc(c.status)}</span></div>`).join('')||'<div class=muted>none</div>')})
j('/api/lifecycle').then(d=>{document.getElementById('life').innerHTML='<h2>Lifecycle</h2>'+
 d.lifecycle.map(s=>`<div class=row><span><b>${esc(s.stage)}</b></span><span class=muted>${esc(s.note)}</span></div>`).join('')})
j('/api/evidence').then(d=>{document.getElementById('evi').innerHTML='<h2>Sealed evidence (latest)</h2>'+
 (d.evidence.map(e=>`<div class=row><span class=muted>${esc(e.bundle)}</span><code>${esc(e.name)}</code></div>`).join('')||'<div class=muted>no evidence yet</div>')})
j('/api/compute').then(d=>{const t=d.telemetry||{};
 document.getElementById('meshsum').innerHTML=`&#9679; <b>${esc(t.live_nodes??0)}</b>/${esc(t.total_nodes??0)} nodes live &middot; backends up: ${esc((t.backends_up||[]).join(', ')||'none')}`;
 document.getElementById('compbody').innerHTML=
 d.backends.map(b=>`<div class=row><span><code>${esc(b.id)}</code> <span class=muted>${esc(b.kind)} &middot; elasticity ${esc(b.elasticity)}</span></span>`+
 `<span><span class="pill ${b.trust==='untrusted'?'exp':''}">${esc(b.trust)}</span> <span class=muted>avail ${esc(b.available)}</span></span></div>`).join('')})
j('/api/placements').then(d=>{document.getElementById('suitebody').innerHTML=
 (d.placements.map(p=>{const b=p.backend?`<code>${esc(p.backend)}</code>`:'<span style=color:#e28a8a>BLOCKED</span>';
  const tr=p.backend_trust?` <span class="pill ${p.backend_trust==='untrusted'?'exp':''}">${esc(p.backend_trust)}</span>`:'';
  return `<div class=row><span><b>${esc(p.product)}</b> <span class=muted>${esc(p.id)}</span></span><span>${b}${tr}</span></div>`}).join('')||'<div class=muted>no profiles</div>')})
j('/api/commons').then(d=>{
 document.getElementById('commonssum').innerHTML=`&#9679; <b>${esc(d.total)}</b> records &middot; <span class=gov>${esc(d.reproducible)} reproducible</span>`;
 document.getElementById('commonsbody').innerHTML=
 d.records.map(r=>`<div class=row><span><code>${esc(r.commons_id.split('+')[0])}</code> <span class=muted>${esc(r.asset_type)}</span></span>`+
 `<span class="pill ${r.reproducibility==='reproducible'?'':'exp'}">${esc(r.reproducibility)}</span></div>`).join('')})
j('/api/inference').then(d=>{
 document.getElementById('epbadge').textContent=(d.endpoint||'box')==='twin'?'twin':'box';
 document.getElementById('inferbody').innerHTML=
 `<div class=muted style=margin-bottom:6px>${esc(d.posture)} &middot; sovereign endpoints: ${esc((d.sovereign_endpoints||[]).join(', ')||'none up')}</div>`+
 d.models.map(m=>`<div class=row><span><code>${esc(m.model)}</code> <span class=muted>${esc(m.params_b)}B</span></span>`+
 `<span class="pill ${m.route==='sovereign'?'':'exp'}">${esc(m.route)}</span></div>`).join('')})
if('serviceWorker' in navigator){navigator.serviceWorker.register('/sw.js').catch(()=>{})}
</script></body></html>"""


def route(path: str) -> tuple[int, str, str]:
    """Pure request router: read-only endpoints only. Returns (status, content_type, body)."""
    path = path.split("?", 1)[0]
    if path == "/":
        return 200, "text/html; charset=utf-8", _CONSOLE
    if path == "/healthz":
        return 200, "text/plain", "ok"
    if path == "/manifest.webmanifest":
        return 200, "application/manifest+json", _MANIFEST
    if path == "/sw.js":
        return 200, "application/javascript", _SW
    api = {"/api/capabilities": _capabilities, "/api/lifecycle": _lifecycle,
           "/api/evidence": _evidence, "/api/compute": _compute,
           "/api/mesh": _mesh, "/api/placements": _placements, "/api/commons": _commons,
           "/api/inference": _inference, "/api/me": _me}
    if path in api:
        return 200, "application/json", json.dumps(api[path](), indent=2, sort_keys=True)
    return 404, "text/plain", "not found"


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # read-only: only GET is served
        status, ctype, body = route(self.path)
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_):  # quiet by default
        pass


def serve(port: int = 8088) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    print(f"[continuum] portal on http://127.0.0.1:{port}  (read-only; Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    import sys
    serve(int(sys.argv[1]) if len(sys.argv) > 1 else 8088)
