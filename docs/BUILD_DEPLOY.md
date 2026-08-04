# Vercel / Heroku, aligned — git-push deploy, sovereign

Vercel and Heroku are the same move (you called it): **detect the app from source, build it into a
runnable image without a Dockerfile, deploy it, and give a preview environment per branch.** That
ergonomic is the gold standard for local→cloud-native developer flow. Here is how it maps onto the
continuum stack — and the one missing piece we just added.

## The mapping

| Vercel / Heroku | Continuum equivalent | Status |
|---|---|---|
| `git push` → it deploys | lifecycle onboard→develop→test→rollout + a push trigger | ◑ (trigger next) |
| **buildpack auto-detect, no Dockerfile** | **`buildpack.py`** — Cloud Native Buildpacks / Paketo `pack build`; detect→build→OCI image | ✅ (this change) |
| slug / build artifact | a reproducible OCI image = a **data sphere** (immutable, provenance, SBOM/SLSA-attestable) | ✅ |
| Procfile / process types (web, worker) | `process_types` on the build → workload `kind` (service=Deployment, worker=Job) | ✅ |
| dyno / serverless runtime | the **executor** adapters (k8s/slurm/wasm/…), scale-to-zero | ✅ |
| **preview deployment per branch** (unique URL) | **Signadot-style sandbox** (`devspace.sandbox_manifests`, header-routed) or a per-user DevSpace | ✅ |
| instant rollback | immutable digest-pinned images + GitOps revision | ✅ |
| pipelines (dev→staging→prod) | the **fail-closed promotion gate** (APPROVE verdict) | ✅ |
| add-ons (Postgres/Redis) | backing services as **data spheres** / a service-broker surface | ◑ |
| account tiers (Free/Pro) | **admission tiers** (entitlement + backend allowlist) | ✅ |

## Why this is the sovereign version, not a re-host

The whole value of Vercel/Heroku is the *build-and-preview ergonomic*, and the whole risk is that
it's a proprietary black box that owns your build, your runtime, and your data. Cloud Native
Buildpacks (buildpacks.io / Paketo — the CNCF standard Heroku itself moved to) gives us the **exact
same ergonomic, open**: `pack build` turns source into a reproducible, SBOM'd OCI image with **no
Docker daemon and no hand-written Dockerfile**, and it runs anywhere. So we get "git push, it
deploys" without surrendering the build (it's reproducible + attestable), the runtime (our executor,
our mesh — including sovereign GPU inference), or the data (data spheres, residency-fenced).

And two things we already had that Vercel/Heroku charge for or don't govern:
- **preview environments** are just our Signadot-style sandboxes / DevSpaces — governed, tenancy-
  labelled, quota-bounded, and free.
- the **pipeline** is our fail-closed promotion gate — a preview is promoted to prod only on a sealed
  APPROVE verdict, not a dashboard toggle.

## The flow (`buildpack.py`)

```
git push  ──>  detect(source)  ──>  pack build (Paketo)  ──>  reproducible OCI image  (a data sphere)
          ──>  deploy_workload()  ──>  executor dispatch into a DevSpace
          ──>  sandbox = the per-branch PREVIEW  (header-routed, shares the baseline)
          ──>  promotion gate  ──>  prod
```

`build_plan()` is content-addressed (same source → same image → reproducible), fail-closed (no
buildpack match → refuse, don't guess), and its image flows straight into the executor's k8s manifest
(verified in tests).

## The push trigger (`push_webhook.py`)

The last piece — what actually *calls* `on_push` when a real push lands — is a governed webhook
receiver the git host (Gitea/GitHub) POSTs to. It is **fail-closed at the door**:

```
POST /hooks/<tenant>/<app>
  ──>  verify HMAC-SHA256 over the RAW body (constant-time)      ← unsigned/forged ⇒ REJECTED, no build
  ──>  parse the push event (branch? tag? delete?)               ← tags & deletes ⇒ ignored
  ──>  resolve the source tree at the pushed SHA (checkout)
  ──>  deploy_flow.on_push()  ──>  build ──> preview
  ──>  a SEALED receipt, bound to the exact body digest          ← the secret is never echoed
```

Every git host signs deliveries (GitHub `X-Hub-Signature-256: sha256=…`, Gitea `X-Gitea-Signature: …`);
we verify against the project's per-tenant secret **before any work starts**. A push that isn't
validly signed is rejected with a sealed receipt and **no build is ever started** — the same
fail-closed posture as the rest of the stack. So `git push` now literally deploys: the Vercel/Heroku
ergonomic, sovereign and governed, with the trigger itself a zero-trust gate rather than an open hook.

## Instant rollback (`release_ledger.py`)

The other half of the Vercel/Heroku ergonomic is **instant rollback** — and it is almost free here,
because of a property the stack already guarantees: **every deploy is a content-addressed, immutable
image** (a data sphere). So a *release* is a sealed record binding `(tenant, app, branch,
image_digest, workload)`, a successful push records one, and rolling back is just re-pointing to a
**prior release's already-built digest**:

```
rollback(app)  ──>  find a PRIOR release that ran         ← target never ran here ⇒ BLOCKED, nothing served
               ──>  re-point to its immutable image_digest ← NO REBUILD (instant), reproducible bits
               ──>  record a new head release (kind=rollback, links from→to)   ← itself auditable
               ──>  a SEALED decision
```

Two things this buys that a plain PaaS rollback doesn't:

- **Reproducible, not "rebuild-and-hope."** The digest *is* the guarantee — you get back exactly the
  bytes that ran, not a fresh build of an old ref.
- **Fail-closed.** You can only roll back to a release that actually ran here; an image that was never
  built and deployed is never served. Rolling *forward* to a new version still goes through the
  promotion gate — rollback to a known-prior-good release is the fast, sealed, audited escape hatch.

`make rollback ARGS="rollback <tenant> <app>"` (or `--to-digest <D>` / `--steps N`); `history` and
`current` read the ledger. That completes the deploy ergonomic: **push → preview → promote → rollback**,
every step governed, sealed, and sovereign.
