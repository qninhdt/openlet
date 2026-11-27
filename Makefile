SHELL := /bin/bash
.DEFAULT_GOAL := check
OPENLET_CONFIG ?= $(CURDIR)/.local/openlet.yaml
OPENLET_GENERATED ?= $(CURDIR)/.local/generated
OPENLET_BACKUPS ?= $(CURDIR)/.local/backups
ENV_FILE ?= $(CURDIR)/.env
COMPOSE_PROJECT_NAME ?= openlet
DEV_PROJECT ?= dev
DEV_WORKSPACE ?= amensa-portfolio-review
DEV_MODE ?= live
GO_PACKAGES := ./apps/platform/... ./apps/letfs/... ./apps/chat/... ./packages/sdk-go/...
PYTHON_PATHS := scripts apps/leta apps/letfs-ingest packages/sdk-python/src/openlet_sdk packages/sdk-python/tests packages/env tests/e2e

.PHONY: tools generate check check-go check-python check-js format test test-go test-python integration \
        e2e e2e-fast e2e-web dev dev-web dev-rebuild dev-reset dev-down dev-logs images backup deploy

tools:
	go install google.golang.org/protobuf/cmd/protoc-gen-go@v1.36.12
	go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@v1.6.2
	go install github.com/bufbuild/buf/cmd/buf@v1.69.0

generate:
	mkdir -p .local
	cd packages/contracts && buf generate
	buf build packages/contracts --as-file-descriptor-set -o .local/contracts.pb
	uv run --no-env-file --locked python -c 'from google.protobuf.descriptor_pb2 import FileDescriptorSet; from grpc_tools.protoc import main; from pathlib import Path; files=FileDescriptorSet.FromString(Path(".local/contracts.pb").read_bytes()).file; raise SystemExit(main(["grpc_tools.protoc", "--descriptor_set_in=.local/contracts.pb", "--python_out=packages/sdk-python/src", "--pyi_out=packages/sdk-python/src", "--grpc_python_out=packages/sdk-python/src", "--mypy_grpc_out=async_only,generate_concrete_servicer_stubs:packages/sdk-python/src", *[file.name for file in files if file.name.startswith(("openlet_api/", "buf/validate/"))]]))'
	buf build packages/contracts --as-file-descriptor-set --path packages/contracts/proto/openlet_api/platform/v1/platform.proto --path packages/contracts/proto/openlet_api/letfs/v1/letfs.proto --path packages/contracts/proto/openlet_api/chat/v1/chat.proto -o packages/contracts/generated/public.pb

format:
	gofmt -w apps/platform apps/letfs apps/chat packages/sdk-go
	uv run --no-env-file --locked ruff check --select I --fix $(PYTHON_PATHS)
	uv run --no-env-file --locked ruff format $(PYTHON_PATHS)
	cd evaluations && uv run --no-env-file --locked ruff check --select I --fix src tests && uv run --no-env-file --locked ruff format src tests
	pnpm format

check: check-go check-python check-js
	buf lint packages/contracts
	bash -n scripts/*.sh

check-go:
	@files=$$(gofmt -l apps/platform apps/letfs apps/chat packages/sdk-go); if [[ -n $$files ]]; then printf '%s\n' "$$files"; exit 1; fi
	go vet $(GO_PACKAGES)

check-python:
	uv run --no-env-file --locked --all-packages --extra cpu ruff check $(PYTHON_PATHS)
	uv run --no-env-file --locked ruff format --check $(PYTHON_PATHS)
	uv run --no-env-file --locked --all-packages --extra cpu pyright
	cd evaluations && uv run --no-env-file --locked ruff check src tests && uv run --no-env-file --locked ruff format --check src tests && uv run --no-env-file --locked pyright

check-js:
	pnpm format:check
	pnpm typecheck
	pnpm lint
	pnpm --filter @openlet/web test
	pnpm build

test: test-go test-python

test-go:
	go test $(GO_PACKAGES)

test-python:
	uv run --no-env-file --locked --all-packages --extra cpu pytest apps/leta/tests apps/letfs-ingest/tests packages/sdk-python/tests packages/env/tests -q

integration:
	@test -n "$$OPENLET_TEST_DATABASE_URL" || { echo 'Set OPENLET_TEST_DATABASE_URL to an isolated, backed-up test database DSN.' >&2; exit 1; }
	go test -tags=integration ./apps/letfs/internal/storage -run TestStorageSQLInvariants -count=1

images:
	cd infra && OPENLET_CONFIG="$(CURDIR)/infra/config/openlet.example.yaml" OPENLET_GENERATED="$(CURDIR)/.local/bake-generated" \
		docker buildx bake --allow=fs.read=.. --load -f compose.yaml platform letfs chat ingest-cpu leta-api

dev:
	uv run --no-env-file --locked openlet-env up --project "$(DEV_PROJECT)" --mode "$(DEV_MODE)" --gateway-port 8080 --seed-workspace "$(DEV_WORKSPACE)" --idempotent-seed

dev-rebuild:
	uv run --no-env-file --locked openlet-env up --project "$(DEV_PROJECT)" --mode "$(DEV_MODE)" --gateway-port 8080 --build --seed-workspace "$(DEV_WORKSPACE)" --idempotent-seed

dev-reset:
	uv run --no-env-file --locked openlet-env reset --project "$(DEV_PROJECT)" --seed-workspace "$(DEV_WORKSPACE)"

dev-down:
	uv run --no-env-file --locked openlet-env down --project "$(DEV_PROJECT)"

dev-logs:
	uv run --no-env-file --locked openlet-env logs --project "$(DEV_PROJECT)" --follow

dev-web:
	VITE_DEV_AUTH=1 OPENLET_DEV_PROJECT="$(DEV_PROJECT)" pnpm --filter @openlet/web dev

e2e:
	uv run --no-env-file --locked pytest -n 4 tests/e2e

e2e-fast:
	OPENLET_E2E_KEEP=1 uv run --no-env-file --locked pytest -n 4 tests/e2e

e2e-web:
	pnpm --filter @openlet/web test:e2e

backup:
	scripts/backup.sh "$(OUTPUT)"

deploy:
	scripts/deploy.sh "$(OPENLET_CONFIG)" "$(ENV_FILE)" "$(IMAGE_LOCK)"
