#!/usr/bin/env python3
"""DevSpace + Sandbox plane — governed, isolated, ephemeral developer environments.

Synthesizes three demonstrated patterns into one governed plane, emitting real, appliable k8s
manifests:

  * Nocalhost DevSpace — an isolated per-user namespace with its own quota and default-deny network
    isolation; the home for the fast inner loop (file-sync / port-forward / remote-debug).
  * The Nocalhost User/Space tenancy model — Workspace/Tenant -> Space -> Application, each space
    isolated and labelled.
  * Signadot sandboxes — a request-routed ephemeral FORK of a baseline workload. Instead of
    duplicating the whole stack, a sandbox shares the baseline cluster and a routing header
    (`x-sandbox-routing-key`) sends only matching requests to the fork; everything else hits
    baseline. That's how you test one changed service against the real rest-of-system, cheaply.

Every environment is tenancy-labelled, quota-bounded (composes with `admission`), and Grant-labelled
(composes with `mcp_a2a_grant`) — so who owns it, what it may consume, and under what authority are
all first-class.
"""
from __future__ import annotations

import re


# The agent-machine's persistent writable FS seam ("inception mount"), backed by a PVC. Per the
# Edge/Fog design this is a TopoLVM volume — topology-aware, LVM-backed local storage, so the
# agent-machine's state lives on fast node-local disk and follows the node it's scheduled to.
INCEPTION_MOUNT_PATH = "/var/lib/sourceos/inception"
INCEPTION_PVC = "inception-mount"
DEFAULT_STORAGE_CLASS = "topolvm-provisioner"


def _slug(*parts: str) -> str:
    s = "-".join(p for p in parts if p)
    s = re.sub(r"[^a-z0-9-]", "-", s.lower()).strip("-")
    return re.sub(r"-+", "-", s)[:63]


def devspace_manifests(*, tenant: str, user: str, space: str, quota: dict | None = None,
                       grant_id: str | None = None, inception_storage: str = "10Gi",
                       storage_class: str = DEFAULT_STORAGE_CLASS) -> list[dict]:
    """Nocalhost-style DevSpace: an isolated per-user Namespace + ResourceQuota + default-deny
    NetworkPolicy + the agent-machine's persistent **inception mount** (a TopoLVM-backed PVC)."""
    ns_name = "ds-" + _slug(tenant, user, space)
    labels = {"sourceos.io/tenant": tenant, "sourceos.io/user": user, "sourceos.io/space": space,
              "sourceos.io/kind": "devspace"}
    if grant_id:
        labels["sourceos.io/grant-id"] = grant_id
    quota = quota or {"pods": "10", "requests.cpu": "4", "requests.memory": "8Gi",
                      "limits.cpu": "8", "limits.memory": "16Gi"}
    return [
        {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": ns_name, "labels": labels}},
        {"apiVersion": "v1", "kind": "ResourceQuota",
         "metadata": {"name": "devspace-quota", "namespace": ns_name, "labels": labels},
         "spec": {"hard": quota}},
        {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy",
         "metadata": {"name": "devspace-isolation", "namespace": ns_name, "labels": labels},
         "spec": {"podSelector": {}, "policyTypes": ["Ingress"],
                  "ingress": [{"from": [{"podSelector": {}}]}]}},  # only same-DevSpace ingress
        {"apiVersion": "v1", "kind": "PersistentVolumeClaim",
         "metadata": {"name": INCEPTION_PVC, "namespace": ns_name,
                      "labels": {**labels, "sourceos.io/mount": "inception"}},
         "spec": {"accessModes": ["ReadWriteOnce"], "storageClassName": storage_class,
                  "resources": {"requests": {"storage": inception_storage}}}},
    ]


def sandbox_manifests(*, baseline: str, image: str, routing_key: str, namespace: str,
                      grant_id: str | None = None, port: int = 8080,
                      command: str | None = None) -> list[dict]:
    """Signadot-style sandbox: a FORK Deployment of `baseline`, plus an Istio VirtualService that
    routes requests carrying `x-sandbox-routing-key: <routing_key>` to the fork and everything else
    to the baseline — so the sandbox shares the cluster instead of duplicating the stack."""
    fork = _slug(baseline, "sbx", routing_key)
    labels = {"sourceos.io/kind": "sandbox", "sourceos.io/baseline": baseline,
              "sourceos.io/routing-key": routing_key}
    if grant_id:
        labels["sourceos.io/grant-id"] = grant_id
    container = {"name": "app", "image": image, "ports": [{"containerPort": port}]}
    if command:
        import shlex
        container["command"] = shlex.split(command)
    deploy = {
        "apiVersion": "apps/v1", "kind": "Deployment",
        "metadata": {"name": fork, "namespace": namespace, "labels": labels},
        "spec": {"replicas": 1, "selector": {"matchLabels": {"app": fork}},
                 "template": {"metadata": {"labels": {**labels, "app": fork}},
                              "spec": {"containers": [container]}}},
    }
    vs = {
        "apiVersion": "networking.istio.io/v1beta1", "kind": "VirtualService",
        "metadata": {"name": _slug(baseline, "sandbox-route"), "namespace": namespace, "labels": labels},
        "spec": {"hosts": [baseline],
                 "http": [
                     {"name": f"sandbox-{routing_key}",
                      "match": [{"headers": {"x-sandbox-routing-key": {"exact": routing_key}}}],
                      "route": [{"destination": {"host": fork}}]},
                     {"name": "baseline", "route": [{"destination": {"host": baseline}}]},
                 ]},
    }
    return [deploy, vs]


def agent_machine_statefulset(*, name: str, tenant: str, space: str, namespace: str,
                              image: str = "busybox:1.36", replicas: int = 1,
                              storage_class: str = DEFAULT_STORAGE_CLASS, storage: str = "10Gi",
                              command: str | None = None, grant_id: str | None = None,
                              port: int = 8080) -> list[dict]:
    """The agent-machine as a STATEFUL app — the right k8s primitive for a long-lived workload that
    keeps state. A StatefulSet gives each replica a stable identity and, via `volumeClaimTemplates`,
    its OWN persistent inception mount (on TopoLVM) that follows it across reschedules; a headless
    Service gives stable network identity. This is what Jobs/Deployments can't do."""
    sname = _slug(name)
    labels = {"sourceos.io/kind": "agent-machine", "sourceos.io/tenant": tenant,
              "sourceos.io/space": space, "app": sname}
    if grant_id:
        labels["sourceos.io/grant-id"] = grant_id
    container = {"name": "agent-machine", "image": image,
                 "ports": [{"containerPort": port}],
                 "resources": {"requests": {"cpu": "100m", "memory": "128Mi"},
                               "limits": {"cpu": "100m", "memory": "128Mi"}},
                 "volumeMounts": [{"name": "inception", "mountPath": INCEPTION_MOUNT_PATH}]}
    if command:
        import shlex
        container["command"] = shlex.split(command)
    svc = {"apiVersion": "v1", "kind": "Service",
           "metadata": {"name": sname, "namespace": namespace, "labels": labels},
           "spec": {"clusterIP": "None", "selector": {"app": sname},
                    "ports": [{"port": port, "name": "agent"}]}}
    sts = {"apiVersion": "apps/v1", "kind": "StatefulSet",
           "metadata": {"name": sname, "namespace": namespace, "labels": labels},
           "spec": {"serviceName": sname, "replicas": replicas,
                    "selector": {"matchLabels": {"app": sname}},
                    "template": {"metadata": {"labels": labels}, "spec": {"containers": [container]}},
                    "volumeClaimTemplates": [
                        {"metadata": {"name": "inception", "labels": {"sourceos.io/mount": "inception"}},
                         "spec": {"accessModes": ["ReadWriteOnce"], "storageClassName": storage_class,
                                  "resources": {"requests": {"storage": storage}}}}]}}
    return [svc, sts]


class DevSpacePlane:
    """The User/Space tenancy model: a tenant owns spaces; a space holds devspaces + sandboxes."""

    def __init__(self):
        self._registry: dict[str, dict] = {}

    def provision_devspace(self, *, tenant, user, space, quota=None, grant_id=None) -> dict:
        manifests = devspace_manifests(tenant=tenant, user=user, space=space, quota=quota, grant_id=grant_id)
        ns = manifests[0]["metadata"]["name"]
        rec = {"kind": "devspace", "tenant": tenant, "user": user, "space": space,
               "namespace": ns, "manifests": manifests}
        self._registry[ns] = rec
        return rec

    def provision_sandbox(self, *, tenant, space, baseline, image, routing_key, namespace,
                          grant_id=None, command=None) -> dict:
        manifests = sandbox_manifests(baseline=baseline, image=image, routing_key=routing_key,
                                      namespace=namespace, grant_id=grant_id, command=command)
        key = f"{namespace}/{baseline}#{routing_key}"
        rec = {"kind": "sandbox", "tenant": tenant, "space": space, "baseline": baseline,
               "routing_key": routing_key, "namespace": namespace, "manifests": manifests}
        self._registry[key] = rec
        return rec

    def environments(self, *, tenant=None) -> list[dict]:
        return [r for r in self._registry.values() if tenant is None or r["tenant"] == tenant]


if __name__ == "__main__":
    import json
    plane = DevSpacePlane()
    ds = plane.provision_devspace(tenant="acme", user="alice", space="feature-x")
    sb = plane.provision_sandbox(tenant="acme", space="feature-x", baseline="productpage",
                                 image="acme/productpage:pr-42", routing_key="pr-42",
                                 namespace=ds["namespace"])
    print(json.dumps({"devspace_namespace": ds["namespace"],
                      "devspace_kinds": [m["kind"] for m in ds["manifests"]],
                      "sandbox_fork": sb["manifests"][0]["metadata"]["name"],
                      "routing": sb["manifests"][1]["spec"]["http"][0]["match"]}, indent=2))
