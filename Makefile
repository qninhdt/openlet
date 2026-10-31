SHELL := /bin/bash
COMPOSE := docker compose -f infra/compose/dev.yaml

.PHONY: configure up down build check test-unit test-integration test-workflow test-replay test-e2e test-provider
configure:
	python3 scripts/bootstrap/configure.py

up: configure
	$(COMPOSE) up -d --build --wait

down:
	$(COMPOSE) down

build:
	pnpm exec turbo run build

check:
	pnpm check

test-unit:
	pnpm exec turbo run test

test-integration:
	pnpm exec turbo run test:integration --concurrency=1

test-workflow:
	pnpm exec turbo run test:workflow

test-replay:
	pnpm exec turbo run test:replay

test-e2e:
	pnpm --dir e2e exec playwright test --project=api

test-provider:
	$(COMPOSE) run --rm --no-deps letfs --provider-smoke
