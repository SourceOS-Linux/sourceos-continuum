# Pattern integration register — demonstrated designs vs. our platform

Every pattern from the reference designs (Nocalhost, Signadot, ShellHub, the Edge/Fog↔Cloud-Twin
K3s design, the 7-layer PaaS, Eclipse/IBM Parallel Environment) mapped to what we have, honestly
graded. `✅` shipped · `◑` partial · `○` gap (named next step).

## Developer inner loop & environments

| Pattern (source) | Our implementation | Status |
|---|---|---|
| **DevSpace** — isolated per-user namespace (Nocalhost) | `devspace.devspace_manifests` — Namespace + ResourceQuota + default-deny NetworkPolicy + inception PVC | ✅ |
| **User → Space → Application** tenancy (Nocalhost) | `DevSpacePlane` (tenant→space→env), tenancy labels; admission quotas per subject | ✅ |
| **MeshSpace / Sandbox** — header-routed fork sharing the baseline (Nocalhost MeshSpace, Signadot) | `devspace.sandbox_manifests` — fork Deployment + Istio VirtualService routing `x-sandbox-routing-key` (≡ Nocalhost `uberctx-trace`) | ✅ |
| **Fast inner loop** — file-sync / port-forward / remote-debug / exec-in-container (Nocalhost Dev Mode) | declared in `caps.dev.devspace-inner-loop`; runtime hot-sync agent | ○ next |
| **KubeConfig connect, any cluster** (Nocalhost) | executor honours an explicit `SOURCEOS_KUBE_CONTEXT` (never the current context) | ✅ |
| **Deploy Helm/Kustomize/YAML** (Nocalhost) | executor emits YAML/JSON manifests; Helm/Kustomize adapters | ◑ |

## Stateful & storage

| Pattern | Our implementation | Status |
|---|---|---|
| **StatefulSet** — stable identity + per-replica storage (k8s framework for stateful apps) | `devspace.agent_machine_statefulset` — headless Service + `volumeClaimTemplates` | ✅ |
| **TopoLVM inception mount** — node-local LVM PV for the agent-machine (Edge/Fog `PersistentVolumes TopoLVM`) | `INCEPTION_MOUNT_PATH` + PVC/volumeClaimTemplates on `topolvm-provisioner`; `deploy/topolvm/`; persistence proven on a real cluster | ✅ |
| **Volumes vs bind-mounts vs tmpfs** (Docker storage) | inception mount = a persistent **volume** (PVC), not a bind/writable-layer — survives pod death | ✅ |
| **Operator pattern** — CRD + controller for stateful lifecycle | `control_loop` is a governed reconciler; a real `AgentMachine` CRD + operator | ○ next |

## Compute fabric & jobs (IBM Parallel Environment / HPC Toolkit)

| Pattern | Our implementation | Status |
|---|---|---|
| **Placement across substrates** (LoadLeveler/SLURM-style) | `compute_plane.place` over local/k8s/hpc-slurm/wasm/p2p/volunteer/blockchain | ✅ |
| **Batch job** | `Job` (k8s, real) / `sbatch` (slurm) | ✅ k8s · ○ slurm submit |
| **Parallel / MPI job (N ranks)** — the POE pattern | `executor.K8sAdapter` emits an **Indexed Job** (completions/parallelism=N, `JOB_COMPLETION_INDEX` = rank); `sourceosctl run --parallelism N` | ✅ |
| **Real SLURM submission** | `executor.SlurmAdapter` emits a real `sbatch` script (`--ntasks` + `srun` MPI ranks), submits via `ssh <SOURCEOS_SLURM_LOGIN> sbatch` | ✅ |
| **Edge/Fog K3s ↔ Cloud Twin sync** over intermittent links (LAN/WAN/sneakernet) | mesh telemetry + hyperswarm scale-up capability; real twin-sync + S3 export | ◑ |

## Reach, governance, evidence

| Pattern | Our implementation | Status |
|---|---|---|
| **SSH gateway to a device fleet** (ShellHub: Server + Agents on computer/device/container/server) | cloud-shell fog: Edge Gateway + HyperSwarm discovery + Grant-bound attach; a ShellHub-style agent per node | ◑ |
| **7-layer PaaS** (UX→Object Store→Derived→Vendor→Retrieval→Policy→Tool-runtime) | knowledge commons (canonical + derived + provenance), MCP surface (tool runtime), promotion gate (policy) | ◑ |
| **Governed connector calls** (Gemini/OpenAI/Claude Files APIs — materialize→handle→dispatch→result) | `executor.ConnectorAdapter` + a `connector` backend (external/untrusted): a connector call is the SAME Grant-gated dispatch as a compute job | ✅ |
| **Append-only audit ledger** (every diagram) | sealed receipts (`artifacts/`), MCP-A2A ledger conformance | ✅ |

## What this establishes

The compute mesh + grants + admission is the **governance & scale-out substrate**; the DevSpace/
Sandbox/StatefulSet plane is the **environment & stateful substrate**; and one `Grant`-gated executor
now dispatches **batch, parallel/MPI (Indexed Job / SLURM `sbatch`+`srun`), stateful, and connector**
work alike — "run a job" and "call a connector" are the same governed dispatch. That codifies the
IBM Parallel Environment / HPC Toolkit pattern on the mesh.

**Remaining frontier** (the next research-driven unit): the **volunteer-compute / global-mesh
substrate** — how a Folding@home-scale volunteer grid (untrusted, churny, 400k-node) plugs in
governed, per the dual-orchestration design and the volunteer-computing corpus. See the incoming
synthesis.
