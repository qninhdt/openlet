FROM golang:1.27.3-trixie@sha256:af1bfc2614ebb1dbd31af514b78740fd678850e76498762b425ecee4c5c6ea80 AS build
WORKDIR /build/apps/letfs
COPY apps/letfs/go.mod apps/letfs/go.sum ./
COPY packages/go/go.mod packages/go/go.sum /build/packages/go/
RUN --mount=type=cache,target=/go/pkg/mod go mod download
RUN --mount=type=bind,source=apps/letfs/cmd,target=./cmd \
    --mount=type=bind,source=apps/letfs/internal,target=./internal \
    --mount=type=bind,source=packages/go,target=/build/packages/go \
    --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 go build -trimpath -o /server ./cmd/server

FROM gcr.io/distroless/static-debian13:nonroot@sha256:25ac8f0c3b2334a9eb05452266bd4697864a8c8ef0ef71e5e6480d7f92868329
COPY --from=build /server /server
COPY packages/contracts/authz/schema.zed /contracts/
ENTRYPOINT ["/server"]
