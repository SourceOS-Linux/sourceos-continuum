# PaaS gap register — Nocalhost + BlueMix/Watson, box by box

Every component OCR'd off the four diagrams (Nocalhost *Sidecar* + *How It Works*; BlueMix/Watson
*Gen3* + DW-DevOps *Gen4*), mapped to our stack and graded honestly. `✅` have · `◑` partial · `○`
GAP. The point: we have strong *primitives* but the **server/control-plane seam** that makes those
diagrams feel seamless is mostly missing — that's what this register makes explicit.

## Nocalhost — developer inner loop (client)

| Box (OCR) | Ours | Grade |
|---|---|---|
| Developer → **Dev Mode** | `devmode.py` (patch + sync + port-forward *plan*) | ◑ plan, no live loop / IDE trigger |
| **IDE (Plugin)** — VS Code | — | ○ **GAP: no IDE plugin** (we have a CLI, not an editor extension) |
| **nhctl (CLI)** | `sourceosctl` | ✅ |
| **DevContainer + App** (sidecar dev container) | `devmode_patch` swaps the container | ◑ (no sidecar-alongside-app mode; we replace, not sidecar) |
| Hot Reloading / Local Access / Debugging | sync (`kubectl cp`) + port-forward commands | ◑ (generated, not run; no debugger wiring) |
| **AppA(terminal)** — remote terminal | cloud-shell fog grant-bound attach (*design*) | ○ **GAP: no running remote terminal** |
| namespace-per-user + **ServiceAccount** isolation | `devspace` (Namespace + quota + NetworkPolicy), grant binding | ✅ |

## Nocalhost — server / admin control plane

| Box | Ours | Grade |
|---|---|---|
| **Nocalhost-Web** (admin web console) | portal (read-only dev console) | ◑ (no admin console) |
| **Nocalhost-API** (REST) | MCP ops surface (agent JSON-RPC) | ◑ (no REST admin API) |
| **Nocalhost-Dep** (cluster-side dep, `nocalhost-reserved` ns) | — | ○ **GAP: no cluster-side controller/operator** |
| **Login** / auth | — | ○ **GAP: no login/session/SSO** |
| Admin: **Create User** | — | ○ **GAP** (this change closes it) |
| Admin: **Configure Cluster** | CapDs (static) | ◑ |
| Admin: **Configure Application** | buildpack + workload specs | ◑ |

## BlueMix / Watson Gen3 — multi-tenant SaaS

| Box | Ours | Grade |
|---|---|---|
| **Load Balancer** | — | ○ GAP (no ingress LB in continuum) |
| DataWorks **UI App Server** | portal | ◑ |
| **BlueMix SSO service** | — | ○ **GAP: no SSO** |
| **BlueMix Entitlement service** | admission **tiers** | ◑ (tier data, no entitlement *service*/token) |
| **Watson Token Server** (per-tenant) + **/me API** | grants (session tokens) | ◑ (no token server / user-profile `/me`) — this change adds `/me` |
| **Service Broker** (add tenant / provision new VM) | `devspace` manifests | ○ **GAP** (this change closes it) |
| **Landing Page** / onboarding | — | ○ GAP |
| **Resource Manager** | `compute_plane.place` | ◑ (no persistent RM service) |
| **Liberty Collective Cluster** | k8s via executor | ◑ |
| **DB2** → **Cloudant** (managed state) | sealed ledger + content-addressed commons | ✅ (state is a log, not a monolith DB) |
| **Free/Paid × Interactive/Batch** Spark tiers | admission tiers (free/pro/enterprise) | ◑ (no interactive×batch × free×paid matrix) |

## DW-DevOps Gen4 — ops / HA

| Box | Ours | Grade |
|---|---|---|
| **CDS Load Balancer** (RM Routes → IHS Routes) | — | ○ **GAP: no routing/LB plane** |
| **RM A / RM B** zero-downtime failover | single `place()` decision | ○ **GAP: no HA/failover for the control plane** |
| **Cluster A / Cluster B** (IHS/CC/CM) active-active | one mesh | ○ GAP (no active-active twin clusters) |
| **Metering** | admission cost/usage ledger | ◑ (tracked, not exported) — this change adds a metering record |
| **BSS** (billing / business support) | credits in admission | ○ **GAP: no billing surface** |
| **ELK / Grafana** | prophet-platform OTel/Prometheus config | ◑ (no dashboards in continuum) |
| **Cloudant** managed state | commons + ledger | ✅ |
| **Continuous-Availability legend** | `availability.py` grades | ✅ |
| **Broker / Services Components** | — | ○ (this change) |

## The seam this register exposes

We have the **substrate** (place/grant/admission/executor/devspace/buildpack/inference) but not the
**server control plane** that a developer and an admin actually touch: *log in → provision my tenant
→ get my namespace + quota + endpoint → see my usage → be billed*. Nocalhost calls that Web+API+Dep;
BlueMix calls it SSO+Entitlement+Broker+Token+BSS. It's the same server. `tools/provisioning.py`
(this change) builds the governed core of it — provision/bind/deprovision a tenant (DevSpace + tier +
session), meter usage, and `/me` — and the portal exposes `/api/me` + `/api/provision`.

**Still open after this change** (the honest ranked backlog): IDE plugin · running remote terminal ·
real login/SSO · cluster-side dep operator · load-balancer + RM-A/B failover HA · ELK/Grafana
dashboards · landing page. Named here so nothing hides.

## Cloud Foundry / BlueMix — similar, different, and why ours is best-of-all

**Similar.** Cloud Foundry *invented* the ergonomic everyone copied: `cf push` — git-push-to-deploy
with **buildpacks** (CF's invention; Heroku popularized it, and it's the direct ancestor of the Cloud
Native Buildpacks / Paketo we use in `buildpack.py`), staged apps, service brokers, org/space
multi-tenancy, and marketplace add-ons. BlueMix was IBM's hosted CF plus the Watson/DataWorks
services in the Gen3/Gen4 diagrams. So the *shape* — build, bind, broker, tier, meter — is the shape
we're matching.

**Different, and why the community walked.** Two reasons, and your read is right:
1. **Not k8s-native.** CF is a *parallel, opinionated stack* — its own scheduler (**Diego**, not
   k8s), its own container runtime (**Garden**, not OCI/Docker), its own release tool (**BOSH**). It
   predated Kubernetes and never aligned with it. When k8s won the orchestration war (~2017), CF's
   parallel universe became a liability; `cf-for-k8s`/Korifi arrived too late.
2. **BlueMix buried the open core under proprietary, hosted lock-in.** CF the core was open, but
   BlueMix was IBM-hosted + IBM-proprietary services (SSO, Entitlement, Token Server, Watson) on top.
   Not the code/cloud-native openness the community wanted.

The community's actual want was **"Heroku's DX on my own Kubernetes, open."** That's why **Porter**
(and Coolify, Dokku, Railway) exist, and why CF's buildpack IP was extracted into the CNCF's
**Cloud Native Buildpacks**.

**Why ours is best-of-all — we took each thing from where it was best:**
- CF's **buildpack / git-push ergonomic** — via open CNB/Paketo (`buildpack.py`), reproducible +
  SLSA-attestable, not a proprietary slug.
- Porter's **k8s-native** runtime — the executor dispatches real k8s (proven on a live cluster), no
  Diego/Garden/BOSH parallel stack.
- Heroku's **radical simplicity** + BlueMix's **entitlement/broker/metering** — as sovereign, light
  primitives (`admission` tiers, `provisioning` broker + BSS meter + `/me`), not a hosted lock-in.
- And what **none** of them have: **zero-trust governance** (grants, Needs firewall, sealed
  receipts), a **multi-substrate mesh** (local→k8s→HPC→wasm→p2p→**volunteer**→blockchain — they are
  k8s-only), **sovereign GPU inference** (our own LLMs, sensitive data never leaving), **data
  spheres** (immutable, residency-fenced), and a **mobile twin/box** front door.

CF/BlueMix answered "how do I push an app to *a* cloud." We answer "how do I run *any* governed
workload — app, batch, MPI, model, volunteer WU — across *my own* sovereign fabric, from my phone,
without a cloud provider." Same push ergonomic on top; a categorically larger, open, governed
substrate underneath.
