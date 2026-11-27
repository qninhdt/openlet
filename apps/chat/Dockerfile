FROM golang:1.27.4@sha256:08bcb99a38f85a265f9a93d1d3323e2440eec333380f3ea26ee0dec9264bb41c AS build
ARG TARGETARCH
WORKDIR /src
RUN set -eux; \
    case "${TARGETARCH}" in \
      amd64) GOOSE_ARCH=x86_64; GOOSE_SHA=ad487c23744ae5de5dbdf5a81d4e6fac05fdfbe74f02379f9e498cf2070a9ef8; PROBE_ARCH=amd64; PROBE_SHA=d7321a60cfb40f0e8786a6d9f74fbc716dc6bcd078d3312f8fb34caf2d92acdc ;; \
      arm64) GOOSE_ARCH=arm64;  GOOSE_SHA=55f65caa1ee94d4b66f1bdf7091df3bdf72578cf8d44a817b2d6cd6f96af8b02; PROBE_ARCH=arm64; PROBE_SHA=ddcaf12db09abde6bfab156fb862ae2a558f23dee3ee64d557077d891003ddfa ;; \
      *) echo "unsupported arch: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    mkdir -p /tools; \
    curl -fsSL "https://github.com/pressly/goose/releases/download/v3.27.0/goose_linux_${GOOSE_ARCH}" -o /tools/goose; \
    echo "${GOOSE_SHA}  /tools/goose" | sha256sum -c -; \
    curl -fsSL "https://github.com/grpc-ecosystem/grpc-health-probe/releases/download/v0.4.62/grpc_health_probe-linux-${PROBE_ARCH}" -o /tools/grpc-health-probe; \
    echo "${PROBE_SHA}  /tools/grpc-health-probe" | sha256sum -c -; \
    chmod 0755 /tools/goose /tools/grpc-health-probe
COPY go.work go.work.sum ./
COPY apps/chat/go.* apps/chat/
COPY apps/platform/go.* apps/platform/
COPY apps/letfs/go.* apps/letfs/
COPY packages/sdk-go/go.* packages/sdk-go/
RUN --mount=type=cache,target=/go/pkg/mod go mod download -C apps/chat
COPY packages/sdk-go packages/sdk-go
COPY apps/chat apps/chat
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/chat ./apps/chat/cmd/chat

FROM gcr.io/distroless/static-debian13:nonroot@sha256:25ac8f0c3b2334a9eb05452266bd4697864a8c8ef0ef71e5e6480d7f92868329
COPY --from=build /tools/ /usr/local/bin/
COPY --from=build /out/chat /usr/local/bin/chat
COPY apps/chat/migrations /migrations
ENTRYPOINT ["/usr/local/bin/chat"]
