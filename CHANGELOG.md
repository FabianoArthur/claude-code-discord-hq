# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Security

- `install.sh` refuses to write through a dangling symlink at `.env` or any symlink at the LaunchAgent path, and refuses repo/home paths whose characters would break the sed, plist, JSON or shell quoting.
- `discord-hq audit-forum` strips control characters from post names before printing them.
- `install.sh` backs up a LaunchAgent that differs before replacing it.
- `Settings` no longer shows the admin token in its `repr`.
- Dependabot for GitHub Actions and pip; upper bounds on the optional and dev dependencies.
- Threat model: how to run kitchens with `--dangerously-skip-permissions` safely (T15), and the installer's own threats (T14). `SECURITY.md` states the response timeline.

## [0.1.0] - 2026-09-25

First public version.

### Added

- **Server as code.** A declarative TOML design (roles, categories, channels, per-role visibility, read-only channels and roles, webhooks, forum tags, Community, pinned messages, cleanup by id).
  - `discord-hq plan` shows the diff; `discord-hq apply` applies it idempotently, with a confirmation prompt, `--yes` and `--allow-delete`.
  - Strict validation before any API call.
  - Example designs: `examples/minimal.toml`, `examples/restaurant.toml`.
- `discord-hq audit-forum` (read-only) and `discord-hq access` (prints the official Discord plugin commands per bot).
- **Notifications.**
  - `discord-hq hook` for Claude Code's `Notification`/`Stop` events, with macOS notifications and Discord webhooks.
  - `discord-hq watch`: stalled-session watchdog, ⏳ alerts from batch manifests, and a live panel message.
- `shell/waiter.zsh`: the `waiter` shortcut for the main session, connected through the Discord plugin.
- `install.sh`: idempotent, confirms every write, `--dry-run`, `--uninstall`. It never edits `~/.claude/settings.json` or shell rc files.
- Documentation in English (plus `README.pt-BR.md`), security and threat models.
- CI: tests, ruff, shellcheck and gitleaks, with actions pinned by SHA.

[Unreleased]: https://github.com/Fabiano-Arthur/claude-code-discord-hq/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Fabiano-Arthur/claude-code-discord-hq/releases/tag/v0.1.0
