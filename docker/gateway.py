"""Gateway bootstrap, health check and skill installer for hermes-sandbox.

Usage: gateway.py prepare | health | install-skill NAME [--replace]
"""

import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path
from urllib.request import Request, urlopen

HOME = Path(os.environ.get("HERMES_HOME", "/opt/data"))
PUBLIC = Path("/run/hermes-public")

# Single source of truth for how the gateway reaches the sandbox and serves its API.
SANDBOX_HOST = "hermes-sandbox"
SANDBOX_PORT = 2222
SANDBOX_USER = "sandbox"
SANDBOX_HOME = "/workspace"
API_PORT = 8000
DEFAULT_MODEL = "gpt-4.1-mini"
MIN_API_KEY_LENGTH = 32

PLACEHOLDERS = {
    "OPENAI_API_KEY": "your_openai_api_key_here",
    "DISCORD_BOT_TOKEN": "your_discord_token_here_optional",
}
STALE_MODEL_KEYS = ("base_url", "key_env", "api_key_env", "api_key", "api_mode")
ALLOW_ALL_SETTINGS = ("DISCORD_ALLOW_ALL_USERS", "GATEWAY_ALLOW_ALL_USERS")
SKILL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
MAX_SKILL_BYTES = 256 * 1024 * 1024
MAX_SKILL_FILES = 10_000


def setting(name):
    """Environment value with surrounding whitespace and example placeholders removed."""
    value = os.environ.get(name, "").strip()
    return "" if value == PLACEHOLDERS.get(name) else value


def truthy(value):
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


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


def private_dir(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def api_key():
    path = private_dir(HOME / ".deployment") / "api-key"
    supplied = setting("API_SERVER_KEY")
    if supplied and len(supplied) < MIN_API_KEY_LENGTH:
        raise ValueError(f"API_SERVER_KEY must have at least {MIN_API_KEY_LENGTH} characters, or be empty")
    key = supplied or (path.read_text().strip() if path.exists() else secrets.token_urlsafe(32))
    if len(key) < MIN_API_KEY_LENGTH:
        raise ValueError("Stored API key is invalid; set API_SERVER_KEY to replace it")
    atomic_write(path, key + "\n")
    return key


def client_key():
    """Create the gateway's SSH identity once and publish only its restricted public half."""
    private = private_dir(HOME / ".ssh") / "id_ed25519"
    if not private.exists():
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(private)], check=True)
    public = subprocess.check_output(["ssh-keygen", "-y", "-f", str(private)], text=True).strip()
    PUBLIC.mkdir(mode=0o755, exist_ok=True)
    PUBLIC.chmod(0o755)
    atomic_write(PUBLIC / "authorized_keys", f"restrict {public}\n", 0o644)
    return private


def section(config, name, allow_string=False):
    value = config.get(name)
    if value is None or (allow_string and isinstance(value, str)):
        value = config[name] = {}
    if not isinstance(value, dict):
        raise ValueError(f"Hermes config.yaml: '{name}' must be a mapping")
    return value


def load_config(path, yaml):
    config = yaml.safe_load(path.read_text()) if path.exists() else None
    config = {} if config is None else config
    if not isinstance(config, dict):
        raise ValueError("Hermes config.yaml must contain a mapping")
    return config


def llm_settings():
    """Model section and credentials for OpenAI, or any OpenAI-compatible endpoint."""
    base_url = setting("LLM_BASE_URL").rstrip("/")
    model = setting("HERMES_MODEL")
    credentials = {"OPENAI_API_KEY": setting("OPENAI_API_KEY"), "LLM_API_KEY": setting("LLM_API_KEY")}
    if not base_url:
        key = credentials["OPENAI_API_KEY"] or credentials["LLM_API_KEY"]
        if not key:
            raise ValueError(
                "Set OPENAI_API_KEY (run ./hermes setup), or LLM_BASE_URL and HERMES_MODEL "
                "for another OpenAI-compatible provider"
            )
        return {"provider": "openai", "default": model or DEFAULT_MODEL}, {
            **credentials,
            "OPENAI_API_KEY": key,
        }
    if not re.fullmatch(r"https?://[^\s/?#]+(/[^\s?#]*)?", base_url):
        raise ValueError("LLM_BASE_URL must be an http(s) URL, e.g. https://openrouter.ai/api/v1")
    if not model:
        raise ValueError("Set HERMES_MODEL to a model name offered by LLM_BASE_URL")
    model_section = {"provider": "custom", "base_url": base_url, "default": model}
    if credentials["LLM_API_KEY"]:
        model_section["key_env"] = "LLM_API_KEY"
    return model_section, credentials


def apply_config(config, private, model):
    current = section(config, "model", allow_string=True)
    for name in STALE_MODEL_KEYS:
        current.pop(name, None)
    current.update(model)
    section(config, "terminal").update(
        backend="ssh",
        cwd=SANDBOX_HOME,
        ssh_host=SANDBOX_HOST,
        ssh_port=SANDBOX_PORT,
        ssh_user=SANDBOX_USER,
        ssh_key=str(private),
        env_passthrough=[],
        credential_files=[],
    )
    return config


def check_access_policy(config):
    enabled = [name for name in ALLOW_ALL_SETTINGS if truthy(os.environ.get(name, ""))]
    gateway = config.get("gateway")
    if isinstance(gateway, dict) and truthy(gateway.get("allow_all_users", "")):
        enabled.append("gateway.allow_all_users in config.yaml")
    if enabled:
        raise ValueError(
            "Refusing to start: " + ", ".join(enabled) + " lets anyone control this agent. "
            "Use DISCORD_ALLOWED_USERS or Hermes pairing instead."
        )


def managed_env(private, credentials, api):
    # Upstream loads $HERMES_HOME/.env with override=True, so it must agree with us.
    return {
        **credentials,
        "DISCORD_BOT_TOKEN": setting("DISCORD_BOT_TOKEN"),
        "DISCORD_ALLOWED_USERS": setting("DISCORD_ALLOWED_USERS"),
        "DISCORD_ALLOW_ALL_USERS": "false",
        "GATEWAY_ALLOW_ALL_USERS": "false",
        "TERMINAL_ENV": "ssh",
        "TERMINAL_SSH_HOST": SANDBOX_HOST,
        "TERMINAL_SSH_PORT": str(SANDBOX_PORT),
        "TERMINAL_SSH_USER": SANDBOX_USER,
        "TERMINAL_SSH_KEY": str(private),
        "API_SERVER_ENABLED": "true",
        "API_SERVER_HOST": "0.0.0.0",
        "API_SERVER_PORT": str(API_PORT),
        "API_SERVER_KEY": api,
    }


def configure():
    import hermes_yaml as yaml
    from dotenv import set_key

    model, credentials = llm_settings()
    path = HOME / "config.yaml"
    config = load_config(path, yaml)
    check_access_policy(config)
    private = client_key()
    atomic_write(path, yaml.safe_dump(apply_config(config, private, model), sort_keys=False))
    api = api_key()
    dotenv = HOME / ".env"
    dotenv.touch(mode=0o600, exist_ok=True)
    dotenv.chmod(0o600)
    for name, value in managed_env(private, credentials, api).items():
        set_key(dotenv, name, value)


def ssh_command(command):
    options = (
        "BatchMode=yes",
        "IdentitiesOnly=yes",
        "StrictHostKeyChecking=accept-new",
        "ConnectTimeout=5",
        f"UserKnownHostsFile={HOME / '.ssh/known_hosts'}",
    )
    flags = [arg for option in options for arg in ("-o", option)]
    key = str(HOME / ".ssh/id_ed25519")
    return ["ssh", "-p", str(SANDBOX_PORT), "-i", key, *flags, f"{SANDBOX_USER}@{SANDBOX_HOST}", command]


def wait_for_sandbox(attempts=30, delay=2):
    error = ""
    for attempt in range(attempts):
        try:
            result = subprocess.run(ssh_command("true"), capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                return
            error = result.stderr.strip()
        except subprocess.TimeoutExpired:
            error = "SSH connection timed out"
        if attempt < attempts - 1:
            time.sleep(delay)
    raise RuntimeError("Sandbox SSH authentication failed: " + error)


def health():
    key = (HOME / ".deployment/api-key").read_text().strip()
    request = Request(f"http://127.0.0.1:{API_PORT}/v1/models", headers={"Authorization": "Bearer " + key})
    with urlopen(request, timeout=5) as response:
        if not isinstance(json.load(response).get("data"), list):
            raise RuntimeError("Gateway models endpoint is not ready")
    subprocess.run(
        ssh_command("true"), check=True, timeout=8, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )


def extract_skill(stream, destination):
    """Extract an untrusted tar stream: regular files and directories only, bounded size."""
    total = files = 0
    with tarfile.open(fileobj=stream, mode="r|*") as archive:
        for member in archive:
            if not (member.isfile() or member.isdir()):
                raise ValueError(f"Rejected {member.name}: only regular files and directories are allowed")
            total += member.size
            files += 1
            if total > MAX_SKILL_BYTES or files > MAX_SKILL_FILES:
                raise ValueError("Skill is too large to install")
            archive.extract(member, destination, filter="data")
    if not (destination / "SKILL.md").is_file():
        raise ValueError("Skill folder must contain SKILL.md at its top level")


def install_skill(name, stream, replace=False):
    if not SKILL_NAME.fullmatch(name):
        raise ValueError(f"Invalid skill name: {name!r}")
    skills = HOME / "skills"
    skills.mkdir(parents=True, exist_ok=True)
    target = skills / name
    if target.exists() and not replace:
        raise FileExistsError(f"Skill '{name}' already exists; use --replace to overwrite it")
    staging = Path(tempfile.mkdtemp(prefix=".install-", dir=skills))
    previous = skills / f".previous-{staging.name}"
    try:
        extract_skill(stream, staging)
        staging.chmod(0o755)
        if target.exists():
            target.rename(previous)
        try:
            staging.rename(target)
        except OSError:
            if previous.exists():
                previous.rename(target)
            raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(previous, ignore_errors=True)
    return target


def main(argv=None):
    os.umask(0o077)
    args = sys.argv[1:] if argv is None else argv
    if args == ["health"]:
        health()
    elif args == ["prepare"]:
        configure()
        wait_for_sandbox()
    elif args[:1] == ["install-skill"] and len(args) in (2, 3) and args[2:] in ([], ["--replace"]):
        os.umask(0o022)
        target = install_skill(args[1], sys.stdin.buffer, replace=len(args) == 3)
        print(f"Installed skill '{args[1]}' at {target}")
    else:
        raise SystemExit(__doc__.strip().splitlines()[-1])


if __name__ == "__main__":
    try:
        main()
    except (ValueError, FileExistsError, RuntimeError, tarfile.TarError) as error:
        raise SystemExit(f"error: {error}") from None
