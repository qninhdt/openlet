FROM golang:1.27.3-bookworm@sha256:d9b6a1beb9474adc2a1ce842573639b44b2a0dd49b6669f51d3821baf9ec37c9 AS build
WORKDIR /build/apps/workspace
COPY apps/workspace/go.mod apps/workspace/go.sum ./
COPY packages/go/go.mod packages/go/go.sum /build/packages/go/
RUN --mount=type=cache,target=/go/pkg/mod go mod download
RUN --mount=type=bind,source=apps/workspace/cmd,target=./cmd \
    --mount=type=bind,source=apps/workspace/internal,target=./internal \
    --mount=type=bind,source=packages/go,target=/build/packages/go \
    --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 go build -trimpath -o /server ./cmd/server

FROM gcr.io/distroless/static-debian13:nonroot@sha256:18f4cc26c9ffa7f20a359298be7deadac5c607c8e03a02b8119f1a5fc2f82c99
COPY --from=build /server /server
COPY packages/contracts/authz/schema.zed /contracts/
ENTRYPOINT ["/server"]
