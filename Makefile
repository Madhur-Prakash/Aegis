#  Aegis - programmable escrow for agentic commerce
#
#  Every target here is real: nothing prints a number it did not measure, and
#  nothing succeeds by skipping work.  `make help` is generated from the `##`
#  comments below, so a target without documentation does not appear and a
#  documented target cannot silently disappear.
#
#  The dependency chain that matters:
#      make up        -> containers, migrations, healthchecks
#      make seed      -> idempotent, resumable demo data
#      make demo      -> drives the seeded deal through the whole narrative
#      make eval      -> regenerates every metric the README quotes
#
#  Quick start from a clean clone:  make bootstrap && make up && make seed && make demo

SHELL := /bin/sh
.DEFAULT_GOAL := help

BACKEND      := backend
FRONTEND     := frontend
CONTRACTS    := contracts
COMPOSE      := docker compose
UV           := uv
UV_RUN       := $(UV) run --project $(BACKEND)
NPM          := npm --prefix $(FRONTEND)
FORGE        := forge

.PHONY: help bootstrap up up-build down destroy logs ps \
        migrate seed demo demo-reset eval eval-demo dataset \
        lint fmt typecheck test test-unit test-integration import-lint secret-scan \
        contracts-build contracts-test deploy-contract contracts-deploy \
        frontend-install frontend-lint frontend-typecheck frontend-build frontend-check \
        verify-ledger verify-chain verify-login \n        check ci verify-all docs open shell-api psql redis-cli kafka-topics

# ── Help ────────────────────────────────────────────────────────────────────
help: ## Show this help
	@printf '\nAegis - make targets\n\n'
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z0-9_-]+:.*?## / {printf "  \033[1m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@printf '\n'

# ── Environment ─────────────────────────────────────────────────────────────
bootstrap: ## Install backend, frontend and contract dependencies
	@test -f .env || (cp .env.example .env && echo "created .env from .env.example")
	$(UV) sync --project $(BACKEND) --all-extras
	$(NPM) ci
	cd $(CONTRACTS) && $(FORGE) install --no-git || true
	@echo "bootstrap done - next: make up"

# ── Containers ──────────────────────────────────────────────────────────────
up: ## Start every service and wait for it to be healthy
	$(COMPOSE) up -d --wait
	@echo "api      http://localhost:8000/docs"
	@echo "app      http://localhost:3000"
	@echo "mail     http://localhost:8025"
	@echo "kafka-ui http://localhost:8080"

up-build: ## Rebuild both images, then start everything
	$(COMPOSE) up -d --build --wait

down: ## Stop every service, keep the volumes
	$(COMPOSE) down

destroy: ## Stop every service and delete the volumes (irreversible)
	$(COMPOSE) down -v

ps: ## Show container status
	$(COMPOSE) ps

logs: ## Follow the logs of every service
	$(COMPOSE) logs -f --tail=120

# ── Database and data ───────────────────────────────────────────────────────
migrate: ## Apply migrations (advisory-locked; safe to run twice)
	$(COMPOSE) run --rm migrate

# Invoked as a module rather than through the entrypoint: an argument beginning
# with `/` is rewritten into a Windows path by MSYS-based shells.
seed: ## Seed demo data (idempotent and resumable)
	$(COMPOSE) run --rm backend python -m scripts.seed

dataset: ## Regenerate the deterministic synthetic corpus (seed 42)
	cd $(BACKEND) && $(UV) run python -m scripts.generate_dataset --seed 42

demo: ## Drive the seeded deal through the whole narrative
	cd $(BACKEND) && $(UV) run python -m scripts.demo

demo-reset: ## Reset the demo deal and drive it again
	cd $(BACKEND) && $(UV) run python -m scripts.demo --reset

# ── Evaluation ──────────────────────────────────────────────────────────────
# The suites TRUNCATE every table to run against a known-empty database, so the
# demo data goes with it -- `make seed` afterwards, or use `make eval-demo`.
eval: ## Run every suite and regenerate every number in the README (truncates the DB)
	-$(COMPOSE) stop worker relay
	cd $(BACKEND) && $(UV) run python -m evals.run_all
	@echo
	@echo "results: backend/evals/out/RESULTS.md"
	@echo 'note: the suites truncated the database -- run make seed before make demo'

eval-demo: eval up seed demo ## Evaluate, then restore the stack and re-run the demo

# ── Quality gates ───────────────────────────────────────────────────────────
lint: ## Lint the backend
	cd $(BACKEND) && $(UV) run ruff check .
	cd $(BACKEND) && $(UV) run ruff format --check .

fmt: ## Format the backend
	cd $(BACKEND) && $(UV) run ruff format .
	cd $(BACKEND) && $(UV) run ruff check --fix .

typecheck: ## Type-check the backend
	cd $(BACKEND) && $(UV) run mypy app

# The suite shares the compose Postgres and drives the consumers in-process, so
# a live `worker`/`relay` would race it.  They are stopped first; `make up`
# brings them back.  CI provisions its own Postgres with no worker at all.
test: ## Run the whole backend test suite (stops worker and relay first)
	-$(COMPOSE) stop worker relay
	cd $(BACKEND) && $(UV) run pytest -q

test-unit: ## Run the unit tests only
	cd $(BACKEND) && $(UV) run pytest -q -m "not integration"

test-integration: ## Run the integration tests only
	cd $(BACKEND) && $(UV) run pytest -q -m integration

import-lint: ## Prove the settlement engine is unreachable from the agents (I2)
	cd $(BACKEND) && $(UV) run python -m scripts.import_lint

secret-scan: ## Fail if a credential-shaped literal is committed
	cd $(BACKEND) && $(UV) run python -m scripts.secret_scan

# ── Contracts ───────────────────────────────────────────────────────────────
contracts-build: ## Compile the Solidity contracts
	cd $(CONTRACTS) && $(FORGE) build

contracts-test: ## Run the Foundry tests
	cd $(CONTRACTS) && $(FORGE) test -vv

deploy-contract: ## Deploy to Base Sepolia (requires OPERATOR_PRIVATE_KEY)
	cd $(CONTRACTS) && $(FORGE) script script/Deploy.s.sol \
		--rpc-url $${BLOCKCHAIN_RPC_URL:-https://sepolia.base.org} \
		--broadcast --slow

# `evals/suite_c` prints this name in its own output, so both spellings work.
contracts-deploy: deploy-contract ## Alias for deploy-contract

# ── Frontend ────────────────────────────────────────────────────────────────
frontend-install: ## Install frontend dependencies from the lockfile
	$(NPM) ci

frontend-lint: ## Lint the frontend
	$(NPM) run lint

frontend-typecheck: ## Type-check the frontend
	$(NPM) run typecheck

frontend-check: ## Token discipline and dictionary completeness
	$(NPM) run check:tokens
	$(NPM) run check:i18n

frontend-build: ## Build the frontend for production
	$(NPM) run build

# ── Aggregates ──────────────────────────────────────────────────────────────
check: lint typecheck import-lint secret-scan frontend-lint frontend-typecheck frontend-check ## Every static gate

# What .github/workflows/ci.yml actually runs: the static gates plus the eval.
ci: check frontend-build eval ## Exactly what GitHub CI runs

# The full gate.  `pytest`, `forge test` and the image build are deliberately
# NOT in CI (too slow for a push), so this is where they get run.
verify-all: ci test contracts-test up-build ## Everything, including what CI skips

docs: ## Regenerate the OpenAPI document
	cd $(BACKEND) && $(UV) run python -m scripts.export_openapi

# ── Verification helpers (spec 37) ──────────────────────────────────────────
# Both hit the live API, so they verify the running system rather than a copy
# of its logic.  DEAL defaults to the seeded demo deal.
DEAL ?= $(shell $(COMPOSE) exec -T postgres psql -U aegis -d aegis -t -A -c "select id from deals where reference='D-4812'" | tr -d '\r')

verify-login: ## Mint a cookie jar for verify-ledger / verify-chain (DEMO_MODE only)
	@curl -fsS -c $(BACKEND)/.verify-cookies \
		-X POST http://localhost:8000/api/v1/dev/assume \
		-H 'content-type: application/json' -d '{"role":"buyer"}' >/dev/null
	@echo "cookie jar written to backend/.verify-cookies"

verify-ledger: ## Re-link and replay a deal's hash-chained ledger (DEAL=<uuid>)
	@curl -fsS -b $(BACKEND)/.verify-cookies \
		"http://localhost:8000/api/v1/ledger/deals/$(DEAL)/verify"

verify-chain: ## Compare every on-chain anchor with its local attestation hash (DEAL=<uuid>)
	@curl -fsS -b $(BACKEND)/.verify-cookies \
		"http://localhost:8000/api/v1/provenance/deals/$(DEAL)/chain"

# ── Conveniences ────────────────────────────────────────────────────────────
open: ## Open the app in a browser
	@python -c "import webbrowser; webbrowser.open('http://localhost:3000')"

shell-api: ## Shell into the running API container
	$(COMPOSE) exec backend sh

psql: ## Open psql against the running database
	$(COMPOSE) exec postgres psql -U aegis -d aegis

redis-cli: ## Open redis-cli against the running cache
	$(COMPOSE) exec redis redis-cli

kafka-topics: ## List the Kafka topics
	$(COMPOSE) exec kafka kafka-topics.sh --bootstrap-server localhost:9092 --list
