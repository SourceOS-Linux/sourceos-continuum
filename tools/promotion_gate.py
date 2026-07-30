#!/usr/bin/env python3
"""Rollout promotion gate — require an APPROVE review verdict before continuum promotes.

Continuum owns the rollout promotion gate and its per-action evidence (LIFECYCLE.md §4). The
review VERDICT it gates on is produced by the review capability CONSUMED from prophet-platform
(`tools/review_gate.py`, named in this repo's CapD `links.integration_target`) — this file
reviews nothing. It enforces the consumed verdict and seals the decision into the evidence
bundle, honouring the CapD `policy.evidence_emitting`.

Fail-closed: promotion is allowed only when the verdict is APPROVE AND its seal recomputes.
A tampered verdict, a non-APPROVE verdict, or a missing seal all block promotion — and the
block is itself written to evidence, because a refused promotion is a decision worth keeping.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
APPROVE = "APPROVE"


def _recompute_seal(verdict: dict) -> str:
    """Recompute the reviewer's seal over the verdict body. This is an integrity check on
    consumed evidence, not a reimplementation of the review — it only proves the verdict
    bytes were not altered between the reviewer and this gate. The seal is a sha256 over the
    canonical JSON of every field except the seal itself; that contract is shared with the
    producer (prophet-platform review_gate._seal_review)."""
    body = {k: v for k, v in verdict.items() if k != "review_digest"}
    return "sha256:" + hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def gate(verdict: dict, evidence_dir: Path, write_evidence: bool = True) -> tuple[bool, dict]:
    claimed = verdict.get("review_digest")
    seal_ok = bool(claimed) and claimed == _recompute_seal(verdict)
    approved = verdict.get("verdict") == APPROVE
    promote = seal_ok and approved

    decision = {
        "gate": "sourceos-continuum.promotion_gate.v1",
        "reviewed": verdict.get("reviewed"),
        "review_tool": verdict.get("tool"),
        "review_verdict": verdict.get("verdict"),
        "seal_ok": seal_ok,
        "promotion": "allow" if promote else "block",
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }
    if not seal_ok:
        decision["reason"] = "review verdict seal did not recompute — not trustworthy evidence"
    elif not approved:
        decision["reason"] = f"review verdict is {verdict.get('verdict')!r}; promotion requires {APPROVE}"

    if write_evidence:
        evidence_dir.mkdir(parents=True, exist_ok=True)
        reviewed = verdict.get("reviewed") or {}
        key = str(reviewed.get("idempotency_key", "unknown")).replace("/", "_").replace("@", "-at-")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = evidence_dir / f"{key}.{stamp}.json"
        path.write_text(json.dumps(decision, indent=2, sort_keys=True) + "\n")
        decision["evidence"] = str(path.relative_to(_ROOT)) if path.is_relative_to(_ROOT) else str(path)

    return promote, decision


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Rollout promotion gate over a consumed review verdict.")
    ap.add_argument("--verdict", type=Path, required=True,
                    help="the sealed review receipt produced by the consumed reviewer")
    ap.add_argument("--evidence-dir", type=Path, default=_ROOT / "artifacts" / "gate-decisions")
    ap.add_argument("--no-write", action="store_true", help="do not emit an evidence artifact (dry-run)")
    args = ap.parse_args(argv)

    try:
        verdict = json.loads(args.verdict.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"BLOCK: cannot read a review verdict from {args.verdict}: {exc}", file=sys.stderr)
        return 1

    promote, decision = gate(verdict, args.evidence_dir, write_evidence=not args.no_write)
    print(json.dumps(decision, indent=2, sort_keys=True))
    if not promote:
        print(f"BLOCK: {decision.get('reason', 'promotion refused')}", file=sys.stderr)
    return 0 if promote else 1


if __name__ == "__main__":
    raise SystemExit(main())
