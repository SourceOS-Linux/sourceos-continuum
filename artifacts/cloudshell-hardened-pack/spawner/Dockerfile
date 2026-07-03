FROM golang:1.22-bookworm AS build
WORKDIR /src
ARG TARGETOS
ARG TARGETARCH
COPY artifacts/cloudshell-hardened-pack/spawner/go.mod ./go.mod
COPY artifacts/cloudshell-hardened-pack/spawner/go.sum ./go.sum
RUN --mount=type=cache,target=/go/pkg/mod go mod download
COPY artifacts/cloudshell-hardened-pack/spawner/ .
RUN --mount=type=cache,target=/go/pkg/mod CGO_ENABLED=0 GOOS=${TARGETOS} GOARCH=${TARGETARCH} go build -o /out/spawner ./cmd/spawner

FROM gcr.io/distroless/static:nonroot
COPY --from=build /out/spawner /spawner
USER 65532:65532
ENTRYPOINT ["/spawner"]
