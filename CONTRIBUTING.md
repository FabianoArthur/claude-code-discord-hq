# Contributing

Thanks for helping! Bug reports, docs fixes and pull requests are all welcome.

## Development setup

```sh
python3.11 -m venv .venv        # or any Python 3.11+
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest                # the whole suite, a few seconds
.venv/bin/ruff check . && .venv/bin/ruff format --check .
shellcheck install.sh
zsh shell/waiter.test.zsh       # needs zsh + tmux; runs on an isolated tmux socket
```

## Ground rules for tests

- **Never talk to Discord.** The Discord API and webhooks are always mocked. A test that needs a real server is a bug.
- **Never touch the developer's real environment.** No writes to `~/.claude`, the shell rc files or `~/.config`: use `tmp_path` and a temporary `HOME` (see `tests/conftest.py` and `tests/test_install_and_shell.py`). tmux tests use their own `-L` socket.
- **Use fake ids and secrets only.** Snowflakes like `100000000000000001`, tokens like `secret-token-x`. Never paste real ones, not even revoked ones.
- **New behavior comes with a test that fails without it.** For regressions, the test comment should say what broke and how.

## Pull requests

- One topic per PR. Use [Conventional Commits](https://www.conventionalcommits.org/) for commit messages (`feat:`, `fix:`, `docs:`...).
- Update `CHANGELOG.md` under *Unreleased*, and the docs if behavior changes.
- CI must be green: tests on Python 3.11 and 3.13, ruff, shellcheck, gitleaks.
- If you change the design format, update `docs/design-format.md` and both examples, and keep the validator strict. A typo in a design must fail loudly.

## Design principles

- **The live server is the source of truth**; `state.json` is only a cache.
- **Idempotent**: running `apply` twice changes nothing the second time.
- **Hooks never break a Claude Code session**: no output, no exceptions, exit 0, short timeouts.
- **Secrets never leave their 0600 files**: not to stdout, logs, state or exception messages.
- **Everything personal is configuration**: no ids, paths or names in the code.

## Code of conduct

Be kind and assume good faith. Harassment or abuse leads to removal from the project's spaces.
