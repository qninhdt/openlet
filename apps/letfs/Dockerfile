FROM golang:1.27.4@sha256:08bcb99a38f85a265f9a93d1d3323e2440eec333380f3ea26ee0dec9264bb41c AS build
WORKDIR /src
COPY go.work go.work.sum ./
COPY apps/platform/go.* apps/platform/
COPY apps/letfs/go.* apps/letfs/
COPY packages/sdk-go/go.* packages/sdk-go/
RUN --mount=type=cache,target=/go/pkg/mod go mod download -C apps/letfs
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    GOBIN=/tools CGO_ENABLED=0 go install github.com/grpc-ecosystem/grpc-health-probe@v0.4.62 && \
    GOBIN=/tools CGO_ENABLED=0 go install -tags='no_clickhouse no_mysql no_mssql no_sqlite3 no_vertica no_ydb no_libsql' github.com/pressly/goose/v3/cmd/goose@v3.27.0
COPY packages/sdk-go packages/sdk-go
COPY apps/letfs apps/letfs
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 go build -trimpath -o /out/letfs ./apps/letfs/cmd/letfs

FROM gcr.io/distroless/static-debian13:nonroot@sha256:25ac8f0c3b2334a9eb05452266bd4697864a8c8ef0ef71e5e6480d7f92868329
COPY --from=build /tools/ /usr/local/bin/
COPY --from=build /out/letfs /usr/local/bin/letfs
COPY apps/letfs/migrations /migrations
ENTRYPOINT ["/usr/local/bin/letfs"]
