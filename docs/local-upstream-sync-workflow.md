# Local Upstream Sync Workflow

Workflow for keeping Hanson's fork aligned with `upstream/main` while carrying
local Hermes gateway patches on a dedicated branch.

## Branch model

- `upstream/main` is the official upstream source of truth.
- `origin/main` mirrors `upstream/main`; do not develop directly on `main`.
- `mattermost-thread-fixes-v2` is the local patch branch.
- New local gateway/Mattermost fixes should be committed on `mattermost-thread-fixes-v2`.

## Standard sync flow

### 1. Check state

```bash
git status --short --branch
git branch -vv
```

Stash or commit any local work before rebasing.

### 2. Update remotes

```bash
git fetch upstream origin --prune
```

### 3. Mirror fork main to upstream

```bash
git push origin upstream/main:main
git branch -f main upstream/main
git branch --set-upstream-to=origin/main main
```

### 4. Rebase the patch branch

```bash
git switch mattermost-thread-fixes-v2
git rebase upstream/main
```

Resolve conflicts if needed, then continue the rebase.

## Verification

After rebasing or changing the patch branch, run targeted tests for the touched
areas.

Current useful command:

```bash
scripts/run_tests.sh \
  tests/gateway/test_config.py \
  tests/gateway/test_mattermost.py \
  tests/gateway/test_mattermost_channel_skills.py \
  tests/hermes_cli/test_gateway_service.py
```

For broader gateway routing/session changes, also run:

```bash
scripts/run_tests.sh tests/gateway/
```

On macOS, the full gateway suite may fail the Matrix E2EE attachment test if
`python-olm` cannot be built. Treat that as an environment dependency issue
unless Matrix files were changed.

## Publishing patch updates

```bash
git push --force-with-lease
```

## Rules of thumb

- Keep `main`, `origin/main`, and `upstream/main` identical.
- Keep local changes on `mattermost-thread-fixes-v2`.
- Rebase `mattermost-thread-fixes-v2` onto `upstream/main` before adding new patches.
- Use `--force-with-lease` after rebasing an already-pushed patch branch.
- Avoid editing `AGENTS.md` for local workflow preferences because upstream may change it often.
