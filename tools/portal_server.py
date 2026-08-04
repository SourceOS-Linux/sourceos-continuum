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


_CONSOLE = """<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>SourceOS Continuum — Console</title>
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
<header><h1>SourceOS Continuum — Developer Console</h1>
<div class=sub>Read-only view of the governed surface. Actions run through the MCP surface + fail-closed promotion gate.</div></header>
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
</script></body></html>"""


def route(path: str) -> tuple[int, str, str]:
    """Pure request router: read-only endpoints only. Returns (status, content_type, body)."""
    path = path.split("?", 1)[0]
    if path == "/":
        return 200, "text/html; charset=utf-8", _CONSOLE
    if path == "/healthz":
        return 200, "text/plain", "ok"
    api = {"/api/capabilities": _capabilities, "/api/lifecycle": _lifecycle,
           "/api/evidence": _evidence, "/api/compute": _compute,
           "/api/mesh": _mesh, "/api/placements": _placements}
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
