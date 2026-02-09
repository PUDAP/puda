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
git tag -a v0.0.1 -m "first release"
git push origin v0.0.1

just publish
```

For a snapshot/dry-run:
```bash
just publish-snapshot
```

## Available Commands

Run `just` or `just --list` to see all available recipes.
