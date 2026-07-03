# Agent Operating Instructions

Work issue-first.

Rules:
- One repo, one issue, one PR.
- Inspect the live repository before editing.
- Keep scope bounded to the issue body.
- Do not broaden scope without asking in the issue.
- Do not touch unrelated files.
- Do not claim production readiness unless acceptance criteria prove it.
- Include validation evidence (`make validate`) in the PR body.
- Leave known gaps explicit.

Boundary:
- This repo owns local PaaS deploy/runtime orchestration only.
- Source, workspace binding, runtime release, and scale-up primitives are CONSUMED from their
  canonical owners (see `docs/CONTINUUM_SCOPE.md`) — never reimplemented here.
