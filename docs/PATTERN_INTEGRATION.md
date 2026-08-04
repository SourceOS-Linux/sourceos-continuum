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
| **Parallel / MPI job (N ranks)** — the POE pattern | Indexed `Job` (k8s) / `--ntasks` MPI + `--array` (slurm) | ○ **next unit** |
| **Real SLURM submission** | today: placement + descriptor only (`DescriptorAdapter`); real `sbatch`/`srun`/MPI adapter | ○ **next unit** |
| **Edge/Fog K3s ↔ Cloud Twin sync** over intermittent links (LAN/WAN/sneakernet) | mesh telemetry + hyperswarm scale-up capability; real twin-sync + S3 export | ◑ |

## Reach, governance, evidence

| Pattern | Our implementation | Status |
|---|---|---|
| **SSH gateway to a device fleet** (ShellHub: Server + Agents on computer/device/container/server) | cloud-shell fog: Edge Gateway + HyperSwarm discovery + Grant-bound attach; a ShellHub-style agent per node | ◑ |
| **7-layer PaaS** (UX→Object Store→Derived→Vendor→Retrieval→Policy→Tool-runtime) | knowledge commons (canonical + derived + provenance), MCP surface (tool runtime), promotion gate (policy) | ◑ |
| **Governed connector calls** (Gemini/OpenAI/Claude Files APIs — materialize→handle→dispatch→result) | the SAME governed dispatch as a compute job: a `connector` effect through grant + executor | ○ **next unit** |
| **Append-only audit ledger** (every diagram) | sealed receipts (`artifacts/`), MCP-A2A ledger conformance | ✅ |

## What this establishes

The compute mesh + grants + admission is the **governance & scale-out substrate**; the DevSpace/
Sandbox/StatefulSet plane is the **environment & stateful substrate**. The two open frontiers that
would make the HPC/connector story first-class are one unit: **parallel/MPI jobs (Indexed Job +
real SLURM) and connector-call-as-dispatch** — unifying "run a job" and "call a connector" under one
`Grant`-gated executor. That is the codification the IBM Parallel Environment pattern is asking for.
