# Cloud Shell — Hardened Pack

This bundle adds real-world hardenings:
- Per-user spawner (OIDC identity → per-user SA/PVC/Deployment/Service)
- Idle culler (annotation-driven)
- Kyverno policies (pod security baseline, disallow :latest, signed image verification scaffold)
- Default-deny NetworkPolicy + ingress/DNS allowlists
- ResourceQuota + LimitRange
- k3s/k8s/OpenShift values overlays

Important:
- NetworkPolicy enforcement depends on your CNI.
- `coreos/toolbox` is deprecated; use `containers/toolbox` for modern immutable hosts.


Build note:
- `spawner/` and `culler/` include Go code that depends on Kubernetes client-go.
- In this sandbox environment, Go module downloads are blocked, so `go mod tidy` cannot run here.
- In your repo, run `go mod tidy` (networked) or vendor dependencies before building images.
