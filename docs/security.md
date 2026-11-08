# Architecture and security

[← Back to README](../README.md)

```text
API client / Discord
        |
        v
hermes-gateway — agent, messaging, provider keys, authenticated API, active skills
        |
        | key-authenticated SSH over the Compose network
        v
hermes-sandbox — non-root Python 3.13 and bash execution
```

> [!IMPORTANT]
> This is risk reduction, not a guarantee that arbitrary code is safe. Containers share
> the host kernel. Use a separate virtual machine for genuinely hostile workloads.

## Protections

| Protection | What it does | What it does not guarantee |
| --- | --- | --- |
| Separate execution container | Routes terminal commands through Hermes' supported SSH backend. | Other Hermes tools and agent code still run in the gateway. |
| Credential separation | Only the gateway receives settings; no provider keys or private client key exist in the sandbox. | The agent can send sensitive text in commands; explicitly registered skill credentials may be synced by Hermes. |
| Kernel hardening | Non-root UID/GID `10000`, `cap_drop: ALL`, `no-new-privileges:true`, read-only root filesystem. | Containers share a kernel; this is not VM isolation. |
| Resource containment | Sandbox limits: 2 GiB RAM, 2 CPUs, 256 processes, 256 MiB `/tmp`. | Persistent disk and network traffic remain possible; the gateway needs its own resources. |
| Restricted API exposure | Bearer-authenticated port 8000, host-loopback binding, dashboard disabled. | A public proxy still needs TLS and preserved authentication. |
| Skill activation gate | `./hermes activate` streams files to the gateway, which accepts only regular files and directories (no links, no paths outside the skill, bounded size) and never overwrites without `--replace`. | Review is still a human decision: an activated skill's instructions influence the agent. |
| Chat access policy | Startup refuses allow-all chat settings; unknown Discord users are denied unless listed or paired. | Allowed users fully control the agent. |

## Skills trust model

Active skills live in the gateway's `hermes_skills` volume; the sandbox cannot write to
it directly. Hermes copies them into the sandbox (`~/.hermes/skills`) before running
commands, skipping symbolic links, and may copy edited files back after a session using
a data-only archive filter. Treat skill files the agent edits in the sandbox like any
other untrusted change.

The bridge network allows outbound internet access and access to reachable network
services. Use host or firewall egress policies for sensitive networks. Do not add the
Docker socket or override the fixed service UIDs.

## SSH and startup

Hermes uses `terminal.backend: ssh`. The sandbox runs an OpenSSH server on internal port
2222. Keys are generated at runtime; only the public client key is shared with the
sandbox, read-only, with the `restrict` option. Password and root login, environment and
TCP/agent forwarding, PTYs and user RC scripts are disabled. The gateway trusts the
sandbox host key on first use and then pins it.

The gateway keeps upstream's s6 initialization, supervision and privilege dropping. A
startup hook (`docker/gateway.py prepare`) writes keys and configuration after upstream
fixes volume permissions and before services start. Managed model, SSH, API and access
settings are reasserted on every start; other Hermes configuration is preserved.

Health checks cover the authenticated API plus SSH (gateway) and the SSH banner
(sandbox). `restart: unless-stopped` handles container exits and host restarts.

## Where data lives

| Volume | Contains | Access |
| --- | --- | --- |
| `hermes_data` | Config, state, private SSH key, known hosts, API key | Gateway only |
| `hermes_skills` | Active skills | Gateway only |
| `hermes_workspace` | Development files, sandbox home, synced skills, SSH host key | Sandbox only |
| `hermes_public_keys` | Public authorized client key | Gateway writable; sandbox read-only |

## Repository integration roadmap — not implemented

| Stage | Planned behavior |
| --- | --- |
| Read-only import | Declare repositories and pinned revisions; fetch into separate development folders without executing or activating code. |
| Private access | Sandbox-only read-only deploy keys per repository, or narrowly scoped read tokens. |
| Optional publishing | Prefer host-side publishing; for autonomous work, limit a separate write credential to a dedicated fork and propose reviewed PRs. |

Adding a repository URL or GitHub token to `.env` does not enable these today. Any
credential readable by sandbox code can be stolen by that code.
