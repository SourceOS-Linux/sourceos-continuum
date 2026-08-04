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
(verified in tests). The only remaining piece is the **push trigger** (a webhook that runs this on a
`git push` and opens the preview) — the ergonomic wrapper over machinery that's now all here.
