"""Discord sink: posts alerts through webhooks (no bot token needed; the
webhook URLs were created by `discord-hq apply`).

Only the configured user is ever mentioned (`allowed_mentions`), free text
is defused against masked links, and the webhook URL never appears in output
or exceptions."""

from __future__ import annotations

import json

import requests

TIMEOUT_SECONDS = 5
MAX_CONTENT = 2000

# "idle" stays on the local notification only; it would be noise on Discord.
ALERT_KINDS = {"permission", "stopped", "stalled", "paused"}


def read_webhooks(settings) -> dict:
    try:
        return json.loads(settings.webhooks_path.read_text())
    except Exception:
        return {}


def safe_text(text: str) -> str:
    """Free text (the assistant's last message, a manifest reason) may carry
    content the agent read from outside. `[text](url)` would render as a link
    hiding its real target, so brackets are swapped for look-alikes."""
    return text.replace("[", "⟦").replace("]", "⟧")


def _content(event, settings) -> str:
    mention = f"<@{settings.mention_user_id}> " if settings.mention_user_id else ""
    head = f"**{event.project}** · `{event.slug}`"
    if event.kind == "ready":
        # Here the message IS the PR URL from `gh pr view`: keep it a real link.
        return f"{mention}✅ {head} ready → {event.message or 'PR not found'}"
    text = safe_text(event.message or "")
    attach = settings.attach_command(event.slug)
    lines = {
        "permission": f"{mention}🔐 {head} needs approval: {text}",
        "stopped": f"{mention}⏸️ {head} stopped: {text}",
        "stalled": f"{mention}🧊 {head} no progress: {text}",
        "paused": f"{mention}⏳ {head} is waiting for you: {text}",
    }
    line = lines.get(event.kind)
    return f"{line}\n{attach}" if line else ""


def webhook_for(kind: str, settings) -> str | None:
    if kind == "ready":
        return settings.webhook_ready
    if kind in ALERT_KINDS:
        return settings.webhook_alert
    return None


def notify(event, settings) -> None:
    name = webhook_for(event.kind, settings)
    if name is None:
        return
    content = _content(event, settings)
    url = read_webhooks(settings).get(name)
    if not content or not url:
        return
    if len(content) > MAX_CONTENT:
        content = content[: MAX_CONTENT - 1] + "…"
    allowed = {"users": [settings.mention_user_id]} if settings.mention_user_id else {"parse": []}
    try:
        requests.post(url, json={"content": content, "allowed_mentions": allowed}, timeout=TIMEOUT_SECONDS)
    except Exception:
        pass
