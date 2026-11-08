# Matches the upstream Hermes runtime (Debian trixie, Python 3.13) so skills behave the same.
FROM python:3.13-slim-trixie@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90

LABEL org.opencontainers.image.source="https://github.com/varunlakshmaiah/hermes-sandbox" \
      org.opencontainers.image.description="Isolated SSH execution sandbox for Hermes Agent"

# hadolint ignore=DL3008
RUN apt-get update && \
    apt-get install -y --no-install-recommends openssh-server bash ca-certificates && \
    rm -rf /var/lib/apt/lists/* /etc/ssh/ssh_host_*key* && \
    groupadd --gid 10000 sandbox && \
    useradd --uid 10000 --gid 10000 --home-dir /workspace --no-create-home \
        --shell /bin/bash --password '*' sandbox && \
    install -d -m 0755 /run/sshd /opt/deployment && \
    install -d -o 10000 -g 10000 -m 0755 /workspace /run/hermes-public
COPY --chmod=0644 docker/sshd_config /etc/ssh/sshd_config
COPY --chmod=0644 docker/sandbox.py /opt/deployment/sandbox.py

ENV HOME=/workspace
WORKDIR /workspace
USER 10000:10000
EXPOSE 2222
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=6 \
    CMD ["python3", "/opt/deployment/sandbox.py", "health"]
CMD ["python3", "/opt/deployment/sandbox.py"]
