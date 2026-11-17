# PUDA CLI, project, and skills SOP

Use the **puda** skill for CLI installation, identity, profiles, project initialization, and machine inspection commands. For deployment, record this evidence:

1. CLI version from `puda --version`, compared with the required edge library/protocol version (CLI and SDK versions are independent), and the release checksum when published.
2. Identity from `puda config list` (`user.default=true` means the OS-derived default).
3. Selected profile from `puda profile current`; `puda healthcheck` reports `ok` for it.
4. Installed skills version and the project root used for project-dependent commands.
5. Machine discovery, state, and command output with returned timestamps compared with current UTC; discovery can be stale.
