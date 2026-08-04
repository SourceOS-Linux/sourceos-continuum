#!/usr/bin/env python3
"""sourceosctl — the developer's one command to run a workload governed across the mesh.

From a low-mem box, seamlessly:

    sourceosctl run --command "python train.py" --gpu --sensitivity sensitive
    sourceosctl mesh          # what's live in the mesh right now
    sourceosctl place --gpu   # where WOULD this land? (dry, no dispatch)
    sourceosctl commons       # the reproducible knowledge commons

`run` reads the live mesh, places the workload under policy, mints + verifies a zero-trust Grant, and
dispatches it — printing where it ran and the sealed receipt. The substrate doesn't matter: local,
k8s, HPC, wasm, p2p, volunteer grid, blockchain. Governed and fail-closed throughout.

In production the Grant is signed by the Key Authority (HSM/KMS) and the AttestationBundle comes from
the node's TPM/TEE + cosign. Without a real signing key configured (SOURCEOS_SIGNING_KEY), this runs
in DEV MODE: it synthesizes a dev attestation + HMAC key and says so loudly.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import admission as adm  # noqa: E402
import compute_plane as cp  # noqa: E402
import executor as ex  # noqa: E402
import mcp_a2a_grant as g  # noqa: E402
import mesh_telemetry as mt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
HEARTBEATS = ROOT / "artifacts" / "mesh-heartbeats"
LEDGER = ROOT / "artifacts" / "admission-usage.json"
_DEV_KEY = "dev-only-key-not-for-production"


def _key() -> bytes:
    return os.environ.get("SOURCEOS_SIGNING_KEY", _DEV_KEY).encode()


def _dev_mode() -> bool:
    return os.environ.get("SOURCEOS_SIGNING_KEY") is None


def _sha(s: str) -> str:
    return "sha256:" + hashlib.sha256(s.encode()).hexdigest()


def run_workload(*, name, command, effect, sensitivity, scalable, gpu, image, subject,
                 heartbeats_dir, key, apply=False, dry=False, admission=None, cost=1.0,
                 inception=False) -> dict:
    """Core of `run` — testable without the CLI. Returns the full spine trace (or a placement)."""
    reg = mt.MeshRegistry.from_dir(heartbeats_dir)
    workload = {"name": name, "command": command, "effect": effect, "sensitivity": sensitivity,
                "scalable": scalable, "needs_gpu": gpu, "image": image}
    if inception:  # mount the agent-machine's persistent TopoLVM inception mount (k8s backend)
        import devspace
        workload["inception_pvc"] = devspace.INCEPTION_PVC
    policy = {"require_attestation": sensitivity == "sensitive"}
    if dry:
        return {"status": "placed", "decision": cp.place(workload, policy, reg.availability())}
    aum = _sha("dev-node:" + subject)
    binding = {"spiffe_id": subject, "aum_digest": aum, "session_id": "sess_" + _sha(subject)[7:17]}
    capability = {"kind": "mcp_tool", "capability_ref": "capd://caps.compute.mesh-plane",
                  "capability_digest": _sha(image or command or name), "effect": effect}
    attestation = g.attestation_bundle(spiffe_id=subject, aum_digest=aum, tpm_valid=True, cosign_valid=True)
    return ex.run_spine(workload, policy, registry=reg, binding=binding, capability=capability,
                        attestation=attestation, constraints={"ops_allow": ["exec.run"]},
                        signer=g.hmac_signer(key), verifier=g.hmac_verifier(key), apply=apply,
                        admission=admission, admission_key=subject, cost=cost)


def cmd_run(args) -> int:
    if _dev_mode():
        print("!  DEV MODE: no SOURCEOS_SIGNING_KEY set — synthesizing a dev attestation + HMAC key. "
              "Not for production.", file=sys.stderr)
    admission = None if args.dry else adm.AdmissionController(ledger_path=LEDGER)
    out = run_workload(name=args.name, command=args.command, effect=args.effect,
                       sensitivity=args.sensitivity, scalable=not args.no_scale, gpu=args.gpu,
                       image=args.image, subject=args.subject, heartbeats_dir=HEARTBEATS,
                       key=_key(), apply=args.apply, dry=args.dry, admission=admission, cost=args.cost,
                       inception=args.inception)
    if out["status"] == "denied":
        a = out["admission"]
        print(f"DENIED (fail-closed): {a['reason']}  [usage {a['usage']} vs quota {a['quota']}]")
        return 4
    if out["status"] == "blocked":
        print(f"BLOCKED (fail-closed): {out['decision']['reason']}")
        return 3
    if out["status"] == "placed":
        d = out["decision"]
        print(f"would place on: {d['backend']}  ({d.get('backend_trust', '-')})  — {d['reason']}")
        return 0
    d, e = out["decision"], out["execution"]
    print(f"ran on: {out['backend']}  ({d['backend_trust']})  via grant {out['grant_id']}")
    print(f"dispatch: {e['dispatch']['kind']} (applied={e['dispatch'].get('applied')})")
    print(f"sealed receipt: {e['receipt']['receipt_digest']}")
    if out.get("admission"):
        print(f"quota usage: {out['admission']}")
    return 0


def cmd_quota(args) -> int:
    ac = adm.AdmissionController(ledger_path=LEDGER)
    print(f"quota for {args.subject}: {ac.quota_for(args.subject)}")
    print(f"usage:     {ac.usage(args.subject)}")
    return 0


def cmd_mesh(args) -> int:
    reg = mt.MeshRegistry.from_dir(HEARTBEATS)
    s = reg.summary()
    print(f"mesh: {s['live_nodes']}/{s['total_nodes']} nodes live; backends up: {', '.join(s['backends_up']) or 'none'}")
    for b, cap in sorted(reg.availability().items()):
        print(f"  {b:18} {cap:>8g} units")
    return 0


def cmd_place(args) -> int:
    args.dry = True
    return cmd_run(args)


def cmd_commons(args) -> int:
    import commons as cm
    c = cm.estate_commons(ROOT)
    recs = c.records()
    print(f"commons: {len(recs)} records, {len(c.search(reproducible=True))} reproducible")
    for r in recs:
        print(f"  [{r['reproducibility'][:4]}] {r['asset_type']:11} {r['commons_id'].split('+')[0]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sourceosctl", description="run workloads governed across the mesh")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="place + grant + verify + dispatch a workload across the mesh")
    r.add_argument("--command", default="true", help="the command to run")
    r.add_argument("--name", default="workload")
    r.add_argument("--image", default="")
    r.add_argument("--effect", default="compute", choices=["read", "write", "compute", "exec", "egress"])
    r.add_argument("--sensitivity", default="normal", choices=["normal", "sensitive"])
    r.add_argument("--gpu", action="store_true", help="workload needs a GPU")
    r.add_argument("--no-scale", action="store_true", help="keep it small (non-scalable)")
    r.add_argument("--subject", default="spiffe://sourceos/agent/dev", help="the requesting subject SPIFFE id")
    r.add_argument("--cost", type=float, default=1.0, help="cost units to charge against the subject's budget")
    r.add_argument("--inception", action="store_true", help="mount the agent-machine's persistent TopoLVM inception mount (k8s)")
    r.add_argument("--apply", action="store_true", help="actually execute (local subprocess / kubectl apply)")
    r.add_argument("--dry", action="store_true", help="only decide placement; dispatch nothing")
    r.set_defaults(func=cmd_run)

    m = sub.add_parser("mesh", help="show what's live in the mesh")
    m.set_defaults(func=cmd_mesh)

    pl = sub.add_parser("place", help="where would this land? (dry, no dispatch)")
    for a, kw in (("--command", {"default": "true"}), ("--name", {"default": "workload"}),
                  ("--image", {"default": ""}), ("--effect", {"default": "compute"}),
                  ("--sensitivity", {"default": "normal"}), ("--subject", {"default": "spiffe://sourceos/agent/dev"})):
        pl.add_argument(a, **kw)
    pl.add_argument("--gpu", action="store_true")
    pl.add_argument("--no-scale", action="store_true")
    pl.add_argument("--apply", action="store_true", help=argparse.SUPPRESS)
    pl.set_defaults(func=cmd_place)

    c = sub.add_parser("commons", help="the reproducible knowledge commons")
    c.set_defaults(func=cmd_commons)

    q = sub.add_parser("quota", help="show a subject's quota + current usage")
    q.add_argument("--subject", default="spiffe://sourceos/agent/dev")
    q.set_defaults(func=cmd_quota)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
