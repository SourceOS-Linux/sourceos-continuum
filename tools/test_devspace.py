#!/usr/bin/env python3
"""Tests for the DevSpace + Sandbox plane. Covers the Nocalhost DevSpace (isolated, tenancy-labelled,
TopoLVM inception mount), the Signadot sandbox (header-routed fork sharing the baseline), and the
agent-machine StatefulSet (per-replica TopoLVM inception mount via volumeClaimTemplates)."""
import devspace as ds


def test_devspace_is_isolated_tenancy_labelled_and_topolvm_backed():
    ms = ds.devspace_manifests(tenant="acme", user="alice", space="feat")
    assert [m["kind"] for m in ms] == ["Namespace", "ResourceQuota", "NetworkPolicy", "PersistentVolumeClaim"]
    ns = ms[0]
    assert ns["metadata"]["name"] == "ds-acme-alice-feat"
    assert ns["metadata"]["labels"]["sourceos.io/tenant"] == "acme"
    pvc = ms[3]
    assert pvc["metadata"]["name"] == "inception-mount"
    assert pvc["spec"]["storageClassName"] == "topolvm-provisioner"  # TopoLVM by default (Edge/Fog design)
    assert pvc["spec"]["accessModes"] == ["ReadWriteOnce"]


def test_devspace_storage_class_is_overridable_for_kind():
    ms = ds.devspace_manifests(tenant="a", user="b", space="c", storage_class="standard")
    assert ms[3]["spec"]["storageClassName"] == "standard"


def test_devspace_netpol_denies_cross_devspace_ingress():
    np = ds.devspace_manifests(tenant="a", user="b", space="c")[2]
    assert np["spec"]["policyTypes"] == ["Ingress"]
    assert np["spec"]["ingress"] == [{"from": [{"podSelector": {}}]}]  # only same-DevSpace


def test_sandbox_routes_by_header_to_the_fork_else_baseline():
    dep, vs = ds.sandbox_manifests(baseline="productpage", image="acme/pp:pr-42",
                                   routing_key="pr-42", namespace="ns")
    assert dep["kind"] == "Deployment" and dep["metadata"]["name"] == "productpage-sbx-pr-42"
    http = vs["spec"]["http"]
    assert http[0]["match"][0]["headers"]["x-sandbox-routing-key"]["exact"] == "pr-42"
    assert http[0]["route"][0]["destination"]["host"] == "productpage-sbx-pr-42"  # matching -> fork
    assert http[1]["route"][0]["destination"]["host"] == "productpage"            # default -> baseline


def test_agent_machine_is_a_statefulset_with_per_replica_topolvm_inception_mount():
    svc, sts = ds.agent_machine_statefulset(name="worker", tenant="acme", space="feat",
                                            namespace="ns", replicas=3)
    assert svc["kind"] == "Service" and svc["spec"]["clusterIP"] == "None"  # headless -> stable identity
    assert sts["kind"] == "StatefulSet"
    assert sts["spec"]["serviceName"] == "worker" and sts["spec"]["replicas"] == 3
    vct = sts["spec"]["volumeClaimTemplates"][0]
    assert vct["metadata"]["name"] == "inception"
    assert vct["spec"]["storageClassName"] == "topolvm-provisioner"  # per-replica TopoLVM volume
    vm = sts["spec"]["template"]["spec"]["containers"][0]["volumeMounts"][0]
    assert vm["mountPath"] == ds.INCEPTION_MOUNT_PATH


def test_plane_provisions_environments_and_lists_by_tenant():
    p = ds.DevSpacePlane()
    p.provision_devspace(tenant="acme", user="alice", space="x")
    p.provision_sandbox(tenant="acme", space="x", baseline="pp", image="img",
                        routing_key="k", namespace="ds-acme-alice-x")
    p.provision_devspace(tenant="other", user="bob", space="y")
    assert len(p.environments(tenant="acme")) == 2
    assert len(p.environments()) == 3


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
    print(f"ok: {len(fns)} devspace tests passed")
    sys.exit(0)
