# Security policy

## Supported versions

Only the latest release (and `main`) gets security fixes while the project is in `0.x`.

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Report privately through GitHub: go to the repository's **Security** tab and choose **Report a vulnerability**. Include:

- what an attacker could do, and under which conditions (who needs to post where, which token they need);
- steps to reproduce, ideally against a throwaway Discord server;
- the version (`discord-hq --version`) and your OS.

You'll get an acknowledgement within 7 days. Fixes are released as soon as they are ready, with credit if you want it.

## Never include secrets

Do not paste real bot tokens, webhook URLs, `.env` contents or server ids in a report, an issue or a pull request. If you already did, reset the token or delete the webhook right away. It's compromised the moment it's public.

## Scope

In scope: this repository's code, installer, CI workflow and documentation that could lead users into an unsafe setup. The design choices behind the defaults are described in [docs/security-model.md](docs/security-model.md) and [docs/threat-model.md](docs/threat-model.md). Vulnerabilities in Discord, Claude Code or the official Discord plugin should go to their maintainers.
