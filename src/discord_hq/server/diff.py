"""Diff engine: compares the desired state (from the design) with the current
state read from the Discord API and returns a list of `Action`s. It never
calls the API; it only compares dicts. `apply.py` decides the order and runs
them.

Lessons encoded here (each one cost a broken server once):

- Channels are matched by (name, type, category), never by name alone.
- A category rename is a PATCH on the same id, never create + delete.
- Permission overwrites are written on EVERY child channel: Discord does not
  propagate a category overwrite to channels that already exist.
- A role removed from a category's visibility gets an explicit deny, because
  a role overwrite beats the @everyone overwrite.
- Overwrites for entities and bits this tool does not control are preserved.
"""

from __future__ import annotations

from dataclasses import dataclass, field

CHANNEL_TYPE = {"text": 0, "voice": 2, "announcement": 5, "forum": 15}
CATEGORY_TYPE = 4

VIEW_CHANNEL_BIT = 1 << 10
SEND_MESSAGES_BIT = 1 << 11
CONTROLLED_BITS = VIEW_CHANNEL_BIT | SEND_MESSAGES_BIT


@dataclass
class Action:
    resource: str  # role | category | channel | community | forum_tags | webhook | icon | role_assignment
    #                | category_overwrite | channel_overwrite
    operation: str  # create | update | rename | delete | apply | assign
    name: str
    details: dict = field(default_factory=dict)


def diff_roles(desired: list[dict], current: list[dict]) -> list[Action]:
    current_by_name = {r["name"]: r for r in current}
    actions: list[Action] = []
    for role in desired:
        name, color, hoist = role["name"], role["color"], role["hoist"]
        existing = current_by_name.get(name)
        if existing is None:
            actions.append(Action("role", "create", name, {"name": name, "color": color, "hoist": hoist}))
        elif existing.get("color", 0) != color or existing.get("hoist", False) != hoist:
            actions.append(
                Action("role", "update", name, {"id": existing["id"], "name": name, "color": color, "hoist": hoist})
            )
    return actions


def diff_categories(desired: list[str], current: list[dict], renames: dict[str, str] | None = None) -> list[Action]:
    """`renames` maps OLD name -> NEW name. When the old name still exists on
    the server, the action is a PATCH of the name on the same id, which keeps
    the category, its child channels and their forum posts. It only becomes a
    "create" when there is nothing to inherit from."""
    renames = renames or {}
    old_by_new = {new: old for old, new in renames.items()}
    id_by_name = {c["name"]: c["id"] for c in current if c.get("type") == CATEGORY_TYPE}
    actions: list[Action] = []
    for name in desired:
        if name in id_by_name:
            continue
        old = old_by_new.get(name)
        if old and old in id_by_name:
            actions.append(Action("category", "rename", name, {"id": id_by_name[old], "old_name": old}))
            continue
        actions.append(Action("category", "create", name, {"name": name, "type": CATEGORY_TYPE}))
    return actions


def diff_channels(
    desired: list[dict],
    current_categories: list[dict],
    current_channels: list[dict],
    renames: dict[str, str] | None = None,
) -> list[Action]:
    """Channels are identified by (name, type, category). With a key of only
    (name, type), several "orders" forums (one per category) collapse into one
    and the diff emits updates that move the same channel through every
    category. With the category in the key, a different category means a
    different channel: it is created, never moved. Moving a channel between
    categories in the design therefore creates a new one and leaves the old
    one for you to delete; that is the safe trade-off.

    The parent id is not resolved here: on the first run the category may be
    created in this same pass, so the action carries the category NAME and
    `apply` resolves the id after the categories exist.

    `renames` translates a channel's current category before matching, since
    the category rename PATCH has not run yet when this diff is computed."""
    renames = renames or {}
    category_name_by_id = {c["id"]: c["name"] for c in current_categories if c.get("type") == CATEGORY_TYPE}
    existing = {}
    for channel in current_channels:
        if channel.get("type") == CATEGORY_TYPE:
            continue
        category = category_name_by_id.get(channel.get("parent_id"))
        existing[(channel["name"], channel["type"], renames.get(category, category))] = channel

    actions: list[Action] = []
    for channel in desired:
        type_number = CHANNEL_TYPE[channel["type"]]
        match = existing.get((channel["name"], type_number, channel["category"]))
        if match is None:
            actions.append(
                Action(
                    "channel",
                    "create",
                    channel["name"],
                    {
                        "name": channel["name"],
                        "type": type_number,
                        "category": channel["category"],
                        "topic": channel.get("topic"),
                    },
                )
            )
        elif match.get("topic") != channel.get("topic"):
            actions.append(
                Action(
                    "channel",
                    "update",
                    channel["name"],
                    {"id": match["id"], "category": channel["category"], "topic": channel.get("topic")},
                )
            )
    return actions


def diff_forum_tags(
    tags: list[dict], layout: int, current_channels: list[dict], managed_categories: list[dict]
) -> list[Action]:
    """Only forums inside the design's categories are touched; an empty tag
    list means "leave forum tags alone"."""
    if not tags:
        return []
    managed_ids = {c["id"] for c in managed_categories}
    wanted_names = {t["name"] for t in tags}
    payload = [{"name": t["name"], "emoji_name": t.get("emoji")} for t in tags]
    actions: list[Action] = []
    for channel in current_channels:
        if channel.get("type") != CHANNEL_TYPE["forum"] or channel.get("parent_id") not in managed_ids:
            continue
        current_names = {t["name"] for t in channel.get("available_tags", [])}
        if current_names != wanted_names or channel.get("default_forum_layout", 0) != layout:
            actions.append(
                Action(
                    "forum_tags",
                    "update",
                    channel["name"],
                    {"id": channel["id"], "available_tags": payload, "default_forum_layout": layout},
                )
            )
    return actions


def webhook_channel_id(
    webhook: dict, current_channels: list[dict], current_categories: list[dict] | None = None
) -> str | None:
    """The text channel a desired webhook lives in. With categories known, a
    same-named channel in an unmanaged category never matches."""
    text_types = (CHANNEL_TYPE["text"], CHANNEL_TYPE["announcement"])
    category_name_by_id = {c["id"]: c["name"] for c in current_categories or []}
    for channel in current_channels:
        if channel.get("type") not in text_types or channel.get("name") != webhook["channel"]:
            continue
        if current_categories is None or category_name_by_id.get(channel.get("parent_id")) == webhook["category"]:
            return channel["id"]
    return None


def diff_webhooks(
    desired: list[dict],
    current_channels: list[dict],
    webhooks_by_channel: dict,
    current_categories: list[dict] | None = None,
) -> list[Action]:
    """`webhooks_by_channel` must contain EVERY channel that has a desired
    webhook (see apply.collect_current_state): a channel missing from it looks
    empty, and a webhook would be created again on every run."""
    actions: list[Action] = []
    for webhook in desired:
        channel_id = webhook_channel_id(webhook, current_channels, current_categories)
        if channel_id is None:
            continue
        if any(w.get("name") == webhook["name"] for w in webhooks_by_channel.get(channel_id, [])):
            continue
        actions.append(Action("webhook", "create", webhook["name"], {"channel_id": channel_id}))
    return actions


def diff_icon(guild: dict, wanted: bool) -> list[Action]:
    """Only sets an icon when the server has none: never replaces yours."""
    if not wanted or guild.get("icon"):
        return []
    return [Action("icon", "apply", "icon", {})]


def find_bot_id(roles: list[dict], bot_role_name: str) -> str | None:
    """When a bot joins, Discord creates a managed role named after it with
    `tags.bot_id`. That is how `assign_to = "bot:<name>"` finds the bot."""
    for role in roles:
        if role.get("managed") and role.get("name") == bot_role_name:
            bot_id = role.get("tags", {}).get("bot_id")
            if bot_id:
                return bot_id
    return None


def diff_role_assignment(
    label: str, user_id: str | None, role_id: str | None, member_roles: list[str] | None
) -> list[Action]:
    """Gives `role_id` to `user_id` if missing. When the member or the role do
    not exist yet, or the member's roles could not be read, there is nothing
    to do now: a later run converges on its own."""
    if not user_id or not role_id or member_roles is None or role_id in member_roles:
        return []
    return [Action("role_assignment", "assign", label, {"user_id": user_id, "role_id": role_id})]


def _current_overwrites(entity: dict) -> dict:
    return {
        ow["id"]: {"allow": int(ow.get("allow", 0)), "deny": int(ow.get("deny", 0)), "type": ow.get("type", 0)}
        for ow in entity.get("permission_overwrites", [])
    }


def _matches(current: dict, wanted: dict) -> bool:
    empty = {"allow": 0, "deny": 0, "type": 0}
    return all(
        (current.get(rid, empty)["allow"] & CONTROLLED_BITS) == (bits["allow"] & CONTROLLED_BITS)
        and (current.get(rid, empty)["deny"] & CONTROLLED_BITS) == (bits["deny"] & CONTROLLED_BITS)
        for rid, bits in wanted.items()
    )


def _payload(current: dict, wanted: dict) -> list[dict]:
    """Keeps entities and bits this diff does not control: the original
    `type` of each overwrite is preserved, and for controlled ids only the bits
    inside CONTROLLED_BITS change."""
    empty = {"allow": 0, "deny": 0, "type": 0}
    payload = [
        {"id": rid, "type": v["type"], "allow": str(v["allow"]), "deny": str(v["deny"])}
        for rid, v in current.items()
        if rid not in wanted
    ]
    for rid, bits in wanted.items():
        now = current.get(rid, empty)
        payload.append(
            {
                "id": rid,
                "type": now["type"],
                "allow": str((now["allow"] & ~CONTROLLED_BITS) | bits["allow"]),
                "deny": str((now["deny"] & ~CONTROLLED_BITS) | bits["deny"]),
            }
        )
    return payload


def _wanted_bits(
    allowed: list[str], read_only: set[str], universe: set[str], role_id_by_name: dict, everyone_deny: int
) -> dict:
    wanted = {role_id_by_name["@everyone"]: {"allow": 0, "deny": everyone_deny}}
    for name in allowed:
        wanted[role_id_by_name[name]] = {
            "allow": VIEW_CHANNEL_BIT,
            "deny": SEND_MESSAGES_BIT if name in read_only else 0,
        }
    for name in universe - set(allowed):
        role_id = role_id_by_name.get(name)
        if role_id:
            wanted[role_id] = {"allow": 0, "deny": VIEW_CHANNEL_BIT}
    return wanted


def diff_category_overwrites(
    visibility: dict[str, list[str]],
    current_categories: list[dict],
    current_roles: list[dict],
    read_only_roles: dict[str, list[str]] | None = None,
) -> list[Action]:
    """Keeps each category in line with its children, mainly so that a channel
    created later in the UI with "sync with category" starts right. This alone
    does NOT fix existing channels (see diff_channel_overwrites).

    Waits until every listed role exists (on the first run roles and
    categories are created together). A category renamed in this same pass
    still has its old name here, so it converges on the next run.

    Every role that appears anywhere in `visibility` and is not listed for
    this category gets an explicit VIEW_CHANNEL deny."""
    read_only_roles = read_only_roles or {}
    role_id_by_name = {r["name"]: r["id"] for r in current_roles}
    if "@everyone" not in role_id_by_name:
        return []
    universe = {name for names in visibility.values() for name in names}
    actions: list[Action] = []
    for category in current_categories:
        allowed = visibility.get(category["name"])
        if allowed is None or any(name not in role_id_by_name for name in allowed):
            continue
        wanted = _wanted_bits(
            allowed, set(read_only_roles.get(category["name"], [])), universe, role_id_by_name, VIEW_CHANNEL_BIT
        )
        current = _current_overwrites(category)
        if _matches(current, wanted):
            continue
        actions.append(
            Action(
                "category_overwrite",
                "update",
                category["name"],
                {"id": category["id"], "permission_overwrites": _payload(current, wanted)},
            )
        )
    return actions


def diff_channel_overwrites(
    visibility: dict[str, list[str]],
    read_only_channels: set[tuple[str, str]],
    current_channels: list[dict],
    current_categories: list[dict],
    current_roles: list[dict],
    read_only_roles: dict[str, list[str]] | None = None,
) -> list[Action]:
    """This is what actually governs permissions: Discord evaluates the
    channel's own overwrites. Each channel gets the VIEW_CHANNEL rules of its
    category, plus SEND_MESSAGES denied to @everyone when (channel, category)
    is read-only, plus SEND_MESSAGES denied to read-only roles of the
    category (other roles in the same category keep writing)."""
    read_only_roles = read_only_roles or {}
    role_id_by_name = {r["name"]: r["id"] for r in current_roles}
    if "@everyone" not in role_id_by_name:
        return []
    category_name_by_id = {c["id"]: c["name"] for c in current_categories}
    universe = {name for names in visibility.values() for name in names}
    actions: list[Action] = []
    for channel in current_channels:
        if channel.get("type") == CATEGORY_TYPE:
            continue
        category = category_name_by_id.get(channel.get("parent_id"))
        allowed = visibility.get(category)
        if allowed is None or any(name not in role_id_by_name for name in allowed):
            continue
        everyone_deny = VIEW_CHANNEL_BIT
        if (channel.get("name"), category) in read_only_channels:
            everyone_deny |= SEND_MESSAGES_BIT
        wanted = _wanted_bits(allowed, set(read_only_roles.get(category, [])), universe, role_id_by_name, everyone_deny)
        current = _current_overwrites(channel)
        if _matches(current, wanted):
            continue
        actions.append(
            Action(
                "channel_overwrite",
                "update",
                channel.get("name", channel["id"]),
                {"id": channel["id"], "permission_overwrites": _payload(current, wanted)},
            )
        )
    return actions


def diff_community(desired: dict, guild: dict, rules_channel_id: str, updates_channel_id: str) -> list[Action]:
    current_features = set(guild.get("features", []))
    wanted_features = current_features | set(desired["features_add"])
    same = (
        current_features == wanted_features
        and guild.get("verification_level") == desired["verification_level"]
        and guild.get("explicit_content_filter") == desired["explicit_content_filter"]
        and guild.get("default_message_notifications") == desired["default_message_notifications"]
        and guild.get("rules_channel_id") == rules_channel_id
        and guild.get("public_updates_channel_id") == updates_channel_id
        and guild.get("description") == desired["description"]
    )
    if same:
        return []
    return [
        Action(
            "community",
            "update",
            "guild",
            {
                "features": sorted(wanted_features),
                "verification_level": desired["verification_level"],
                "explicit_content_filter": desired["explicit_content_filter"],
                "default_message_notifications": desired["default_message_notifications"],
                "rules_channel_id": rules_channel_id,
                "public_updates_channel_id": updates_channel_id,
                "description": desired["description"],
            },
        )
    ]
