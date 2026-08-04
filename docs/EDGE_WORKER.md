# Edge-worker + evolvable topology — Giant Swarm, reversed

## The model

**Giant Swarm** runs a cloud **management cluster** that provisions and operates **workload clusters**
top-down (k8s-on-k8s, Cluster API). Powerful, but cloud-owns-edge, and heavy.

We **reverse it.** The edge **agent-machine** — a lightweight, **single-master k3s** (k3s-in-docker on
the M2, or k3s on a server) — is sovereign and local-first, and it **registers *up* into a cloud pool
as a worker.** The cloud **twin** is a rendezvous, not a master. Two design facts drive this:

- **An ephemeral dev node doesn't need HA.** Single-master k3s is the right weight at the edge;
  redundant multi-master k8s is for the cloud. So `k3s-edge` is a distinct, trusted backend from full
  `k8s` — not a lesser one, the *right-sized* one.
- **The topology is evolvable, not pinned.** The same workload climbs the ladder as needs grow, and
  it shouldn't matter which rung it's on:

  ```
  k3s-edge  ──►  k3s-server  ──►  k8s-cloud
  (in-docker      (a box on         (redundant,
   on the box)     the LAN/DC)       multi-master)
  ```

## What's built (`tools/edge_worker.py`)

- **`register_worker`** — the agent-machine joins a cloud **pool** as a worker (the reversed
  direction). It emits a **mesh heartbeat** (`mesh_telemetry`), so the edge node's CPU becomes real,
  **placeable** capacity the compute plane can schedule onto — the box's compute is now in the pool.
- **`shared_storage_mount`** — the agent-machine's local **TopoLVM flash** exposed to the cluster as a
  shared container mount (`topolvm-provisioner`, at `/var/lib/sourceos/inception`). The registered
  worker contributes **storage as well as compute**.
- **`evolve`** — migrate a workload across the ladder (`k3s-edge ⇄ k3s-server ⇄ k8s-cloud`). State
  follows via the TopoLVM inception mount; no rung is special, migration is just an index move.
- **`k3s-edge` backend** (`compute_plane`) — trusted, single-master, `residency: edge`. A sensitive
  workload may run on the sovereign edge; the Needs firewall and placement treat it as first-class.

## Why this beats both models

Giant Swarm gives you managed clusters but the cloud owns them. A plain k3s gives you a sovereign
edge but it's an island. The **edge-worker + evolvable topology** gives you both: the edge is
**sovereign and local-first** (your k3s, your TopoLVM flash, your data), *and* it **federates up** —
registering compute + storage into a cloud pool when you want scale, migrating workloads up the
ladder as needs grow, and falling back to fully-local single-master when you don't. Same governed
placement/grant/needs plane across every rung. It shouldn't matter where it runs — and now it doesn't.
