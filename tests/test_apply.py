import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from discord_hq import config
from discord_hq.server import apply, design, diff

GUILD = "100000000000000001"
EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
RESTAURANT = design.load_design(EXAMPLES / "restaurant.toml")


def _settings(tmp_path, **env):
    environ = {
        "HOME": str(tmp_path),
        "DISCORD_HQ_CONFIG_DIR": str(tmp_path / "cfg"),
        "DISCORD_HQ_ADMIN_TOKEN": "secret-token-x",
        "DISCORD_HQ_GUILD_ID": GUILD,
    }
    environ.update(env)
    return config.load_settings(environ)


def _get(routes):
    def get(path):
        return routes[path]

    return get


def _empty_guild_routes(**extra):
    routes = {
        f"/guilds/{GUILD}": {"id": GUILD, "features": []},
        f"/guilds/{GUILD}/roles": [],
        f"/guilds/{GUILD}/channels": [],
    }
    routes.update(extra)
    return routes


# --- report ------------------------------------------------------------------


def test_report_lists_each_action():
    report = apply.build_report(
        [diff.Action("role", "create", "👑 Chef", {}), diff.Action("channel", "update", "rules", {"id": "1"})]
    )
    assert "create role 👑 Chef" in report
    assert "update channel rules" in report


def test_empty_report_says_zero_changes():
    assert "0 changes" in apply.build_report([])


def test_report_never_contains_tokens_or_webhook_urls():
    report = apply.build_report(
        [diff.Action("webhook", "create", "Pass", {"token_used": "SECRET123", "url": "https://x"})]
    )
    assert "SECRET123" not in report
    assert "https://x" not in report


def test_report_lists_deletions_separately():
    report = apply.build_report([diff.Action("channel", "delete", "general", {"id": "5"})], held_back=[])
    assert "DELETE" in report


# --- collect -----------------------------------------------------------------


def test_collect_reads_guild_roles_and_channels():
    api = MagicMock()
    api.get.side_effect = _get(_empty_guild_routes(**{f"/guilds/{GUILD}/roles": [{"id": "1", "name": "@everyone"}]}))
    current = apply.collect_current_state(api, GUILD, design.Design())
    assert current["roles"][0]["name"] == "@everyone"
    assert current["channels"] == []
    assert current["guild"]["id"] == GUILD
    assert current["webhooks_by_channel"] == {}
    assert current["assignments"] == []


def test_collect_reads_webhooks_of_every_channel_with_a_desired_webhook():
    # Found running for real: the channel filter was a hardcoded tuple, so a
    # new webhook channel in the design ("panel") never had its webhooks read,
    # always looked empty, and every apply created one more duplicate webhook.
    wanted = design.Design(
        webhooks=[
            {"name": "Pass", "channel": "served", "category": "🛎️ COUNTER"},
            {"name": "Panel", "channel": "panel", "category": "🛎️ COUNTER"},
        ]
    )
    channels = [
        {"id": "10", "name": "served", "type": 0},
        {"id": "20", "name": "panel", "type": 0},
        {"id": "12", "name": "table", "type": 0},
    ]
    api = MagicMock()
    api.get.side_effect = _get(
        _empty_guild_routes(
            **{
                f"/guilds/{GUILD}/channels": channels,
                "/channels/10/webhooks": [{"name": "Pass", "id": "x"}],
                "/channels/20/webhooks": [{"name": "Panel", "id": "y"}],
            }
        )
    )
    current = apply.collect_current_state(api, GUILD, wanted)
    assert current["webhooks_by_channel"] == {"10": [{"name": "Pass", "id": "x"}], "20": [{"name": "Panel", "id": "y"}]}


def test_collect_resolves_owner_and_bots_and_reads_their_roles():
    roles = [
        {"id": "r-waiter", "name": "WaiterBot", "managed": True, "tags": {"bot_id": "b-waiter"}},
        {"id": "r-station", "name": "StationBot", "managed": True, "tags": {"bot_id": "b-station"}},
    ]
    wanted = design.Design(
        role_assignments=[
            {"role": "👑 Chef", "to": "owner"},
            {"role": "🤵 Waiter", "to": "bot:WaiterBot"},
            {"role": "🖥️ Second Station", "to": "bot:StationBot"},
            {"role": "🧪 Missing", "to": "bot:NotInvitedYet"},
        ]
    )
    api = MagicMock()
    api.get.side_effect = _get(
        _empty_guild_routes(
            **{
                f"/guilds/{GUILD}": {"features": [], "owner_id": "u-owner"},
                f"/guilds/{GUILD}/roles": roles,
                f"/guilds/{GUILD}/members/u-owner": {"roles": ["r-waiter"]},
                f"/guilds/{GUILD}/members/b-waiter": {"roles": []},
                f"/guilds/{GUILD}/members/b-station": {"roles": ["r-x"]},
            }
        )
    )
    current = apply.collect_current_state(api, GUILD, wanted)
    by_role = {a["role"]: a for a in current["assignments"]}
    assert by_role["👑 Chef"]["user_id"] == "u-owner"
    assert by_role["👑 Chef"]["member_roles"] == ["r-waiter"]
    assert by_role["🤵 Waiter"]["user_id"] == "b-waiter"
    assert by_role["🖥️ Second Station"]["member_roles"] == ["r-x"]
    assert by_role["🧪 Missing"]["user_id"] is None


def test_collect_tolerates_a_member_that_left():
    wanted = design.Design(role_assignments=[{"role": "👑 Chef", "to": "owner"}])
    api = MagicMock()

    def get(path):
        if path.endswith("/members/u-owner"):
            raise apply.DiscordAPIError(404, {"message": "Unknown Member"})
        return _empty_guild_routes(**{f"/guilds/{GUILD}": {"features": [], "owner_id": "u-owner"}})[path]

    api.get.side_effect = get
    current = apply.collect_current_state(api, GUILD, wanted)
    assert current["assignments"][0]["member_roles"] is None


# --- compute -----------------------------------------------------------------


def test_compute_on_an_empty_guild_creates_roles_categories_and_channels():
    actions = apply.compute_actions(RESTAURANT, {"roles": [], "channels": [], "guild": {"features": []}})
    resources = {a.resource for a in actions}
    assert {"role", "category", "channel"} <= resources


def test_compute_deletes_factory_channels_only_by_exact_id():
    wanted = design.Design(delete_channel_ids=["300000000000000003"])
    current = {
        "roles": [],
        "guild": {"features": []},
        "channels": [
            {"id": "300000000000000003", "name": "general", "type": 0},
            {"id": "300000000000000999", "name": "general", "type": 0},
        ],
    }
    deletes = [a for a in apply.compute_actions(wanted, current) if a.operation == "delete"]
    # A "general" you create on purpose later must survive: match by id.
    assert [a.details["id"] for a in deletes] == ["300000000000000003"]


def test_compute_community_waits_for_its_channels():
    assert not any(
        a.resource == "community"
        for a in apply.compute_actions(RESTAURANT, {"roles": [], "channels": [], "guild": {"features": []}})
    )
    current = _guild_matching(RESTAURANT)
    current["guild"] = {"features": []}
    assert any(a.resource == "community" for a in apply.compute_actions(RESTAURANT, current))


def test_compute_applies_the_real_restaurant_guest_rules():
    # Runs the whole pipeline with the shipped example: the guest reads START
    # without writing, never sees BACKSTAGE, writes in GUESTS; the second
    # station never sees GUESTS (two bots never answer the same channel).
    current = _guild_matching(RESTAURANT)
    for channel in current["channels"]:
        channel["permission_overwrites"] = []
    role_ids = {r["name"]: r["id"] for r in current["roles"]}
    guest, station = role_ids["🤝 Guest"], role_ids["🖥️ Second Station"]

    actions = apply.compute_actions(RESTAURANT, current)
    by_channel = {}
    for a in actions:
        if a.resource == "channel_overwrite":
            by_channel[a.details["id"]] = {ow["id"]: ow for ow in a.details["permission_overwrites"]}
    ids = {(c["name"], c["_category"]): c["id"] for c in current["channels"] if c.get("type") != 4}

    start = by_channel[ids[("announcements", "📌 START")]]
    assert int(start[guest]["allow"]) & diff.VIEW_CHANNEL_BIT
    assert int(start[guest]["deny"]) & diff.SEND_MESSAGES_BIT

    backstage = by_channel[ids[("moderation", "🔒 BACKSTAGE")]]
    assert int(backstage[guest]["deny"]) & diff.VIEW_CHANNEL_BIT

    guests = by_channel[ids[("guest-table", "🤝 GUESTS")]]
    assert int(guests[guest]["allow"]) & diff.VIEW_CHANNEL_BIT
    assert not int(guests[guest]["deny"]) & diff.SEND_MESSAGES_BIT
    assert int(guests[station]["deny"]) & diff.VIEW_CHANNEL_BIT


def _guild_matching(wanted):
    """A mock guild that already matches the design exactly."""
    roles = [{"id": "role-everyone", "name": "@everyone"}]
    for i, r in enumerate(wanted.roles):
        roles.append({"id": f"role-{i}", "name": r["name"], "color": r["color"], "hoist": r["hoist"]})
    categories = [{"id": f"cat-{i}", "name": n, "type": 4} for i, n in enumerate(wanted.categories)]
    cat_id = {c["name"]: c["id"] for c in categories}
    channels = []
    for i, ch in enumerate(wanted.channels):
        channel = {
            "id": f"ch-{i}",
            "name": ch["name"],
            "type": diff.CHANNEL_TYPE[ch["type"]],
            "parent_id": cat_id[ch["category"]],
            "topic": ch["topic"],
            "_category": ch["category"],
        }
        if ch["type"] == "forum":
            channel["available_tags"] = [{"name": t["name"]} for t in wanted.forum_tags]
            channel["default_forum_layout"] = wanted.forum_layout
        channels.append(channel)
    return {
        "roles": roles,
        "channels": categories + channels,
        "guild": {"features": [], "icon": "hash"},
        "webhooks_by_channel": {},
    }


def _converged(wanted):
    """Apply every overwrite/community/webhook action once, so the mock
    guild ends up exactly where a real server would after `apply`."""
    current = _guild_matching(wanted)
    for action in apply.compute_actions(wanted, current):
        if action.resource in ("category_overwrite", "channel_overwrite"):
            target = next(c for c in current["channels"] if c["id"] == action.details["id"])
            target["permission_overwrites"] = action.details["permission_overwrites"]
        elif action.resource == "community":
            current["guild"].update(action.details)
        elif action.resource == "webhook":
            current["webhooks_by_channel"].setdefault(action.details["channel_id"], []).append({"name": action.name})
    return current


def test_full_idempotency_on_a_guild_that_already_matches():
    # Review finding: an empty/missing state.json must never duplicate
    # anything. The live server is the source of truth: 0 creates and 0
    # overwrite changes once it matches.
    assert apply.compute_actions(RESTAURANT, _converged(RESTAURANT)) == []


def test_compute_scopes_forum_tags_to_managed_categories():
    current = _converged(RESTAURANT)
    current["channels"].append({"id": "foreign-cat", "name": "SOMEONE ELSE", "type": 4})
    current["channels"].append(
        {"id": "foreign-forum", "name": "ideas", "type": 15, "parent_id": "foreign-cat", "available_tags": []}
    )
    assert apply.compute_actions(RESTAURANT, current) == []


# --- apply actions --------------------------------------------------------------


def _run(api, actions, tmp_path, state=None, categories=None, icon_spec=None):
    state = {} if state is None else state
    apply.apply_actions(
        api,
        GUILD,
        actions,
        state,
        current_categories=categories,
        webhooks_path=tmp_path / "cfg" / "webhooks.json",
        icon_spec=icon_spec,
    )
    return state


def test_create_role_records_its_id(tmp_path):
    api = MagicMock()
    api.post.return_value = {"id": "new-id-123"}
    state = _run(
        api, [diff.Action("role", "create", "👑 Chef", {"name": "👑 Chef", "color": 0xF1C40F, "hoist": True})], tmp_path
    )
    api.post.assert_called_once_with(
        f"/guilds/{GUILD}/roles", json={"name": "👑 Chef", "color": 0xF1C40F, "hoist": True}
    )
    assert state["roles"]["👑 Chef"] == "new-id-123"


def test_update_role_patches_by_id(tmp_path):
    api = MagicMock()
    _run(
        api,
        [diff.Action("role", "update", "👑 Chef", {"id": "1", "name": "👑 Chef", "color": 1, "hoist": True})],
        tmp_path,
    )
    api.patch.assert_called_once_with(f"/guilds/{GUILD}/roles/1", json={"color": 1, "hoist": True})


def test_delete_channel_by_id(tmp_path):
    api = MagicMock()
    _run(api, [diff.Action("channel", "delete", "general", {"id": "555"})], tmp_path)
    api.delete.assert_called_once_with("/channels/555")


def test_no_actions_no_calls(tmp_path):
    api = MagicMock()
    _run(api, [], tmp_path)
    api.post.assert_not_called()
    api.patch.assert_not_called()
    api.delete.assert_not_called()


def test_category_then_channel_resolves_parent_id_at_apply_time(tmp_path):
    api = MagicMock()
    api.post.side_effect = [{"id": "cat-1"}, {"id": "channel-1"}]
    state = _run(
        api,
        [
            diff.Action("category", "create", "📌 START", {"name": "📌 START", "type": 4}),
            diff.Action(
                "channel", "create", "rules", {"name": "rules", "type": 0, "category": "📌 START", "topic": "x"}
            ),
        ],
        tmp_path,
    )
    assert state["categories"]["📌 START"] == "cat-1"
    assert state["channels"]["rules (📌 START)"] == "channel-1"
    assert api.post.call_args_list[1].kwargs["json"]["parent_id"] == "cat-1"


def test_same_channel_name_in_several_categories_keeps_every_id(tmp_path):
    # Same bug as in the diff, when writing state: without the category in the
    # key, one "orders" forum per category would overwrite the same entry.
    api = MagicMock()
    api.post.side_effect = [{"id": "id-alpha"}, {"id": "id-lab"}]
    state = _run(
        api,
        [
            diff.Action(
                "channel",
                "create",
                "orders",
                {"name": "orders", "type": 15, "category": "🍝 PROJECT ALPHA", "topic": "t"},
            ),
            diff.Action(
                "channel", "create", "orders", {"name": "orders", "type": 15, "category": "🧪 LAB", "topic": "t"}
            ),
        ],
        tmp_path,
    )
    assert state["channels"]["orders (🍝 PROJECT ALPHA)"] == "id-alpha"
    assert state["channels"]["orders (🧪 LAB)"] == "id-lab"


def test_channel_in_existing_category_uses_the_current_category_id(tmp_path):
    api = MagicMock()
    api.post.return_value = {"id": "channel-1"}
    _run(
        api,
        [diff.Action("channel", "create", "rules", {"name": "rules", "type": 0, "category": "📌 START", "topic": "x"})],
        tmp_path,
        categories=[{"id": "cat-existing", "name": "📌 START", "type": 4}],
    )
    assert api.post.call_args.kwargs["json"]["parent_id"] == "cat-existing"


def test_rename_category_patches_and_rekeys_state(tmp_path):
    api = MagicMock()
    state = {"categories": {"📊 OLD": "cat-old"}, "channels": {"orders (📊 OLD)": "forum-old"}}
    _run(
        api,
        [diff.Action("category", "rename", "💻 NEW", {"id": "cat-old", "old_name": "📊 OLD"})],
        tmp_path,
        state=state,
    )
    api.patch.assert_called_once_with("/channels/cat-old", json={"name": "💻 NEW"})
    assert state["categories"] == {"💻 NEW": "cat-old"}
    assert state["channels"] == {"orders (💻 NEW)": "forum-old"}


def test_channel_created_after_rename_in_same_pass_gets_the_renamed_id(tmp_path):
    api = MagicMock()
    api.post.return_value = {"id": "new-channel"}
    _run(
        api,
        [
            diff.Action("category", "rename", "💻 NEW", {"id": "cat-old", "old_name": "📊 OLD"}),
            diff.Action(
                "channel", "create", "other", {"name": "other", "type": 0, "category": "💻 NEW", "topic": None}
            ),
        ],
        tmp_path,
    )
    assert api.post.call_args.kwargs["json"]["parent_id"] == "cat-old"


def test_update_channel_resolves_parent_by_category_name(tmp_path):
    api = MagicMock()
    _run(
        api,
        [diff.Action("channel", "update", "rules", {"id": "99", "category": "📌 START", "topic": "new"})],
        tmp_path,
        categories=[{"id": "10", "name": "📌 START", "type": 4}],
    )
    api.patch.assert_called_once_with("/channels/99", json={"parent_id": "10", "topic": "new"})


def test_community_patches_the_guild(tmp_path):
    api = MagicMock()
    details = {"features": ["COMMUNITY"], "verification_level": 2}
    _run(api, [diff.Action("community", "update", "guild", details)], tmp_path)
    api.patch.assert_called_once_with(f"/guilds/{GUILD}", json=details)


def test_forum_tags_patch_the_channel(tmp_path):
    api = MagicMock()
    tags = [{"name": "✨ feature", "emoji_name": "✨"}]
    _run(
        api,
        [diff.Action("forum_tags", "update", "orders", {"id": "7", "available_tags": tags, "default_forum_layout": 1})],
        tmp_path,
    )
    api.patch.assert_called_once_with("/channels/7", json={"available_tags": tags, "default_forum_layout": 1})


def test_webhook_url_is_saved_outside_the_repo_with_mode_0600(tmp_path, capsys):
    api = MagicMock()
    api.post.return_value = {"id": "999", "token": "tok-secret"}
    state = _run(api, [diff.Action("webhook", "create", "Pass", {"channel_id": "10"})], tmp_path)
    api.post.assert_called_once_with("/channels/10/webhooks", json={"name": "Pass"})
    path = tmp_path / "cfg" / "webhooks.json"
    assert json.loads(path.read_text())["Pass"] == "https://discord.com/api/webhooks/999/tok-secret"
    assert path.stat().st_mode & 0o777 == 0o600
    assert "tok-secret" not in json.dumps(state)
    assert "tok-secret" not in capsys.readouterr().out


def test_webhook_file_is_created_0600_even_with_a_permissive_umask(tmp_path):
    import os

    old = os.umask(0)
    try:
        api = MagicMock()
        api.post.return_value = {"id": "1", "token": "t"}
        _run(api, [diff.Action("webhook", "create", "Bell", {"channel_id": "10"})], tmp_path)
    finally:
        os.umask(old)
    assert (tmp_path / "cfg" / "webhooks.json").stat().st_mode & 0o777 == 0o600


def test_icon_patches_the_guild(tmp_path):
    api = MagicMock()
    with patch.object(apply, "icon_data_uri", return_value="data:image/png;base64,XYZ"):
        _run(api, [diff.Action("icon", "apply", "icon", {})], tmp_path, icon_spec={"letter": "K"})
    api.patch.assert_called_once_with(f"/guilds/{GUILD}", json={"icon": "data:image/png;base64,XYZ"})


def test_role_assignment_puts_the_role_on_the_member(tmp_path):
    api = MagicMock()
    _run(api, [diff.Action("role_assignment", "assign", "x", {"user_id": "u-1", "role_id": "role-1"})], tmp_path)
    api.put.assert_called_once_with(f"/guilds/{GUILD}/members/u-1/roles/role-1")


def test_overwrites_patch_the_channel(tmp_path):
    api = MagicMock()
    _run(api, [diff.Action("channel_overwrite", "update", "rules", {"id": "5", "permission_overwrites": []})], tmp_path)
    api.patch.assert_called_once_with("/channels/5", json={"permission_overwrites": []})


# --- pinned messages ------------------------------------------------------------


def test_pinned_messages_are_posted_pinned_and_recorded():
    wanted = design.Design(pinned_messages=[{"channel": "rules", "category": "📌 START", "content": "Be kind."}])
    current = {
        "channels": [
            {"id": "c-start", "name": "📌 START", "type": 4},
            {"id": "c-rules", "name": "rules", "type": 0, "parent_id": "c-start"},
        ]
    }
    api = MagicMock()
    api.post.return_value = {"id": "msg-1"}
    state = {}
    apply.post_pinned_messages(api, wanted, state, current)
    api.post.assert_called_once_with(
        "/channels/c-rules/messages", json={"content": "Be kind.", "allowed_mentions": {"parse": []}}
    )
    api.put.assert_called_once_with("/channels/c-rules/pins/msg-1")
    assert state["pinned"] == {"rules (📌 START)": "msg-1"}


def test_pinned_messages_are_posted_once():
    wanted = design.Design(pinned_messages=[{"channel": "rules", "category": "📌 START", "content": "Be kind."}])
    api = MagicMock()
    apply.post_pinned_messages(api, wanted, {"pinned": {"rules (📌 START)": "msg-1"}}, {"channels": []})
    api.post.assert_not_called()


# --- audit forum ------------------------------------------------------------------


def test_audit_forum_joins_active_and_archived_threads():
    api = MagicMock()
    api.get.side_effect = _get(
        {
            f"/guilds/{GUILD}/threads/active": {
                "threads": [
                    {"name": "active post", "parent_id": "forum-1"},
                    {"name": "other forum", "parent_id": "forum-2"},
                ]
            },
            "/channels/forum-1/threads/archived/public": {"threads": [{"name": "archived post"}]},
        }
    )
    assert apply.audit_forum(api, GUILD, "forum-1") == {"total": 2, "names": ["active post", "archived post"]}


def test_audit_forum_empty():
    api = MagicMock()
    api.get.side_effect = _get(
        {
            f"/guilds/{GUILD}/threads/active": {"threads": []},
            "/channels/forum-1/threads/archived/public": {"threads": []},
        }
    )
    assert apply.audit_forum(api, GUILD, "forum-1") == {"total": 0, "names": []}


# --- run: plan / apply ------------------------------------------------------------


def _design_file(tmp_path):
    path = tmp_path / "design.toml"
    path.write_text((EXAMPLES / "minimal.toml").read_text())
    return path


def test_plan_never_writes(tmp_path, capsys):
    api = MagicMock()
    api.get.side_effect = _get(_empty_guild_routes())
    with patch.object(apply, "DiscordClient", return_value=api):
        code = apply.run(_settings(tmp_path), _design_file(tmp_path), mode="plan")
    assert code == 0
    api.post.assert_not_called()
    api.patch.assert_not_called()
    api.put.assert_not_called()
    api.delete.assert_not_called()
    out = capsys.readouterr().out
    assert "create role" in out
    assert "secret-token-x" not in out


def test_apply_asks_for_confirmation_and_stops_on_no(tmp_path):
    api = MagicMock()
    api.get.side_effect = _get(_empty_guild_routes())
    with patch.object(apply, "DiscordClient", return_value=api):
        code = apply.run(_settings(tmp_path), _design_file(tmp_path), mode="apply", confirm=lambda prompt: False)
    assert code == 1
    api.post.assert_not_called()


def test_apply_without_tty_needs_yes(tmp_path):
    api = MagicMock()
    api.get.side_effect = _get(_empty_guild_routes())
    with (
        patch.object(apply, "DiscordClient", return_value=api),
        patch.object(apply.sys.stdin, "isatty", return_value=False),
    ):
        code = apply.run(_settings(tmp_path), _design_file(tmp_path), mode="apply")
    assert code == 1
    api.post.assert_not_called()


def test_apply_iterates_until_it_converges_and_saves_state(tmp_path):
    empty = {"roles": [], "channels": [], "guild": {"features": []}, "webhooks_by_channel": {}, "assignments": []}
    converged = _converged(design.load_design(_design_file(tmp_path)))
    converged["assignments"] = []
    api = MagicMock()
    api.post.return_value = {"id": "generic-id", "token": "tok"}
    with (
        patch.object(apply, "DiscordClient", return_value=api),
        patch.object(apply, "collect_current_state", side_effect=[empty, converged, converged]) as collect,
    ):
        code = apply.run(_settings(tmp_path), _design_file(tmp_path), mode="apply", yes=True)
    assert code == 0
    assert collect.call_count >= 2
    saved = json.loads((tmp_path / "state.json").read_text())
    assert saved["channels"]["table (🛎️ COUNTER)"]
    assert "tok" not in json.dumps(saved)


def test_deletions_are_held_back_without_allow_delete(tmp_path, capsys):
    path = tmp_path / "design.toml"
    path.write_text('[cleanup]\ndelete_channel_ids = ["300000000000000003"]\n')
    routes = _empty_guild_routes(
        **{f"/guilds/{GUILD}/channels": [{"id": "300000000000000003", "name": "general", "type": 0}]}
    )
    api = MagicMock()
    api.get.side_effect = _get(routes)
    with patch.object(apply, "DiscordClient", return_value=api):
        code = apply.run(_settings(tmp_path), path, mode="apply", yes=True)
    assert code == 0
    api.delete.assert_not_called()
    assert "--allow-delete" in capsys.readouterr().out


def test_deletions_run_with_allow_delete(tmp_path):
    path = tmp_path / "design.toml"
    path.write_text('[cleanup]\ndelete_channel_ids = ["300000000000000003"]\n')
    channels = [[{"id": "300000000000000003", "name": "general", "type": 0}], [], []]
    api = MagicMock()

    def get(p):
        if p == f"/guilds/{GUILD}/channels":
            return channels.pop(0) if len(channels) > 1 else channels[0]
        return _empty_guild_routes()[p]

    api.get.side_effect = get
    with patch.object(apply, "DiscordClient", return_value=api):
        code = apply.run(_settings(tmp_path), path, mode="apply", yes=True, allow_delete=True)
    assert code == 0
    api.delete.assert_called_once_with("/channels/300000000000000003")


def test_missing_token_is_a_clear_error_without_api_calls(tmp_path, capsys):
    settings = _settings(tmp_path, DISCORD_HQ_ADMIN_TOKEN="")
    with patch.object(apply, "DiscordClient") as client_class:
        code = apply.run(settings, _design_file(tmp_path), mode="plan")
    assert code == 2
    client_class.assert_not_called()
    assert "DISCORD_HQ_ADMIN_TOKEN" in capsys.readouterr().err


def test_invalid_design_is_reported_before_any_api_call(tmp_path, capsys):
    path = tmp_path / "design.toml"
    path.write_text("[[role]]\n")
    with patch.object(apply, "DiscordClient") as client_class:
        code = apply.run(_settings(tmp_path), path, mode="plan")
    assert code == 2
    client_class.assert_not_called()
    assert "unknown" in capsys.readouterr().err


def test_state_path_defaults_next_to_the_design(tmp_path):
    assert apply.state_path_for(_settings(tmp_path), tmp_path / "x" / "design.toml") == tmp_path / "x" / "state.json"
    custom = _settings(tmp_path, DISCORD_HQ_STATE=str(tmp_path / "s.json"))
    assert apply.state_path_for(custom, tmp_path / "design.toml") == tmp_path / "s.json"


@pytest.mark.parametrize("example", ["minimal.toml", "restaurant.toml"])
def test_examples_plan_cleanly_against_an_empty_guild(example, tmp_path):
    api = MagicMock()
    api.get.side_effect = _get(_empty_guild_routes())
    with patch.object(apply, "DiscordClient", return_value=api):
        assert apply.run(_settings(tmp_path), EXAMPLES / example, mode="plan") == 0


def test_apply_with_nothing_to_change_still_rebuilds_state_and_posts_pins(tmp_path):
    # Review finding: returning early on 0 actions left a lost state.json
    # unrebuilt forever and never posted a newly added pinned message.
    path = _design_file(tmp_path)
    path.write_text(path.read_text() + '\n[[pinned_messages]]\nchannel = "table"\ncontent = "Hello."\n')
    converged = _converged(design.load_design(path))
    converged["assignments"] = []
    api = MagicMock()
    api.post.return_value = {"id": "msg-1"}
    with (
        patch.object(apply, "DiscordClient", return_value=api),
        patch.object(apply, "collect_current_state", return_value=converged),
    ):
        code = apply.run(
            _settings(tmp_path), path, mode="apply", confirm=lambda prompt: pytest.fail("asked with nothing to apply")
        )
    assert code == 0
    saved = json.loads((tmp_path / "state.json").read_text())
    assert saved["channels"]["table (🛎️ COUNTER)"]
    assert saved["pinned"] == {"table (🛎️ COUNTER)": "msg-1"}


def test_plan_with_nothing_to_change_writes_nothing(tmp_path):
    converged = _converged(design.load_design(_design_file(tmp_path)))
    converged["assignments"] = []
    with patch.object(apply, "DiscordClient"), patch.object(apply, "collect_current_state", return_value=converged):
        assert apply.run(_settings(tmp_path), _design_file(tmp_path), mode="plan") == 0
    assert not (tmp_path / "state.json").exists()


def test_discord_api_error_is_a_clean_message_not_a_traceback(tmp_path, capsys):
    with (
        patch.object(apply, "DiscordClient"),
        patch.object(
            apply, "collect_current_state", side_effect=apply.DiscordAPIError(403, {"message": "Missing Access"})
        ),
    ):
        code = apply.run(_settings(tmp_path), _design_file(tmp_path), mode="plan")
    assert code == 1
    err = capsys.readouterr().err
    assert "403" in err and "Traceback" not in err
    assert "secret-token-x" not in err


def test_pinned_message_is_recorded_even_if_pinning_fails():
    # Otherwise a failed pin PUT would post the message again next run.
    wanted = design.Design(pinned_messages=[{"channel": "rules", "category": "📌 START", "content": "x"}])
    current = {
        "channels": [
            {"id": "c", "name": "📌 START", "type": 4},
            {"id": "r", "name": "rules", "type": 0, "parent_id": "c"},
        ]
    }
    api = MagicMock()
    api.post.return_value = {"id": "msg-1"}
    api.put.side_effect = apply.DiscordAPIError(403, {})
    state = {}
    with pytest.raises(apply.DiscordAPIError):
        apply.post_pinned_messages(api, wanted, state, current)
    assert state["pinned"] == {"rules (📌 START)": "msg-1"}
