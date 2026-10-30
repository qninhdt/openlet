SHELL := /bin/bash
GO ?= go
GOFMT ?= $(shell $(GO) env GOROOT)/bin/gofmt
COMPOSE := docker compose -f deploy/compose.yaml
PLAN := plans/261029-1220-openlet-backend-mvp

.PHONY: configure up down migrate fmt fmt-check test-unit test-integration test-workflow test-e2e verify
configure:
	python3 scripts/configure.py

up: configure
	$(COMPOSE) up -d --wait postgres
	$(MAKE) migrate
	$(COMPOSE) up -d --build --wait

down:
	$(COMPOSE) down

migrate:
	@for service in user workspace letfs; do $(COMPOSE) exec -T postgres sh /migrate.sh $$service || exit $$?; done

fmt:
	"$(GOFMT)" -w services/user services/workspace tests/e2e tests/testinfra
	cargo fmt --manifest-path services/letfs/Cargo.toml
	uv run --project services/letfs/processor --locked ruff format services/letfs/processor

fmt-check:
	@files=$$("$(GOFMT)" -l services/user services/workspace tests/e2e tests/testinfra) || exit $$?; \
	if [ -n "$$files" ]; then printf '%s\n' "$$files"; exit 1; fi
	cargo fmt --manifest-path services/letfs/Cargo.toml -- --check
	uv run --project services/letfs/processor --locked ruff format --check services/letfs/processor

test-unit:
	@case "$(SERVICE)" in ''|all|user|workspace|letfs|processor) ;; *) echo 'SERVICE must be user, workspace, letfs, processor or all' >&2; exit 2 ;; esac
	@if [ -z "$(SERVICE)" ] || [ "$(SERVICE)" = all ] || [ "$(SERVICE)" = user ]; then $(GO) test ./services/user/... || exit $$?; fi
	@if [ -z "$(SERVICE)" ] || [ "$(SERVICE)" = all ] || [ "$(SERVICE)" = workspace ]; then $(GO) test ./services/workspace/... || exit $$?; fi
	@if [ -z "$(SERVICE)" ] || [ "$(SERVICE)" = all ] || [ "$(SERVICE)" = letfs ]; then cargo test --manifest-path services/letfs/Cargo.toml --locked --lib || exit $$?; fi
	@if [ -z "$(SERVICE)" ] || [ "$(SERVICE)" = all ] || [ "$(SERVICE)" = processor ]; then uv run --project services/letfs/processor --locked pytest services/letfs/processor/tests -m 'not parser' || exit $$?; fi

test-integration:
	GO="$(GO)" bash scripts/test-integration.sh "$(SERVICE)" "$(TEST)"

test-e2e:
	bash scripts/verify-foundation.sh "$(TEST)"

test-workflow:
	GO="$(GO)" bash scripts/test-workflow.sh "$(TEST)"

verify: fmt-check test-unit
	$(GO) vet -tags integration ./services/user/... ./services/workspace/... ./tests/testinfra/...
	cargo clippy --manifest-path services/letfs/Cargo.toml --locked --all-targets -- -D warnings
	uv run --project services/letfs/processor --locked ruff check services/letfs/processor
	python3 scripts/configure-test.py
	python3 scripts/verify-contracts.py
	@for script in scripts/*.sh deploy/postgres/*.sh deploy/temporal/*.sh; do bash -n "$$script" || exit $$?; done

.PHONY: test-recovery backup-restore-drill test-clerk test-provider

test-recovery:
	bash scripts/verify-foundation.sh "$(if $(TEST),$(TEST),worker-restarts)"

backup-restore-drill:
	bash scripts/backup-restore-drill.sh

test-clerk:
	python3 scripts/test-clerk.py

test-provider:
	@test -s .local/secrets/s3_access_key_id && test -n "$(S3_ENDPOINT)" || { echo 'NOT RUN: configure the selected external S3 provider first' >&2; exit 2; }
	$(COMPOSE) run --rm --no-deps letfs --provider-smoke
