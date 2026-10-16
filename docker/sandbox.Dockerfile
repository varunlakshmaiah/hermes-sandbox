FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends openssh-server openssh-client bash ca-certificates && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd --gid 10000 sandbox && \
    useradd --uid 10000 --gid 10000 --home-dir /workspace --shell /bin/bash --password '' sandbox && \
    install -d -m 0755 /run/sshd /run/hermes-public /opt/deployment && \
    install -d -o 10000 -g 10000 -m 0755 /workspace /workspace/skills /workspace/.hermes /run/hermes-public && \
    ln -s /workspace/skills /workspace/.hermes/skills && \
    rm -f /etc/ssh/ssh_host_*key*
COPY --chmod=0644 docker/sshd_config /etc/ssh/sshd_config
COPY --chmod=0644 docker/sandbox.py /opt/deployment/sandbox.py

ENV HOME=/workspace
WORKDIR /workspace
USER 10000:10000
EXPOSE 2222
CMD ["python3", "/opt/deployment/sandbox.py"]
