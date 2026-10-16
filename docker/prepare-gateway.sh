#!/command/with-contenv sh
set -eu
export HOME=/opt/data
exec /command/s6-setuidgid hermes /opt/hermes/.venv/bin/python /opt/deployment/gateway.py prepare
