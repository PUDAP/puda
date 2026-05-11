# BEARS Skills

A local repository of PUDA skills for BEARS machine operation and experiment workflows.

## Overview

This repository contains skills for PUDA work at BEARS, following the [Agent Skills](https://agentskills.io) standard. Each skill lives in its own directory with a required `SKILL.md` and optional `references/`, `scripts/`, or `assets/`.

These skills help agents select the correct PUDA-connected machine, load the right machine reference, choose the correct experiment workflow, and ask for required inputs before generating commands, protocols, reports, or experiment logs.

## Skill Modules

| Skill | Description |
|-------|-------------|
| **bears-machines** | PUDA machines skill for machines at BEARS. Use when selecting a BEARS machine, checking capabilities, loading machine references, or generating machine/protocol commands. |
| **bears-workflows** | PUDA workflow skill for BEARS experiments. Use when selecting, setting up, or running experiment workflows such as colour mixing optimization or viscosity optimization. |

## BEARS Machine Skills

The `bears-machines` skill covers PUDA-connected machines available at BEARS.

| Machine | Machine ID | Description |
|---------|------------|-------------|
| **First Machine** | `first` | Liquid handling and deck operations, including aspirate, dispense, attach tip, drop tip, and sequenced wet-lab protocol steps. |
| **Biologic Machine** | `biologic` | Electrochemical testing and characterization, including OCV, CA, PEIS, GEIS, CV, and MPP variants. |
| **Balance Machine** | `balance` | Gravimetric mass measurement using an Arduino-based USB load-cell balance on Linux, with tare, freshness checks, and NATS telemetry. |
| **Opentrons Machine** | `opentrons` | OT-2 liquid handling and protocol generation, including labware setup, pipetting, flow control, CSV-driven loops, and camera capture. |


## BEARS Workflows

The `bears-workflows` skill covers PUDA experiment workflows used at BEARS.

| Workflow | Description |
|----------|-------------|
| **colour-mixing-opt** | Iterative RGB dye mixing optimization using OT-2 dispensing, camera feedback, image processing, RMSE scoring, and Bayesian Optimization or LLM suggestions. |
| **viscosity-optimization** | Iterative tuning of OT-2 liquid handling parameters for viscous fluids using PUDA balance machine feedback, transfer-error calculation, Bayesian Optimization or LLM suggestions, and final `puda-report` reporting. |


## CLI Reference

Common PUDA CLI commands used by these skills:

```bash
puda
├── protocol
│   ├── run                  Run a protocol on machines via NATS
│   └── validate             Validate a protocol JSON file
├── machine
│   ├── list                 Discover machines via heartbeat
│   ├── state <machine_id>   Get the state of a machine
│   ├── reset <machine_id>   Reset a machine
│   └── commands <machine_id> Show available commands
├── init [path]              Initialize a new PUDA project
├── skills
│   ├── install              Install agent skills
│   └── update               Update agent skills
└── db
    ├── exec [sql]           Execute SQL queries on the database
    └── schema               Display the database schema
```

## Installing Skills With The PUDA CLI

Run these from a PUDA project directory after `puda init` if you are starting fresh.

**Install** - first-time setup or full sync from the configured skill source:

```bash
puda skills install
```

**Update** - refresh skills when upstream or local skill definitions change:

```bash
puda skills update
```

## Developing And Testing Skills

To try skills from a branch or local checkout before they land on the main skill source, use the skills CLI.

**GitHub branch** - substitute your branch name for `<branch_name>`:

```bash
npx skills add https://github.com/PUDAP/skills/tree/<branch_name> -y
```

**Local directory** - path to this repository or another folder containing skill packages:

```bash
npx skills add ./bears-skills -y
```

