# Using UV Workspaces

This guide explains how to set up and use workspace packages in a UV-managed Python monorepo.

## Overview

UV workspaces allow you to manage multiple related Python packages in a single repository. This enables:
- Shared dependencies across packages
- Local development with live code changes
- Easier refactoring across package boundaries
- Single lockfile for the entire workspace

## Workspace Structure

A UV workspace consists of:
1. **Root `pyproject.toml`** - Defines the workspace and its members
2. **Member packages** - Individual packages that are part of the workspace
3. **Shared lockfile** - Single `uv.lock` at the root

## Setting Up a Workspace

### 1. Root Configuration

Create or update the root `pyproject.toml`:

```toml
[tool.uv.workspace]
members = [
    "libs/comms",
    "libs/drivers",
    "services/first/edge",
    "services/first/mcp",
]
```

The `members` array lists all directories containing packages that should be part of the workspace.

### 2. Member Package Configuration

Each member package needs its own `pyproject.toml` with standard project metadata:

```toml
[project]
name = "puda-drivers"
version = "0.0.16"
description = "Hardware drivers for the PUDA platform."
requires-python = ">=3.10"
dependencies = [
    "nats-py>=2.12.0",
    "opencv-python>=4.12.0.88",
]
```

## Using Workspace Dependencies

### Adding a Workspace Dependency

When one workspace package depends on another, use the `tool.uv.sources` section to specify it's a workspace dependency:

**Example: `libs/comms/pyproject.toml`**

```toml
[project]
name = "puda-comms"
dependencies = [
    "nats-py>=2.12.0",
    "puda-drivers"  # Reference the workspace package
]

[tool.uv.sources]
puda-drivers = {workspace = true}  # Mark as workspace dependency
```

**Example: `services/first/edge/pyproject.toml`**

```toml
[project]
name = "first-edge"
dependencies = [
    "puda-drivers",
    "puda-comms",
]

[tool.uv.sources]
puda-drivers = {workspace = true}
puda-comms = {workspace = true}
```

### Key Points

- **No version constraints needed**: Workspace dependencies don't require version specifiers
- **Must specify `workspace = true`**: This tells UV to use the local workspace package instead of fetching from PyPI
- **Multiple workspace dependencies**: You can list multiple packages in `tool.uv.sources`

## Common Commands

### Install Dependencies

Install all workspace dependencies:

```bash
uv sync
```

This creates/updates the `uv.lock` file and installs all packages in editable mode.

### Update Dependencies

Update all packages to their latest versions:

```bash
uv sync --upgrade
```

Update a specific package:

```bash
uv sync --upgrade-package <package_name>
```

### Add a New Dependency

Add a dependency to a specific workspace package:

```bash
cd libs/comms
uv add nats-py
```

Or from the root:

```bash
uv add --package puda-comms nats-py
```

### Add a Workspace Dependency

To add a workspace dependency, edit the `pyproject.toml` manually:

1. Add the package name to `dependencies`
2. Add an entry in `[tool.uv.sources]` with `workspace = true`

Then run:

```bash
uv sync
```

### Run Commands in Workspace Context

Run commands with workspace dependencies available:

```bash
uv run python -m puda_comms
```

Or activate the environment:

```bash
source .venv/bin/activate  # or `.venv\Scripts\activate` on Windows
python -m puda_comms
```

## Workspace Package Development

### Editable Installs

Workspace packages are automatically installed in editable mode, so changes to source code are immediately available without reinstalling.

### Testing Changes

After modifying a workspace package:

1. No reinstall needed - changes are live
2. Run tests/scripts that use the package
3. If you add new dependencies, run `uv sync`

### Adding a New Workspace Package

1. Create the package directory structure
2. Add a `pyproject.toml` with project metadata
3. Add the directory to `members` in root `pyproject.toml`
4. Run `uv sync` to register it

## Example: Current Workspace Structure

```
puda/
├── pyproject.toml          # Workspace root
├── uv.lock                  # Shared lockfile
├── libs/
│   ├── comms/
│   │   └── pyproject.toml   # Depends on puda-drivers (workspace)
│   └── drivers/
│       └── pyproject.toml   # Standalone package
└── services/
    └── first/
        ├── edge/
        │   └── pyproject.toml  # Depends on puda-drivers, puda-comms (workspace)
        └── mcp/
            └── pyproject.toml  # No workspace dependencies
```

## Troubleshooting

### Package Not Found

If you get import errors:
1. Ensure the package is listed in `members` in root `pyproject.toml`
2. Run `uv sync` to update the lockfile
3. Verify `tool.uv.sources` has `workspace = true` for workspace dependencies

### Dependency Conflicts

If you encounter version conflicts:
- Check that all packages use compatible Python versions (`requires-python`)
- Ensure shared dependencies have compatible version ranges
- Use `uv sync --resolution=highest` to see resolution details

### Changes Not Reflecting

If code changes aren't visible:
- Ensure the package is installed in editable mode (automatic for workspace packages)
- Restart your Python interpreter/process
- Verify you're using the correct virtual environment

## Best Practices

1. **Keep workspace members organized**: Group related packages (e.g., `libs/`, `services/`)
2. **Use descriptive names**: Package names should be clear and unique
3. **Document dependencies**: Keep README files updated with dependency information
4. **Single lockfile**: Always commit `uv.lock` at the root
5. **Consistent Python versions**: Align `requires-python` across packages when possible

## References

- [UV Workspace Documentation](https://docs.astral.sh/uv/workspaces/)
- [UV Dependency Management](https://docs.astral.sh/uv/dependency-management/)
