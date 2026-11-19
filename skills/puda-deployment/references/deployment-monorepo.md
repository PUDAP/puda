# Deployment monorepo

One PUDA deployment (lab, factory line, pilot plant, or cell) lives in one Git repository, usually `puda-<deployment>`. It holds every edge, driver, Docker service, configuration, and deployment skill, even when they run on different hosts. Docs: <https://docs.puda.co/docs/setup/deployment-monorepo>.

## Rules

- Add templates as plain folders tracked by the deployment repository. Never `git clone` a template into it, never add a submodule, never leave a nested `.git`.
- Copy only what the deployment uses: the chosen NATS layout plus `jetstream/`, and only the one logger database (`influxdb`, `clickhouse`, `postgres`, or `reductstore`) from `puda-logger`.
- Put deployment machine and workflow skills under `skills/<skill-name>/` and commit them. Run `puda skills install <path-to-monorepo>/skills`: local paths are symlinked, not copied, so edits stay in Git. Check that the output lists `symlinked <target> -> <source>` for each skill. If it reports a copied folder with the same name, ask the user before removing that folder, then re-run. Re-run after adding a skill; edits need no reinstall. Commit skill changes in the deployment repository.
- Commit `.env.example` with placeholders. Keep `.env`, tokens, and keys ignored at the repository root; copied subfolders may lose the template's root `.gitignore`.
- Each host checks out the same repository and runs only its folders. Record host-to-folder mapping and template source commits in the deployment `README.md`.
- If the user has no deployment repository yet, ask where it should live before creating one. Do not create or push a remote repository without approval.
- Exception: tools installed into the agent itself, such as Hermes plugins, are not deployment code.

## Layout

```text
puda-<deployment>/
├── README.md
├── .gitignore
├── edges/<machine_id>/          # code that talks to machines
├── services/                    # shared services, each copied from a template
│   ├── nats/
│   ├── chrony/
│   ├── <database>/{server,logger}/   # only the database in use; logger = PUDA logger
│   ├── grafana/
│   └── livestream/
└── skills/<skill-name>/
```

## Copy a template folder

From the repository root:

```bash
mkdir -p <dest>
curl -fsSL https://github.com/<owner>/<template>/archive/refs/heads/main.tar.gz \
  | tar -xz --strip-components=<n> -C <dest> [<template>-main/<subpath>]
```

| Destination | Source archive | `--strip-components` and member |
|---|---|---|
| `edges/<machine_id>` | `PUDAP/edge-python-template` (or `edge-python-gui-template`) | `1` |
| `services/nats` | `PUDAP/puda` | `3`, `puda-main/infra/nats/<layout> puda-main/infra/nats/jetstream` |
| `services/chrony` | `PUDAP/puda` | `3`, `puda-main/infra/chrony` |
| `services/<database>` | `PUDAP/puda-logger` | `2`, `puda-logger-main/<database>` |
| `services/grafana` | `PUDAP/puda-grafana` | `1` |
| `services/livestream` | `PUDAP/livestream` | `1` |

For a private template: `gh repo clone <owner>/<template> /tmp/<template> -- --depth 1`, copy the folder, then delete the clone. Record the source commit with `git ls-remote <url> HEAD`. Verify afterwards that `find . -mindepth 2 -name .git` prints nothing.
