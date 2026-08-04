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
    """The compute-mesh view: every substrate the compute plane can target (local -> supercomputer
    -> volunteer grid -> wasm -> p2p -> blockchain), with trust and live availability. Real
    availability comes from mesh telemetry; a representative snapshot is shown here."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("compute_plane", Path(__file__).resolve().parent / "compute_plane.py")
    cp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cp)
    snapshot = {"local": 1, "k8s": 10, "hpc-slurm": 50, "wasm-edge": 20,
                "p2p-mesh": 30, "volunteer-boinc": 200, "blockchain-rlc": 15}
    return cp.backends_view(snapshot)


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
<div class=muted>Develop local; the compute plane routes each workload by per-project policy + live mesh availability. Untrusted (volunteer/p2p/blockchain) backends never receive sensitive work.</div>
<div id=compbody class=muted style=margin-top:10px>loading…</div></section>
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
j('/api/compute').then(d=>{document.getElementById('compbody').innerHTML=
 d.backends.map(b=>`<div class=row><span><code>${esc(b.id)}</code> <span class=muted>${esc(b.kind)} &middot; elasticity ${esc(b.elasticity)}</span></span>`+
 `<span><span class="pill ${b.trust==='untrusted'?'exp':''}">${esc(b.trust)}</span> <span class=muted>avail ${esc(b.available)}</span></span></div>`).join('')})
</script></body></html>"""


def route(path: str) -> tuple[int, str, str]:
    """Pure request router: read-only endpoints only. Returns (status, content_type, body)."""
    path = path.split("?", 1)[0]
    if path == "/":
        return 200, "text/html; charset=utf-8", _CONSOLE
    if path == "/healthz":
        return 200, "text/plain", "ok"
    api = {"/api/capabilities": _capabilities, "/api/lifecycle": _lifecycle,
           "/api/evidence": _evidence, "/api/compute": _compute}
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
