# PUDA docs

Source for [docs.puda.co](https://docs.puda.co), part of the [PUDA monorepo](../../README.md). Run the commands below from this `apps/docs/` directory; it is a standalone pnpm project, separate from the root Nx workspace.

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

The default docs (`/docs/...`) are **v0.1.x** (CLI v0.1.x, Python SDK 0.0.x), frozen in `versioned_docs/version-0.1.6/`. **v0.2.0 (beta)** is at `/docs/0.2.0/` and **v0.0.36** at `/docs/0.0.36/`.

`docs/` is the v0.2.0 source (CLI v0.2.0-rc1, Python SDK 0.1.0rc1). It is labelled beta with the unreleased banner, and `lastVersion` keeps v0.1.x the default. Edit `docs/` for 0.2 changes, and `versioned_docs/version-0.1.6/` for fixes to the v0.1.x docs.

When v0.2.0 is released, freeze it and make it the default:

```bash
npx pnpm docs:version 0.2.0
```

That copies `docs/` into `versioned_docs/version-0.2.0/` and updates `versions.json`. Then in `docusaurus.config.ts` set `lastVersion: '0.2.0'`, give the new version its label, and point `current` at the next release.

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

## Deployment

docs.puda.co is deployed by Cloudflare Workers Builds (worker `puda-docs`, root directory `apps/docs`) on every push to `main` that changes `apps/docs/`. Build command: `pnpm run build`; deploy command: `npx wrangler deploy` (uploads `build/` per `wrangler.jsonc`).
