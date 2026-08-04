#!/usr/bin/env python3
"""Git-push webhook — the trigger that makes `git push` literally deploy.

`deploy_flow.on_push` is the build->deploy->preview flow, but something has to *call* it when a real
push lands. That is this: a governed webhook receiver a git host (Gitea, GitHub, Gitea-Actions) POSTs
to on every push. It is the FIRST link in the chain and it is FAIL-CLOSED at the door:

    an unsigned or mis-signed push is NEVER built and NEVER deployed.

Every git host signs webhook deliveries with an HMAC-SHA256 over the raw body (GitHub:
`X-Hub-Signature-256: sha256=<hex>`; Gitea: `X-Gitea-Signature: <hex>`). We verify it in constant
time before we do anything. A push that does not carry a valid signature for the project's secret is
rejected with a sealed receipt and no build is ever started — the same posture as the rest of the
stack (sensitive work fails closed, never silently proceeds).

Design:
  * `verify_signature` / `parse_push_event` / `handle_push` are a PURE core (no socket, unit-tested).
  * `handle_push` returns a sealed, tamper-evident decision bound to the exact request body digest;
    the project secret NEVER appears in the decision or the written receipt.
  * the full source manifest at the pushed commit is resolved by an injected `resolve_files(repo,
    ref, after)` — in production wired to a checkout of the pushed SHA. Without it we fall back to the
    changed files in the payload (honest: that can under-detect a buildpack; production supplies it).
  * `serve()` is a thin stdlib http.server wrapper (POST /hooks/<tenant>/<app>), no dependencies.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import deploy_flow as df
import release_ledger as rl

_ROOT = Path(__file__).resolve().parent.parent
_RECEIPTS = _ROOT / "artifacts" / "webhook-receipts"
_RELEASES = _ROOT / "artifacts" / "releases"
_ZERO_SHA = "0" * 40  # git's null object — a branch delete pushes "after": 0000...


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(raw_body: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw_body).hexdigest()


def _obj(x) -> dict:
    """A dict or {} — defensive access into an authenticated-but-arbitrary JSON payload."""
    return x if isinstance(x, dict) else {}


def _seal(body: dict) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def verify_signature(secret: str, raw_body: bytes, sig_header: str) -> bool:
    """Constant-time HMAC-SHA256 check over the RAW request body. Accepts both `sha256=<hex>`
    (GitHub) and a bare `<hex>` (Gitea). Empty secret, body, or header -> False (fail-closed)."""
    if not secret or not sig_header or not raw_body:
        return False
    mac = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    provided = sig_header.split("=", 1)[1] if sig_header.startswith("sha256=") else sig_header
    return hmac.compare_digest(mac, provided.strip())


def parse_push_event(payload: dict) -> dict:
    """Normalise a git-host push payload (GitHub/Gitea share this shape) to what the deploy needs."""
    ref = payload.get("ref") or ""
    is_branch = ref.startswith("refs/heads/")
    after = payload.get("after")
    changed = sorted({f
                      for c in (payload.get("commits") or [])
                      if isinstance(c, dict)
                      for key in ("added", "modified")
                      for f in (c.get(key) or [])})
    return {
        "ref": ref,
        "is_branch": is_branch,
        "branch": ref[len("refs/heads/"):] if is_branch else None,
        "repo": _obj(payload.get("repository")).get("name"),
        "pusher": _obj(payload.get("pusher")).get("name") or _obj(payload.get("sender")).get("login"),
        "after": after,
        "deleted": bool(payload.get("deleted")) or after == _ZERO_SHA,
        "changed_files": changed,
    }


def _finish(decision: dict, receipts_dir) -> dict:
    """Seal the decision (tamper-evident) and, if a receipts dir is given, persist it. The project
    secret is never part of `decision`, so it is never sealed and never written."""
    decision["receipt_digest"] = _seal({k: v for k, v in decision.items() if k != "receipt_digest"})
    if receipts_dir is not None:
        d = Path(receipts_dir)
        d.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        (d / f"push-{stamp}-{decision['receipt_digest'][7:19]}.json").write_text(
            json.dumps(decision, indent=2, sort_keys=True))
    return decision


def handle_push(*, secret: str, sig_header: str, raw_body: bytes, project: dict,
                resolve_files=None, receipts_dir=None, ledger_dir=None) -> dict:
    """The governed decision for one webhook delivery. Fail-closed: verify the signature FIRST; an
    unsigned/mis-signed push returns `rejected` and NO build is started.

    project: {tenant, user, app?, sensitivity?}  — resolved per-repo by the caller.
    resolve_files(repo, ref, after) -> [paths]   — the full source manifest at the pushed commit
                                                    (production: a checkout of `after`). Optional.
    ledger_dir                                    — if given, a successful deploy is recorded as a
                                                    release so it can be rolled back to. Optional.
    Returns a sealed decision; status in {rejected, ignored, deployed, build-failed}.
    """
    decision = {"surface": "sourceos-continuum.push_webhook.v1",
                "received_at": _now(), "body_digest": _digest(raw_body)}

    # 1. THE DOOR — fail-closed. No valid signature => never build, never deploy.
    if not verify_signature(secret, raw_body, sig_header):
        return _finish({**decision, "status": "rejected", "accepted": False,
                        "reason": "signature verification failed — an unsigned or mis-signed push is "
                                  "never built or deployed (fail-closed)"}, receipts_dir)

    # 2. a valid signature guarantees an authentic body; now it must be a well-formed push.
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _finish({**decision, "status": "rejected", "accepted": False,
                        "reason": "signature valid but body is not JSON — malformed push payload"},
                       receipts_dir)
    if not isinstance(payload, dict):
        return _finish({**decision, "status": "rejected", "accepted": False,
                        "reason": "signature valid but body is not a JSON object — malformed push payload"},
                       receipts_dir)

    ev = parse_push_event(payload)
    decision["event"] = {"repo": ev["repo"], "branch": ev["branch"], "ref": ev["ref"],
                         "pusher": ev["pusher"], "after": ev["after"]}

    if not ev["is_branch"] or not ev["repo"]:
        return _finish({**decision, "status": "ignored", "accepted": True,
                        "reason": "not a branch push (tag or other ref) — nothing to deploy"},
                       receipts_dir)
    if ev["deleted"]:
        return _finish({**decision, "status": "ignored", "accepted": True,
                        "reason": "branch deleted — nothing to build"}, receipts_dir)

    # 3. resolve the full source tree at the pushed commit, then run the real deploy flow.
    if resolve_files is not None:
        source_files = list(resolve_files(ev["repo"], ev["ref"], ev["after"]))
        files_source = "checkout"
    else:
        source_files = ev["changed_files"]
        files_source = "push-payload-changed-files"

    result = df.on_push(tenant=project["tenant"], user=project["user"], repo=ev["repo"],
                        branch=ev["branch"], source_files=source_files,
                        sensitivity=project.get("sensitivity", "normal"), app=project.get("app"))
    out = {**decision, "status": result["status"],
           "accepted": result["status"] != "build-failed",
           "files_source": files_source, "deploy": result}
    # a successful deploy becomes a rollback-able release (fail-closed deploys are not releases).
    if ledger_dir is not None and result.get("status") == "deployed":
        rel = rl.record_deploy(ledger_dir, tenant=project["tenant"],
                               app=project.get("app") or "default", deploy_result=result)
        if rel is not None:
            out["release_id"] = rel["release_id"]
    return _finish(out, receipts_dir)


# --- thin HTTP wrapper (stdlib only) -------------------------------------------------------------

def _secret_for(tenant: str) -> str:
    """Per-tenant webhook secret from the environment (never printed). A per-tenant override wins over
    the global secret; production reads these from the sovereign secret store, minted in CI."""
    return (os.environ.get(f"SOURCEOS_WEBHOOK_SECRET_{tenant.upper().replace('-', '_')}")
            or os.environ.get("SOURCEOS_WEBHOOK_SECRET", ""))


def project_for_path(path: str) -> dict:
    """Map the webhook URL to a project. `/hooks/<tenant>/<app>` is the multi-tenant form; anything
    else falls back to env defaults. The secret is resolved per-tenant and never returned to a client."""
    parts = [p for p in path.split("?", 1)[0].strip("/").split("/") if p]
    if len(parts) >= 2 and parts[0] == "hooks":
        tenant, app = parts[1], (parts[2] if len(parts) > 2 else "default")
    else:
        tenant, app = os.environ.get("SOURCEOS_TENANT", "you"), "default"
    return {"tenant": tenant, "user": os.environ.get("SOURCEOS_USER", "dev"), "app": app,
            "secret": _secret_for(tenant),
            "sensitivity": os.environ.get("SOURCEOS_SENSITIVITY", "normal")}


_STATUS_CODE = {"deployed": 202, "ignored": 202, "build-failed": 422, "rejected": 401}


def serve(port: int = 8099) -> None:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length > 0 else b""
            sig = (self.headers.get("X-Hub-Signature-256")
                   or self.headers.get("X-Gitea-Signature")
                   or self.headers.get("X-SourceOS-Signature") or "")
            proj = project_for_path(self.path)
            decision = handle_push(secret=proj["secret"], sig_header=sig, raw_body=raw,
                                   project=proj, receipts_dir=_RECEIPTS, ledger_dir=_RELEASES)
            body = json.dumps(decision, indent=2, sort_keys=True).encode("utf-8")
            self.send_response(_STATUS_CODE.get(decision["status"], 200))
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            ok = self.path.split("?", 1)[0] == "/healthz"
            body = b"ok" if ok else b"this is a POST-only webhook receiver"
            self.send_response(200 if ok else 404)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    print(f"[continuum] push webhook on http://127.0.0.1:{port}/hooks/<tenant>/<app>  "
          f"(POST, HMAC-signed, fail-closed; Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        serve(int(sys.argv[2]) if len(sys.argv) > 2 else 8099)
        raise SystemExit(0)

    # Demo: sign a push the way a git host would, then show the fail-closed door in action.
    secret = "demo-webhook-secret"
    payload = {"ref": "refs/heads/pr-42", "after": "a" * 40,
               "repository": {"name": "productpage"}, "pusher": {"name": "alice"},
               "commits": [{"added": ["package.json"], "modified": ["server.js"]}]}
    raw = json.dumps(payload).encode("utf-8")
    good_sig = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    project = {"tenant": "acme", "user": "alice", "app": "shop", "sensitivity": "normal"}

    accepted = handle_push(secret=secret, sig_header=good_sig, raw_body=raw, project=project)
    rejected = handle_push(secret=secret, sig_header="sha256=deadbeef", raw_body=raw, project=project)

    print(json.dumps({
        "signed_push": {"status": accepted["status"], "image": accepted["deploy"]["image"],
                        "preview_route": accepted["deploy"]["preview"]["route_header"],
                        "receipt": accepted["receipt_digest"]},
        "forged_push": {"status": rejected["status"], "accepted": rejected["accepted"],
                        "built": "deploy" in rejected, "reason": rejected["reason"]},
        "secret_leaked_in_receipt": secret in json.dumps(accepted),
    }, indent=2))
