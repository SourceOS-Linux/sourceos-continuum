# Mount-intent taxonomy — sharpened by the live mount table

The mount-intent → backend diagram was scored against the sandbox's own live mount table (now a real
VM: `/dev/vda` ext4 root, `/dev/vdb–vdd` squashfs read-only, four `rclone` FUSE mounts projecting a
remote object store as a filesystem). Four of the eight intents don't instantiate there — not a gap,
just evidence that the taxonomy is scoped to a **stateful fog node** while that environment is a
**disposable single-session actor**. The taxonomy survives; only a subgraph lights up. But the
comparison surfaced four real upgrades, now codified in `tools/data_sphere.py`.

## 1. Integrity by construction, not by flag

`readOnly: true` (a ro bind mount, a ro PVC) is a *mount-flag* assertion — the underlying inode stays
writable through any other view (a second mount, the host, an rw sidecar holding the same PV). For a
corpus that must be provably unmutated between crawl-time and query-time (SP-SCOPE-CRAWL-001), that's
a trust assertion, not a guarantee.

**A squashfs/erofs image + dm-verity with the root hash pinned in the deployment manifest** has no
write path at any layer, and integrity becomes a **signature check**. `data_sphere.mint_sphere`
carries `integrity: dm-verity` + a pinned `root_hash`; `access_check` **refuses a sphere with no
pinned integrity root**. This is the correct sovereign form of `type=image mount` — wire that
otherwise-dangling node to `curated_corpus` as **T0**.

## 2. Tenancy by construction, not by policy

The sandbox binds isolation in the mount **source** string (`rclone-filestore:<session>:/mnt/…`) —
session-scoped and unforgeable from inside the guest. Contrast K8s: a PVC is namespace-scoped *by
policy*, and a bad manifest can bind a pod to a volume it shouldn't. Putting the identity in the
remote **name**, not a path prefix or an admission rule, moves isolation from *policy-enforced* to
*construction-enforced*. `data_sphere.tenancy_binding` returns `sphere-store:<session>:<sphere_id>`.

## 3. The missing axis — DIRECTION

The intents encoded **lifecycle** (canonical/derived/scratch/cache) and **sensitivity**
(secrets/config_ro) but not **direction**. The sandbox's entire security model *is* directional:
three `ro` ingress channels, exactly one `rw` egress channel, nothing bidirectional except the
disposable root. That yields a **single durable-write chokepoint** — exactly what a chain-of-custody
wants, because egress attestation then has one place to live.

`direction ∈ {ingress, egress, bidirectional, none}` is now a first-class attribute on every sphere,
with the invariant enforced by `data_sphere.check_egress_invariant`:

> **At most one egress mount per workload, named — and it is the only mount whose contents survive
> the workload.**

Our current diagram permits `canonical_data → PVC | Docker volume | Podman volume`, all `rw`: three
durable write paths, three attestation points, three ways to get it wrong. The invariant collapses
that to one.

## 4. Backend is a function of the product, not the data

The edge/fog↔cloud-twin diagram's three link modes (LAN/WAN/sneakernet) all have **copy semantics**
(snapshot, export, reconcile). The sandbox's rclone FUSE has **reference semantics** — no second
copy, therefore no divergence, therefore no reconciliation, therefore no conflict algebra. The
`(S3-compatible store)` box and rclone are *the same object*; "how does the edge reach the store" is
answered *mount it*, not *sync to it* (price: zero offline capability — cut the link and every channel
fails at once).

So the two diagrams compose into one lattice. The real signature is not `intent → backend` but:

```
intent × link_availability × durability_requirement → backend
```

`data_sphere.backend_for` implements it:

| link | durability | backend | copy? | reconcile? |
|---|---|---|---|---|
| reliable | any | **reference-mount** | no | no |
| intermittent | canonical | copy + reconcile | yes | **yes** (SP-EVAL-CRF-001 earns its keep here) |
| intermittent | derived/scratch | copy | yes | no |

The reconciliation burden is a **function of the product**, not a property of the data — so the
Mellumwork ternary / conflict-resolution-faithfulness machinery is paid *only* on the
`intermittent × canonical` cell, and every other mount class gets correctness for free from the link.
Add `reference mount (no copy)` as a fourth column on the intermittent-link box with the availability
precondition on the edge, and the two diagrams are one.

**The Needs firewall prunes the lattice first.** `backend_for` now takes `needs` +
`offline_tolerant` + `store_locality`, and two Needs forbid the cheap reference-mount *before* link
availability is even consulted: a **`no_egress`** Need on a **remote** store (a remote reference-mount
*is* egress → forced to a local copy), and **offline-tolerance** (a reference-mount has zero offline
capability → must cache locally even over a reliable link). A `no_egress` Need on a *local* store is
fine — a local mount is not egress. So the real signature is
`intent × link × durability × needs → backend`, and the Needs firewall and the mount lattice are one
plane, not two.

## The honest counterexample

The sandbox's root ext4 is simultaneously runtime image, scratch, cache, and working directory — the
exact collapse this taxonomy exists to prevent. Harmless when the whole thing is disposable per
session; **wrong for a fog node** where retention policy differs per class. It's the counterexample
that motivates the taxonomy, and it's why the direction axis + the egress chokepoint matter: they
make the collapse structurally impossible to express.
