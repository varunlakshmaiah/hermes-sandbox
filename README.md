# hermes-sandbox

Hey there! Created by [@varunlakshmaiah](https://github.com/varunlakshmaiah). I built this to be the most frictionless, set-and-forget way to run an autonomous Hermes agent safely.

Two containers, automatic SSH keys, persistent named volumes, and no Docker socket.
The gateway runs [NousResearch's Hermes Agent](https://github.com/NousResearch/hermes-agent);
terminal commands run in a separate, resource-limited Python sandbox.

## Deploy in two steps

Prerequisites: a Linux Docker host (or Docker Desktop), Docker Compose v2, and an
OpenAI API key with access to the configured model. Allow enough disk and RAM for
the upstream Hermes image **in addition to** the sandbox's 2 GiB allowance.
Clone this repository and enter its directory first.

1. Copy `.env.example` to `.env` and replace `OPENAI_API_KEY`:
   ```sh
   cp .env.example .env
   ```
   This is the only configuration file you need to edit. The Discord placeholder
   is ignored; leave it unchanged or empty unless you actually want Discord.
2. Deploy:
   ```sh
   docker compose up -d --build --wait
   ```
   Subsequent starts can use `docker compose up -d`. On first deployment Docker
   builds two small derivative images and creates/populates all volumes.
   No manual key generation, volume creation, host paths, or `chown` is needed.

The default model is `gpt-4.1-mini`; change `HERMES_MODEL` in `.env` if your account
uses another OpenAI model. Invalid or missing provider credentials fail explicitly;
successful startup does not verify your OpenAI account quota.

### Use the API

The OpenAI-compatible API is available at `http://127.0.0.1:8000/v1`.
It always requires a bearer token. On first boot a random token is generated and
persisted privately in `hermes_data`; it is never printed in startup logs.
Retrieve it as the host administrator:

```sh
docker compose exec -T --user hermes hermes-gateway cat /opt/data/.deployment/api-key
```

Use that value as your client's API key and `hermes-agent` as the API model name
(the actual upstream model is configured separately by `HERMES_MODEL`).
Alternatively set a unique random `API_SERVER_KEY` of at least 32 characters in
`.env`. This token is different from your OpenAI API key.

Port 8000 binds **only to host loopback**. For remote access use an SSH tunnel
(`ssh -L 8000:127.0.0.1:8000 user@host`) or a TLS reverse proxy forwarding to the
gateway's container port 8000. Preserve the `Authorization` header and do not
publish the sandbox SSH port. There is no public dashboard enabled by this stack.

### Optional Discord

Set `DISCORD_BOT_TOKEN` to a real bot token and `DISCORD_ALLOWED_USERS` to your
Discord user IDs, separated by commas. Enable the Message Content Intent in the
Discord developer portal and invite the bot to your server. Hermes' own Discord
pairing/access policies still apply; do not enable unrestricted bot access.
Recreate the gateway after editing `.env` with `docker compose up -d`.

### Dokploy and Portainer

**Named volumes** make this suitable for Dokploy, Portainer, and ordinary Docker
Compose without host-directory permission fixes. This is a two-container,
**same-Docker-host** deployment, not an orchestrator for multiple physical hosts.

For Dokploy, create a **Docker Compose application** from this Git repository,
select `docker-compose.yml`, and provide the `.env.example` values in its
environment editor so Dokploy writes the `.env` used by `env_file`. Deploy using
repository builds. If adding a domain, route HTTPS to `hermes-gateway:8000`,
retain bearer authentication, and keep the sandbox off the proxy network.

For Portainer, use a **standalone Docker/Compose** Git stack that supports
repository-relative Dockerfile builds. Supply an actual stack `.env` accessible to
`env_file`; interpolation-only UI variables are not a replacement for that file.
Portainer editions/configurations that cannot build Git stacks need these images
built and pushed to your own registry first. **Swarm stacks are not supported**:
they do not build these Dockerfiles and do not honor Compose health dependencies.
PaaS environment/file handling varies; this is not a claim of zero-click
compatibility with every platform version.

## Architecture & Security

```text
API client / Discord
        |
        v
hermes-gateway (agent, provider keys, authenticated API)
        |
        | authenticated SSH on the private Compose network
        v
hermes-sandbox (UID 10000, Python 3.11, bash, no provider keys)
```

**Separation of Gateway and Execution.** Hermes' supported `terminal.backend: ssh`
and `TERMINAL_SSH_*` settings send terminal commands to `hermes-sandbox:2222`.
The gateway still runs the agent, messaging adapters, and built-in tools locally:
an SSH terminal backend does **not** make every Hermes tool remote or guarantee
"zero code locally." There is no supported `SANDBOX_HOST` transport assumed here.
The sandbox needs a real SSH endpoint; `tail -f /dev/null` alone cannot execute
remote commands.

**Credential isolation.** Only the gateway receives `.env`. Its private SSH key,
API bearer token, provider keys, and bot tokens are not mounted in the sandbox.
Only the SSH **public** authorization key is shared through a separate volume,
read-only on the sandbox side. SSH password login, environment forwarding, agent/
TCP forwarding, PTYs, user RC scripts, and root login are disabled. Keys are
generated automatically at runtime, not baked into images. SSH uses trust on
first use on the private network and persists the host fingerprint in
`hermes_data`; a changed host key fails rather than being silently accepted.

This protects against a terminal process simply reading the gateway's environment
or filesystem. It is **not** a guarantee against every prompt injection: the
agent can send sensitive text in commands, other gateway tools have their own
privileges, and Hermes can sync explicitly registered skill credential files.
Do not add secrets to skills, enable credential passthrough, install untrusted
skills, or treat a compromised agent as a trusted secret custodian.

**Kernel security hardening.** The SSH server and tasks run as non-root UID/GID
10000, including at startup; no capability is needed to bind port 2222.
`cap_drop: ALL` removes Linux capabilities (including network administration),
and `no-new-privileges:true` prevents gaining privileges through setuid binaries
or file capabilities. The root filesystem is read-only, with a bounded temporary
filesystem. These measures reduce privilege escalation and network/kernel
manipulation risks, but containers still **share the host kernel**. This is not a
VM or a defense against all kernel vulnerabilities.

**Strict resource containment.** Compose enforces `mem_limit: 2G`, `cpus: 2.0`,
and `pids_limit: 256` on the sandbox even outside Swarm. Runaway code is constrained
to these CPU/RAM/process budgets; it can still fill persistent disk or produce
network traffic. The gateway has separate resource needs, so these limits do not
guarantee that the whole host cannot fail. The default bridge allows outbound
internet access and access to reachable network services; use host/firewall egress
policies for hostile workloads or sensitive LANs.

### Persistence and trust

| Named volume | Purpose | Mounted in |
| --- | --- | --- |
| `hermes_data` | Hermes config/state, private client key, known hosts, API token | Gateway only |
| `hermes_skills` | Shared persistent skills | Both containers |
| `hermes_workspace` | Sandbox files, home, and SSH host key | Sandbox only |
| `hermes_public_keys` | Public authorized client key only | Gateway; sandbox read-only |

Writable shared skills are an intentional convenience, **not a trust boundary**:
sandbox edits can affect later agent behavior. Hermes also synchronizes supported
skills/cache files through its SSH backend. Keep backups, review skill changes,
and use separate hosts or a VM/microVM boundary for genuinely adversarial tasks.
Named-volume ownership is seeded by the images; do not override the fixed service
UIDs or add the Docker socket.

The gateway preserves upstream s6 initialization, supervision, and privilege
dropping rather than bypassing `/init`. A startup hook prepares configuration and
keys **before** upstream restores gateway services, so updated credentials take
effect on container recreation as well as first boot. Health checks cover the
authenticated API and SSH command
execution; startup waits for the sandbox. `restart: unless-stopped` handles exits
and host restarts. Docker reports unhealthy containers but does not automatically
restart a live unhealthy process.

## Operations

```sh
docker compose ps
docker compose logs --tail=100
# Fetch/rebuild against the configured upstream image, preserving all data:
docker compose build --pull
docker compose up -d --wait
# Stop without deleting volumes:
docker compose down
```

`latest` follows upstream and is not an immutable release. For controlled
production upgrades, set `HERMES_IMAGE` in `.env` to a tested upstream digest,
back up all four volumes, and run the smoke test before upgrading. This stack
reasserts its managed model and SSH settings on gateway startup; other Hermes
configuration is preserved. No automatic updater or cloud credentials are needed.
**`docker compose down -v` permanently deletes all state and keys.**

If the sandbox workspace is deliberately replaced, its SSH host key changes.
After verifying that replacement as the host administrator, remove the old
fingerprint with `docker compose exec --user hermes hermes-gateway ssh-keygen -R
'[hermes-sandbox]:2222' -f /opt/data/.ssh/known_hosts` and restart the gateway.
Do not disable host-key checks to work around an unexpected mismatch.

## Validation

```sh
python3 -m pip install -r tests/requirements.txt
python3 -m unittest discover -s tests -v
docker compose --env-file .env.example config --no-env-resolution --quiet
python3 tests/smoke.py
```

The smoke test uses an isolated Compose project, synthetic credentials, and no
paid model calls. It checks real SSH execution through Hermes' backend, API
authentication and token generation/rotation, secret isolation,
non-root/capability/resource settings, and
restart persistence, then removes only its own test volumes. It requires Docker
Compose v2 and can download the large upstream image. GitHub Actions runs the
same checks on pushes and pull requests.
