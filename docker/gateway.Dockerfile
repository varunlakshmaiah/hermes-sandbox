# Pinned upstream release; Dependabot proposes updates, CI smoke-tests them.
FROM nousresearch/hermes-agent:v0.23.0@sha256:adb7890916de63245523492be8f68f9d2095fecbec4e2a6dab7960381f0fc002

LABEL org.opencontainers.image.source="https://github.com/varunlakshmaiah/hermes-sandbox" \
      org.opencontainers.image.description="Hermes Agent gateway that executes commands in an SSH sandbox"

# Upstream's s6 init runs as root and drops to the hermes user itself.
# hadolint ignore=DL3002,DL3066
USER 0
# Our hook must run after upstream's volume permission fix (015) and before services start.
RUN command -v ssh && command -v ssh-keygen && \
    /opt/hermes/.venv/bin/python -c "import hermes_yaml, dotenv" && \
    test -x /etc/cont-init.d/015-supervise-perms && \
    install -d -m 0755 /opt/deployment && \
    install -d -o 10000 -g 10000 -m 0755 /run/hermes-public
COPY --chmod=0644 docker/gateway.py /opt/deployment/gateway.py
COPY --chmod=0755 docker/prepare-gateway.sh /etc/cont-init.d/019-hermes-sandbox

HEALTHCHECK --interval=30s --timeout=15s --start-period=120s --retries=3 \
    CMD ["/opt/hermes/.venv/bin/python", "/opt/deployment/gateway.py", "health"]
# Keep the upstream entrypoint: s6 initializes volumes and drops to hermes.
CMD ["gateway", "run"]
