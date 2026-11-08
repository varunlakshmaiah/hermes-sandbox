# hermes-sandbox

**Build skills. Test them in a separate container. Save reviewed work to GitHub.**

[Quick start](#quick-start) · [Connect](#connect-to-hermes) · [Skills](#use-your-skills) ·
[Commands](#everyday-commands) · [Troubleshooting](#troubleshooting) ·
[Deployment](docs/deployment.md) · [Security](docs/security.md) · [Development](docs/development.md)

Hey there! Created by [@varunlakshmaiah](https://github.com/varunlakshmaiah).
I built this to be the most frictionless, set-and-forget way to run an autonomous
Hermes agent safely.

## What is this?

**Goal: securely build and test Hermes skills and save them to a Git repository.**
This project runs [Hermes Agent](https://github.com/NousResearch/hermes-agent) in two
Docker containers: a **gateway** that holds your keys and runs the agent, and a
**sandbox** where its terminal commands run — with no access to your keys.

| You want to… | Use it for… |
| --- | --- |
| Create or improve a skill | Prototype instructions and Python helpers, then test changes. |
| Try an existing skill | Inspect unfamiliar code before deciding to trust it. |
| Automate small tasks | Process non-sensitive sample data or run repeatable checks. |
| Work through chat | Connect an OpenAI-compatible client or an access-controlled Discord bot. |
| Keep a skills library | Export reviewed skills to GitHub for history and collaboration. |

> [!IMPORTANT]
> This is risk reduction, not a guarantee that arbitrary code is safe. Containers share
> the host kernel. Use a separate virtual machine for genuinely hostile workloads.
> See [Architecture and security](docs/security.md).

## Quick start

You need [Docker](https://docs.docker.com/get-docker/) (Compose 2.24+) and an OpenAI
API key. On Windows, use WSL.

```sh
git clone https://github.com/varunlakshmaiah/hermes-sandbox.git
cd hermes-sandbox
./hermes setup
```

`setup` asks for your OpenAI key (stored privately in `.env`), downloads the tested
images, starts both containers, waits until they are healthy, and prints everything your
client needs. That's it — storage, SSH keys and the API key are created automatically,
and the services restart on their own after a reboot.

> [!TIP]
> On Dokploy, Portainer or similar, deploy `docker-compose.yml` and set
> `OPENAI_API_KEY` as an environment variable. No `.env` file or build is needed.
> See the [deployment guide](docs/deployment.md).

## Connect to Hermes

Use any OpenAI-compatible client:

| Client field | Value |
| --- | --- |
| Base URL | `http://127.0.0.1:8000/v1` |
| API key | Printed by `setup`; show it again with `./hermes key` |
| Model | `hermes-agent` |

Your **OpenAI key** pays for the model; your **Hermes API key** controls access to this
deployment. The API only accepts connections from the Docker host — use an SSH tunnel to
connect from another computer. For Discord, remote access and other settings, see the
[deployment guide](docs/deployment.md).

## Use your skills

A **skill** is a folder containing `SKILL.md` instructions plus optional scripts.

```text
Download a reviewed copy → Import → Inspect and test → Activate → Export → Save to GitHub
```

**1. Import.** Download your skills repository (for example **Code → Download ZIP** on
GitHub, which also works for private repositories you can access), extract it, then:

```sh
./hermes import ~/Downloads/my-skills-main my-skills
```

This copies it into the sandbox at `/workspace/repos/my-skills`, skipping `.git` and
`.env` files. Nothing is executed or activated. Remove any other credentials or sensitive
data first.

**2. Inspect and test.** Ask Hermes through your client:

> Inspect `/workspace/repos/my-skills` in the SSH sandbox. Explain its skills and scripts
> before running anything. Work only in that folder. Do not request credentials or
> publish changes.

Read the explanation, then approve specific tests or changes. A prompt is not a security
control: imported instructions and code may still be unsafe.

**3. Activate** an approved skill (the folder containing its `SKILL.md`):

```sh
./hermes activate my-skills/skills/my-skill
```

The gateway rejects links and files outside the skill, and never overwrites an existing
skill unless you add `--replace`. New conversations pick it up; run `./hermes restart`
if Hermes does not list it.

**4. Export and save to GitHub.**

```sh
./hermes export my-skill                      # an active skill
./hermes export my-skills/skills/my-skill     # or a development copy
```

Files land in `./skills-export/`. Open your skills repository in
[GitHub Desktop](https://desktop.github.com/) (or the command line), copy the reviewed
skill in, review the changes, commit, and push — ideally on a new branch with a pull
request. Never publish tokens, private keys, `.env` files or sensitive data.

## Everyday commands

| Task | Command |
| --- | --- |
| Check health | `./hermes status` |
| Read recent logs | `./hermes logs` |
| Apply `.env` changes | `./hermes up` |
| Stop without deleting data | `./hermes down` |
| Update to the latest tested release (backs up first) | `./hermes update` |
| Back up / restore everything | `./hermes backup` / `./hermes restore backups/hermes-<timestamp>` |
| All commands | `./hermes help` |

## Troubleshooting

| Symptom | First thing to check |
| --- | --- |
| `setup` or `up` fails | It prints recent logs. Check disk space, memory and Docker access. Do not share logs without checking for secrets. |
| Model requests fail | Check `OPENAI_API_KEY`, account quota, and access to `HERMES_MODEL`. A healthy start is not a paid inference test. |
| API returns `401` or `403` | Use the Hermes API key (`./hermes key`), not your OpenAI key. |
| Client cannot reach port 8000 | It binds to host loopback. Use the host itself or an SSH tunnel. Change the port with `HERMES_API_PORT`. |
| Edited `.env` has no effect | Run `./hermes up`, not just a restart. |
| Startup says allow-all access is refused | Remove `DISCORD_ALLOW_ALL_USERS`/`GATEWAY_ALLOW_ALL_USERS`; list users in `DISCORD_ALLOWED_USERS`. |
| Imported skills are not active | Files under `/workspace/repos` are development copies. Use `./hermes activate`. |

<details>
<summary><strong>SSH host-key mismatch after replacing sandbox storage</strong></summary>

A changed sandbox host key is deliberately rejected. First verify that you intentionally
replaced the sandbox workspace; an unexpected mismatch needs investigation. Only then:

```sh
docker compose exec --user hermes hermes-gateway ssh-keygen -R '[hermes-sandbox]:2222' -f /opt/data/.ssh/known_hosts
./hermes restart
```

</details>

---

**New to the terminology?** A *container* runs software in a separate environment. A
*gateway* connects the agent to messages and model services. A *sandbox* limits where
terminal tasks run. A *commit* saves a Git version; a *push* uploads it; a *pull request*
proposes changes for review.
