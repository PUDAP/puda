# Skills migration to the PUDA monorepo

## Status and ownership

The canonical source is now `PUDAP/puda/skills/`, alongside the CLI and SDK.
These are ordinary source files, **not a Git submodule or nested repository**.
The initial import copies the separate skills checkout's working tree, including
its pending `puda/SKILL.md` restructure. No `.git`, environments, caches, or
temporary files belong in the subtree. `puda-memory` is absent: run-note recording
belongs in `puda-protocol`, and retrieval/analysis notes in `puda-data`.

The original checkout/repository is preserved, not archived or deleted. CLI
0.1.6 is the first release containing this subtree and installer migration.
Earlier published tags do not gain this subtree retroactively. Changes to the
old repository require separate authorization.

## Installation policy

After installing a CLI release containing this migration:

```sh
puda skills install
# On a CLI upgrade, or to migrate an old PUDAP/skills global installation:
puda skills update
```

Both commands re-add the official subtree at the binary's release tag:
`https://github.com/PUDAP/puda/tree/v<VERSION>/skills`. GoReleaser's `0.1.6` and `v0.1.6` resolve to the same
`v0.1.6` tag; a release-candidate suffix is retained. Version numbers here are
examples, not a claim that those releases have been published. Streamlit is not
installed or refreshed automatically, and existing Streamlit skills are not removed.
It remains available as an explicit custom source: `puda skills install streamlit/agent-skills`
or `puda skills update streamlit/agent-skills`.

Each source uses `npx skills add <source> -y -g`. There is **no subsequent blanket
`npx skills update`**. Missing tags/subtrees or installer errors stop the command;
there is no silent fallback to main. This is a Git tag pin, not a content-addressed
commit pin; maintainers must not move published release tags.

```sh
# Explicit opt-in to development skills, including for locally built CLIs:
puda skills install --ref main
puda skills update --ref main
# Select a specific release tag instead of the installed CLI release:
puda skills install --ref v0.1.6
puda skills update --ref v0.1.6
# Optional custom sources are passed through unchanged, after the defaults:
puda skills install owner/custom#stable
puda skills update owner/custom#stable
```

`dev`, dirty development builds, snapshots, and Go pseudo-versions have no known
release tag and fail before invoking npx unless an explicit `--ref` is supplied. To test
unpublished local changes, bypass the release defaults explicitly:

```sh
npx skills add /absolute/path/to/puda/skills -y -g
```

`--ref <git-reference>` accepts simple branch or tag names, starting with a letter
or digit and containing only letters, digits, dots, underscores or hyphens.
Empty refs, slashes, `..`, trailing dots and `.lock` are rejected before npx runs.
Refs are used literally: `--ref 0.1.6` does not add a `v` prefix. This restriction
keeps the installer's `/tree/<ref>/skills` parser unambiguous; revision expressions
and slash-containing branches are not supported by this option.
`--ref main` means the **remote main branch**, not the local working tree. Do not use
an old CLI's installer expecting it to know the new source; upgrade the CLI first,
or explicitly add the new release subtree with npx.

## Coexistence, locks, and migration precautions

- Back up customized installed skill files before re-adding. The installer keys
  installations and global lock entries by **skill name**, not repository name.
  Same-name skills replace the old source entry/files; two repositories do not
  give you two independent global versions of `puda`.
- With skills CLI 1.8.1, the global lock is `~/.agents/.skill-lock.json`. A GitHub
  source records `source`, `sourceUrl`, `ref`, and `skillPath`; the new source
  should be `PUDAP/puda`, with the chosen tag and `skills/<name>/SKILL.md` path.
  Inspect the lock and actual agent files after migration. Do not hand-edit the
  lock to claim an install happened.
- Re-addition is intentional: merely running an updater against an existing
  `PUDAP/skills` entry will not migrate its repository. PUDA's update command
  re-adds the official defaults even if old entries already exist.
- Legacy-only names such as `puda-memory` are **not removed automatically**.
  Review customizations, then explicitly remove the retired skill if desired:
  `npx skills remove puda-memory -g -y`. This cleanup is a separate user action.
- Global installs can coexist with project-local skills and `skills-lock.json`.
  PUDA does not rewrite project locks or remove project-local copies; an agent
  may prefer the local copy. Review those separately to avoid stale guidance.
- Unspecified custom sources remain untouched. Explicit custom arguments are
  re-added after the defaults and may intentionally overwrite same-name skills,
  including official ones. Passing `PUDAP/skills` explicitly reinstalls the old
  source; remove it from scripts rather than expecting it to be rewritten.
- The current upstream updater preserves recorded refs, but it can refresh other
  installed sources and select a different scope. PUDA avoids that broad action
  entirely; its `update` now means re-add defaults plus explicitly named sources,
  **not update every installed custom skill**.

## Verified installer contract and experiment

Inspected the actual published **skills 1.8.1** npm tarball, its
`docs/commands.md`, and bundled parser/lock/update implementation. Also inspected
`vercel-labs/skills` source at `af860243b8c68053b3b5151e3732b9322933674d`:

- `src/source-parser.ts` parses GitHub `/tree/<ref>/<subpath>` into repository,
  ref, and subpath. Tags without slashes fit this form. Do not guess that a
  slash-containing branch works in the same form; use the upstream documented
  fragment-ref syntax if needed.
- `src/add.ts` writes the selected ref and skill path into the global lock;
  `src/skill-lock.ts` keys entries by name.
- Upstream documentation: <https://github.com/vercel-labs/skills/blob/main/docs/commands.md>
  and parser: <https://github.com/vercel-labs/skills/blob/main/src/source-parser.ts>.

The actual `npx --yes skills@1.8.1 add ... -y -g --agent claude-code` experiment
used an isolated scratch HOME, XDG directories, npm cache, TMPDIR, and working
directory; no live agent profile was selected:

1. Remote `PUDAP/skills` installed **8** skills, including `puda-memory`.
2. Re-adding the new local `puda/skills` directory installed **7** skills and
   replaced their same-name lock sources. The legacy `puda-memory` entry/files
   remained, proving the coexistence warning above.
3. Remote `https://github.com/PUDAP/puda/tree/main/skills` parsed as repository
   `PUDAP/puda`, ref `main`, subpath `skills`, then failed with
   `SKILLS_NO_VALID_SKILLS`: the migration is not published. This is a release
   gate, not a syntax failure. A full remote release-tag install must be rerun
   after an approved release includes the subtree; do not claim it passed now.

## Old-repository pointer plan (not executed)

After the user approves release notes and publication, and a real release-tag
install succeeds:

1. Request separate permission to update the old `PUDAP/skills` README.
2. Add a prominent pointer to `PUDAP/puda/tree/main/skills` and this migration
   guide, naming the first released CLI version with this installer behavior.
3. Keep existing files/history available for old pinned clients. Do not delete,
   archive, redirect, or rewrite the old repository without separate approval.
4. Update references in external docs only within their separately approved scope.

## Verification before an approved release

Run CLI `go test ./...` and `go vet ./...` from `apps/cli`, run Python skill tests,
and check local Markdown resource links. Inspect `git ls-files --stage -- skills`
for mode `160000` and ensure no `.git` file or directory exists under `skills/`.
Keep the original source checkout and unrelated pending CLI/SDK changes intact.
After publication, rerun the remote pinned install and verify lock ref/path and
installed file contents before announcing migration completion to users.
