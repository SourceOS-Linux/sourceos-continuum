# Commercial PaaS Parity Map

Generated: 2026-01-14 14:16:53Z

We compare our platform to common commercial PaaS offerings (Heroku, Render, Fly, Vercel, Cloud Run style systems).

## What they reliably provide
- golden paths (templates) that don’t require tribal knowledge
- previews (PR envs) with easy teardown
- integrated logs/metrics/traces
- domains + TLS + routing
- rollbacks and safe rollouts
- autoscaling and quotas
- managed secrets
- strong CLI + developer portal

## Where we already match conceptually
- GitOps truth (arguably stronger)
- policy gates and attestations
- previews via Porter + Argo patterns
- local-first differentiator (edge constraints)

## Where we must productize (high priority)
- Templates + service catalog layer (golden paths)
- Per-user Cloud Shell with port previews and launch links
- Default resource/security/probe conventions in every template
- Cost and quota visibility per team/user
- One-command / one-PR-label operations

## Strategy to “get up to snuff”
- Make the existing flows feel like a product:
  - fewer knobs, safer defaults
  - explicit, repeatable promotions
  - strong evidence bundles
