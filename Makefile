SHELL := /bin/bash
.DEFAULT_GOAL := check
OPENLET_CONFIG ?= $(CURDIR)/.local/openlet.yaml
OPENLET_GENERATED ?= $(CURDIR)/.local/generated
OPENLET_BACKUPS ?= $(CURDIR)/.local/backups
ENV_FILE ?= $(CURDIR)/.env
COMPOSE_PROJECT_NAME ?= openlet
export OPENLET_CONFIG OPENLET_GENERATED OPENLET_BACKUPS COMPOSE_PROJECT_NAME
export COMPOSE_FILE := $(CURDIR)/infra/compose.yaml:$(OPENLET_GENERATED)/compose.runtime.yaml
GO_PACKAGES := ./apps/platform/... ./apps/letfs/... ./packages/sdk-go/...
PYTHON_PATHS := scripts apps/leta apps/letfs-ingest packages/sdk-python/src/openlet_sdk packages/sdk-python/tests

.PHONY: tools generate check check-go check-python check-js format test test-go test-python integration e2e configure images up down logs backup restore deploy

tools:
	go install google.golang.org/protobuf/cmd/protoc-gen-go@v1.36.12
	go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@v1.6.2
	go install github.com/bufbuild/buf/cmd/buf@v1.69.0

generate:
	mkdir -p .local
	cd packages/contracts && buf generate
	buf build packages/contracts --as-file-descriptor-set -o .local/contracts.pb
	uv run --no-env-file --locked python -c 'from google.protobuf.descriptor_pb2 import FileDescriptorSet; from grpc_tools.protoc import main; from pathlib import Path; files=FileDescriptorSet.FromString(Path(".local/contracts.pb").read_bytes()).file; raise SystemExit(main(["grpc_tools.protoc", "--descriptor_set_in=.local/contracts.pb", "--python_out=packages/sdk-python/src", "--pyi_out=packages/sdk-python/src", "--grpc_python_out=packages/sdk-python/src", "--mypy_grpc_out=async_only,generate_concrete_servicer_stubs:packages/sdk-python/src", *[file.name for file in files if file.name.startswith(("openlet_api/", "buf/validate/"))]]))'
	buf build packages/contracts --as-file-descriptor-set --path packages/contracts/proto/openlet_api/platform/v1/platform.proto --path packages/contracts/proto/openlet_api/letfs/v1/letfs.proto -o packages/contracts/generated/public.pb

format:
	gofmt -w apps/platform apps/letfs packages/sdk-go
	uv run --no-env-file --locked ruff check --select I --fix $(PYTHON_PATHS)
	uv run --no-env-file --locked ruff format $(PYTHON_PATHS)
	pnpm format

check: check-go check-python check-js
	buf lint packages/contracts
	bash -n scripts/*.sh

check-go:
	@files=$$(gofmt -l apps/platform apps/letfs packages/sdk-go); if [[ -n $$files ]]; then printf '%s\n' "$$files"; exit 1; fi
	go vet $(GO_PACKAGES)

check-python:
	uv run --no-env-file --locked --all-packages --extra cpu ruff check $(PYTHON_PATHS)
	uv run --no-env-file --locked ruff format --check $(PYTHON_PATHS)
	uv run --no-env-file --locked --all-packages --extra cpu pyright

check-js:
	pnpm format:check
	pnpm typecheck
	pnpm lint
	pnpm build

test: test-go test-python

test-go:
	go test $(GO_PACKAGES)

test-python:
	uv run --no-env-file --locked --all-packages --extra cpu pytest apps/leta/tests apps/letfs-ingest/tests packages/sdk-python/tests -q

integration:
	@test -n "$$OPENLET_TEST_DATABASE_URL" || { echo 'Set OPENLET_TEST_DATABASE_URL to an isolated, backed-up test database DSN.' >&2; exit 1; }
	go test -tags=integration ./apps/letfs/internal/storage -run TestStorageSQLInvariants -count=1

e2e:
	scripts/e2e.sh api

configure:
	mkdir -p "$(OPENLET_BACKUPS)"
	chmod 700 "$(OPENLET_BACKUPS)"
	uv run --env-file "$(ENV_FILE)" --locked python scripts/configure.py --output "$(OPENLET_GENERATED)"

images:
	docker compose build platform letfs ingest-cpu ingest-io
	@if [[ ",$$COMPOSE_PROFILES," == *,leta,* ]]; then docker compose build leta-api; fi

up: configure images
	mapfile -t writers < <(docker compose config --services | grep -E '^(envoy|platform|letfs|ingest-cpu|ingest-io|leta-api|leta-worker|temporal|spicedb)$$'); docker compose stop "$${writers[@]}"
	docker compose up --detach --wait --wait-timeout 180

down:
	docker compose down

logs:
	docker compose logs --follow --tail 100

backup:
	scripts/backup.sh "$(OUTPUT)"

restore:
	scripts/restore.sh "$(INPUT)"

deploy:
	scripts/deploy.sh "$(OPENLET_CONFIG)" "$(ENV_FILE)" "$(IMAGE_LOCK)"
