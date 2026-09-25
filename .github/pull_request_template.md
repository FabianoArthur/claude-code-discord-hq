## What and why

<!-- What changes, and the reason. Link the issue if there is one. -->

## Checklist

- [ ] Tests added or updated; they fail without this change.
- [ ] `pytest`, `ruff check .`, `ruff format --check .` and `shellcheck install.sh` pass locally.
- [ ] Docs and `CHANGELOG.md` (*Unreleased*) updated if behavior changed.
- [ ] No real tokens, webhook URLs, server/user ids or personal paths anywhere in the diff.
- [ ] No test talks to Discord or touches the real `~/.claude`, `~/.config` or tmux sessions.
