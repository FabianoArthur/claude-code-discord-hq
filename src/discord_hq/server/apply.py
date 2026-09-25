"""`discord-hq plan` / `discord-hq apply`: read the live server, diff it
against the design, and (for apply) run the changes in dependency order.

`apply` loops collect -> diff -> apply a few times: Community, forum tags,
webhooks and overwrites depend on ids (channels, roles) that only exist after
the first pass creates them. Without the loop, a second `apply` would still
find work to do.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from pathlib import Path

from discord_hq.config import ConfigError, Settings
from discord_hq.server import diff
from discord_hq.server.client import DiscordAPIError, DiscordClient
from discord_hq.server.design import Design, DesignError, load_design
from discord_hq.server.state import load_state, save_state

MAX_CONVERGENCE_PASSES = 4
SENSITIVE_KEYS = {"token_used", "token", "url", "webhook_url"}
TEXT_TYPES = (diff.CHANNEL_TYPE["text"], diff.CHANNEL_TYPE["announcement"])


def icon_data_uri(spec: dict) -> str:
    # Imported lazily: Pillow is an optional extra.
    from discord_hq.server.icon import icon_data_uri as render

    return render(spec)


def _safe(details: dict) -> dict:
    return {k: v for k, v in details.items() if k not in SENSITIVE_KEYS}


def build_report(actions: list[diff.Action], held_back: list[diff.Action] | None = None) -> str:
    held_back = held_back or []
    if not actions and not held_back:
        return "0 changes: the server already matches the design."
    lines = [f"{len(actions)} change(s):"] if actions else ["0 changes to apply."]
    for action in actions:
        marker = "DELETE " if action.operation == "delete" else ""
        lines.append(f"- {marker}{action.operation} {action.resource} {action.name} {_safe(action.details)}")
    if held_back:
        lines.append(f"{len(held_back)} deletion(s) held back (rerun with --allow-delete to run them):")
        for action in held_back:
            lines.append(f"- DELETE {action.resource} {action.name} {_safe(action.details)}")
    return "\n".join(lines)


def _member_roles(client: DiscordClient, guild_id: str, user_id: str) -> list[str] | None:
    try:
        member = client.get(f"/guilds/{guild_id}/members/{user_id}")
    except DiscordAPIError as exc:
        if exc.status == 404:
            return None
        raise
    return member.get("roles") if member else None


def collect_current_state(client: DiscordClient, guild_id: str, design: Design) -> dict:
    guild = client.get(f"/guilds/{guild_id}")
    roles = client.get(f"/guilds/{guild_id}/roles")
    channels = client.get(f"/guilds/{guild_id}/channels")

    # Derived from the design, never hardcoded: a webhook channel missing here
    # looks empty to the diff, and every apply would create a duplicate.
    webhook_channel_names = {w["channel"] for w in design.webhooks}
    webhooks_by_channel: dict = {}
    for channel in channels:
        if channel.get("type") in TEXT_TYPES and channel.get("name") in webhook_channel_names:
            webhooks_by_channel[channel["id"]] = client.get(f"/channels/{channel['id']}/webhooks")

    assignments = []
    for assignment in design.role_assignments:
        target = assignment["to"]
        user_id = guild.get("owner_id") if target == "owner" else diff.find_bot_id(roles, target[len("bot:") :])
        assignments.append(
            {
                "role": assignment["role"],
                "label": f"{assignment['role']} → {target}",
                "user_id": user_id,
                "member_roles": _member_roles(client, guild_id, user_id) if user_id else None,
            }
        )

    return {
        "guild": guild,
        "roles": roles,
        "channels": channels,
        "webhooks_by_channel": webhooks_by_channel,
        "assignments": assignments,
    }


def _channel_id(current: dict, name: str, category: str) -> str | None:
    category_ids = {
        c["id"] for c in current["channels"] if c.get("type") == diff.CATEGORY_TYPE and c["name"] == category
    }
    for channel in current["channels"]:
        if (
            channel.get("name") == name
            and channel.get("parent_id") in category_ids
            and channel.get("type") != diff.CATEGORY_TYPE
        ):
            return channel["id"]
    return None


def compute_actions(design: Design, current: dict) -> list[diff.Action]:
    channels = current["channels"]
    categories = [c for c in channels if c.get("type") == diff.CATEGORY_TYPE]
    managed_categories = [c for c in categories if c["name"] in design.categories]

    actions: list[diff.Action] = []
    actions += diff.diff_roles(design.roles, current["roles"])
    actions += diff.diff_categories(design.categories, categories, design.category_renames)
    actions += diff.diff_channels(design.channels, categories, channels, design.category_renames)

    if design.community:
        rules_id = _channel_id(current, *design.community["rules_channel"])
        updates_id = _channel_id(current, *design.community["public_updates_channel"])
        if rules_id and updates_id:
            actions += diff.diff_community(design.community, current["guild"], rules_id, updates_id)

    actions += diff.diff_forum_tags(design.forum_tags, design.forum_layout, channels, managed_categories)
    actions += diff.diff_webhooks(design.webhooks, channels, current.get("webhooks_by_channel", {}), categories)
    actions += diff.diff_icon(current["guild"], wanted=design.icon is not None)

    role_id_by_name = {r["name"]: r["id"] for r in current["roles"]}
    for assignment in current.get("assignments", []):
        actions += diff.diff_role_assignment(
            assignment["label"],
            assignment["user_id"],
            role_id_by_name.get(assignment["role"]),
            assignment["member_roles"],
        )

    # The category overwrite only shapes channels created later in the UI;
    # the channel's own overwrite is what governs existing channels.
    actions += diff.diff_category_overwrites(
        design.category_visibility, categories, current["roles"], design.read_only_roles
    )
    actions += diff.diff_channel_overwrites(
        design.category_visibility,
        design.read_only_channels,
        channels,
        categories,
        current["roles"],
        design.read_only_roles,
    )

    to_delete = set(design.delete_channel_ids)
    for channel in channels:
        if channel["id"] in to_delete:
            actions.append(diff.Action("channel", "delete", channel.get("name", channel["id"]), {"id": channel["id"]}))
    return actions


def audit_forum(client: DiscordClient, guild_id: str, channel_id: str) -> dict:
    """GET-only: the posts (active + archived public threads) of a forum. Run
    it before renaming or moving a forum's category, so deciding where
    existing posts go is never a guess. Active threads only come from the
    guild endpoint (the per-channel one was removed in API v10)."""
    active = client.get(f"/guilds/{guild_id}/threads/active") or {}
    archived = client.get(f"/channels/{channel_id}/threads/archived/public") or {}
    names = [t["name"] for t in active.get("threads", []) if t.get("parent_id") == channel_id]
    names += [t["name"] for t in archived.get("threads", [])]
    return {"total": len(names), "names": names}


def save_webhook_url(path: Path, name: str, url: str) -> None:
    """Webhook URLs are secrets (anyone holding one can post). They live in the
    config dir, created 0600 from the start, never in state.json or stdout."""
    path = Path(path)
    data = {}
    if path.exists():
        data = json.loads(path.read_text())
    data[name] = url
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        os.fchmod(handle.fileno(), 0o600)
        handle.write(json.dumps(data, indent=2))


def apply_actions(
    client: DiscordClient,
    guild_id: str,
    actions: list[diff.Action],
    state: dict,
    current_categories: list[dict] | None = None,
    webhooks_path: Path | None = None,
    icon_spec: dict | None = None,
) -> None:
    """Runs actions in the given order. Categories always come before channels
    (compute_actions guarantees it), so the category map is complete when a
    channel needs its parent id, for new and existing categories alike."""
    category_ids = {c["name"]: c["id"] for c in (current_categories or []) if c.get("type") == diff.CATEGORY_TYPE}

    for action in actions:
        kind, op, d = action.resource, action.operation, action.details
        if kind == "role" and op == "create":
            created = client.post(
                f"/guilds/{guild_id}/roles", json={"name": d["name"], "color": d["color"], "hoist": d["hoist"]}
            )
            state.setdefault("roles", {})[action.name] = created["id"]
        elif kind == "role" and op == "update":
            client.patch(f"/guilds/{guild_id}/roles/{d['id']}", json={"color": d["color"], "hoist": d["hoist"]})
        elif kind == "category" and op == "create":
            created = client.post(f"/guilds/{guild_id}/channels", json=d)
            state.setdefault("categories", {})[action.name] = created["id"]
            category_ids[action.name] = created["id"]
        elif kind == "category" and op == "rename":
            client.patch(f"/channels/{d['id']}", json={"name": action.name})
            old = d["old_name"]
            categories = state.setdefault("categories", {})
            categories.pop(old, None)
            categories[action.name] = d["id"]
            category_ids.pop(old, None)
            category_ids[action.name] = d["id"]
            channels = state.setdefault("channels", {})
            old_suffix, new_suffix = f" ({old})", f" ({action.name})"
            for key in list(channels):
                if key.endswith(old_suffix):
                    channels[key[: -len(old_suffix)] + new_suffix] = channels.pop(key)
        elif kind == "channel" and op == "create":
            payload = {
                "name": d["name"],
                "type": d["type"],
                "parent_id": category_ids.get(d["category"]),
                "topic": d.get("topic"),
            }
            created = client.post(f"/guilds/{guild_id}/channels", json=payload)
            state.setdefault("channels", {})[f"{action.name} ({d['category']})"] = created["id"]
        elif kind == "channel" and op == "update":
            client.patch(
                f"/channels/{d['id']}", json={"parent_id": category_ids.get(d["category"]), "topic": d.get("topic")}
            )
        elif kind == "channel" and op == "delete":
            client.delete(f"/channels/{d['id']}")
        elif kind == "community":
            client.patch(f"/guilds/{guild_id}", json=d)
        elif kind == "forum_tags":
            client.patch(
                f"/channels/{d['id']}",
                json={"available_tags": d["available_tags"], "default_forum_layout": d["default_forum_layout"]},
            )
        elif kind == "webhook":
            created = client.post(f"/channels/{d['channel_id']}/webhooks", json={"name": action.name})
            if webhooks_path is not None:
                save_webhook_url(
                    webhooks_path, action.name, f"https://discord.com/api/webhooks/{created['id']}/{created['token']}"
                )
        elif kind == "icon" and icon_spec:
            client.patch(f"/guilds/{guild_id}", json={"icon": icon_data_uri(icon_spec)})
        elif kind == "role_assignment":
            client.put(f"/guilds/{guild_id}/members/{d['user_id']}/roles/{d['role_id']}")
        elif kind in ("category_overwrite", "channel_overwrite"):
            client.patch(f"/channels/{d['id']}", json={"permission_overwrites": d["permission_overwrites"]})


def post_pinned_messages(client: DiscordClient, design: Design, state: dict, current: dict) -> None:
    """Posts and pins each `[[pinned_messages]]` entry once. There is no cheap
    way to compare "the same message", so a flag in state is the idempotency
    key: edit the message by hand in Discord, or drop its key from state.json
    to post it again."""
    pinned = state.setdefault("pinned", {})
    for message in design.pinned_messages:
        key = f"{message['channel']} ({message['category']})"
        if key in pinned:
            continue
        channel_id = _channel_id(current, message["channel"], message["category"])
        if not channel_id:
            continue
        posted = client.post(
            f"/channels/{channel_id}/messages", json={"content": message["content"], "allowed_mentions": {"parse": []}}
        )
        # Recorded before pinning: if the pin call fails, the next run must
        # not post the message a second time.
        pinned[key] = posted["id"]
        client.put(f"/channels/{channel_id}/pins/{posted['id']}")


def record_managed_ids(state: dict, design: Design, current: dict) -> None:
    """Every managed id, including ones that already existed before this tool
    ran. `discord-hq access` reads channel ids from here."""
    role_ids = {r["name"]: r["id"] for r in current["roles"]}
    state["roles"] = {r["name"]: role_ids[r["name"]] for r in design.roles if r["name"] in role_ids}
    category_ids = {c["name"]: c["id"] for c in current["channels"] if c.get("type") == diff.CATEGORY_TYPE}
    state["categories"] = {n: category_ids[n] for n in design.categories if n in category_ids}
    channels = {}
    for channel in design.channels:
        channel_id = _channel_id(current, channel["name"], channel["category"])
        if channel_id:
            channels[f"{channel['name']} ({channel['category']})"] = channel_id
    state["channels"] = channels


def state_path_for(settings: Settings, design_path: Path) -> Path:
    return settings.state_path or Path(design_path).parent / "state.json"


def _split_deletions(actions: list[diff.Action], allow_delete: bool) -> tuple[list[diff.Action], list[diff.Action]]:
    if allow_delete:
        return actions, []
    keep = [a for a in actions if a.operation != "delete"]
    held = [a for a in actions if a.operation == "delete"]
    return keep, held


def _ask(prompt: str) -> bool:
    return input(prompt).strip().lower() in ("y", "yes")


def run(
    settings: Settings,
    design_path: Path,
    mode: str,
    yes: bool = False,
    allow_delete: bool = False,
    confirm: Callable[[str], bool] | None = None,
) -> int:
    """mode: "plan" (read-only) or "apply". Returns a process exit code."""
    try:
        design = load_design(design_path)
        token = settings.require("admin_token")
        guild_id = settings.require("guild_id")
    except (DesignError, ConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        return _run(DiscordClient(token), guild_id, settings, design, design_path, mode, yes, allow_delete, confirm)
    except DiscordAPIError as exc:
        print(f"error: {exc} {exc.body}", file=sys.stderr)
        return 1


def _run(client, guild_id, settings, design, design_path, mode, yes, allow_delete, confirm) -> int:
    current = collect_current_state(client, guild_id, design)
    actions, held = _split_deletions(compute_actions(design, current), allow_delete)
    print(build_report(actions, held))

    if mode == "plan":
        return 0

    if actions and not yes:
        if confirm is None:
            if not sys.stdin.isatty():
                print("error: refusing to apply without a terminal; rerun with --yes", file=sys.stderr)
                return 1
            confirm = _ask
        if not confirm(f"Apply {len(actions)} change(s) to the server? [y/N] "):
            print("Nothing applied.")
            return 1

    state_path = state_path_for(settings, design_path)
    state = load_state(state_path)
    applied = bool(actions)
    for _ in range(MAX_CONVERGENCE_PASSES):
        if not actions:
            break
        categories = [c for c in current["channels"] if c.get("type") == diff.CATEGORY_TYPE]
        apply_actions(client, guild_id, actions, state, categories, settings.webhooks_path, design.icon)
        save_state(state_path, state)
        current = collect_current_state(client, guild_id, design)
        actions, held = _split_deletions(compute_actions(design, current), allow_delete)

    # Runs even when nothing changed: rebuilds a lost state.json and posts
    # pinned messages added to an otherwise unchanged design.
    try:
        post_pinned_messages(client, design, state, current)
    finally:
        record_managed_ids(state, design, current)
        save_state(state_path, state)

    if applied:
        print(build_report(actions, held))
    return 0
