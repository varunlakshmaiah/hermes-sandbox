import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, urlopen

import hermes_yaml as yaml
from dotenv import set_key


HOME = Path(os.environ.get("HERMES_HOME", "/opt/data"))
PUBLIC = Path("/run/hermes-public")


def atomic_write(path, text, mode=0o600):
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(text)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def api_key():
    directory = HOME / ".deployment"
    directory.mkdir(mode=0o700, exist_ok=True)
    directory.chmod(0o700)
    path = directory / "api-key"
    supplied = os.environ.get("API_SERVER_KEY", "").strip()
    if supplied and len(supplied) < 32:
        raise ValueError("API_SERVER_KEY must have at least 32 characters, or be empty")
    key = supplied or (path.read_text().strip() if path.exists() else secrets.token_urlsafe(32))
    if len(key) < 32:
        raise ValueError("Stored API key is invalid; set API_SERVER_KEY to replace it")
    atomic_write(path, key + "\n")
    return key


def ssh_command(command):
    return [
        "ssh", "-p", "2222", "-i", str(HOME / ".ssh/id_ed25519"),
        "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
        "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=5",
        "-o", f"UserKnownHostsFile={HOME / '.ssh/known_hosts'}",
        "sandbox@hermes-sandbox", command,
    ]


def configure():
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key or key == "your_openai_api_key_here":
        raise ValueError("Set OPENAI_API_KEY in .env before deploying")
    if os.environ.get("DISCORD_BOT_TOKEN", "").strip() == "your_discord_token_here_optional":
        os.environ.pop("DISCORD_BOT_TOKEN", None)

    ssh_dir = HOME / ".ssh"
    ssh_dir.mkdir(mode=0o700, exist_ok=True)
    ssh_dir.chmod(0o700)
    private = ssh_dir / "id_ed25519"
    if not private.exists():
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(private)],
            check=True,
        )
    public = subprocess.check_output(["ssh-keygen", "-y", "-f", str(private)], text=True)
    PUBLIC.mkdir(mode=0o755, exist_ok=True)
    PUBLIC.chmod(0o755)
    atomic_write(PUBLIC / "authorized_keys", "restrict " + public.strip() + "\n", 0o644)

    path = HOME / "config.yaml"
    config = yaml.safe_load(path.read_text()) if path.exists() else {}
    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise ValueError("Hermes config.yaml must contain a mapping")
    if isinstance(config.get("model"), str):
        config["model"] = {}
    config.setdefault("model", {}).update(
        provider="openai", default=os.environ.get("HERMES_MODEL", "gpt-4.1-mini")
    )
    config.setdefault("terminal", {}).update(
        backend="ssh", cwd="/workspace", ssh_host="hermes-sandbox",
        ssh_port=2222, ssh_user="sandbox", ssh_key=str(private),
        env_passthrough=[], credential_files=[],
    )
    atomic_write(path, yaml.safe_dump(config, sort_keys=False))
    os.environ["API_SERVER_KEY"] = api_key()
    os.environ["TERMINAL_ENV"] = "ssh"
    # Upstream loads this file with override=True, even for container env vars.
    dotenv = HOME / ".env"
    dotenv.touch(mode=0o600, exist_ok=True)
    dotenv.chmod(0o600)
    managed = {
        "OPENAI_API_KEY": key,
        "DISCORD_BOT_TOKEN": os.environ.get("DISCORD_BOT_TOKEN", ""),
        "DISCORD_ALLOWED_USERS": os.environ.get("DISCORD_ALLOWED_USERS", ""),
        "TERMINAL_ENV": "ssh",
        "TERMINAL_SSH_HOST": "hermes-sandbox",
        "TERMINAL_SSH_PORT": "2222",
        "TERMINAL_SSH_USER": "sandbox",
        "TERMINAL_SSH_KEY": str(private),
        "API_SERVER_ENABLED": "true",
        "API_SERVER_HOST": "0.0.0.0",
        "API_SERVER_PORT": "8000",
        "API_SERVER_KEY": os.environ["API_SERVER_KEY"],
    }
    for name, value in managed.items():
        set_key(dotenv, name, value)


def wait_for_sandbox():
    error = ""
    for attempt in range(30):
        try:
            result = subprocess.run(
                ssh_command("true"), capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                return
            error = result.stderr.strip()
        except subprocess.TimeoutExpired:
            error = "SSH connection timed out"
        if attempt == 29:
            raise RuntimeError("Sandbox SSH authentication failed: " + error)
        time.sleep(2)


def health():
    key = (HOME / ".deployment/api-key").read_text().strip()
    request = Request(
        "http://127.0.0.1:8000/v1/models",
        headers={"Authorization": "Bearer " + key},
    )
    with urlopen(request, timeout=5) as response:
        payload = json.load(response)
        if response.status != 200 or not isinstance(payload.get("data"), list):
            raise RuntimeError("Gateway models endpoint is not ready")
    subprocess.run(
        ssh_command("true"), check=True, timeout=8,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def main():
    os.umask(0o077)
    if sys.argv[1:] == ["health"]:
        health()
        return
    if sys.argv[1:] != ["prepare"]:
        raise ValueError("Expected prepare or health")
    configure()
    wait_for_sandbox()


if __name__ == "__main__":
    main()
