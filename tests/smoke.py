"""Isolated Docker smoke test. Never reads the operator's .env."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid

import yaml


ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    if shutil.which("docker") is None:
        raise SystemExit("Docker is required for the container smoke test")
    with tempfile.TemporaryDirectory(prefix="hermes-smoke-") as directory:
        root = Path(directory)
        shutil.copytree(ROOT / "docker", root / "docker")
        shutil.copy2(ROOT / ".dockerignore", root / ".dockerignore")
        config = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
        # All API checks run inside the gateway: publish no host ports.
        config["services"]["hermes-gateway"]["ports"] = []
        (root / "docker-compose.yml").write_text(yaml.safe_dump(config))
        token = "synthetic-smoke-api-token-not-a-real-secret"
        (root / ".env").write_text(
            "OPENAI_API_KEY=synthetic-provider-sentinel\n"
            "DISCORD_BOT_TOKEN=your_discord_token_here_optional\n"
            "API_SERVER_KEY=\n"
        )
        project = "hermes-smoke-" + uuid.uuid4().hex[:12]
        base = ["docker", "compose", "-p", project, "-f", str(root / "docker-compose.yml")]
        # Shell credentials must not override the synthetic .env values.
        environment = {
            key: value for key, value in os.environ.items()
            if key not in {"OPENAI_API_KEY", "DISCORD_BOT_TOKEN", "API_SERVER_KEY", "HERMES_IMAGE"}
        }

        def compose(*args, capture=False, check=True):
            return subprocess.run(
                base + list(args), cwd=root, env=environment, check=check,
                text=True, stdout=subprocess.PIPE if capture else None,
            )

        def execute(script):
            return compose(
                "exec", "-T", "--user", "hermes", "hermes-gateway",
                "/opt/hermes/.venv/bin/python",
                "-c", script, capture=True,
            ).stdout.strip()

        try:
            compose("config", "--quiet")
            compose("up", "-d", "--build", "--wait", "--wait-timeout", "300")
            execute("""
import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from dotenv import dotenv_values
token = open('/opt/data/.deployment/api-key').read().strip()
assert len(token) >= 32
assert dotenv_values('/opt/data/.env')['DISCORD_BOT_TOKEN'] == ''
for headers in ({}, {'Authorization': 'Bearer invalid'}):
    try:
        urlopen(Request('http://127.0.0.1:8000/v1/models', headers=headers), timeout=10)
    except HTTPError as error:
        assert error.code in (401, 403), error.code
    else:
        raise AssertionError('Unauthenticated API request succeeded')
with urlopen(Request('http://127.0.0.1:8000/v1/models',
    headers={'Authorization': 'Bearer ' + token}), timeout=10) as response:
    assert isinstance(json.load(response)['data'], list)
""")
            # Use upstream's actual environment implementation, not just a raw SSH connection.
            execute("""
from tools.environments.ssh import SSHEnvironment
env = SSHEnvironment(host='hermes-sandbox', user='sandbox', port=2222,
    key_path='/opt/data/.ssh/id_ed25519', cwd='/workspace', sync_files=False)
result = env.execute("set -e; id -u; test -z \\"$OPENAI_API_KEY$DISCORD_BOT_TOKEN$API_SERVER_KEY\\"; "
    "test ! -e /opt/data/.deployment/api-key; "
    "test ! -e /opt/data/.ssh/id_ed25519; "
    "test ! -S /var/run/docker.sock; "
    "printf persistent > /workspace/smoke-persistence; "
    "printf shared > /workspace/skills/smoke-shared; "
    "grep -E '^(CapEff|NoNewPrivs):' /proc/self/status; "
    "test -z \\"$OPENAI_API_KEY$DISCORD_BOT_TOKEN$API_SERVER_KEY\\"")
assert result['returncode'] == 0, result
assert '10000' in result['output'], result
assert '0000000000000000' in result['output'], result
assert 'NoNewPrivs:\\t1' in result['output'], result
assert open('/opt/data/skills/smoke-shared').read() == 'shared'
env.cleanup()
""")
            sandbox_id = compose("ps", "-q", "hermes-sandbox", capture=True).stdout.strip()
            details = json.loads(subprocess.check_output(
                ["docker", "inspect", sandbox_id], text=True
            ))[0]
            host = details["HostConfig"]
            require(host["Memory"] == 2 * 1024**3, "Sandbox RAM limit is not 2 GiB")
            require(host["NanoCpus"] == 2 * 10**9, "Sandbox CPU limit is not 2")
            require(host["PidsLimit"] == 256, "Sandbox PID limit is not 256")
            require(host["ReadonlyRootfs"], "Sandbox root filesystem is writable")
            require("ALL" in host["CapDrop"], "Sandbox capabilities were not dropped")
            require(any("no-new-privileges" in item for item in host["SecurityOpt"]),
                    "Sandbox permits privilege escalation")
            before = execute("""
import hashlib
print(hashlib.sha256(open('/opt/data/.ssh/id_ed25519', 'rb').read()).hexdigest())
""")
            compose("down")
            dotenv = root / ".env"
            dotenv.write_text(dotenv.read_text().replace("API_SERVER_KEY=\n", f"API_SERVER_KEY={token}\n"))
            compose("up", "-d", "--wait", "--wait-timeout", "300")
            after = execute("""
import hashlib
print(hashlib.sha256(open('/opt/data/.ssh/id_ed25519', 'rb').read()).hexdigest())
""")
            require(before == after, "Gateway SSH identity changed after recreation")
            execute("""
import subprocess
from urllib.request import Request, urlopen
token = open('/opt/data/.deployment/api-key').read().strip()
assert token == 'synthetic-smoke-api-token-not-a-real-secret'
with urlopen(Request('http://127.0.0.1:8000/v1/models',
    headers={'Authorization': 'Bearer ' + token}), timeout=10) as response:
    assert response.status == 200
result = subprocess.check_output([
    'ssh', '-p', '2222', '-i', '/opt/data/.ssh/id_ed25519',
    '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
    'sandbox@hermes-sandbox', 'cat /workspace/smoke-persistence'], text=True)
assert result == 'persistent', result
""")
            print("PASS: API auth/generation/rotation, Hermes SSH, isolation, limits, and persistence")
        finally:
            compose("logs", "--no-color", "--tail", "80", check=False)
            compose("down", "-v", "--rmi", "local", "--remove-orphans", check=False)


if __name__ == "__main__":
    main()
