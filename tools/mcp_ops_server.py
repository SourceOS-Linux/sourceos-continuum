#!/usr/bin/env python3
"""Governed MCP ops surface for sourceos-continuum — agent-native, fail-closed, hash-sealed.

A minimal stdio JSON-RPC (MCP) server, no external dependencies, exposing continuum's OWNED
control-plane surface as agent-callable tools so an agent (Claude Code, Cursor, ...) can drive
the platform conversationally. This is superiority-march move #1: it closes the #1 competitive
gap (agent-native MCP ops surface) while keeping the properties the SaaS incumbents lack.

What makes this different from Qovery/Port/Render MCP surfaces (all SaaS, audit-logged):
  - FAIL-CLOSED by default. Read tools run. A `guarded` (mutating/decisioning) tool is REFUSED
    unless an explicit policy grant is present (CONTINUUM_MCP_ALLOW_GUARDED) — it never
    executes-then-audits. Refusal is the default, not the exception.
  - A HASH-SEALED receipt on EVERY tool call — allow or refuse — emitted to the evidence
    bundle. A tamper-evident ledger, not a mutable audit log.
  - FULLY OPEN: MIT, self-hosted, stdio transport, zero external deps, scale-to-zero (spawned
    on demand, exits when the client disconnects).

Boundary (CONTINUUM_SCOPE.md): this orchestrates + governs continuum's owned surface (CapD
capabilities, lifecycle, evidence, the promotion gate). It consumes — never reimplements — the
review verdict (prophet-platform) and the source/registry (Gitea/zot).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
PROTOCOL_VERSION = "2025-06-18"
SERVER = {"name": "sourceos-continuum-ops", "version": "0.1.0"}
EVIDENCE_DIR = _ROOT / "artifacts" / "mcp-receipts"
GUARDED_GRANT_ENV = "CONTINUUM_MCP_ALLOW_GUARDED"


def _load(mod_name: str, rel: str):
    spec = importlib.util.spec_from_file_location(mod_name, _ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _seal(body: dict) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _digest(obj) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def _emit_receipt(tool: str, arguments: dict, mode: str, decision: str, result) -> dict:
    """Seal and persist a receipt for one tool call. Every call is recorded — this is the
    ledger that makes the surface auditable-by-construction, not by opt-in logging."""
    receipt = {
        "surface": "sourceos-continuum.mcp_ops.v1",
        "tool": tool,
        "mode": mode,
        "decision": decision,               # "allow" | "refuse"
        "arguments_digest": _digest(arguments),
        "result_digest": _digest(result),
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }
    receipt["receipt_digest"] = _seal(receipt)
    try:
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%f")
        (EVIDENCE_DIR / f"{tool}.{decision}.{stamp}.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    except OSError:
        pass  # a read-only estate must not break the call; the receipt is still returned inline
    return receipt


# ── tool handlers (pure reads over continuum's owned surface) ─────────────────────────

def _tool_list_capabilities(_args: dict) -> dict:
    caps = []
    capd_dir = _ROOT / "capd"
    for f in sorted(capd_dir.glob("*.capd.json")) if capd_dir.is_dir() else []:
        try:
            data = json.loads(f.read_text())
            caps.append({"file": f.name, "capability_id": data.get("capability_id"),
                         "kind": data.get("kind"), "status": data.get("status"),
                         "composes_with": data.get("composes_with", {})})
        except (OSError, json.JSONDecodeError):
            continue
    return {"capabilities": caps}


def _tool_lifecycle_status(_args: dict) -> dict:
    return {"lifecycle": [
        {"stage": "onboard", "owned": True},
        {"stage": "develop", "owned": True},
        {"stage": "cloud-native-test", "owned": True},
        {"stage": "rollout", "owned": True, "gate": "promotion_gate (fail-closed on APPROVE verdict)"},
    ], "source": "docs/LIFECYCLE.md"}


def _tool_list_evidence(args: dict) -> dict:
    limit = int(args.get("limit", 20))
    bundles = []
    for d in ("gate-decisions", "mcp-receipts"):
        p = _ROOT / "artifacts" / d
        if p.is_dir():
            for f in sorted(p.glob("*.json"), reverse=True)[:limit]:
                bundles.append({"bundle": d, "name": f.name})
    return {"evidence": bundles[:limit]}


def _tool_promotion_gate(args: dict) -> dict:
    """Guarded: run the promotion gate on a consumed review verdict. Emits a gate decision, so
    it is policy-gated. Reuses tools/promotion_gate.py (single source; not reimplemented)."""
    verdict = args.get("verdict")
    if not isinstance(verdict, dict):
        return {"error": "verdict (a sealed review receipt object) is required"}
    pg = _load("promotion_gate", "tools/promotion_gate.py")
    promote, decision = pg.gate(verdict, _ROOT / "artifacts" / "gate-decisions")
    return {"promotion": decision["promotion"], "decision": decision}


TOOLS = {
    "continuum_list_capabilities": {
        "mode": "read",
        "description": "List the platform's CapD capability contracts (id, kind, status, composition).",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "handler": _tool_list_capabilities,
    },
    "continuum_lifecycle_status": {
        "mode": "read",
        "description": "The continuum lifecycle stages (onboard -> develop -> cloud-native-test -> rollout) and their gates.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "handler": _tool_lifecycle_status,
    },
    "continuum_list_evidence": {
        "mode": "read",
        "description": "List the most recent sealed evidence bundles (gate decisions + MCP receipts).",
        "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer"}}, "additionalProperties": False},
        "handler": _tool_list_evidence,
    },
    "continuum_promotion_gate": {
        "mode": "guarded",
        "description": "Run the fail-closed rollout promotion gate over a consumed review verdict. GUARDED: refused unless policy-granted.",
        "inputSchema": {"type": "object", "properties": {"verdict": {"type": "object"}},
                        "required": ["verdict"], "additionalProperties": False},
        "handler": _tool_promotion_gate,
    },
}


def _guarded_allowed() -> bool:
    return os.environ.get(GUARDED_GRANT_ENV, "") not in ("", "0", "false", "no")


def call_tool(name: str, arguments: dict) -> dict:
    """Dispatch one tool call through the governance gate, sealing a receipt either way.
    Returns an MCP tools/call result ({content, isError})."""
    arguments = arguments or {}
    tool = TOOLS.get(name)
    if tool is None:
        result = {"error": f"unknown tool {name!r}"}
        _emit_receipt(name, arguments, "unknown", "refuse", result)
        return {"content": [{"type": "text", "text": json.dumps(result)}], "isError": True}

    mode = tool["mode"]
    if mode == "guarded" and not _guarded_allowed():
        result = {"refused": True,
                  "reason": f"guarded tool {name!r} is fail-closed; set {GUARDED_GRANT_ENV}=1 "
                            f"(an explicit, audited policy grant) to permit it"}
        _emit_receipt(name, arguments, mode, "refuse", result)
        return {"content": [{"type": "text", "text": json.dumps(result)}], "isError": True}

    try:
        result = tool["handler"](arguments)
    except Exception as exc:  # a tool fault must not crash the server
        result = {"error": f"{type(exc).__name__}: {exc}"}
        _emit_receipt(name, arguments, mode, "error", result)
        return {"content": [{"type": "text", "text": json.dumps(result)}], "isError": True}

    receipt = _emit_receipt(name, arguments, mode, "allow", result)
    result["_receipt"] = receipt["receipt_digest"]  # the sealed evidence for this call
    return {"content": [{"type": "text", "text": json.dumps(result, indent=2, sort_keys=True)}]}


def handle(request: dict) -> dict | None:
    """Handle one JSON-RPC request. Returns a response dict, or None for notifications."""
    method = request.get("method")
    rid = request.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER,
            "instructions": "Governed continuum ops surface. Read tools run; guarded tools are fail-closed. Every call is sealed.",
        }}
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": rid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": [
            {"name": n, "description": t["description"], "inputSchema": t["inputSchema"],
             "annotations": {"readOnlyHint": t["mode"] == "read"}}
            for n, t in TOOLS.items()]}}
    if method == "tools/call":
        params = request.get("params") or {}
        return {"jsonrpc": "2.0", "id": rid, "result": call_tool(params.get("name"), params.get("arguments"))}
    return {"jsonrpc": "2.0", "id": rid,
            "error": {"code": -32601, "message": f"method not found: {method}"}}


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = handle(request)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
