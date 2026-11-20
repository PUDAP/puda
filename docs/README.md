# puda-docs

View the docs at [docs.puda.co](https://docs.puda.co).

This website is built using [Docusaurus](https://docusaurus.io/), a modern static website generator.

## Installation

```bash
pnpm install
```

## Local Development

```bash
pnpm start
```

This command starts a local development server and opens up a browser window. Most changes are reflected live without having to restart the server.

## Docs versions

The default docs (`/docs/...`) are **v0.1.x** (CLI v0.1.0, Python SDK 0.0.17). **v0.0.36** is at `/docs/0.0.36/`.

`docs/` is the v0.1.x source. Frozen copies live in `versioned_docs/`.

To freeze another release:

```bash
npx pnpm docs:version 0.2.0
```

That copies `docs/` into `versioned_docs/version-0.2.0/` and updates `versions.json`. Then set `lastVersion` / version labels in `docusaurus.config.ts`.

## Build

```bash
pnpm build
```

This command generates static content into the `build` directory and can be served using any static contents hosting service.

## Deployment

Using SSH:

```bash
USE_SSH=true pnpm deploy
```

Not using SSH:

```bash
GIT_USER=<Your GitHub username> pnpm deploy
```

If you are using GitHub pages for hosting, this command is a convenient way to build the website and push to the `gh-pages` branch.
