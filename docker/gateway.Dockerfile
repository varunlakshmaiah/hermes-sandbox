ARG HERMES_IMAGE=nousresearch/hermes-agent:latest
FROM ${HERMES_IMAGE}

USER root
RUN command -v ssh && command -v ssh-keygen && \
    /opt/hermes/.venv/bin/python -c "import hermes_yaml, dotenv" && \
    install -d -m 0755 /opt/deployment && \
    install -d -o 10000 -g 10000 -m 0755 /run/hermes-public
COPY --chmod=0644 docker/gateway.py /opt/deployment/gateway.py
COPY --chmod=0755 docker/prepare-gateway.sh /etc/cont-init.d/019-hermes-sandbox

# Keep the upstream entrypoint: s6 initializes volumes and drops to hermes.
CMD ["gateway", "run"]
