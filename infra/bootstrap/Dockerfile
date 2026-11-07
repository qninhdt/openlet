FROM golang:1.27.3-bookworm@sha256:d9b6a1beb9474adc2a1ce842573639b44b2a0dd49b6669f51d3821baf9ec37c9 AS build
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 go install -tags 'no_mysql no_sqlite3 no_ydb no_mssql no_clickhouse no_libsql no_vertica' github.com/pressly/goose/v3/cmd/goose@v3.29.0
WORKDIR /build/packages/go
COPY packages/go/go.mod packages/go/go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download
RUN --mount=type=bind,source=packages/go,target=/build/packages/go \
    --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 go build -trimpath -o /authz-schema ./cmd/authz-schema

FROM debian:bookworm-slim@sha256:99c0b25c46d0214d5a2091092e7908907dcaecd6a962cde0ac700acee222b6f3
COPY --from=build /go/bin/goose /usr/local/bin/goose
COPY --from=build /authz-schema /usr/local/bin/authz-schema
COPY --from=build /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
COPY packages/contracts/authz/schema.zed /contracts/schema.zed
USER 65532:65532
ENTRYPOINT ["goose"]
