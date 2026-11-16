# Edge source, packaging, and Compose SOP

## Repository

Verify GitHub access with repository metadata and `git ls-remote`. Interpret private-repository `404`/`403` as an access/SSO/permission issue, not a bad clone command. Inspect `git status` before pull or patch.

## Python/uv workspace

- Confirm `requires-python`, lockfile, workspace members, and package sources.
- A Docker build must copy every local workspace package required by the lockfile before `uv sync`.
- Verify package imports inside the built image, not only on the host.
- Decode bytes before applying string regex/parsers; add regression fixtures for real controller payload types.

## Compose

Inspect `.env.example`, actual environment source, build context, Dockerfile, volumes, network mode, restart policy, and healthcheck. Validate with `docker compose ... config -q`.

Use `--no-build --force-recreate` for a configuration-only change when the current image is known good. Use `--build` only when source/dependencies changed. A successful build is not a readiness result.
