# Design format

A design is a TOML file describing your server. `discord-hq plan` compares it with the live server; `discord-hq apply` makes the server match. Two complete examples ship in [`examples/`](../examples):

- `minimal.toml`: one category and three channels;
- `restaurant.toml`: the full waiter/kitchen server.

The validator is strict on purpose. An unknown key, a role that doesn't exist, or a channel name Discord would rewrite each stop the run **before** any API call, with a message saying where.

## Top-level tables

| Table | Required | What it holds |
|---|---|---|
| `[server]` | no | description and the optional monogram icon |
| `[community]` | no | turns on Discord Community and its settings |
| `[forum]` | no | tags and layout for the forums in your categories |
| `[[roles]]` | no | the roles the design manages |
| `[[categories]]` | no | categories, their visibility and their channels |
| `[[pinned_messages]]` | no | messages posted and pinned once |
| `[cleanup]` | no | channels to delete, by exact id |

## `[server]`

```toml
[server]
description = "Run your Claude Code kitchen from your phone."
icon_letter = "K"            # optional: 1-2 letters, needs `pip install .[icon]`
icon_color = "#F1C40F"       # optional
icon_background = "#121214"  # optional
```

The icon is only set when the server has **no icon**. It never replaces yours.

## `[[roles]]`

```toml
[[roles]]
name = "🤵 Waiter"
color = "#1ABC9C"            # "#RRGGBB" or an integer
hoist = true                 # shown separately in the member list
assign_to = "bot:WaiterBot"  # optional
```

- Roles are matched **by name**, and color/hoist are kept in sync.
- `assign_to` gives the role to someone on every `apply`:
  - `"owner"`: the server owner (you).
  - `"bot:<name>"`: the bot whose **managed role** (the one Discord created when you invited it) is called `<name>`.

  If that member isn't in the server yet, nothing happens, and a later `apply` picks it up.
- `@everyone` can't be declared. It is always denied *View Channel* on the categories the design manages.

## `[[categories]]` and their channels

```toml
[[categories]]
name = "📌 START"
visible_to = ["👑 Chef", "🤵 Waiter", "🤝 Guest"]
read_only_for = ["🤝 Guest"]       # optional: these roles see but never write
rename_from = "📌 OLD NAME"        # optional: rename in place

  [[categories.channels]]
  name = "rules"
  type = "text"                    # text | announcement | forum | voice
  topic = "Read me first."
  read_only = true                 # nobody writes here except the admin bot
  webhook = "Pass"                 # optional: create a webhook with this name
  answered_by = { waiter = "always" }  # optional: which bot answers here
```

### Visibility

- `visible_to` lists the roles that can see the category and every channel in it. `@everyone` is always denied.
- A role that appears in **any** category's `visible_to` but not in this one gets an **explicit deny** here. Removing a role from a list therefore really revokes it; a stale "allow" would otherwise win over the @everyone deny.
- The overwrite is written on the category **and on each channel in it**. Discord doesn't propagate a category's permissions to channels that already exist ("synced" is a one-time copy made by the app).
- **Channels you add by hand inside a managed category get the same permissions** on the next `apply`.
- A category without `visible_to` is created, but its permissions are left alone.
- Overwrites for other roles or members, and permission bits other than *View Channel* and *Send Messages*, are preserved.

### Read-only

- `read_only = true` on a channel denies *Send Messages* to @everyone. Only an admin (the admin bot, or a webhook) can post there. Use it for rules and for the live panel.
- `read_only_for` on a category lets those roles read every channel in it without writing. Other roles keep writing. A role in `read_only_for` must also be in `visible_to`.

### Channel identity

A channel is identified by **(name, type, category)**:

- You can have an `orders` forum in every project category.
- Changing a channel's category in the design **creates a new channel**. The old one is left for you to delete; automatic moves once corrupted a real server. Before moving a forum, run `discord-hq audit-forum <id>` to see its posts.
- To rename a **category** in place, keeping its id, channels and forum posts, set `rename_from` to the old name.

### Channel names

Text, announcement and forum names must be lowercase and have no spaces. Discord rewrites them otherwise, and the diff would try to create them again on every run. Emoji and accents are fine. Voice channels can use any name.

### `webhook`

This creates a webhook with that name in the channel. The URL goes to `~/.config/claude-code-discord-hq/webhooks.json` (mode 0600), never to stdout or `state.json`.

- Webhook names must be unique.
- A webhook's channel name must be unique among text channels, because the lookup is by channel name.
- The notification tools look webhooks up by name. Defaults:
  - `Pass`: ready (PR opened);
  - `Bell`: alerts;
  - `Panel`: the live board.

  Change them with `DISCORD_HQ_WEBHOOK_*`.

### `answered_by`

`answered_by = { waiter = "always" }` doesn't change the server. It records which bot answers in the channel, and how:

- `"always"`: the bot answers every message there (the plugin's `--no-mention`).
- `"mention"`: the bot answers only when mentioned.

The validator rejects two bots in one channel unless all of them are `"mention"`. `discord-hq access --bot waiter` turns these into the plugin's `/discord:access group add <id> [--no-mention]` commands, using the channel ids from `state.json`.

## `[community]`

```toml
[community]
description = "..."
rules_channel = "rules"               # a text channel in the design
public_updates_channel = "moderation" # a text channel in the design
verification_level = 2                # default 2
explicit_content_filter = 2           # default 2
default_message_notifications = 1     # default 1 = only @mentions
```

Community is enabled once both channels exist, so on a new server that happens on the same `apply`, one pass later. Other guild features are preserved.

## `[forum]`

```toml
[forum]
layout = "list"                       # list | gallery | default
tags = [{ name = "🐞 bug", emoji = "🐞" }]
```

These apply only to forums inside the design's categories. Without tags, forum tags are left alone.

## `[[pinned_messages]]`

```toml
[[pinned_messages]]
channel = "how-it-works"
content = """Up to 2000 characters."""
```

Each message is posted and pinned once, then recorded in `state.json`. Edit it in Discord afterwards, or remove its key from `state.json` to post it again. Mentions inside it never ping anyone.

## `[cleanup]`

```toml
[cleanup]
delete_channel_ids = ["123456789012345678"]
```

This deletes channels by **exact id**, for example the "general" channels Discord creates with a new server. Matching by name would one day delete a channel you created on purpose. Deletions are listed separately by `plan` and only run with `apply --allow-delete`.

## `state.json`

After `apply`, `state.json` (next to the design, or `DISCORD_HQ_STATE`) records the ids of every managed role, category and channel, plus the pinned messages. It holds ids only, never secrets, and it is git-ignored anyway.

The live server is always the source of truth. Losing the file never duplicates roles, channels or webhooks, and the next `apply` rebuilds it even when nothing else changed. Pinned messages are the exception: their "already posted" flag lives only here, so they would be posted again.
