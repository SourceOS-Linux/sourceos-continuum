# SourceOS Continuum — lifecycle entry points.
# Control-plane targets delegate to Makefile.porter (the rehomed Porter control plane).
.PHONY: validate onboard dev-up dev-down shim-test test tools-test rollout promotion-gate portal compute

validate: ## repo hygiene + CapD validity
	python3 tools/validate.py

tools-test: ## unit-test the governed tools (portal router, compute plane, promotion gate, MCP surface)
	cd tools && python3 -m pytest -q

portal: ## developer portal: read-only web console over the governed surface (scale-to-zero, stdlib only)
	python3 tools/portal_server.py $(PORT)

compute: ## compute plane: route one workload across the mesh under per-project policy + availability
	python3 tools/compute_plane.py

onboard: ## bring up a workstation: local sovereign forge + local cluster + sourceosctl
	@echo "[continuum] onboard — scaffold: wires Gitea bring-up + kind/k3s + sourceos-devtools/sourceosctl"

dev-up: ## start the local PaaS control plane (porter-shim over kind/k3s)
	$(MAKE) -f Makefile.porter dev-up

dev-down: ## tear down the local PaaS control plane
	$(MAKE) -f Makefile.porter dev-down

shim-test: ## test the porter-shim control plane
	$(MAKE) -f Makefile.porter shim-test

test: ## cloud-native test: ephemeral preview env + GitOps PR checks + evidence bundle
	@echo "[continuum] test — scaffold: PR-driven preview environments + evidence"

promotion-gate: ## rollout gate: require an APPROVE review verdict (fail-closed, evidence-emitting)
	@test -n "$(VERDICT)" || (echo "[continuum] promotion-gate BLOCKED: set VERDICT=<review-receipt.json>" && exit 1)
	python3 tools/promotion_gate.py --verdict $(VERDICT)

rollout: promotion-gate ## promote local → scale-up cluster (hyperswarm), gated on an APPROVE review verdict
	@echo "[continuum] rollout — promote via caps.infra.cluster-scaleup.hyperswarm (promotion gate passed)"
