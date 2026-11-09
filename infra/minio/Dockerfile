FROM golang:1.27.3-trixie@sha256:af1bfc2614ebb1dbd31af514b78740fd678850e76498762b425ecee4c5c6ea80 AS build
ENV CGO_ENABLED=0 GOBIN=/out GOMAXPROCS=2
RUN go install -p 2 -trimpath \
    -ldflags '-s -w -X github.com/minio/minio/cmd.Version=2025-10-15T17:29:55Z -X github.com/minio/minio/cmd.ReleaseTag=RELEASE.2025-10-15T17-29-55Z -X github.com/minio/minio/cmd.CommitID=9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a' \
    github.com/minio/minio@v0.0.0-20251015172955-9e49d5e7a648

FROM debian:trixie-slim@sha256:a72b4433de1cf7d6bae0c4cee74d0547f58601a643b3375f070c51600d63b6b2
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir /data && chown 65532:65532 /data
COPY --from=build /out/minio /usr/local/bin/minio
COPY --from=build /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
ENV HOME=/tmp MINIO_UPDATE=off MINIO_BROWSER=off
USER 65532:65532
EXPOSE 9000
ENTRYPOINT ["minio"]
CMD ["server", "/data", "--address", ":9000"]
