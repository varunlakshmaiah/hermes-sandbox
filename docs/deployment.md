# Deployment guide

[← Back to README](../README.md)

## Requirements

- Docker Engine or Docker Desktop with **Docker Compose 2.24 or newer**
  (`docker compose version`).
- An API key for OpenAI or another OpenAI-compatible provider (none for local model
  servers). Provider usage may incur charges.
- Disk space and memory for the upstream Hermes image, plus up to 2 GiB of RAM for the
  sandbox. Both containers run on the same Docker host.
- `./hermes` is a POSIX shell script: use Linux, macOS, or Windows with WSL.

## Configuration reference

`./hermes setup` creates `.env` from [`.env.example`](../.env.example) and asks for your
provider and key (`./hermes setup --reconfigure` asks again). Every setting can instead
come from your shell or platform environment variables.

| Setting | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | Your OpenAI credential, when using OpenAI (the default provider). |
| `LLM_BASE_URL` | Base URL of any OpenAI-compatible API, e.g. `https://openrouter.ai/api/v1`. Empty means OpenAI. |
| `LLM_API_KEY` | Key for `LLM_BASE_URL`; leave empty for keyless local servers. |
| `HERMES_MODEL` | Model name. Default `gpt-4.1-mini` for OpenAI; required with `LLM_BASE_URL`. |
| `API_SERVER_KEY` | Your client's Hermes API password. Leave empty to generate one, or supply a unique random value of at least 32 characters. |
| `DISCORD_BOT_TOKEN` | Optional Discord bot token. The example placeholder is ignored. |
| `DISCORD_ALLOWED_USERS` | Comma-separated Discord user IDs allowed to use the bot. |
| `HERMES_API_PORT` | Host port for the API, bound to `127.0.0.1`; default `8000`. |
| `HERMES_SANDBOX_VERSION` | Image release to run, e.g. `v0.2.0`; default `latest`. |

Apply changes with `./hermes up`. A plain `docker compose restart` does not reload
environment changes. Any other variable in `.env` (for example a different provider's
key) is passed to Hermes unchanged.

With `LLM_BASE_URL` set, startup configures Hermes' `custom` provider (`model.base_url`,
with `model.key_env: LLM_API_KEY`), so the key is sent only to that endpoint. Model
servers on the Docker host are reachable as `host.docker.internal` (mapped on Linux too).
On Linux, such a server must listen on an interface containers can reach, not only
`127.0.0.1`. Providers that need OAuth or non-OpenAI protocols are not configured by this
deployment.

Startup refuses `DISCORD_ALLOW_ALL_USERS`, `GATEWAY_ALLOW_ALL_USERS` and
`gateway.allow_all_users`: an agent with shell access must not accept commands from
anyone who can reach it. Unknown Discord users are denied unless listed or approved
through Hermes pairing.

## Images and updates

The default deployment pulls two images published by this repository's CI after the full
test suite passes:

- `ghcr.io/varunlakshmaiah/hermes-sandbox/gateway`
- `ghcr.io/varunlakshmaiah/hermes-sandbox/sandbox`

Both support `linux/amd64` and `linux/arm64`. If they cannot be pulled, Compose builds
them from this checkout automatically.

`./hermes update` backs up all data, pulls the newest tested images (or rebuilds from
source), and redeploys. For controlled upgrades, set `HERMES_SANDBOX_VERSION` to a
release tag and change it deliberately. The upstream Hermes image and base images are
pinned by digest; Dependabot proposes updates that CI must pass before release.

To always build locally instead, run `docker compose build --pull` before `./hermes up`.

## Platforms

### Dokploy

Create a **Docker Compose application** from this Git repository and select
`docker-compose.yml`. Add `OPENAI_API_KEY` (and any optional settings) in its environment
editor. Retrieve the API key with the command in [Without the CLI](#without-the-cli).

### Portainer

Create a **Stack** from this Git repository (or paste `docker-compose.yml`) and add
`OPENAI_API_KEY` as a stack environment variable. Prebuilt images mean no Git build
support is required.

**Swarm stacks are not supported:** they ignore Compose health dependencies and several
sandbox restrictions.

## Remote access

Port 8000 accepts connections only from the Docker host. From another computer, open an
SSH tunnel and keep it running:

```sh
ssh -L 8000:127.0.0.1:8000 user@your-server
```

Then use `http://127.0.0.1:8000/v1` locally. Alternatively, put a TLS reverse proxy in
front of the gateway's container port 8000 and preserve the `Authorization` header.
Never publish the sandbox's SSH port. A client running in another container must use a
network route to the host; its own `127.0.0.1` is not the host.

## Discord (optional)

Set `DISCORD_BOT_TOKEN` and `DISCORD_ALLOWED_USERS`, enable **Message Content Intent** in
the Discord developer portal, invite the bot to your server, then run `./hermes up`.

## Backups

`./hermes backup [dir]` briefly stops the services and writes two archives (gateway data
and sandbox workspace) to `./backups`. `./hermes restore backups/hermes-<timestamp>`
replaces all current data with that backup. Keep backups private: they contain your
provider key, API key and SSH keys.

## Without the CLI

Everything `./hermes` does uses plain Docker Compose:

| Task | Command |
| --- | --- |
| Deploy | `docker compose up -d --wait` |
| API key | `docker compose exec -T --user hermes hermes-gateway cat /opt/data/.deployment/api-key` |
| Health | `docker compose ps` |
| Logs | `docker compose logs --tail=100` |
| Stop (keep data) | `docker compose down` |

> [!CAUTION]
> `docker compose down -v` permanently deletes skills, workspace, configuration and keys.

## Upgrading from releases before the CLI

Existing volumes are reused unchanged. Active skills stay in the gateway; the sandbox no
longer mounts them directly, and Hermes syncs them into the sandbox at
`~/.hermes/skills` when it runs commands. Run commands from the same project folder as
before: Docker Compose names volumes after it (or set `COMPOSE_PROJECT_NAME`).
