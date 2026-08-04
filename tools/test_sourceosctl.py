#!/usr/bin/env python3
"""Tests for sourceosctl — the developer front door. Exercises the run_workload core (dry placement,
full spine dispatch, fail-closed block) against an isolated mesh, plus the parser and read-only
subcommands."""
import tempfile

import mesh_telemetry as mt
import sourceosctl as ctl

KEY = b"ctl-test-key"


def _seed(td):
    mt.write_heartbeat(td, "slurm", "hpc-slurm", 100)
    mt.write_heartbeat(td, "k8s1", "k8s", 10)


def test_run_workload_dry_places_without_dispatch():
    with tempfile.TemporaryDirectory() as td:
        _seed(td)
        out = ctl.run_workload(name="t", command="python x.py", effect="compute",
                               sensitivity="sensitive", scalable=True, gpu=True, image="",
                               subject="spiffe://sourceos/agent/a", heartbeats_dir=td, key=KEY, dry=True)
        assert out["status"] == "placed" and out["decision"]["backend"] == "hpc-slurm"


def test_run_workload_full_spine_dispatches_and_seals():
    with tempfile.TemporaryDirectory() as td:
        _seed(td)
        out = ctl.run_workload(name="t", command="echo hi", effect="compute", sensitivity="normal",
                               scalable=True, gpu=False, image="img:1",
                               subject="spiffe://sourceos/agent/a", heartbeats_dir=td, key=KEY)
        assert out["status"] == "ran"
        assert out["execution"]["receipt"]["receipt_digest"].startswith("sha256:")
        assert out["backend"] in ("hpc-slurm", "k8s")


def test_run_workload_blocks_fail_closed_for_sensitive_on_untrusted_only():
    with tempfile.TemporaryDirectory() as td:
        mt.write_heartbeat(td, "boinc", "volunteer-boinc", 500)  # only untrusted up
        out = ctl.run_workload(name="t", command="x", effect="compute", sensitivity="sensitive",
                               scalable=True, gpu=False, image="",
                               subject="spiffe://sourceos/agent/a", heartbeats_dir=td, key=KEY)
        assert out["status"] == "blocked"


def test_parser_builds_run_subcommand():
    args = ctl.build_parser().parse_args(["run", "--command", "echo hi", "--gpu", "--sensitivity", "sensitive"])
    assert args.gpu and args.command == "echo hi" and args.sensitivity == "sensitive"


def test_readonly_subcommands_exit_clean():
    assert ctl.cmd_mesh(None) == 0
    assert ctl.cmd_commons(None) == 0


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
    print(f"ok: {len(fns)} sourceosctl tests passed")
    sys.exit(0)
