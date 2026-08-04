#!/usr/bin/env python3
"""Release ledger + instant rollback — the last of the Vercel/Heroku deploy ergonomics, sovereign.

Vercel and Heroku sell "instant rollback": one click and prod is serving the previous release again.
In our model that is almost free, and *better*, because of one property the rest of the stack already
guarantees:

    every deploy produces a CONTENT-ADDRESSED, immutable image (a data sphere).

So a "release" is just a sealed record binding (tenant, app, branch, image_digest, workload). Rolling
back is re-pointing to a PRIOR release's already-built image digest — **no rebuild**, and because the
digest is content-addressed you get back *exactly* the bits that ran before (reproducible rollback,
not "rebuild the old ref and hope"). It is instant for the same reason it is safe.

It is fail-closed: you can only roll back to a release that ACTUALLY RAN. A rollback target that isn't
in the history — an image that was never built and deployed here — is blocked, never served. Rolling
*forward* to a new version still goes through the promotion gate; rollback to a known-prior-good
release is the fast escape hatch, sealed and audited but ungated (that is the point of a rollback).

`make_release` / `history` / `current` / `rollback` are a pure, file-backed core (unit-tested).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_RELEASES = _ROOT / "artifacts" / "releases"  # where the webhook records real deploys


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seal(body: dict) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _appdir(ledger_dir, tenant: str, app: str) -> Path:
    return Path(ledger_dir) / tenant / app


def make_release(*, tenant: str, app: str, branch: str, image: str, image_digest: str,
                 workload_name: str, status: str = "deployed", kind: str = "deploy",
                 rolled_back_from: str | None = None, rolled_back_to: str | None = None) -> dict:
    """A sealed release record. `release_id` is content+time addressed. `kind` is deploy|rollback;
    `status` is deployed|rolled-back. A rollback record carries the linkage to what it replaced."""
    created_at = _now()
    core = {"tenant": tenant, "app": app, "branch": branch, "image": image,
            "image_digest": image_digest, "workload_name": workload_name, "status": status,
            "kind": kind, "created_at": created_at,
            "rolled_back_from": rolled_back_from, "rolled_back_to": rolled_back_to}
    core["release_id"] = "rel-" + hashlib.sha256(
        json.dumps({"t": tenant, "a": app, "d": image_digest, "ts": created_at},
                   sort_keys=True).encode()).hexdigest()[:12]
    core["receipt_digest"] = _seal({k: v for k, v in core.items()})
    return core


def record(ledger_dir, release: dict) -> dict:
    """Append a sealed release to the app's ledger. A zero-padded monotonic sequence prefixes the
    filename so history order is deterministic (append order) regardless of wall-clock resolution —
    two releases in the same microsecond must not sort by their (hash-based) release_id."""
    d = _appdir(ledger_dir, release["tenant"], release["app"])
    d.mkdir(parents=True, exist_ok=True)
    seq = len(list(d.glob("*.json")))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    (d / f"{seq:08d}-{stamp}-{release['release_id']}.json").write_text(
        json.dumps(release, indent=2, sort_keys=True))
    return release


def record_deploy(ledger_dir, *, tenant: str, app: str, deploy_result: dict) -> dict | None:
    """Turn a successful deploy_flow.on_push result into a recorded release. Failed builds are NOT
    releases (you can't roll back to something that never ran), so they are not recorded."""
    if deploy_result.get("status") != "deployed":
        return None
    return record(ledger_dir, make_release(
        tenant=tenant, app=app, branch=deploy_result.get("branch"),
        image=deploy_result.get("image"), image_digest=deploy_result.get("build_digest"),
        workload_name=(deploy_result.get("workload") or {}).get("name")))


def history(ledger_dir, tenant: str, app: str) -> list:
    """All releases for an app, NEWEST FIRST."""
    d = _appdir(ledger_dir, tenant, app)
    if not d.is_dir():
        return []
    out = []
    for f in sorted(d.glob("*.json"), reverse=True):
        try:
            out.append(json.loads(f.read_text()))
        except (OSError, json.JSONDecodeError):
            continue
    return out


def current(ledger_dir, tenant: str, app: str) -> dict | None:
    """What is serving now — the head of history."""
    h = history(ledger_dir, tenant, app)
    return h[0] if h else None


def _resolve_target(hist: list, *, to_release_id, to_digest, steps: int):
    """Pick the rollback target from history (hist is newest-first, hist[0] = current)."""
    if to_release_id is not None:
        return next((r for r in hist if r.get("release_id") == to_release_id), None)
    if to_digest is not None:
        # newest prior release that ran this exact (content-addressed) image
        return next((r for r in hist[1:] if r.get("image_digest") == to_digest), None)
    # default: `steps` releases back from current
    return hist[steps] if len(hist) > steps else None


def rollback(ledger_dir, *, tenant: str, app: str, to_release_id: str | None = None,
             to_digest: str | None = None, steps: int = 1) -> dict:
    """Instantly re-point an app to a PRIOR release's immutable image. Fail-closed: the target must be
    a real prior release that actually ran (has a deployed/rolled-back status and an image digest),
    else the rollback is blocked and nothing is served. On success a new head release (kind=rollback)
    is recorded so you can roll again (forward or back)."""
    hist = history(ledger_dir, tenant, app)
    decision = {"surface": "sourceos-continuum.release_ledger.rollback.v1",
                "tenant": tenant, "app": app, "decided_at": _now()}

    if not hist:
        decision.update({"ok": False, "placement": "blocked",
                         "reason": "no release history for this app — nothing to roll back to"})
        decision["receipt_digest"] = _seal(decision)
        return decision

    cur = hist[0]
    target = _resolve_target(hist, to_release_id=to_release_id, to_digest=to_digest, steps=steps)

    # fail-closed: only roll to a release that actually ran and carries a content-addressed image.
    ran = target is not None and target.get("status") in ("deployed", "rolled-back") \
        and bool(target.get("image_digest"))
    if not ran:
        decision.update({"ok": False, "placement": "blocked",
                         "reason": "rollback target is not a prior release that ran here — an image "
                                   "that was never built+deployed is never served (fail-closed)",
                         "current": {"release_id": cur.get("release_id"), "image_digest": cur.get("image_digest")}})
        decision["receipt_digest"] = _seal(decision)
        return decision

    if target.get("image_digest") == cur.get("image_digest"):
        decision.update({"ok": True, "placement": "no-op", "instant": True, "no_rebuild": True,
                         "reason": "target image is already serving — nothing to do",
                         "current": {"release_id": cur.get("release_id"), "image_digest": cur.get("image_digest")}})
        decision["receipt_digest"] = _seal(decision)
        return decision

    new_head = record(ledger_dir, make_release(
        tenant=tenant, app=app, branch=target.get("branch"), image=target.get("image"),
        image_digest=target.get("image_digest"), workload_name=target.get("workload_name"),
        status="rolled-back", kind="rollback",
        rolled_back_from=cur.get("release_id"), rolled_back_to=target.get("release_id")))

    decision.update({
        "ok": True, "placement": "rolled-back", "instant": True, "no_rebuild": True,
        "reason": "re-pointed to a prior release's content-addressed image — no rebuild, reproducible",
        "from": {"release_id": cur.get("release_id"), "image": cur.get("image"),
                 "image_digest": cur.get("image_digest")},
        "to": {"release_id": target.get("release_id"), "image": target.get("image"),
               "image_digest": target.get("image_digest")},
        "new_head": {"release_id": new_head["release_id"], "kind": new_head["kind"],
                     "receipt_digest": new_head["receipt_digest"]},
    })
    decision["receipt_digest"] = _seal({k: v for k, v in decision.items() if k != "receipt_digest"})
    return decision


def _cli(argv: list) -> int:
    """history|current|rollback <tenant> <app> [--to-digest D | --to-release R | --steps N].
    Operates on the real ledger (artifacts/releases). Returns a process exit code."""
    cmd, rest = argv[0], argv[1:]
    pos, opts, it = [], {}, iter(rest)
    for a in it:
        if a.startswith("--"):
            opts[a[2:]] = next(it, None)
        else:
            pos.append(a)
    tenant = pos[0] if pos else "you"
    app = pos[1] if len(pos) > 1 else "default"
    if cmd == "history":
        print(json.dumps([{"release_id": r["release_id"], "kind": r["kind"], "status": r["status"],
                           "image_digest": r["image_digest"], "created_at": r["created_at"]}
                          for r in history(_RELEASES, tenant, app)], indent=2))
        return 0
    if cmd == "current":
        print(json.dumps(current(_RELEASES, tenant, app), indent=2))
        return 0
    d = rollback(_RELEASES, tenant=tenant, app=app, to_release_id=opts.get("to-release"),
                 to_digest=opts.get("to-digest"), steps=int(opts.get("steps") or 1))
    print(json.dumps(d, indent=2))
    return 0 if d.get("ok") else 1


if __name__ == "__main__":
    import sys
    import tempfile

    if len(sys.argv) > 1 and sys.argv[1] in ("history", "current", "rollback"):
        raise SystemExit(_cli(sys.argv[1:]))

    # no subcommand: an in-memory demo of the full story.
    with tempfile.TemporaryDirectory() as td:
        t, a = "acme", "shop"
        # three deploys land, oldest -> newest (v1, v2, v3 have distinct content-addressed images).
        for i, dig in enumerate(("aa" * 32, "bb" * 32, "cc" * 32), start=1):
            record(td, make_release(tenant=t, app=a, branch="main", image=f"shop@sha256:{dig[:12]}",
                                    image_digest="sha256:" + dig, workload_name="shop"))
        before = current(td, t, a)["image_digest"]

        one_back = rollback(td, tenant=t, app=a)                       # v3 -> v2
        to_v1 = rollback(td, tenant=t, app=a, to_digest="sha256:" + "aa" * 32)  # -> v1 exactly
        forged = rollback(td, tenant=t, app=a, to_digest="sha256:" + "99" * 32)  # never ran -> blocked

        print(json.dumps({
            "history_depth": len(history(td, t, a)),
            "was_serving": before[:19] + "…",
            "rollback_1_step": {"ok": one_back["ok"], "to": one_back["to"]["image_digest"][:19] + "…",
                                "instant": one_back["instant"], "no_rebuild": one_back["no_rebuild"]},
            "rollback_to_v1_digest": {"ok": to_v1["ok"], "to": to_v1["to"]["image_digest"][:19] + "…"},
            "rollback_to_never_built": {"ok": forged["ok"], "placement": forged["placement"],
                                        "reason": forged["reason"][:60] + "…"},
            "now_serving": current(td, t, a)["image_digest"][:19] + "…",
        }, indent=2))
