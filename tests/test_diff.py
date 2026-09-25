from discord_hq.server import diff

VIEW_CHANNEL = 1 << 10
SEND_MESSAGES = 1 << 11
FORUM = diff.CHANNEL_TYPE["forum"]
TEXT = diff.CHANNEL_TYPE["text"]


# --- roles -------------------------------------------------------------------


def test_missing_role_is_created():
    actions = diff.diff_roles([{"name": "👑 Chef", "color": 0xF1C40F, "hoist": True}], [])
    assert len(actions) == 1
    assert actions[0].operation == "create"
    assert actions[0].name == "👑 Chef"


def test_identical_role_needs_nothing():
    current = [{"id": "1", "name": "👑 Chef", "color": 0xF1C40F, "hoist": True}]
    assert diff.diff_roles([{"name": "👑 Chef", "color": 0xF1C40F, "hoist": True}], current) == []


def test_role_with_other_color_is_updated_by_id():
    current = [{"id": "1", "name": "👑 Chef", "color": 0x000000, "hoist": True}]
    actions = diff.diff_roles([{"name": "👑 Chef", "color": 0xF1C40F, "hoist": True}], current)
    assert len(actions) == 1
    assert actions[0].operation == "update"
    assert actions[0].details["id"] == "1"


# --- categories --------------------------------------------------------------


def test_missing_category_is_created():
    actions = diff.diff_categories(["📌 START"], [])
    assert len(actions) == 1
    assert actions[0].resource == "category"
    assert actions[0].operation == "create"


def test_existing_category_needs_nothing():
    assert diff.diff_categories(["📌 START"], [{"id": "10", "name": "📌 START", "type": 4}]) == []


def test_rename_when_the_old_name_exists():
    # A split/rename must PATCH the name on the same id (keeping child
    # channels and their forum posts), never create a new category and
    # orphan the old one. Match by id, never by name.
    current = [{"id": "cat-old", "name": "📊 OLD", "type": 4}]
    actions = diff.diff_categories(["💻 NEW"], current, renames={"📊 OLD": "💻 NEW"})
    assert len(actions) == 1
    assert actions[0].resource == "category"
    assert actions[0].operation == "rename"
    assert actions[0].name == "💻 NEW"
    assert actions[0].details == {"id": "cat-old", "old_name": "📊 OLD"}


def test_rename_without_the_old_name_falls_back_to_create():
    actions = diff.diff_categories(["💻 NEW"], [], renames={"📊 OLD": "💻 NEW"})
    assert len(actions) == 1
    assert actions[0].operation == "create"


def test_already_renamed_category_needs_nothing():
    current = [{"id": "cat-1", "name": "💻 NEW", "type": 4}]
    assert diff.diff_categories(["💻 NEW"], current, renames={"📊 OLD": "💻 NEW"}) == []


# --- channels ----------------------------------------------------------------


def test_channel_under_renamed_category_is_not_duplicated():
    # First --apply pass: the category rename PATCH has not run yet when the
    # channel diff is computed. Without translating through `renames`, this
    # would create a second "orders" forum next to the one holding the posts.
    categories = [{"id": "cat-old", "name": "📊 OLD", "type": 4}]
    channels = [{"id": "forum-old", "name": "orders", "type": FORUM, "parent_id": "cat-old", "topic": "t"}]
    desired = [{"name": "orders", "type": "forum", "category": "💻 NEW", "topic": "t"}]
    assert diff.diff_channels(desired, categories, channels, renames={"📊 OLD": "💻 NEW"}) == []


def test_channel_without_renames_is_created_in_the_new_category():
    categories = [{"id": "cat-old", "name": "📊 OLD", "type": 4}]
    channels = [{"id": "forum-old", "name": "orders", "type": FORUM, "parent_id": "cat-old", "topic": "t"}]
    desired = [{"name": "orders", "type": "forum", "category": "💻 NEW", "topic": "t"}]
    actions = diff.diff_channels(desired, categories, channels)
    assert len(actions) == 1
    assert actions[0].operation == "create"


def test_missing_channel_carries_category_name_not_parent_id():
    # On the first run the category may not exist yet (it is being created in
    # the same pass). The real parent_id is resolved at apply time, so the
    # action carries the category NAME, never an id resolved here.
    categories = [{"id": "10", "name": "📌 START", "type": 4}]
    desired = [{"name": "rules", "type": "text", "category": "📌 START", "topic": "x"}]
    actions = diff.diff_channels(desired, categories, [])
    assert len(actions) == 1
    assert actions[0].operation == "create"
    assert actions[0].details["category"] == "📌 START"
    assert "parent_id" not in actions[0].details
    assert actions[0].details["type"] == TEXT


def test_missing_channel_in_category_not_created_yet_is_created():
    actions = diff.diff_channels([{"name": "rules", "type": "text", "category": "📌 START", "topic": "x"}], [], [])
    assert len(actions) == 1
    assert actions[0].operation == "create"
    assert actions[0].details["category"] == "📌 START"


def test_same_name_different_type_is_a_new_channel():
    categories = [{"id": "10", "name": "📌 START", "type": 4}]
    channels = [{"id": "99", "name": "orders", "type": TEXT, "parent_id": "10"}]
    desired = [{"name": "orders", "type": "forum", "category": "📌 START", "topic": "x"}]
    actions = diff.diff_channels(desired, categories, channels)
    assert len(actions) == 1
    assert actions[0].operation == "create"


def test_identical_channel_needs_nothing():
    categories = [{"id": "10", "name": "📌 START", "type": 4}]
    channels = [{"id": "99", "name": "rules", "type": 0, "parent_id": "10", "topic": "x"}]
    desired = [{"name": "rules", "type": "text", "category": "📌 START", "topic": "x"}]
    assert diff.diff_channels(desired, categories, channels) == []


def test_channel_with_other_topic_is_updated():
    categories = [{"id": "10", "name": "📌 START", "type": 4}]
    channels = [{"id": "99", "name": "rules", "type": 0, "parent_id": "10", "topic": "old"}]
    desired = [{"name": "rules", "type": "text", "category": "📌 START", "topic": "new"}]
    actions = diff.diff_channels(desired, categories, channels)
    assert len(actions) == 1
    assert actions[0].operation == "update"
    assert actions[0].details["id"] == "99"
    assert actions[0].details["category"] == "📌 START"


def test_channel_in_another_category_is_created_never_moved():
    # Found running for real: a channel with the same name and type in ANOTHER
    # category must not become an "update" (that would move the wrong
    # channel). Identity is (name, type, category).
    categories = [{"id": "10", "name": "📌 START", "type": 4}, {"id": "20", "name": "🛎️ COUNTER", "type": 4}]
    channels = [{"id": "99", "name": "rules", "type": 0, "parent_id": "10", "topic": "x"}]
    desired = [{"name": "rules", "type": "text", "category": "🛎️ COUNTER", "topic": "x"}]
    actions = diff.diff_channels(desired, categories, channels)
    assert len(actions) == 1
    assert actions[0].operation == "create"
    assert actions[0].details["category"] == "🛎️ COUNTER"


def test_many_channels_with_same_name_and_type_do_not_collide():
    # Exact reproduction of the real bug: one "orders" forum per category.
    # Keyed only by (name, type), they collapse into one and the diff emits
    # spurious updates moving the SAME channel through every category.
    categories = [{"id": str(i), "name": f"🍝 PROJECT {i}", "type": 4} for i in range(1, 8)]
    channels = [
        {"id": f"c-{c['id']}", "name": "orders", "type": FORUM, "parent_id": c["id"], "topic": "t"} for c in categories
    ]
    desired = [{"name": "orders", "type": "forum", "category": c["name"], "topic": "t"} for c in categories]
    assert diff.diff_channels(desired, categories, channels) == []


# --- community ---------------------------------------------------------------

COMMUNITY = {
    "features_add": ["COMMUNITY"],
    "verification_level": 2,
    "explicit_content_filter": 2,
    "default_message_notifications": 1,
    "rules_channel": ("rules", "📌 START"),
    "public_updates_channel": ("moderation", "🔒 BACKSTAGE"),
    "description": "A server.",
}


def test_community_already_enabled_with_right_values_needs_nothing():
    guild = {
        "features": ["COMMUNITY"],
        "verification_level": 2,
        "explicit_content_filter": 2,
        "default_message_notifications": 1,
        "rules_channel_id": "1",
        "public_updates_channel_id": "2",
        "description": "A server.",
    }
    assert diff.diff_community(COMMUNITY, guild, rules_channel_id="1", updates_channel_id="2") == []


def test_community_disabled_is_updated():
    actions = diff.diff_community(COMMUNITY, {"features": [], "verification_level": 0}, "1", "2")
    assert len(actions) == 1
    assert actions[0].resource == "community"
    assert actions[0].operation == "update"
    assert "COMMUNITY" in actions[0].details["features"]


def test_community_keeps_existing_features():
    actions = diff.diff_community(COMMUNITY, {"features": ["NEWS"]}, "1", "2")
    assert set(actions[0].details["features"]) == {"NEWS", "COMMUNITY"}


# --- forum tags --------------------------------------------------------------

TAGS = [{"name": "✨ feature", "emoji": "✨"}, {"name": "🐞 bug", "emoji": "🐞"}]
MANAGED = [{"id": "cat-1", "name": "🍝 PROJECT", "type": 4}]


def _forum(**over):
    base = {
        "id": "1",
        "name": "orders",
        "type": FORUM,
        "parent_id": "cat-1",
        "available_tags": [],
        "default_forum_layout": 1,
    }
    base.update(over)
    return base


def test_forum_without_tags_is_updated():
    actions = diff.diff_forum_tags(TAGS, 1, [_forum()], MANAGED)
    assert len(actions) == 1
    assert actions[0].resource == "forum_tags"
    assert actions[0].operation == "update"
    assert actions[0].details["id"] == "1"
    assert {t["name"] for t in actions[0].details["available_tags"]} == {"✨ feature", "🐞 bug"}
    assert actions[0].details["default_forum_layout"] == 1


def test_forum_with_tags_needs_nothing():
    tags = [{"name": "✨ feature", "emoji": "✨"}]
    forum = _forum(available_tags=[{"name": "✨ feature", "id": "999"}])
    assert diff.diff_forum_tags(tags, 1, [forum], MANAGED) == []


def test_forum_with_wrong_layout_is_updated():
    tags = [{"name": "✨ feature", "emoji": "✨"}]
    forum = _forum(available_tags=[{"name": "✨ feature", "id": "999"}], default_forum_layout=0)
    actions = diff.diff_forum_tags(tags, 1, [forum], MANAGED)
    assert len(actions) == 1
    assert actions[0].details["default_forum_layout"] == 1


def test_forum_tags_ignore_non_forum_channels():
    assert (
        diff.diff_forum_tags(TAGS, 1, [{"id": "1", "name": "served", "type": 0, "parent_id": "cat-1"}], MANAGED) == []
    )


def test_forum_tags_leave_unmanaged_forums_alone():
    # Behavior change from the original private version: a public template
    # runs on servers that already have other forums. Only forums inside the
    # design's categories are touched.
    forum = _forum(parent_id="someone-elses-category")
    assert diff.diff_forum_tags(TAGS, 1, [forum], MANAGED) == []


def test_no_forum_tags_declared_means_hands_off():
    assert diff.diff_forum_tags([], 1, [_forum(available_tags=[{"name": "x"}])], MANAGED) == []


# --- webhooks ----------------------------------------------------------------


def test_missing_webhook_is_created():
    desired = [{"name": "Pass", "channel": "served", "category": "🛎️ COUNTER"}]
    channels = [{"id": "10", "name": "served", "type": 0}]
    actions = diff.diff_webhooks(desired, channels, {"10": []})
    assert len(actions) == 1
    assert actions[0].resource == "webhook"
    assert actions[0].operation == "create"
    assert actions[0].details["channel_id"] == "10"


def test_existing_webhook_needs_nothing():
    desired = [{"name": "Pass", "channel": "served", "category": "🛎️ COUNTER"}]
    channels = [{"id": "10", "name": "served", "type": 0}]
    assert diff.diff_webhooks(desired, channels, {"10": [{"name": "Pass", "id": "555"}]}) == []


def test_webhook_waits_for_its_channel():
    desired = [{"name": "Pass", "channel": "served", "category": "🛎️ COUNTER"}]
    assert diff.diff_webhooks(desired, [], {}) == []


# --- icon --------------------------------------------------------------------


def test_missing_icon_is_applied_when_the_design_has_one():
    actions = diff.diff_icon({"icon": None}, wanted=True)
    assert len(actions) == 1
    assert actions[0].resource == "icon"
    assert actions[0].operation == "apply"


def test_existing_icon_is_never_replaced():
    assert diff.diff_icon({"icon": "abc123hash"}, wanted=True) == []


def test_no_icon_in_design_means_hands_off():
    assert diff.diff_icon({"icon": None}, wanted=False) == []


# --- bots and role assignment -------------------------------------------------


def test_bot_id_is_found_through_its_managed_role():
    roles = [
        {"name": "@everyone", "managed": False},
        {"name": "WaiterBot", "managed": True, "tags": {"bot_id": "100000000000000011"}},
        {"name": "StationBot", "managed": True, "tags": {"bot_id": "100000000000000012"}},
    ]
    assert diff.find_bot_id(roles, "StationBot") == "100000000000000012"


def test_bot_not_in_server_gives_none():
    assert diff.find_bot_id([{"name": "WaiterBot", "managed": True, "tags": {"bot_id": "1"}}], "StationBot") is None


def test_unmanaged_role_with_the_bot_name_is_not_a_bot():
    assert diff.find_bot_id([{"name": "StationBot", "managed": False}], "StationBot") is None


def test_assignment_without_member_needs_nothing():
    assert diff.diff_role_assignment("x", user_id=None, role_id="role-1", member_roles=None) == []


def test_assignment_already_done_needs_nothing():
    assert diff.diff_role_assignment("x", user_id="u-1", role_id="role-1", member_roles=["role-1", "other"]) == []


def test_assignment_missing_is_assigned():
    actions = diff.diff_role_assignment(
        "🖥️ Second Station → bot", user_id="u-1", role_id="role-1", member_roles=["other"]
    )
    assert len(actions) == 1
    assert actions[0].resource == "role_assignment"
    assert actions[0].operation == "assign"
    assert actions[0].name == "🖥️ Second Station → bot"
    assert actions[0].details == {"user_id": "u-1", "role_id": "role-1"}


# --- category overwrites ------------------------------------------------------


def test_category_without_overwrites_is_updated():
    roles = [
        {"id": "everyone-id", "name": "@everyone"},
        {"id": "chef-id", "name": "👑 Chef"},
        {"id": "waiter-id", "name": "🤵 Waiter"},
    ]
    categories = [{"id": "cat-1", "name": "📌 START", "type": 4, "permission_overwrites": []}]
    actions = diff.diff_category_overwrites({"📌 START": ["👑 Chef", "🤵 Waiter"]}, categories, roles)
    assert len(actions) == 1
    assert actions[0].resource == "category_overwrite"
    overwrites = {ow["id"]: ow for ow in actions[0].details["permission_overwrites"]}
    assert int(overwrites["everyone-id"]["deny"]) & VIEW_CHANNEL
    assert int(overwrites["chef-id"]["allow"]) & VIEW_CHANNEL
    assert int(overwrites["waiter-id"]["allow"]) & VIEW_CHANNEL


def test_category_already_right_needs_nothing():
    roles = [{"id": "everyone-id", "name": "@everyone"}, {"id": "chef-id", "name": "👑 Chef"}]
    categories = [
        {
            "id": "cat-1",
            "name": "🔒 BACKSTAGE",
            "type": 4,
            "permission_overwrites": [
                {"id": "everyone-id", "type": 0, "allow": "0", "deny": str(VIEW_CHANNEL)},
                {"id": "chef-id", "type": 0, "allow": str(VIEW_CHANNEL), "deny": "0"},
            ],
        }
    ]
    assert diff.diff_category_overwrites({"🔒 BACKSTAGE": ["👑 Chef"]}, categories, roles) == []


ROLES_4 = [
    {"id": "everyone-id", "name": "@everyone"},
    {"id": "chef-id", "name": "👑 Chef"},
    {"id": "waiter-id", "name": "🤵 Waiter"},
    {"id": "station-id", "name": "🖥️ Second Station"},
]
STALE_WAITER_ALLOW = [
    {"id": "everyone-id", "type": 0, "allow": "0", "deny": str(VIEW_CHANNEL)},
    {"id": "chef-id", "type": 0, "allow": str(VIEW_CHANNEL), "deny": "0"},
    {"id": "waiter-id", "type": 0, "allow": str(VIEW_CHANNEL), "deny": "0"},
]
VISIBILITY_WITHOUT_WAITER_IN_STUDIO = {
    "🎬 STUDIO": ["👑 Chef", "🖥️ Second Station"],
    "🍝 PROJECT": ["👑 Chef", "🤵 Waiter"],
}


def test_category_role_removed_from_visibility_gets_explicit_deny():
    # Found running for real: removing a role from a category's list was not
    # enough. Its old allow overwrite stayed untouched (it was not in the
    # desired bits), and a ROLE overwrite beats @everyone in Discord, so the
    # role kept seeing the category. Every role that appears anywhere in the
    # visibility map gets an explicit deny where it is not listed.
    categories = [{"id": "cat-studio", "name": "🎬 STUDIO", "type": 4, "permission_overwrites": STALE_WAITER_ALLOW}]
    actions = diff.diff_category_overwrites(VISIBILITY_WITHOUT_WAITER_IN_STUDIO, categories, ROLES_4)
    assert len(actions) == 1
    overwrites = {ow["id"]: ow for ow in actions[0].details["permission_overwrites"]}
    assert int(overwrites["waiter-id"]["deny"]) & VIEW_CHANNEL
    assert not int(overwrites["waiter-id"]["allow"]) & VIEW_CHANNEL
    assert int(overwrites["station-id"]["allow"]) & VIEW_CHANNEL


def test_channel_role_removed_from_visibility_gets_explicit_deny():
    categories = [{"id": "cat-studio", "name": "🎬 STUDIO", "type": 4}]
    channels = [
        {
            "id": "c-1",
            "name": "orders",
            "type": FORUM,
            "parent_id": "cat-studio",
            "permission_overwrites": STALE_WAITER_ALLOW,
        }
    ]
    actions = diff.diff_channel_overwrites(VISIBILITY_WITHOUT_WAITER_IN_STUDIO, set(), channels, categories, ROLES_4)
    assert len(actions) == 1
    overwrites = {ow["id"]: ow for ow in actions[0].details["permission_overwrites"]}
    assert int(overwrites["waiter-id"]["deny"]) & VIEW_CHANNEL
    assert not int(overwrites["waiter-id"]["allow"]) & VIEW_CHANNEL


def test_category_waits_for_its_roles_to_exist():
    roles = [{"id": "everyone-id", "name": "@everyone"}]
    categories = [{"id": "cat-1", "name": "🔒 BACKSTAGE", "type": 4, "permission_overwrites": []}]
    assert diff.diff_category_overwrites({"🔒 BACKSTAGE": ["👑 Chef"]}, categories, roles) == []


def test_category_read_only_role_is_denied_send_on_the_template_too():
    # So that a channel created later in the UI with "sync with category"
    # already starts read-only for the guest, instead of waiting for the next
    # apply to fix that channel.
    roles = [
        {"id": "everyone-id", "name": "@everyone"},
        {"id": "chef-id", "name": "👑 Chef"},
        {"id": "guest-id", "name": "🤝 Guest"},
    ]
    categories = [{"id": "cat-start", "name": "📌 START", "type": 4, "permission_overwrites": []}]
    actions = diff.diff_category_overwrites(
        {"📌 START": ["👑 Chef", "🤝 Guest"]}, categories, roles, read_only_roles={"📌 START": ["🤝 Guest"]}
    )
    assert len(actions) == 1
    overwrites = {ow["id"]: ow for ow in actions[0].details["permission_overwrites"]}
    assert int(overwrites["guest-id"]["allow"]) & VIEW_CHANNEL
    assert int(overwrites["guest-id"]["deny"]) & SEND_MESSAGES
    assert int(overwrites["chef-id"]["allow"]) & VIEW_CHANNEL
    assert not int(overwrites["chef-id"]["deny"]) & SEND_MESSAGES


def test_category_keeps_other_entities_and_their_type():
    # A MEMBER overwrite (type 1) must stay a member overwrite: rewriting it
    # as type 0 would turn it into a role overwrite, which Discord rejects or
    # corrupts.
    roles = [{"id": "everyone-id", "name": "@everyone"}, {"id": "chef-id", "name": "👑 Chef"}]
    categories = [
        {
            "id": "cat-1",
            "name": "🔒 BACKSTAGE",
            "type": 4,
            "permission_overwrites": [{"id": "member-x", "type": 1, "allow": "999", "deny": "0"}],
        }
    ]
    actions = diff.diff_category_overwrites({"🔒 BACKSTAGE": ["👑 Chef"]}, categories, roles)
    assert len(actions) == 1
    entry = next(ow for ow in actions[0].details["permission_overwrites"] if ow["id"] == "member-x")
    assert entry["type"] == 1
    assert entry["allow"] == "999"


# --- channel overwrites -------------------------------------------------------


def test_child_channel_without_its_own_overwrite_is_updated():
    # The real bug: Discord does NOT propagate a category overwrite to
    # existing channels. "Synced" is a one-time copy made by the UI at
    # creation, not a live link. Fixing only the category left @everyone
    # seeing everything, so every child channel gets its own overwrite.
    roles = [
        {"id": "everyone-id", "name": "@everyone"},
        {"id": "chef-id", "name": "👑 Chef"},
        {"id": "station-id", "name": "🖥️ Second Station"},
    ]
    categories = [{"id": "cat-studio", "name": "🎬 STUDIO", "type": 4}]
    channels = [{"id": "c-1", "name": "orders", "type": FORUM, "parent_id": "cat-studio", "permission_overwrites": []}]
    actions = diff.diff_channel_overwrites(
        {"🎬 STUDIO": ["👑 Chef", "🖥️ Second Station"]}, set(), channels, categories, roles
    )
    assert len(actions) == 1
    assert actions[0].resource == "channel_overwrite"
    overwrites = {ow["id"]: ow for ow in actions[0].details["permission_overwrites"]}
    assert int(overwrites["everyone-id"]["deny"]) & VIEW_CHANNEL
    assert int(overwrites["station-id"]["allow"]) & VIEW_CHANNEL
    assert "waiter-id" not in overwrites


def test_child_channel_already_right_needs_nothing():
    roles = [{"id": "everyone-id", "name": "@everyone"}, {"id": "chef-id", "name": "👑 Chef"}]
    categories = [{"id": "cat-1", "name": "🔒 BACKSTAGE", "type": 4}]
    channels = [
        {
            "id": "c-1",
            "name": "moderation",
            "type": 0,
            "parent_id": "cat-1",
            "permission_overwrites": [
                {"id": "everyone-id", "type": 0, "allow": "0", "deny": str(VIEW_CHANNEL)},
                {"id": "chef-id", "type": 0, "allow": str(VIEW_CHANNEL), "deny": "0"},
            ],
        }
    ]
    assert diff.diff_channel_overwrites({"🔒 BACKSTAGE": ["👑 Chef"]}, set(), channels, categories, roles) == []


def test_read_only_channel_denies_send_to_everyone():
    roles = [{"id": "everyone-id", "name": "@everyone"}, {"id": "chef-id", "name": "👑 Chef"}]
    categories = [{"id": "cat-1", "name": "📌 START", "type": 4}]
    channels = [{"id": "c-1", "name": "rules", "type": 0, "parent_id": "cat-1", "permission_overwrites": []}]
    actions = diff.diff_channel_overwrites(
        {"📌 START": ["👑 Chef"]}, {("rules", "📌 START")}, channels, categories, roles
    )
    assert len(actions) == 1
    everyone = next(ow for ow in actions[0].details["permission_overwrites"] if ow["id"] == "everyone-id")
    assert int(everyone["deny"]) & VIEW_CHANNEL
    assert int(everyone["deny"]) & SEND_MESSAGES


def test_read_only_is_per_channel_and_category():
    # Behavior change: read-only used to be keyed by channel name only, so a
    # "rules" channel in any category became read-only.
    roles = [{"id": "everyone-id", "name": "@everyone"}, {"id": "chef-id", "name": "👑 Chef"}]
    categories = [{"id": "cat-lab", "name": "🧪 LAB", "type": 4}]
    channels = [{"id": "c-2", "name": "rules", "type": 0, "parent_id": "cat-lab", "permission_overwrites": []}]
    actions = diff.diff_channel_overwrites(
        {"🧪 LAB": ["👑 Chef"]}, {("rules", "📌 START")}, channels, categories, roles
    )
    everyone = next(ow for ow in actions[0].details["permission_overwrites"] if ow["id"] == "everyone-id")
    assert not int(everyone["deny"]) & SEND_MESSAGES


def test_channel_rewrite_keeps_bits_outside_the_controlled_mask():
    other_bit = 1 << 20
    roles = [{"id": "everyone-id", "name": "@everyone"}, {"id": "chef-id", "name": "👑 Chef"}]
    categories = [{"id": "cat-1", "name": "🔒 BACKSTAGE", "type": 4}]
    channels = [
        {
            "id": "c-1",
            "name": "moderation",
            "type": 0,
            "parent_id": "cat-1",
            "permission_overwrites": [{"id": "chef-id", "type": 0, "allow": str(other_bit), "deny": "0"}],
        }
    ]
    actions = diff.diff_channel_overwrites({"🔒 BACKSTAGE": ["👑 Chef"]}, set(), channels, categories, roles)
    assert len(actions) == 1
    chef = next(ow for ow in actions[0].details["permission_overwrites"] if ow["id"] == "chef-id")
    assert int(chef["allow"]) & other_bit
    assert int(chef["allow"]) & VIEW_CHANNEL


def test_channel_outside_managed_categories_is_left_alone():
    roles = [{"id": "everyone-id", "name": "@everyone"}]
    channels = [{"id": "c-1", "name": "table", "type": 0, "parent_id": None, "permission_overwrites": []}]
    assert diff.diff_channel_overwrites({}, set(), channels, [], roles) == []


def test_read_only_role_is_denied_send_but_keeps_view():
    roles = [
        {"id": "everyone-id", "name": "@everyone"},
        {"id": "chef-id", "name": "👑 Chef"},
        {"id": "guest-id", "name": "🤝 Guest"},
    ]
    categories = [{"id": "cat-start", "name": "📌 START", "type": 4}]
    channels = [
        {"id": "c-1", "name": "announcements", "type": 0, "parent_id": "cat-start", "permission_overwrites": []}
    ]
    actions = diff.diff_channel_overwrites(
        {"📌 START": ["👑 Chef", "🤝 Guest"]},
        set(),
        channels,
        categories,
        roles,
        read_only_roles={"📌 START": ["🤝 Guest"]},
    )
    assert len(actions) == 1
    overwrites = {ow["id"]: ow for ow in actions[0].details["permission_overwrites"]}
    assert int(overwrites["guest-id"]["allow"]) & VIEW_CHANNEL
    assert int(overwrites["guest-id"]["deny"]) & SEND_MESSAGES
    assert int(overwrites["chef-id"]["allow"]) & VIEW_CHANNEL
    assert not int(overwrites["chef-id"]["deny"]) & SEND_MESSAGES


def test_read_only_role_already_applied_needs_nothing():
    roles = [{"id": "everyone-id", "name": "@everyone"}, {"id": "guest-id", "name": "🤝 Guest"}]
    categories = [{"id": "cat-start", "name": "📌 START", "type": 4}]
    channels = [
        {
            "id": "c-1",
            "name": "announcements",
            "type": 0,
            "parent_id": "cat-start",
            "permission_overwrites": [
                {"id": "everyone-id", "type": 0, "allow": "0", "deny": str(VIEW_CHANNEL)},
                {"id": "guest-id", "type": 0, "allow": str(VIEW_CHANNEL), "deny": str(SEND_MESSAGES)},
            ],
        }
    ]
    actions = diff.diff_channel_overwrites(
        {"📌 START": ["🤝 Guest"]}, set(), channels, categories, roles, read_only_roles={"📌 START": ["🤝 Guest"]}
    )
    assert actions == []
