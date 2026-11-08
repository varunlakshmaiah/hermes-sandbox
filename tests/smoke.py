"""Isolated end-to-end Docker smoke test. Never reads the operator's .env.

Builds both images, deploys through ./hermes, and checks: API auth, that Hermes'
own terminal tool executes in the sandbox (with native skill sync), isolation and
limits, the CLI skill workflow, backup/restore, and persistence across recreation.
"""

import json
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "synthetic-smoke-api-token-not-a-real-secret"
MARKER = "smoke-skill-marker"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    if shutil.which("docker") is None:
        raise SystemExit("Docker is required for the container smoke test")
    with tempfile.TemporaryDirectory(prefix="hermes-smoke-") as directory:
        run(Path(directory))


def run(root):
    project = "hermes-smoke-" + uuid.uuid4().hex[:12]
    shutil.copytree(ROOT / "docker", root / "docker")
    for name in (".dockerignore", ".env.example", "hermes"):
        shutil.copy2(ROOT / name, root / name)
    config = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    for name, service in config["services"].items():
        service["image"] = f"{project}-{name}:smoke"
    # All API checks run inside the gateway: publish no host ports.
    config["services"]["hermes-gateway"]["ports"] = []
    (root / "docker-compose.yml").write_text(yaml.safe_dump(config))
    (root / ".env").write_text(
        "OPENAI_API_KEY=synthetic-provider-sentinel\n"
        "DISCORD_BOT_TOKEN=your_discord_token_here_optional\n"
        "API_SERVER_KEY=\n"
    )
    # Shell settings must not override the synthetic .env values.
    ignored = {
        "OPENAI_API_KEY",
        "DISCORD_BOT_TOKEN",
        "DISCORD_ALLOWED_USERS",
        "API_SERVER_KEY",
        "HERMES_MODEL",
        "HERMES_API_PORT",
        "HERMES_SANDBOX_VERSION",
    }
    environment = {key: value for key, value in os.environ.items() if key not in ignored}
    environment["COMPOSE_PROJECT_NAME"] = project

    def command(*args, capture=False, check=True, stdin=None):
        result = subprocess.run(
            list(args),
            cwd=root,
            env=environment,
            check=False,
            text=True,
            stdin=stdin,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
        )
        if check and result.returncode:
            raise RuntimeError(f"{args} failed ({result.returncode}): {result.stdout}{result.stderr}")
        return result

    def compose(*args, **options):
        return command("docker", "compose", "-f", str(root / "docker-compose.yml"), *args, **options)

    def cli(*args, **options):
        return command(str(root / "hermes"), *args, **options)

    def gateway(script):
        # Redirect inside the container: Hermes' SSH ControlMaster outlives the script.
        return compose(
            "exec",
            "-T",
            "--user",
            "hermes",
            "hermes-gateway",
            "sh",
            "-c",
            '/opt/hermes/.venv/bin/python -c "$1" > /tmp/smoke.out 2>&1 < /dev/null;'
            " status=$?; cat /tmp/smoke.out; exit $status",
            "sh",
            script,
            capture=True,
        ).stdout.strip()

    def sandbox(script, check=True):
        return compose("exec", "-T", "hermes-sandbox", "sh", "-c", script, capture=True, check=check)

    def identity():
        script = "import hashlib; print(hashlib.sha256(open('{}', 'rb').read()).hexdigest())"
        return gateway(script.format("/opt/data/.ssh/id_ed25519"))

    try:
        compose("config", "--quiet")
        compose("build", "--pull")
        output = cli("setup", capture=True).stdout
        require("Hermes is ready" in output, output)
        api_key = cli("key", capture=True).stdout.strip()
        require(len(api_key) >= 32 and api_key in output, "Generated API key was not reported")

        gateway("""
import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from dotenv import dotenv_values
token = open('/opt/data/.deployment/api-key').read().strip()
values = dotenv_values('/opt/data/.env')
assert values['DISCORD_BOT_TOKEN'] == '' and values['GATEWAY_ALLOW_ALL_USERS'] == 'false'
for headers in ({}, {'Authorization': 'Bearer wrong-token'}):
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

        # CLI skill workflow: import (skipping secrets), activate, export.
        source = root / "skill-source"
        (source / "skills/smoke-skill").mkdir(parents=True)
        (source / "skills/smoke-skill/SKILL.md").write_text(f"---\nname: smoke-skill\n---\n{MARKER}\n")
        (source / ".env").write_text("LEAK=1\n")
        (source / ".git").mkdir()
        cli("import", str(source), "smoke-repo")
        sandbox(
            "set -e; cd /workspace/repos/smoke-repo; test -f skills/smoke-skill/SKILL.md; "
            "test ! -e .env; test ! -e .git"
        )
        cli("activate", "smoke-repo/skills/smoke-skill")
        require(
            cli("activate", "smoke-repo/skills/smoke-skill", check=False).returncode != 0,
            "Activation overwrote an existing skill without --replace",
        )
        cli("activate", "smoke-repo/skills/smoke-skill", "--replace")
        cli("export", "smoke-skill", str(root / "exported"))
        require(MARKER in (root / "exported/smoke-skill/SKILL.md").read_text(), "Export failed")

        # Untrusted sandbox content must not smuggle links into the gateway.
        sandbox(
            "set -e; mkdir -p /workspace/repos/evil; echo x > /workspace/repos/evil/SKILL.md; "
            "ln -s /opt/data/.env /workspace/repos/evil/leak"
        )
        require(cli("activate", "evil", check=False).returncode != 0, "Symlinked skill was activated")
        gateway("import os; assert not os.path.exists('/opt/data/skills/evil')")

        # Hermes' own terminal tool must run in the sandbox and see natively synced skills.
        gateway(f"""
import json
from pathlib import Path
from hermes_cli.env_loader import load_hermes_dotenv
load_hermes_dotenv(hermes_home=Path('/opt/data'))
from tools.terminal_tool import terminal_tool
result = json.loads(terminal_tool(
    'test -e /opt/deployment/sandbox.py && test ! -e /opt/data && id -u && '
    'cat ~/.hermes/skills/smoke-skill/SKILL.md'))
assert result.get('exit_code') == 0, result
assert '10000' in result['output'] and {MARKER!r} in result['output'], result
""")

        # Raw isolation checks through upstream's SSH environment.
        gateway("""
from tools.environments.ssh import SSHEnvironment
env = SSHEnvironment(host='hermes-sandbox', user='sandbox', port=2222,
    key_path='/opt/data/.ssh/id_ed25519', cwd='/workspace', sync_files=False)
result = env.execute("set -e; id -u; test -z \\"$OPENAI_API_KEY$DISCORD_BOT_TOKEN$API_SERVER_KEY\\"; "
    "test ! -e /opt/data; test ! -S /var/run/docker.sock; "
    "! touch /opt/deployment/x 2>/dev/null; ! touch /run/hermes-public/x 2>/dev/null; "
    "printf persistent > /workspace/smoke-persistence; "
    "grep -E '^(CapEff|NoNewPrivs):' /proc/self/status")
assert result['returncode'] == 0, result
assert '10000' in result['output'], result
assert '0000000000000000' in result['output'], result
assert 'NoNewPrivs:\\t1' in result['output'], result
env.cleanup()
""")

        sandbox_id = compose("ps", "-q", "hermes-sandbox", capture=True).stdout.strip()
        host = json.loads(command("docker", "inspect", sandbox_id, capture=True).stdout)[0]["HostConfig"]
        require(host["Memory"] == 2 * 1024**3, "Sandbox RAM limit is not 2 GiB")
        require(host["NanoCpus"] == 2 * 10**9, "Sandbox CPU limit is not 2")
        require(host["PidsLimit"] == 256, "Sandbox PID limit is not 256")
        require(host["ReadonlyRootfs"], "Sandbox root filesystem is writable")
        require("ALL" in host["CapDrop"], "Sandbox capabilities were not dropped")
        require(
            any("no-new-privileges" in item for item in host["SecurityOpt"]),
            "Sandbox permits privilege escalation",
        )

        # Backup, damage, restore.
        before = identity()
        cli("backup", str(root / "backups"))
        archives = sorted((root / "backups").glob("hermes-*-gateway.tar.gz"))
        require(len(archives) == 1, f"Unexpected backups: {archives}")
        sandbox("rm /workspace/smoke-persistence")
        gateway("import shutil; shutil.rmtree('/opt/data/skills/smoke-skill')")
        cli("restore", str(archives[0]).removesuffix("-gateway.tar.gz"), "--yes")
        sandbox('test "$(cat /workspace/smoke-persistence)" = persistent')
        gateway("import os; assert os.path.isfile('/opt/data/skills/smoke-skill/SKILL.md')")
        require(identity() == before, "Gateway SSH identity changed after restore")

        # Recreate with a supplied API key: identity, host key trust and data persist.
        compose("down")
        dotenv = root / ".env"
        dotenv.write_text(dotenv.read_text().replace("API_SERVER_KEY=\n", f"API_SERVER_KEY={TOKEN}\n"))
        cli("up")
        require(identity() == before, "Gateway SSH identity changed after recreation")
        require(cli("key", capture=True).stdout.strip() == TOKEN, "Supplied API key was not applied")
        gateway("""
import subprocess
result = subprocess.check_output([
    'ssh', '-p', '2222', '-i', '/opt/data/.ssh/id_ed25519', '-o', 'BatchMode=yes',
    '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=/opt/data/.ssh/known_hosts',
    'sandbox@hermes-sandbox', 'cat /workspace/smoke-persistence'], text=True)
assert result == 'persistent', result
""")
        print(
            "PASS: CLI setup/import/activate/export/backup/restore, API auth, Hermes SSH terminal + "
            "skill sync, link rejection, isolation, limits, persistence"
        )
    finally:
        compose("logs", "--no-color", "--tail", "80", check=False)
        compose("down", "-v", "--rmi", "all", "--remove-orphans", check=False)


if __name__ == "__main__":
    main()
