FROM debian:12-slim

ARG DEBIAN_FRONTEND=noninteractive
ARG TARGETOS
ARG TARGETARCH

ARG KUBECTL_VERSION=v1.30.3
ARG HELM_VERSION=v3.15.3
ARG YQ_VERSION=v4.44.3
ARG JQ_VERSION=1.7.1
ARG TTYD_VERSION=1.7.7

RUN apt-get update && apt-get install -y --no-install-recommends     ca-certificates curl git bash openssh-client tini   && rm -rf /var/lib/apt/lists/*

# ttyd binaries are named ttyd.x86_64 (amd64) and ttyd.aarch64 (arm64)
RUN set -eux;     case "${TARGETARCH}" in       amd64) TTYD_TARGET="x86_64" ;;       arm64) TTYD_TARGET="aarch64" ;;       *) echo "unsupported TARGETARCH=${TARGETARCH}" >&2; exit 1 ;;     esac;     curl -fsSL -o /usr/local/bin/ttyd       "https://github.com/tsl0922/ttyd/releases/download/${TTYD_VERSION}/ttyd.${TTYD_TARGET}";     chmod +x /usr/local/bin/ttyd

# kubectl
RUN curl -fsSL -o /usr/local/bin/kubectl       "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${TARGETARCH}/kubectl"  && chmod +x /usr/local/bin/kubectl

# helm
RUN curl -fsSL -o /tmp/helm.tgz       "https://get.helm.sh/helm-${HELM_VERSION}-linux-${TARGETARCH}.tar.gz"  && tar -C /tmp -xzf /tmp/helm.tgz  && mv "/tmp/linux-${TARGETARCH}/helm" /usr/local/bin/helm  && rm -rf /tmp/helm.tgz "/tmp/linux-${TARGETARCH}"

# yq (Go arch naming aligns with TARGETARCH for amd64/arm64)
RUN curl -fsSL -o /usr/local/bin/yq       "https://github.com/mikefarah/yq/releases/download/${YQ_VERSION}/yq_linux_${TARGETARCH}"  && chmod +x /usr/local/bin/yq

# jq
RUN curl -fsSL -o /usr/local/bin/jq       "https://github.com/jqlang/jq/releases/download/jq-${JQ_VERSION}/jq-linux-${TARGETARCH}"  && chmod +x /usr/local/bin/jq

RUN useradd -m -u 1000 -s /bin/bash cloud || true
ENV HOME=/home/cloud
WORKDIR /home/cloud

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 7681
ENTRYPOINT ["/usr/bin/tini","--","/entrypoint.sh"]
