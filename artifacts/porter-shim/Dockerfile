FROM golang:1.22-bookworm AS build
WORKDIR /src
ARG TARGETOS
ARG TARGETARCH
COPY artifacts/porter-shim/go.mod ./go.mod
COPY artifacts/porter-shim/go.sum ./go.sum
RUN --mount=type=cache,target=/go/pkg/mod go mod download
COPY artifacts/porter-shim/ .
RUN --mount=type=cache,target=/go/pkg/mod CGO_ENABLED=0 GOOS=${TARGETOS} GOARCH=${TARGETARCH} go build -o /out/shim ./cmd/shim

FROM gcr.io/distroless/static:nonroot
COPY --from=build /out/shim /shim
USER 65532:65532
ENTRYPOINT ["/shim"]
