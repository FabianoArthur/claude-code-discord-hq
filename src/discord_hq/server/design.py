"""Load a server design (TOML) and turn it into the desired state the diff
engine understands.

The design is the single source of truth: changing the server means editing
the TOML file, never the code. Validation is strict on purpose — a typo that
silently does nothing (an unknown key, a role that doesn't exist, a channel
name Discord will rewrite) is worse than a loud error before any API call.
See docs/design-format.md for the full reference.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CHANNEL_TYPES = {"text", "voice", "announcement", "forum"}
TEXT_LIKE = {"text", "announcement"}
FORUM_LAYOUTS = {"default": 0, "list": 1, "gallery": 2}
ANSWER_MODES = {"always", "mention"}

_TOP_LEVEL_KEYS = {"server", "community", "forum", "roles", "categories", "pinned_messages", "cleanup"}
_SERVER_KEYS = {"description", "icon_letter", "icon_color", "icon_background"}
_COMMUNITY_KEYS = {
    "description",
    "rules_channel",
    "public_updates_channel",
    "verification_level",
    "explicit_content_filter",
    "default_message_notifications",
}
_FORUM_KEYS = {"tags", "layout"}
_ROLE_KEYS = {"name", "color", "hoist", "assign_to"}
_CATEGORY_KEYS = {"name", "visible_to", "read_only_for", "rename_from", "channels"}
_CHANNEL_KEYS = {"name", "type", "topic", "read_only", "webhook", "answered_by"}
_PINNED_KEYS = {"channel", "content"}
_CLEANUP_KEYS = {"delete_channel_ids"}

# Discord rewrites text-like channel names to lowercase with dashes. A name it
# would rewrite never matches on the next run, so the diff would recreate it
# forever. Non-ASCII (emoji, accents) is kept by Discord as-is.
_DISCORD_SAFE_NAME = re.compile(r"^[^A-Z\s]+$")
_HEX_COLOR = re.compile(r"^#?[0-9a-fA-F]{6}$")


class DesignError(ValueError):
    """The design file is missing, unparsable or inconsistent."""


@dataclass
class Design:
    roles: list[dict] = field(default_factory=list)
    role_assignments: list[dict] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    category_renames: dict[str, str] = field(default_factory=dict)
    channels: list[dict] = field(default_factory=list)
    category_visibility: dict[str, list[str]] = field(default_factory=dict)
    read_only_roles: dict[str, list[str]] = field(default_factory=dict)
    read_only_channels: set[tuple[str, str]] = field(default_factory=set)
    webhooks: list[dict] = field(default_factory=list)
    answered_by: dict[tuple[str, str], dict[str, str]] = field(default_factory=dict)
    community: dict | None = None
    forum_tags: list[dict] = field(default_factory=list)
    forum_layout: int = FORUM_LAYOUTS["list"]
    pinned_messages: list[dict] = field(default_factory=list)
    delete_channel_ids: list[str] = field(default_factory=list)
    icon: dict | None = None


def _check_keys(where: str, table: dict, allowed: set[str]) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise DesignError(f"{where}: unknown key(s) {', '.join(unknown)} (allowed: {', '.join(sorted(allowed))})")


def _color(where: str, value, default: int | None = None) -> int:
    if value is None:
        if default is None:
            return 0
        return default
    if isinstance(value, bool):
        raise DesignError(f"{where}: invalid color {value!r}")
    if isinstance(value, int) and 0 <= value <= 0xFFFFFF:
        return value
    if isinstance(value, str) and _HEX_COLOR.match(value):
        return int(value.lstrip("#"), 16)
    raise DesignError(f'{where}: invalid color {value!r} (use "#RRGGBB" or an integer)')


def _rgb(value: int) -> tuple[int, int, int]:
    return ((value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF)


def _str_list(where: str, value) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise DesignError(f"{where}: expected a list of strings")
    return list(value)


def load_design(path: Path) -> Design:
    path = Path(path)
    try:
        raw = tomllib.loads(path.read_text())
    except FileNotFoundError:
        raise DesignError(f"design file not found: {path}") from None
    except tomllib.TOMLDecodeError as exc:
        raise DesignError(f"{path}: invalid TOML: {exc}") from None
    return parse_design(raw)


def parse_design(raw: dict) -> Design:
    _check_keys("design", raw, _TOP_LEVEL_KEYS)
    out = Design()

    server = raw.get("server", {})
    _check_keys("[server]", server, _SERVER_KEYS)
    if server.get("icon_letter"):
        out.icon = {
            "letter": str(server["icon_letter"])[:2],
            "color": _rgb(_color("[server] icon_color", server.get("icon_color"), 0xF1C40F)),
            "background": _rgb(_color("[server] icon_background", server.get("icon_background"), 0x121214)),
        }

    role_names: list[str] = []
    for i, role in enumerate(raw.get("roles", [])):
        where = f"[[roles]] #{i + 1}"
        _check_keys(where, role, _ROLE_KEYS)
        name = role.get("name")
        if not isinstance(name, str) or not name.strip():
            raise DesignError(f"{where}: missing name")
        if name == "@everyone":
            raise DesignError(f"{where}: @everyone is built in; it is always denied VIEW_CHANNEL on managed categories")
        if name in role_names:
            raise DesignError(f"{where}: duplicate role {name!r}")
        role_names.append(name)
        out.roles.append(
            {
                "name": name,
                "color": _color(f"{where} ({name})", role.get("color")),
                "hoist": bool(role.get("hoist", False)),
            }
        )
        assign_to = role.get("assign_to")
        if assign_to is not None:
            valid = assign_to == "owner" or (
                isinstance(assign_to, str) and assign_to.startswith("bot:") and len(assign_to) > 4
            )
            if not valid:
                raise DesignError(f'{where} ({name}): assign_to must be "owner" or "bot:<bot role name>"')
            out.role_assignments.append({"role": name, "to": assign_to})

    channel_keys: set[tuple[str, str, str]] = set()
    text_channels_by_name: dict[str, list[str]] = {}
    webhook_names: set[str] = set()
    for i, category in enumerate(raw.get("categories", [])):
        where = f"[[categories]] #{i + 1}"
        _check_keys(where, category, _CATEGORY_KEYS)
        cat_name = category.get("name")
        if not isinstance(cat_name, str) or not cat_name.strip():
            raise DesignError(f"{where}: missing name")
        if cat_name in out.categories:
            raise DesignError(f"{where}: duplicate category {cat_name!r}")
        out.categories.append(cat_name)
        where = f"category {cat_name!r}"

        if category.get("rename_from"):
            out.category_renames[str(category["rename_from"])] = cat_name

        if "visible_to" in category:
            visible = _str_list(f"{where} visible_to", category["visible_to"])
            read_only = _str_list(f"{where} read_only_for", category.get("read_only_for"))
            for role in visible + read_only:
                if role not in role_names:
                    raise DesignError(f"{where}: unknown role {role!r} (declare it under [[roles]])")
            for role in read_only:
                if role not in visible:
                    raise DesignError(f"{where}: read_only_for role {role!r} must also be in visible_to")
            out.category_visibility[cat_name] = visible
            if read_only:
                out.read_only_roles[cat_name] = read_only
        elif "read_only_for" in category:
            raise DesignError(f"{where}: read_only_for needs visible_to")

        for j, channel in enumerate(category.get("channels", [])):
            cwhere = f"{where} channel #{j + 1}"
            _check_keys(cwhere, channel, _CHANNEL_KEYS)
            name = channel.get("name")
            kind = channel.get("type", "text")
            if not isinstance(name, str) or not name.strip():
                raise DesignError(f"{cwhere}: missing name")
            cwhere = f"{where} channel {name!r}"
            if kind not in CHANNEL_TYPES:
                raise DesignError(f"{cwhere}: unknown type {kind!r} (use one of {', '.join(sorted(CHANNEL_TYPES))})")
            if kind != "voice" and not _DISCORD_SAFE_NAME.match(name):
                raise DesignError(
                    f"{cwhere}: text/forum channel names must be lowercase without spaces (Discord rewrites them)"
                )
            key = (name, kind, cat_name)
            if key in channel_keys:
                raise DesignError(f"{cwhere}: duplicate channel")
            channel_keys.add(key)
            topic = channel.get("topic") or None  # Discord returns null for an empty topic
            if topic is not None and kind == "voice":
                raise DesignError(f"{cwhere}: voice channels have no topic")
            out.channels.append({"name": name, "type": kind, "category": cat_name, "topic": topic})
            if kind in TEXT_LIKE:
                text_channels_by_name.setdefault(name, []).append(cat_name)

            if channel.get("read_only"):
                if kind not in TEXT_LIKE:
                    raise DesignError(f"{cwhere}: read_only applies to text channels")
                out.read_only_channels.add((name, cat_name))

            webhook = channel.get("webhook")
            if webhook is not None:
                if kind not in TEXT_LIKE:
                    raise DesignError(f"{cwhere}: a webhook needs a text channel")
                if webhook in webhook_names:
                    raise DesignError(f"{cwhere}: duplicate webhook {webhook!r}")
                webhook_names.add(webhook)
                out.webhooks.append({"name": webhook, "channel": name, "category": cat_name})

            answered_by = channel.get("answered_by")
            if answered_by is not None:
                if not isinstance(answered_by, dict) or not all(m in ANSWER_MODES for m in answered_by.values()):
                    raise DesignError(f'{cwhere}: answered_by values must be "always" or "mention"')
                if len(answered_by) > 1 and "always" in answered_by.values():
                    raise DesignError(
                        f"{cwhere}: two bots would answer every message here; "
                        'with more than one bot, all must be "mention"'
                    )
                out.answered_by[(name, cat_name)] = dict(answered_by)

    for renamed_from in out.category_renames:
        if renamed_from in out.categories:
            raise DesignError(f"rename_from {renamed_from!r} is also a category in the design")

    for webhook in out.webhooks:
        if len(text_channels_by_name.get(webhook["channel"], [])) > 1:
            raise DesignError(
                f"webhook {webhook['name']!r}: channel name {webhook['channel']!r} "
                "is ambiguous (used in several categories)"
            )

    def text_channel_ref(where: str, name) -> tuple[str, str]:
        categories = text_channels_by_name.get(name, [])
        if not categories:
            raise DesignError(f"{where}: no text channel named {name!r} in the design")
        if len(categories) > 1:
            raise DesignError(f"{where}: channel name {name!r} is ambiguous (used in several categories)")
        return (name, categories[0])

    if "community" in raw:
        community = raw["community"]
        _check_keys("[community]", community, _COMMUNITY_KEYS)
        out.community = {
            "features_add": ["COMMUNITY"],
            "verification_level": int(community.get("verification_level", 2)),
            "explicit_content_filter": int(community.get("explicit_content_filter", 2)),
            "default_message_notifications": int(community.get("default_message_notifications", 1)),
            "rules_channel": text_channel_ref("[community] rules_channel", community.get("rules_channel")),
            "public_updates_channel": text_channel_ref(
                "[community] public_updates_channel", community.get("public_updates_channel")
            ),
            "description": community.get("description", server.get("description")),
        }

    forum = raw.get("forum", {})
    _check_keys("[forum]", forum, _FORUM_KEYS)
    layout = forum.get("layout", "list")
    if layout not in FORUM_LAYOUTS:
        raise DesignError(f"[forum] layout must be one of {', '.join(FORUM_LAYOUTS)}")
    out.forum_layout = FORUM_LAYOUTS[layout]
    for tag in forum.get("tags", []):
        if not isinstance(tag, dict) or not tag.get("name"):
            raise DesignError("[forum] each tag needs a name")
        out.forum_tags.append({"name": tag["name"], "emoji": tag.get("emoji")})

    for i, message in enumerate(raw.get("pinned_messages", [])):
        where = f"[[pinned_messages]] #{i + 1}"
        _check_keys(where, message, _PINNED_KEYS)
        name, cat_name = text_channel_ref(where, message.get("channel"))
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise DesignError(f"{where}: missing content")
        if len(content) > 2000:
            raise DesignError(f"{where}: content is longer than Discord's 2000 characters")
        out.pinned_messages.append({"channel": name, "category": cat_name, "content": content})

    cleanup = raw.get("cleanup", {})
    _check_keys("[cleanup]", cleanup, _CLEANUP_KEYS)
    ids = _str_list("[cleanup] delete_channel_ids", cleanup.get("delete_channel_ids"))
    if not all(i.isdigit() for i in ids):
        raise DesignError("[cleanup] delete_channel_ids must be numeric channel ids (quoted strings)")
    out.delete_channel_ids = ids

    return out
