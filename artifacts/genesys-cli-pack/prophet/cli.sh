#!/usr/bin/env bash
# prophet — CapD-driven agentic GitOps CLI. Thin client over the porter-shim.
set -euo pipefail
API="${PROPHET_API:-http://localhost:8081}"

usage() {
  cat <<EOF
prophet — CapD-driven agentic GitOps CLI  (API: $API)

  prophet release publish --service <svc> --env <env> --digest <repo@sha256:...> [--chart-version <v>]
  prophet cloudshell launch [--repo <url>] [--ref <ref>] [--cmd <cmd>] [--size s|m|l]
  prophet compose convert --repo <url> --compose-path <path>
  prophet health

Env: PROPHET_API (default http://localhost:8081)
EOF
}

# Collect --flags into a JSON object (kebab flags → snake_case keys).
build_json() {
  local json="{" first=1 key val
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --*)
        key="${1#--}"; key="${key//-/_}"; shift
        val="${1:-}"; shift || true
        [[ $first -eq 0 ]] && json+=","
        json+="\"$key\":\"$val\""; first=0 ;;
      *) shift ;;
    esac
  done
  json+="}"; printf '%s' "$json"
}

post() { curl -fsS -X POST "$API$1" -H 'content-type: application/json' -d "$2"; echo; }

[[ $# -lt 1 ]] && { usage; exit 1; }
group="$1"; shift || true

case "$group" in
  release)
    [[ "${1:-}" == "publish" ]] || { usage; exit 1; }; shift
    # normalize --digest → image_digest
    body="$(build_json "$@")"; body="${body//\"digest\":/\"image_digest\":}"
    post "/release/publish" "$body" ;;
  cloudshell)
    [[ "${1:-}" == "launch" ]] || { usage; exit 1; }; shift
    post "/cloudshell/launch" "$(build_json "$@")" ;;
  compose)
    [[ "${1:-}" == "convert" ]] || { usage; exit 1; }; shift
    post "/compose/kompose/convert" "$(build_json "$@")" ;;
  health)
    curl -fsS "$API/healthz"; echo ;;
  *) usage; exit 1 ;;
esac
