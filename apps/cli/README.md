# puda-cli

This project uses [just](https://github.com/casey/just) for task automation. Install just first:

```bash
# Install just (choose your method)
# macOS
brew install just

# Linux
# See https://github.com/casey/just#installation
```

## Development

### References

- https://github.com/golang-standards/project-layout

### Run in development mode
```bash
just dev [arguments]
# Example: just dev nats send --help
```

### Build
```bash
just build
```

### Install globally
```bash
just install
```

### Run tests
```bash
just test
```

### Format code
```bash
just fmt
```

### Clean build artifacts
```bash
just clean
```

### Publish

Requires [goreleaser](https://goreleaser.com/install/) to be installed:

```bash
just publish
```

For a snapshot/dry-run:
```bash
just publish-snapshot
```

## Usage

### With .env file configured
```bash
puda nats send --file commands.json
```

### With command-line overrides
```bash
puda nats send --file commands.json --user-id "..." --username "..." --nats-servers "..."
```

## Available Commands

Run `just` or `just --list` to see all available recipes.