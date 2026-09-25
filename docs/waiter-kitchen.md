# The waiter and the kitchen

This is the way of working that motivated the project. You don't need to adopt it to use the tools, but it explains why they look the way they do.

## The problem

One Claude Code session doing everything has two failure modes:

- **It gets buried.** While it's deep in a refactor, you can't ask it anything else, and its context fills up with one task's details.
- **It's slow.** Tasks that could run side by side wait in line.

Running many sessions by hand has the opposite problem: you lose track of which one needs you, which one is stuck, and which one finished an hour ago.

## The restaurant

| | Who | Rule |
|---|---|---|
| **Waiter** | your main Claude Code session, in a tmux session called `waiter` | Takes the order, sends it to the kitchen, **comes straight back to the table**, and serves the dish when it's ready. **Never cooks**: no code changes in the main session, however small. At the table it only talks, answers, reads, takes notes and serves. |
| **Kitchen** | one Claude Code session per order, in its own tmux session (`kitchen-<order>`) and its own git worktree | Cooks one order until a pull request is open, then stops. Several kitchens cook at once. |
| **Chef** | you | Tastes (reviews) the pull request and merges it. Nothing reaches the main branch without the chef. |
| **Guest** | someone you invite to the server | Places orders at the guest table. The waiter writes them down; nothing is cooked without the chef's OK. |

Each order goes through the same cycle:

1. **Write it down**: *What / Why / Acceptance criteria*.
2. **Send it to the kitchen**: a worktree, a branch and a tmux session.
3. **Go back to the table**: the waiter is free for the next order.
4. **Serve**: when the PR is open, check it and tell the chef.

## Where this project fits

The kitchen runs in tmux on your computer. You are not always at your computer. The Discord server is the **counter** between you and the restaurant:

- **#table**: talk to the waiter from your phone (through the official Discord plugin).
- **#orders** forums, one per project: place orders as posts.
- **#served**: "✅ order X ready → PR link" (ready webhook).
- **#alerts**:
  - "🔐 needs approval";
  - "⏸️ stopped";
  - "🧊 no progress for 12 min";
  - "⏳ waiting for you: needs the dev server" (alert webhook).
- **#panel**: one live message listing every kitchen session and its state.

On your Mac, the same alerts arrive as notifications, with the `tmux attach` command already on your clipboard.

## Manifests: how the kitchen tells you it's waiting

An orchestrator that dispatches several orders can keep a **batch manifest**: a Markdown table with one row per order, whose state cell starts with an emoji:

```markdown
| unit | route | state | PR |
|---|---|---|---|
| add-login | kitchen | 🔄 cooking | |
| fix-export | kitchen | ⏳ waiting for you — needs the dev server | |
| docs-faq | kitchen | ✅ PR #42 | #42 |
```

A kitchen session that needs a human writes ⏳ plus a one-line reason in **its own row**, and waits. No Claude Code hook fires for this, because nobody asked a question in the terminal. The watchdog notices the file change and alerts you. See [notifications.md](notifications.md) for the exact format.

## Lessons baked into the tools

- **tmux targets are exact.** `-t 'kitchen-a'` also matches `kitchen-ab`; always use `'=kitchen-a'` (and `'=kitchen-a:'` for pane commands).
- **Some terminal integrations hijack tmux panes.** For example, Ghostty with ghost-complete takes over the PTY inside tmux and hangs every shell command a tool runs. The waiter shortcut unsets the variables that trigger it.
- **One bot token, one client.** The waiter shortcut re-attaches instead of starting a second session.
- **A hung session fires no hook.** Hence the watchdog.
- **A subagent's progress lives in another transcript file.** The watchdog looks at both, so a busy subagent doesn't look like a hang.
