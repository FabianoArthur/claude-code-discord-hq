# Creating the bots and their permissions

You will create up to three kinds of Discord applications. Keep them separate. Each has a different job, and a different blast radius if its token leaks.

| Bot | Used by | Permissions | Lifetime |
|---|---|---|---|
| **Admin bot** (the "architect") | `discord-hq plan/apply/audit-forum` | **Administrator** | **Temporary**: reset its token right after `apply` |
| **Waiter bot** | your main Claude Code session, through the official Discord plugin | Only what the plugin needs (below) | Long-lived |
| **Second station bot** (optional) | a Claude Code session on another machine | Same as the waiter | Long-lived |

Notifications don't use any bot: they post through **webhooks**, which `apply` creates.

## 1. Turn on Developer Mode

Discord → User Settings → Advanced → **Developer Mode**. Now you can right-click things and use *Copy ID*.

- **Server id**: right-click the server icon → Copy Server ID. Goes in `DISCORD_HQ_GUILD_ID`.
- **Your user id**: right-click your name → Copy User ID. Goes in `DISCORD_HQ_MENTION_USER_ID`, so alerts ping only you.

## 2. The temporary admin bot

1. Go to <https://discord.com/developers/applications> → **New Application** (for example "HQ Architect").
2. **Bot** → Reset Token → copy it. Put it in `~/.config/claude-code-discord-hq/.env` as `DISCORD_HQ_ADMIN_TOKEN=...`. Never paste it in a chat, an issue, or a Discord channel.
3. **Bot** → turn **off** "Public Bot", so nobody else can invite it.
4. **OAuth2 → URL Generator**: scope `bot`, permission **Administrator**. Open the URL and add the bot to your server.
5. Run `discord-hq plan`, then `discord-hq apply`.
6. **Right after `apply`:** Developer Portal → Bot → **Reset Token**, and don't copy the new one. The old token stops working. Remove the line from `.env`. When you want to change the server again, reset the token once more and put the new one in for the duration of the `apply`.

Why Administrator? Creating roles, channels, permission overwrites, webhooks and Community settings needs several management permissions. Administrator also bypasses channel overwrites, so a half-applied design can never lock the admin bot out. That power is exactly why the token must be short-lived.

## 3. The waiter bot (and a second station)

Follow the official Discord plugin's own setup (`/plugin install discord@claude-plugins-official`, then `/discord:configure <token>`). In short:

1. New Application (for example "WaiterBot"). **Bot** → turn **on** *Message Content Intent*, and turn **off** "Public Bot".
2. OAuth2 → URL Generator: scope `bot`, with these permissions only:
   - View Channels
   - Send Messages
   - Send Messages in Threads
   - Read Message History
   - Attach Files
   - Add Reactions

   Do **not** give it Administrator.
3. Invite it. Discord gives it a managed role with the bot's name, for example `WaiterBot`. That is the name you put in the design: `assign_to = "bot:WaiterBot"`.
4. After the next `apply`, the bot gets your design's role (for example `🤵 Waiter`), which decides which categories it can see.
5. Run `discord-hq access --bot waiter` and type the printed `/discord:access group add ...` lines **in the waiter's own Claude Code terminal**.
6. Keep DMs closed: `/discord:access policy allowlist`, with only your own user id allowed.

A second machine gets its own bot the same way (for example `StationBot` with `assign_to = "bot:StationBot"`). **Never give two bots "always answer" on the same channel.** The design validator rejects it; where two bots share a channel, both must be `"mention"`.

## 4. Webhooks

`apply` creates the webhooks declared in the design (`webhook = "Pass"` on a channel). It stores their URLs in `~/.config/claude-code-discord-hq/webhooks.json` with mode 0600. Anyone holding a webhook URL can post as it, so treat the file like a password. If a URL leaks, delete that webhook in Discord (Channel settings → Integrations → Webhooks) and run `apply` again: it creates a new one.

## 5. Checklist

- [ ] The admin bot's token has been reset after `apply`.
- [ ] No bot has "Public Bot" turned on.
- [ ] The waiter and station bots do **not** have Administrator.
- [ ] The DM policy is allowlist, and only you are on the list.
- [ ] `~/.config/claude-code-discord-hq/.env` and `webhooks.json` are mode 0600.
