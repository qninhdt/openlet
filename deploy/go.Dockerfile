FROM golang:1.27.3-bookworm@sha256:d9b6a1beb9474adc2a1ce842573639b44b2a0dd49b6669f51d3821baf9ec37c9 AS build
ARG SERVICE
WORKDIR /build/services/${SERVICE}
COPY tests/testinfra/go.mod tests/testinfra/go.sum /build/tests/testinfra/
COPY services/${SERVICE}/go.mod services/${SERVICE}/go.sum ./
RUN go mod download
COPY services/${SERVICE}/ ./
RUN CGO_ENABLED=0 go build -trimpath -o /server ./cmd/server

FROM gcr.io/distroless/static-debian13:nonroot@sha256:18f4cc26c9ffa7f20a359298be7deadac5c607c8e03a02b8119f1a5fc2f82c99
COPY --from=build /server /server
ENTRYPOINT ["/server"]
