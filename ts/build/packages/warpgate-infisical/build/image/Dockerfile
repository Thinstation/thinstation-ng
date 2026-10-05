FROM rust:1.97.1-bookworm AS build
ARG WARPGATE_VERSION=0.29.1
ENV DEBIAN_FRONTEND=noninteractive SOURCE_DATE_EPOCH=0
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN curl -fsSL https://deb.nodesource.com/setup_24.x | bash - \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates-java nodejs default-jre-headless git \
    && rm -rf /var/lib/apt/lists/* \
    && cargo install --locked just@1.4.0
RUN git clone --depth 1 --branch "v${WARPGATE_VERSION}" https://github.com/warp-tech/warpgate.git /opt/warpgate
COPY warpgate-infisical.patch /tmp/warpgate-infisical.patch
COPY infisical.rs /tmp/infisical.rs
WORKDIR /opt/warpgate
RUN git apply --check /tmp/warpgate-infisical.patch \
    && git apply /tmp/warpgate-infisical.patch \
    && install -m 0644 /tmp/infisical.rs warpgate-protocol-ssh/src/infisical.rs \
    && just npm ci \
    && just openapi \
    && just npm run build \
    && cargo build --features mysql,postgres,rdp-openssl-tls --release

FROM debian:bookworm-slim
ARG USER_ID=1000
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get -y update -qq \
    && apt-get install --no-install-recommends --no-install-suggests -y ca-certificates wget sqlite3 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && adduser warpgate --disabled-password --gecos "" --uid ${USER_ID} --home /data --shell /usr/sbin/nologin
COPY --from=build /opt/warpgate/target/release/warpgate /usr/local/bin/warpgate
VOLUME /data
ENV WARPGATE_CONFIG=/data/warpgate.yaml \
    INFISICAL_CLIENT_SECRET_FILE=/run/secrets/infisical-client-secret \
    DOCKER=1
HEALTHCHECK CMD warpgate healthcheck
USER warpgate
ENTRYPOINT ["warpgate"]
CMD ["run"]
