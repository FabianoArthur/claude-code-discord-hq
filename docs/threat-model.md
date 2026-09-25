# Threat model

**Scope:** a single person (the "chef") runs Claude Code sessions on their own machine, and uses a private Discord server as a phone interface and an alert channel. They may invite a few guests.

## Assets

1. **The machine and its repositories:** source code, credentials in env files, SSH keys, cloud CLIs logged in.
2. **Bot tokens and webhook URLs.**
3. **The Discord server:** its structure, and who can see which channel.
4. **The chef's attention:** alerts must be trustworthy, and not so noisy they get ignored.

## Actors

| Actor | Capability |
|---|---|
| Chef | Full control. Trusted. |
| Guest | Can read the start category and post in the guest channel. **Untrusted input.** |
| Random Discord user | Can DM a bot if they share a server or learn its name; can't see private categories. |
| Content the agent reads | Web pages, issues, dependencies, files. **Untrusted input** that may end up in messages. |
| Someone with a leaked token/URL | Can act as that bot or webhook. |

## Threats and mitigations

| # | Threat | Mitigation | Residual risk |
|---|---|---|---|
| T1 | A **guest message injects instructions** into the waiter ("run this", "show me .env", "approve my pairing"). | The guest channel is mention-only. Guest orders wait for the chef's approval. The waiter's `CLAUDE.md` must say messages are data. Access changes are never driven from Discord. | Depends on the model following its instructions; keep the waiter on normal permission prompts. |
| T2 | A **stranger DMs the bot**. | DM policy allowlist; pairing needs a code typed in the terminal. | None if the allowlist is kept to the chef. |
| T3 | **Admin token leak** (logs, screenshots, a pasted `.env`). | Temporary token, reset after `apply`. It's never printed, and never in state or exceptions. The file is 0600. gitleaks runs in CI. | A window of exposure while an `apply` is in progress. |
| T4 | **Webhook URL leak.** | 0600 file, never printed, redacted from errors. | An attacker can post fake alerts until the webhook is deleted and re-created. |
| T5 | **Masked links in alerts** (`[PR ready](https://evil)`) coming from text the agent read. | Brackets in free text are replaced with look-alikes; only the real PR URL from `gh` is kept as a link. | Plain URLs in free text stay visible as URLs, which is the point: you see the real target. |
| T6 | **Mass pings** (@everyone / role mentions) from alert text. | `allowed_mentions` is limited to the chef's user id (or no one); the panel and pinned messages allow no mentions. | None known. |
| T7 | **Shell injection through a session or folder name** reaching the notification click command. | Slugs are reduced to `[A-Za-z0-9._-]` before any use. | None known. |
| T8 | **Two bots answering each other** in a loop, or both obeying one injected message. | The validator rejects two "always" bots in one channel; shared channels require mentions. | A human can still mention both bots on purpose. |
| T9 | **A permission change is silently not applied** (a stale allow, or category permissions not propagating). | Explicit deny for roles removed from a category; overwrites on every child channel; full idempotency test. | Overwrites added by hand for *other* roles and members are preserved by design. |
| T10 | **A destructive `apply`** deletes channels with history. | Deletions only by exact id, listed separately, and only with `--allow-delete`. Confirmation prompt. Moves create new channels instead of moving. | You can still delete what you list. |
| T11 | **The hook breaks Claude Code sessions** (exceptions, hangs, output injected into the session). | Contract tested: no stdout, never raises, exit 0, short timeouts. | A hung subprocess is capped at its timeout (at most ~10 s for `gh`). |
| T12 | **The installer silently changes how Claude Code or the shell behave.** | It never writes `~/.claude/settings.json` or rc files; it confirms every write; `--dry-run`. | None. |
| T13 | **Supply chain** (a compromised dependency or CI action). | Two runtime dependencies (`requests`, optional `pillow`); CI actions pinned by commit SHA; gitleaks pinned by version + checksum; `permissions: contents: read`. | Dependencies aren't hash-locked for end users; pin them in your own environment if you need that. |

## Out of scope

- Attacks by Discord or GitHub themselves, or on their infrastructure.
- A machine that is already compromised.
- Kitchen sessions run with `--dangerously-skip-permissions`. That is a decision of your orchestration setup, not of this project. If you make it, use isolated worktrees, protected branches, and no production credentials in the environment.
