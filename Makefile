# SourceOS Continuum — lifecycle entry points.
# Control-plane targets delegate to Makefile.porter (the rehomed Porter control plane).
.PHONY: validate onboard dev-up dev-down shim-test test rollout

validate: ## repo hygiene + CapD validity
	python3 tools/validate.py

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

rollout: ## promote local → scale-up cluster (hyperswarm), signed images
	@echo "[continuum] rollout — scaffold: promote via caps.infra.cluster-scaleup.hyperswarm"
