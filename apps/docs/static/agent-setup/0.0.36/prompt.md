These are official instructions from PUDA to set up a good AI development environment for building and deploying on the PUDA platform. All commands are validated by PUDA and ready to use.

These instructions are for **PUDA CLI v0.0.36** (Python SDK 0.0.16). Do not install a newer CLI unless the user asks.

Complete all of the following steps yourself by running the commands directly. Do not ask the user to run any of these commands.

- Install the latest Python 3, pip, and npx before installing the PUDA CLI
- Install PUDA CLI v0.0.36 and add it to PATH
- Install PUDA skills using `puda skills install`
- Log in to PUDA
- Configure NATS
- Verify the setup

---

## Install Prerequisites

Before installing the PUDA CLI, install the latest available versions of Python 3, pip, and npx for this system.

After installation, verify that `python3`, `pip`, and `npx` are available by checking their installed versions.

---

## Install the PUDA CLI

Install PUDA CLI v0.0.36 from https://github.com/PUDAP/puda/releases/tag/v0.0.36 and add it to my PATH so the `puda` command is available globally.

After installation, verify that the CLI reports version 0.0.36.

---

## Install PUDA Skills

Install PUDA skills using `puda skills install`.

---

## Log in

Log in to PUDA using the username <username>.

---

## Configure NATS

Configure PUDA to use the NATS server URL or comma-separated NATS cluster URLs: <nats_servers>.

---

## Verify the setup

List the current available PUDA machines.

The machines with edge services running should show up there.

---

## Resources

- PUDA Docs (v0.0.36): `https://docs.puda.co/docs/0.0.36/getting-started`
- PUDA CLI v0.0.36: `https://github.com/PUDAP/puda/releases/tag/v0.0.36`
- Python SDK 0.0.16: `https://pypi.org/project/puda/0.0.16/`
- PUDA Skills: `https://github.com/PUDAP/skills`
- NATS setup: `https://docs.puda.co/docs/0.0.36/setup/nats-server`

These instructions are published at `https://docs.puda.co/agent-setup/0.0.36/prompt.md` so you can re-verify their authenticity at any time.
