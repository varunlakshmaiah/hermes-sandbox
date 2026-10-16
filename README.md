# hermes-sandbox

**Build skills. Test in a separate container. Save reviewed work to GitHub.**

[Getting started](#getting-started) · [Connect to Hermes](#connect-to-hermes) ·
[Use your skills](#use-your-skills) · [Save to GitHub](#save-to-github) ·
[Security](#architecture-and-security) · [Developer guide](#developer-guide)

Hey there! Created by [@varunlakshmaiah](https://github.com/varunlakshmaiah).
I built this to be the most frictionless, set-and-forget way to run an autonomous
Hermes agent safely.

## What is this?

**Project goal: to securely build and test Hermes skills and save them to a Git
repository.** This project runs [Hermes Agent](https://github.com/NousResearch/hermes-agent)
in two Docker containers: one manages the agent and credentials; the other runs
its terminal commands.

| You want to… | Use it for… |
| --- | --- |
| Create or improve a skill | Prototype instructions and Python helpers, then test changes. |
| Try an existing skill | Inspect unfamiliar code before deciding to trust it. |
| Automate small tasks | Process non-sensitive sample data or run repeatable checks. |
| Work through chat | Connect an API client or an access-controlled Discord bot. |
| Keep a skills library | Export reviewed skills to GitHub for history and collaboration. |

> [!IMPORTANT]
> This is risk reduction, not a guarantee that arbitrary code is safe. Containers
> share the host kernel, and active skills are writable by the sandbox. Use a
> separate virtual machine for genuinely hostile workloads.

### What works today?

| Included | Not included |
| --- | --- |
| Automatic SSH keys, persistent storage, authenticated API | A built-in chat website or public dashboard |
| Manual import of public **and private** skills | Automatic repository syncing |
| Sandbox testing and host-side GitHub publishing | Git installed in the sandbox or automatic agent commits/pushes |
| CPU, memory, and process limits for sandbox commands | Isolation of every Hermes tool or protection against every prompt injection |

## Getting started

### Before you begin

You need a Docker host: a Linux server or a computer with Docker Desktop, with
**Docker Compose v2** available. You also need an OpenAI API key with access to
your chosen model. Provider usage may incur charges.

Allow disk space and memory for the upstream Hermes image **in addition to** the
sandbox's 2 GiB memory allowance. Both containers run on the same Docker host.

**Get the project:** use **Code → Download ZIP** on this repository and extract
it, or run:

```sh
git clone https://github.com/varunlakshmaiah/hermes-sandbox.git
cd hermes-sandbox
```

Open a terminal in the extracted/cloned project folder. Unless stated otherwise,
run commands on the **Docker host**, from the folder containing
`docker-compose.yml`. Examples use a Linux/macOS shell or Windows WSL.

### Step 1 — Add your API key

Duplicate `.env.example`, name the copy `.env`, and open it in a text editor.
On Linux/macOS/WSL, you can create the copy with:

```sh
cp .env.example .env
```

Replace `your_openai_api_key_here` with your OpenAI key. Leave the other settings
unchanged to start. **Never upload `.env` to GitHub or share it.**

### Step 2 — Deploy

```sh
docker compose up -d --build --wait
```

The first start downloads images, builds the containers, and creates storage and
SSH keys automatically. No manual volume creation, host paths, or permission
commands are needed.

**Check that it is ready:**

```sh
docker compose ps
```

Both services should report **healthy**. If not, see
[Troubleshooting](#troubleshooting). Startup checks do not verify your provider
account balance or model access.

<details>
<summary><strong>Optional settings in .env</strong></summary>

| Setting | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | Required: your OpenAI provider credential. |
| `HERMES_MODEL` | OpenAI model available to your account; default `gpt-4.1-mini`. |
| `API_SERVER_KEY` | Your client's Hermes API password. Leave empty to generate one, or supply a unique random value of at least 32 characters. |
| `DISCORD_BOT_TOKEN` | Optional real Discord bot token. The example placeholder is ignored. |
| `DISCORD_ALLOWED_USERS` | Comma-separated Discord user IDs allowed to use the bot. |
| `HERMES_IMAGE` | Upstream image reference; default `nousresearch/hermes-agent:latest`. Pin a tested digest for controlled production upgrades. |

After editing `.env`, apply changes with `docker compose up -d`.
A plain restart does not reload Compose environment-file changes. If you change
`HERMES_IMAGE`, rebuild with `docker compose build --pull` first.

</details>

<details>
<summary><strong>Deploy with Dokploy or Portainer</strong></summary>

**Dokploy:** create a **Docker Compose application** from this Git repository and
select `docker-compose.yml`. Supply the `.env.example` values in its environment
editor so it creates the `.env` file required by `env_file`. Use repository
builds. If you add a domain, route HTTPS to `hermes-gateway:8000`, preserve the
`Authorization` header, and do not expose the sandbox.

**Portainer:** use a standalone Docker/Compose Git stack with repository-relative
Dockerfile build support. Provide a real stack `.env` file accessible to
`env_file`; interpolation-only UI variables do not replace it. If your Portainer
setup cannot build Git stacks, build and push the images to your own registry
first and adapt the stack to use them.

Named volumes avoid host-folder permission fixes. Platform file/build support
varies; this is not zero-click compatibility with every version.
**Swarm stacks are not supported:** they do not build these Dockerfiles or honor
Compose health dependencies.

</details>

## Connect to Hermes

This deployment is a backend, not a chat website. Choose an OpenAI-compatible
client or configure Discord.

### API client

Retrieve your generated Hermes API key:

```sh
docker compose exec -T --user hermes hermes-gateway cat /opt/data/.deployment/api-key
```

Treat the displayed value as a password. It persists across restarts and is not
printed in startup logs.

| Client field | Value |
| --- | --- |
| Base URL | `http://127.0.0.1:8000/v1` |
| API key | The value retrieved above, or your configured `API_SERVER_KEY` |
| Model | `hermes-agent` |

Your **OpenAI key** pays for the model; your **Hermes API key** controls access to
this deployment. They are different. The underlying OpenAI model is selected by
`HERMES_MODEL`, not the client's `hermes-agent` label.

Port 8000 is accessible only from the Docker host by default.

<details>
<summary><strong>Connect from another computer</strong></summary>

Create an SSH tunnel from your computer, replacing `user@host` with your server:

```sh
ssh -L 8000:127.0.0.1:8000 user@host
```

Keep it open and use the same local base URL in your client. Alternatively,
configure a TLS reverse proxy to the gateway's container port 8000, preserving
bearer authentication. Do not publish the sandbox SSH port. If your client runs
in another container, its `127.0.0.1` refers to that container, not the Docker host;
configure a suitable private network route.

</details>

### Discord (optional)

Set a real `DISCORD_BOT_TOKEN` and your user IDs in `DISCORD_ALLOWED_USERS` in
`.env`. Enable **Message Content Intent** in the Discord developer portal,
invite the bot to your server, then run `docker compose up -d`.

Hermes' own pairing and access policies still apply. Do not enable unrestricted
bot access. Leave the token blank or keep the example placeholder to skip Discord.

## Use your skills

A **skill** is usually a folder containing `SKILL.md` instructions plus optional
scripts and supporting files. A **repository** is the project folder on GitHub.

The safest starting workflow needs **no GitHub token inside Hermes**:

```text
Download a reviewed copy → Inspect and test → Review changes → Save to GitHub
```

### 1. Download your public or private repository

Open the repository on GitHub, select a reviewed release or commit, then choose
**Code → Download ZIP**. For a private repository, sign in with an account that
has access. Extract the download and rename its folder to `skill-source`.

Record the source URL and commit for later reference. Remove credentials,
private keys, `.env` files, and sensitive sample data before importing.
Keep private skills private.

### 2. Import a development copy

Place `skill-source` beside `docker-compose.yml` on the Docker host. If the host
is remote, upload it there using your normal secure file-transfer method.

With the deployment running:

```sh
docker compose cp ./skill-source hermes-sandbox:/tmp/skill-source
docker compose exec hermes-sandbox mkdir -p /workspace/repos
docker compose exec hermes-sandbox cp -R /tmp/skill-source /workspace/repos/my-skills
```

Use a **fresh destination name** instead of `my-skills` for later imports.
Do not overwrite unfinished work. This copy is writable by the sandbox and
survives restarts. It is not automatically activated as a skill.

The upload must fit in the sandbox's 256 MiB temporary storage. After a successful
copy, delete just the temporary upload:

```sh
docker compose exec hermes-sandbox rm -r /tmp/skill-source
```

### 3. Ask Hermes to inspect, then test

Send this through your API client or Discord:

> Inspect `/workspace/repos/my-skills` in the SSH sandbox. Explain its skills
> and scripts before running anything. Work only in that development folder.
> Do not request credentials, change active skills, or publish changes.

Read the explanation, then approve specific tests or changes. A prompt is not a
security control: imported instructions and code may still be unsafe.
Python dependencies may require a virtual environment inside the workspace.
The current sandbox does not include Git.

<details>
<summary><strong>Activate an approved skill in Hermes</strong></summary>

Testing a development copy does not install it. After reviewing all files and
rejecting symbolic links (shortcuts to other paths), copy only the approved
skill folder into the active library.

Replace the source path below with the folder containing your skill's
`SKILL.md`. Some repositories store skills at their root, not under `skills/`.

First check that the destination does not exist:

```sh
docker compose exec hermes-sandbox test ! -e /workspace/skills/my-skill
```

**Only if that command succeeds**, copy and restart:

```sh
docker compose exec hermes-sandbox cp -R /workspace/repos/my-skills/skills/my-skill /workspace/skills/my-skill
docker compose restart hermes-gateway
```

Restarting interrupts active conversations. Back up an existing skill before
replacing it; these instructions intentionally do not overwrite one.

**Limitation:** the active library is shared and writable by sandbox code.
Human review is a workflow, not an enforced approval barrier.

</details>

## Save to GitHub

Export the skill into a **new** local folder:

```sh
mkdir skills-export
docker compose cp hermes-sandbox:/workspace/repos/my-skills/skills/my-skill ./skills-export/
```

Adjust the source to your skill's actual location. To export an active skill,
use `hermes-sandbox:/workspace/skills/my-skill` instead.

**Without the command line:** use [GitHub Desktop](https://desktop.github.com/)
on your computer to open your skills repository (or your own fork). Transfer
the export from the Docker host if necessary, then copy the reviewed skill into
that repository. Review new and changed files, commit (save a version), and push
(upload). Prefer a new branch and a pull request (a change proposal) instead of
changing the main version directly.

Never publish tokens, private keys, `.env`, sensitive data, or an entire Hermes
storage volume. Keep private skills in a private repository.

<details>
<summary><strong>Command-line alternative</strong></summary>

Copy the export into your separate skills repository checkout first. From that
checkout, adapting the path and branch name:

```sh
git switch -c skills/my-skill-update
git add -- skills/my-skill
git diff --cached --check
git diff --cached -- skills/my-skill
git commit -m "Update tested my-skill Hermes skill"
git push -u origin skills/my-skill-update
```

Review the staged diff before committing, then open a pull request on GitHub.
Only stage the files you intend to publish.

</details>

Exports are snapshots, not live sync. Repeat export and review for later changes.
Persistent Docker storage is **not a Git backup**.

## Everyday commands

| Task | Command |
| --- | --- |
| Check health | `docker compose ps` |
| Read recent logs | `docker compose logs --tail=100` |
| Apply `.env` changes | `docker compose up -d` |
| Stop without deleting data | `docker compose down` |
| Start again | `docker compose up -d --wait` |

To upgrade, **back up all four volumes first**, then:

```sh
docker compose build --pull
docker compose up -d --wait
```

The upstream `latest` image changes over time. For controlled production
upgrades, pin `HERMES_IMAGE` to a tested digest and run the smoke test before
upgrading. There is no automatic updater.

> [!CAUTION]
> `docker compose down -v` permanently deletes skills, workspace, configuration,
> and keys. Ordinary `docker compose down` preserves them.

## Troubleshooting

| Symptom | First thing to check |
| --- | --- |
| Deployment fails or a service is unhealthy | Run `docker compose logs --tail=100`; check disk space, memory, and Docker image access. Do not share logs without checking for secrets. |
| `.env` is missing | Copy `.env.example` to `.env` in the project folder. |
| Model requests fail | Check `OPENAI_API_KEY`, account quota, and access to `HERMES_MODEL`. Healthy startup is not a paid inference test. |
| API returns `401` or `403` | Use the Hermes API key, not your OpenAI key; retrieve the current key again. |
| Client cannot reach port 8000 | It binds to host loopback. Use the host itself, an SSH tunnel, or a properly configured private proxy route. |
| Discord does not respond | Check the real token, allowed user IDs, Message Content Intent, invitation, and Hermes pairing policies. |
| Edited `.env` has no effect | Run `docker compose up -d`, not just `restart`. |
| Imported skills are not active | Development files under `/workspace/repos` are not automatically installed. Follow the activation instructions above. |

<details>
<summary><strong>SSH host-key mismatch after replacing sandbox storage</strong></summary>

A changed SSH host key is deliberately rejected. First verify that you
intentionally replaced the sandbox workspace; an unexpected mismatch needs
investigation. Only after verifying the replacement:

```sh
docker compose exec --user hermes hermes-gateway ssh-keygen -R '[hermes-sandbox]:2222' -f /opt/data/.ssh/known_hosts
docker compose restart hermes-gateway
```

Do not disable host-key checking to hide a mismatch.

</details>

## Architecture and security

```text
API client / Discord
        |
        v
hermes-gateway — agent, messaging, provider keys, authenticated API
        |
        | key-authenticated SSH over the Compose network
        v
hermes-sandbox — non-root Python 3.11 and bash execution
```

| Protection | What it does | What it does not guarantee |
| --- | --- | --- |
| Separate execution container | Routes terminal commands through Hermes' supported SSH backend. | Other Hermes tools and agent code still run in the gateway. |
| Credential separation | Only the gateway receives `.env`; no provider keys or private client key are mounted in the sandbox. | The agent can send sensitive text in commands; explicitly registered skill credentials may be synced by Hermes. |
| Kernel hardening | Non-root UID/GID `10000`, `cap_drop: ALL`, `no-new-privileges:true`, read-only root filesystem. | Containers share a kernel; this is not VM isolation or protection against every kernel exploit. |
| Resource containment | Sandbox limits: 2 GiB RAM, 2 CPUs, 256 processes, 256 MiB temporary storage. | Persistent disk and network traffic remain possible; the gateway needs its own resources. The entire host is not guaranteed safe from exhaustion. |
| Restricted API exposure | Authenticated port 8000, host-loopback binding, dashboard disabled. | A public proxy still needs TLS and preserved authentication. |

Shared writable skills are **not a trust boundary**: sandbox changes can affect
future agent behavior. The bridge network allows outbound internet and access
to reachable network services. Use host/firewall egress policies for sensitive
networks. Do not add the Docker socket or override the fixed service UIDs.

<details>
<summary><strong>SSH and startup details</strong></summary>

Hermes uses `terminal.backend: ssh` and `TERMINAL_SSH_*`, not an assumed
`SANDBOX_HOST` transport. The sandbox has a real SSH server on internal port
2222; an idle Python container alone cannot execute remote commands.

Keys are generated at runtime. Only the public client authorization key is
shared with the sandbox, read-only. Password/root login, environment forwarding,
TCP/agent forwarding, PTYs, and user RC scripts are disabled. Host verification
uses trust on first use on the private network and then persists the fingerprint.

The gateway preserves upstream s6 initialization, supervision, and privilege
dropping. A startup hook prepares keys and configuration before upstream restores
gateway services. Managed model and SSH settings are reasserted on startup;
other Hermes configuration is preserved.

Health checks cover the authenticated API and SSH execution. Startup waits for
the sandbox. `restart: unless-stopped` handles container exits and host restarts;
Docker does not automatically restart a live process just because it is unhealthy.

</details>

### Where your data lives

Docker **named volumes** are persistent storage managed by Docker, without
host-folder path changes or manual ownership fixes.

| Volume | Contains | Access |
| --- | --- | --- |
| `hermes_data` | Config, state, private SSH key, known hosts, API token | Gateway only |
| `hermes_skills` | Active skills | Gateway and sandbox, writable |
| `hermes_workspace` | Development files, sandbox home, SSH host key | Sandbox only |
| `hermes_public_keys` | Public authorized client key | Gateway writable; sandbox read-only |

## Developer guide

<details>
<summary><strong>Run validation</strong></summary>

From the project folder, using Python in your preferred virtual environment:

```sh
python3 -m pip install -r tests/requirements.txt
python3 -m unittest discover -s tests -v
docker compose config --quiet
python3 tests/smoke.py
```

The Compose check needs `.env` from setup and prints no expanded credentials.
The Docker smoke test uses its own project and synthetic credentials, makes no
paid model calls, and removes its test containers, volumes, and tagged images.
It may download the large upstream image.

Checks cover real Hermes SSH execution, API authentication and token generation/
rotation, credential isolation, capability/resource settings, and recreation
persistence. GitHub Actions runs the same checks on pushes and pull requests.
These checks do not exercise paid inference or live Discord login.

</details>

<details>
<summary><strong>Repository integration roadmap — not implemented</strong></summary>

| Stage | Planned behavior |
| --- | --- |
| Read-only import | Declare multiple public/private repositories and pinned revisions; fetch into separate development folders without executing or activating code. |
| Private access | Sandbox-only read-only deploy keys per repository, or narrowly scoped read tokens. No credentials in URLs or images. |
| Reviewed activation | Explicit promotion and rollback, separating active skills from sandbox writes while preserving Hermes SSH synchronization. |
| Optional publishing | Prefer host-side publishing; for autonomous work, limit a separate write credential to a dedicated fork and propose reviewed PRs. |

These features need implementation and testing. Adding a repository URL or
GitHub token to `.env` does not enable them today. Any credential readable by
sandbox code can be stolen by that code; a read-only secret file prevents
modification, not disclosure. Write credentials are safest outside the sandbox.

</details>

---

**New to the terminology?** A *container* runs software in a separate environment.
A *gateway* connects the agent to messages and model services. A *sandbox* limits
where terminal tasks run. A *commit* saves a Git version; a *push* uploads it;
a *pull request* proposes changes for review.
