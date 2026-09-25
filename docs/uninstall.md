# Uninstall

## 1. Local pieces

```sh
./install.sh --uninstall --dry-run   # see what would be removed
./install.sh --uninstall             # asks before each removal
```

This unloads and removes the LaunchAgent (macOS) and removes `<repo>/.venv`. It **leaves** your settings folder, because it holds your webhook URLs and you may want them back.

Then remove by hand the things the installer never wrote:

1. **Claude Code hooks:** in `~/.claude/settings.json`, delete the `Notification` and `Stop` entries whose command ends with `-m discord_hq hook`. Keep any other hooks you have.
2. **The waiter shortcut:** delete the `source .../shell/waiter.zsh` line from `~/.zshrc`.
3. **Linux watchdog:** remove the `discord_hq watch` line from `crontab -e` (or disable your systemd timer).
4. **Settings and secrets:**
   ```sh
   rm -rf ~/.config/claude-code-discord-hq
   ```
5. **The clone** itself, and your `design.toml` / `state.json` if you kept them elsewhere.

## 2. Discord side

The server itself is left as it is. Deleting it is a Discord action: Server Settings → Delete Server. If you keep the server:

- **Webhooks:** Channel settings → Integrations → Webhooks → delete `Pass`, `Bell`, `Panel` (or your names). This invalidates the URLs that were in `webhooks.json`.
- **Bots:** remove them from the server. In the Developer Portal, reset or delete each application's token.
- **Plugin access:** in the waiter's Claude Code session, run `/discord:access group rm <channel id>` for each channel, or remove the plugin (`/plugin uninstall discord@claude-plugins-official`).

## 3. Check

```sh
launchctl print gui/$(id -u)/com.claude-code-discord-hq.watch   # should fail: not found
grep -n "discord_hq" ~/.claude/settings.json ~/.zshrc           # should print nothing
ls ~/.config/claude-code-discord-hq                              # should not exist
```
