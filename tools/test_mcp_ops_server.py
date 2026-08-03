"""Coverage for tools/mcp_ops_server.py — the governed MCP ops surface.

Drives the real MCP JSON-RPC methods (initialize / tools/list / tools/call) and proves the
governance model: read tools run and seal a receipt; a guarded tool is refused fail-closed
without a policy grant and runs with one; every call — allow or refuse — lands a tamper-evident
receipt in the evidence bundle.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


srv = _load("mcp_ops_server", "tools/mcp_ops_server.py")


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(srv, "EVIDENCE_DIR", tmp_path / "mcp-receipts")
    monkeypatch.delenv(srv.GUARDED_GRANT_ENV, raising=False)


def _call(name, arguments=None):
    return srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": name, "arguments": arguments or {}}})


def test_initialize_advertises_the_server():
    r = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert r["result"]["protocolVersion"] == srv.PROTOCOL_VERSION
    assert r["result"]["serverInfo"]["name"] == "sourceos-continuum-ops"
    assert "tools" in r["result"]["capabilities"]


def test_notifications_get_no_response():
    assert srv.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_tools_list_flags_read_vs_guarded():
    r = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    by = {t["name"]: t for t in r["result"]["tools"]}
    assert set(by) == {"continuum_list_capabilities", "continuum_lifecycle_status",
                       "continuum_list_evidence", "continuum_promotion_gate"}
    assert by["continuum_list_capabilities"]["annotations"]["readOnlyHint"] is True
    assert by["continuum_promotion_gate"]["annotations"]["readOnlyHint"] is False


def test_read_tool_runs_and_seals_a_receipt():
    r = _call("continuum_list_capabilities")
    assert "isError" not in r["result"]
    payload = json.loads(r["result"]["content"][0]["text"])
    assert "capabilities" in payload and payload["_receipt"].startswith("sha256:")
    files = list(srv.EVIDENCE_DIR.glob("*.json"))
    assert len(files) == 1
    rec = json.loads(files[0].read_text())
    assert rec["decision"] == "allow"
    body = {k: v for k, v in rec.items() if k != "receipt_digest"}
    assert srv._seal(body) == rec["receipt_digest"]  # tamper-evident


def test_guarded_tool_is_fail_closed_without_a_grant():
    r = _call("continuum_promotion_gate", {"verdict": {}})
    assert r["result"]["isError"] is True
    payload = json.loads(r["result"]["content"][0]["text"])
    assert payload["refused"] is True and "fail-closed" in payload["reason"]
    # the refusal is itself sealed
    refusals = list(srv.EVIDENCE_DIR.glob("*refuse*.json"))
    assert len(refusals) == 1 and json.loads(refusals[0].read_text())["decision"] == "refuse"


def test_guarded_tool_runs_with_an_explicit_grant(monkeypatch):
    monkeypatch.setenv(srv.GUARDED_GRANT_ENV, "1")
    pg = _load("promotion_gate", "tools/promotion_gate.py")
    verdict = {"tool": "prophet-platform.review_gate.v1",
               "reviewed": {"idempotency_key": "engine@0.4.45"}, "verdict": "APPROVE", "checks": []}
    verdict["review_digest"] = pg._recompute_seal(verdict)
    r = _call("continuum_promotion_gate", {"verdict": verdict})
    assert "isError" not in r["result"], r["result"]
    payload = json.loads(r["result"]["content"][0]["text"])
    assert payload["promotion"] == "allow"


def test_unknown_tool_is_refused_and_sealed():
    r = _call("does_not_exist")
    assert r["result"]["isError"] is True
    assert list(srv.EVIDENCE_DIR.glob("*.json"))  # even the unknown-tool refusal is recorded


def test_unknown_method_returns_jsonrpc_error():
    r = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "bogus/method"})
    assert r["error"]["code"] == -32601
