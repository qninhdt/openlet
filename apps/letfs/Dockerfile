FROM rust:1.96.1-bookworm@sha256:a339861ae23e9abb272cea45dfafde21760d2ce6577a70f8a926153677902663 AS build
RUN apt-get update && apt-get install -y --no-install-recommends protobuf-compiler libprotobuf-dev && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY Cargo.toml Cargo.lock ./
COPY apps/letfs/Cargo.toml apps/letfs/Cargo.toml
# Cargo checks mtimes; source can predate the cached compiler output after a checkout.
RUN --mount=type=bind,source=apps/letfs/src,target=/build/apps/letfs/src,rw \
    --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/usr/local/cargo/git \
    --mount=type=cache,target=/build/target,sharing=locked \
    find apps/letfs/src -type f -exec touch {} + && cargo build --release --locked && cp /build/target/release/letfs /letfs

FROM debian:bookworm-slim@sha256:99c0b25c46d0214d5a2091092e7908907dcaecd6a962cde0ac700acee222b6f3
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=build /letfs /usr/local/bin/letfs
USER 65532:65532
ENTRYPOINT ["letfs"]
