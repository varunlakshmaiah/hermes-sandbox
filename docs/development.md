# Development guide

[← Back to README](../README.md)

## Layout

| Path | Purpose |
| --- | --- |
| `hermes` | Host CLI (POSIX `sh`, needs only Docker). |
| `docker-compose.yml` | Two services, four named volumes; prebuilt images with source fallback. |
| `docker/gateway.py` | Gateway startup hook (`prepare`), health check, and validated skill installer. |
| `docker/prepare-gateway.sh`, `docker/skills-owner.sh` | Gateway startup hooks wired into upstream's s6 `cont-init.d`. |
| `docker/sandbox.py` | Sandbox entrypoint (host key, sshd) and health check. |
| `tests/test_deployment.py`, `tests/test_cli.py` | Unit tests; no Docker daemon needed. |
| `tests/smoke.py` | End-to-end test against real containers. |

## Validate

```sh
python3 -m pip install -r tests/requirements.txt
ruff check . && ruff format --check .
shellcheck hermes docker/*.sh
python3 -m unittest discover -s tests -v
python3 tests/smoke.py   # needs Docker; builds images, no paid model calls
```

The smoke test uses its own Compose project and synthetic credentials, never reads your
`.env`, and removes its containers, volumes and images. It deploys through `./hermes`
and verifies API authentication, that Hermes' own terminal tool runs in the sandbox with
skills synced, credential isolation and limits, the import/activate/export workflow,
symlink rejection, backup/restore, and persistence across recreation. It does not
exercise paid inference or live Discord login.

## CI and releases

[`.github/workflows/validate.yml`](../.github/workflows/validate.yml) runs on every push and
pull request: lint (ruff, shellcheck, hadolint) and unit tests → smoke test → multi-arch
image builds. Pushes to `main` publish `:latest` and `:sha-…` images to GHCR; pushing a
`v*` tag publishes that tag. Users pin a release with `HERMES_SANDBOX_VERSION`.

Dependabot proposes weekly updates for the pinned upstream Hermes and Python images,
GitHub Actions, and test tools; each must pass the smoke test before merging.

After the first publish, make both GHCR packages **public** (Package settings → Change
visibility) so deployments can pull them without logging in. Until then, Compose builds
from source automatically.
