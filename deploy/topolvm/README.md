# TopoLVM — the agent-machine inception mount

Per the Edge/Fog design, the agent-machine's persistent **inception mount** (`/var/lib/sourceos/inception`)
is backed by **TopoLVM**: topology-aware, LVM-backed, node-local persistent volumes. The DevSpace PVC
and the agent-machine StatefulSet's `volumeClaimTemplates` default to `storageClassName:
topolvm-provisioner`.

## Why TopoLVM (not local-path / NFS)

- **Node-local + fast** — the inception mount is on the node's SSD via LVM, not a network hop.
- **Topology-aware** — `WaitForFirstConsumer` schedules the pod to a node that actually has capacity
  to carve the LV, then binds. No "volume provisioned on the wrong node" failures.
- **Capacity-aware + expandable** — TopoLVM tracks free VG space per node and reports it to the
  scheduler; `allowVolumeExpansion: true`.

## Install (production cluster)

TopoLVM needs cert-manager (its webhook) and an LVM volume group on each storage node.

```bash
# 1. cert-manager (webhook certs)
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/latest/download/cert-manager.yaml

# 2. on each node: a volume group named to match the device-class (e.g. an SSD VG)
#    sudo vgcreate ssd-vg /dev/nvme1n1        # real disk in prod
#    (lab: losetup a sparse file, then vgcreate)

# 3. TopoLVM (Helm) with lvmd pointed at that VG/device-class
helm repo add topolvm https://topolvm.github.io/topolvm
helm install topolvm topolvm/topolvm -n topolvm-system --create-namespace \
  --set lvmd.deviceClasses[0].name=ssd \
  --set lvmd.deviceClasses[0].volume-group=ssd-vg \
  --set lvmd.deviceClasses[0].default=true

# 4. the StorageClass the DevSpace + StatefulSet reference
kubectl apply -f deploy/topolvm/topolvm-storageclass.yaml
```

## Local (kind/podman) note

A rootless-podman `kind` node has no LVM tooling, so TopoLVM won't provision there. For local proofs
the DevSpace is created with `storage_class="standard"` (kind's local-path) — the inception mount
persistence was verified end-to-end that way (write in one pod, read in another). Production is a
one-field swap back to `topolvm-provisioner`.
