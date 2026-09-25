from pathlib import Path

import pytest

from discord_hq.server import design

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"

MINIMAL = """
[[roles]]
name = "👑 Chef"
color = "#F1C40F"
hoist = true
assign_to = "owner"

[[categories]]
name = "📌 START"
visible_to = ["👑 Chef"]

  [[categories.channels]]
  name = "rules"
  type = "text"
  topic = "Read me first."
  read_only = true
"""


def _load(tmp_path, text):
    path = tmp_path / "design.toml"
    path.write_text(text)
    return design.load_design(path)


class TestExamples:
    @pytest.mark.parametrize("name", ["minimal.toml", "restaurant.toml"])
    def test_shipped_examples_load_and_validate(self, name):
        loaded = design.load_design(EXAMPLES / name)
        assert loaded.roles
        assert loaded.categories

    def test_restaurant_example_uses_the_english_vocabulary(self):
        loaded = design.load_design(EXAMPLES / "restaurant.toml")
        role_names = " ".join(r["name"] for r in loaded.roles)
        for word in ("Chef", "Waiter", "Kitchen", "Guest"):
            assert word in role_names

    def test_restaurant_example_keeps_two_bots_off_the_same_channel(self):
        loaded = design.load_design(EXAMPLES / "restaurant.toml")
        for bots in loaded.answered_by.values():
            if len(bots) > 1:
                assert set(bots.values()) == {"mention"}


class TestLoad:
    def test_minimal_design_converts_to_internal_state(self, tmp_path):
        loaded = _load(tmp_path, MINIMAL)
        assert loaded.roles == [{"name": "👑 Chef", "color": 0xF1C40F, "hoist": True}]
        assert loaded.role_assignments == [{"role": "👑 Chef", "to": "owner"}]
        assert loaded.categories == ["📌 START"]
        assert loaded.channels == [{"name": "rules", "type": "text", "category": "📌 START", "topic": "Read me first."}]
        assert loaded.category_visibility == {"📌 START": ["👑 Chef"]}
        assert loaded.read_only_channels == {("rules", "📌 START")}
        assert loaded.read_only_roles == {}
        assert loaded.community is None
        assert loaded.delete_channel_ids == []

    def test_color_accepts_integer(self, tmp_path):
        loaded = _load(tmp_path, MINIMAL.replace('"#F1C40F"', "15844367"))
        assert loaded.roles[0]["color"] == 15844367

    def test_category_without_visible_to_is_not_permission_managed(self, tmp_path):
        loaded = _load(tmp_path, '[[categories]]\nname = "🎧 ROOMS"\n')
        assert loaded.category_visibility == {}

    def test_rename_from_becomes_a_category_rename(self, tmp_path):
        loaded = _load(tmp_path, '[[categories]]\nname = "💻 NEW"\nrename_from = "📊 OLD"\n')
        assert loaded.category_renames == {"📊 OLD": "💻 NEW"}

    def test_webhooks_and_answered_by_are_keyed_by_channel_and_category(self, tmp_path):
        loaded = _load(
            tmp_path,
            """
[[categories]]
name = "🛎️ COUNTER"
  [[categories.channels]]
  name = "served"
  type = "text"
  webhook = "Pass"
  answered_by = { waiter = "always" }
""",
        )
        assert loaded.webhooks == [{"name": "Pass", "channel": "served", "category": "🛎️ COUNTER"}]
        assert loaded.answered_by == {("served", "🛎️ COUNTER"): {"waiter": "always"}}

    def test_forum_defaults(self, tmp_path):
        loaded = _load(tmp_path, MINIMAL)
        assert loaded.forum_tags == []
        assert loaded.forum_layout == 1

    def test_forum_tags_and_layout(self, tmp_path):
        loaded = _load(
            tmp_path,
            MINIMAL + '\n[forum]\nlayout = "gallery"\ntags = [{ name = "🐞 bug", emoji = "🐞" }]\n',
        )
        assert loaded.forum_tags == [{"name": "🐞 bug", "emoji": "🐞"}]
        assert loaded.forum_layout == 2

    def test_community_resolves_channel_references(self, tmp_path):
        text = (
            MINIMAL
            + """
  [[categories.channels]]
  name = "moderation"
  type = "text"

[community]
description = "A server."
rules_channel = "rules"
public_updates_channel = "moderation"
"""
        )
        loaded = _load(tmp_path, text)
        assert loaded.community["rules_channel"] == ("rules", "📌 START")
        assert loaded.community["public_updates_channel"] == ("moderation", "📌 START")
        assert loaded.community["verification_level"] == 2
        assert loaded.community["features_add"] == ["COMMUNITY"]

    def test_pinned_messages(self, tmp_path):
        loaded = _load(tmp_path, MINIMAL + '\n[[pinned_messages]]\nchannel = "rules"\ncontent = "Be kind."\n')
        assert loaded.pinned_messages == [{"channel": "rules", "category": "📌 START", "content": "Be kind."}]

    def test_icon_is_optional(self, tmp_path):
        assert _load(tmp_path, MINIMAL).icon is None
        loaded = _load(tmp_path, '[server]\nicon_letter = "K"\n' + MINIMAL)
        assert loaded.icon == {"letter": "K", "color": (241, 196, 15), "background": (18, 18, 20)}

    def test_missing_file_is_a_clear_error(self, tmp_path):
        with pytest.raises(design.DesignError):
            design.load_design(tmp_path / "missing.toml")

    def test_invalid_toml_is_a_clear_error(self, tmp_path):
        with pytest.raises(design.DesignError):
            _load(tmp_path, "[[roles]\nname=")


class TestValidation:
    def _error(self, tmp_path, text, fragment):
        with pytest.raises(design.DesignError) as exc:
            _load(tmp_path, text)
        assert fragment in str(exc.value)

    def test_unknown_role_in_visible_to(self, tmp_path):
        self._error(tmp_path, MINIMAL.replace('visible_to = ["👑 Chef"]', 'visible_to = ["Ghost"]'), "Ghost")

    def test_read_only_role_must_also_be_visible(self, tmp_path):
        # Listing a role as read-only where it cannot see anything is a dead
        # entry: the diff denies VIEW_CHANNEL to it anyway, so the config
        # mistake would pass silently.
        text = MINIMAL.replace('visible_to = ["👑 Chef"]', 'visible_to = []\nread_only_for = ["👑 Chef"]')
        self._error(tmp_path, text, "read_only_for")

    def test_duplicate_role(self, tmp_path):
        self._error(tmp_path, MINIMAL + '\n[[roles]]\nname = "👑 Chef"\n', "duplicate role")

    def test_everyone_is_not_a_declarable_role(self, tmp_path):
        self._error(tmp_path, '[[roles]]\nname = "@everyone"\n', "@everyone")

    def test_bad_color(self, tmp_path):
        self._error(tmp_path, MINIMAL.replace('"#F1C40F"', '"yellow"'), "color")

    def test_duplicate_category(self, tmp_path):
        self._error(tmp_path, MINIMAL + '\n[[categories]]\nname = "📌 START"\n', "duplicate category")

    def test_duplicate_channel_in_same_category(self, tmp_path):
        text = MINIMAL + '\n  [[categories.channels]]\n  name = "rules"\n  type = "text"\n'
        self._error(tmp_path, text, "duplicate channel")

    def test_same_channel_name_in_different_categories_is_fine(self, tmp_path):
        text = (
            MINIMAL
            + '\n[[categories]]\nname = "🧪 LAB"\n  [[categories.channels]]\n  name = "rules"\n  type = "text"\n'
        )
        loaded = _load(tmp_path, text)
        assert len(loaded.channels) == 2

    def test_unknown_channel_type(self, tmp_path):
        self._error(tmp_path, MINIMAL.replace('type = "text"', 'type = "stage"'), "type")

    def test_uppercase_text_channel_name_is_rejected(self, tmp_path):
        # Discord lowercases text channel names: "Rules" would come back as
        # "rules" and the diff would try to create it again on every run.
        self._error(tmp_path, MINIMAL.replace('name = "rules"', 'name = "Rules"'), "lowercase")

    def test_text_channel_name_with_space_is_rejected(self, tmp_path):
        self._error(tmp_path, MINIMAL.replace('name = "rules"', 'name = "house rules"'), "lowercase")

    def test_voice_channel_may_have_capitals_and_spaces(self, tmp_path):
        text = '[[categories]]\nname = "🎧 ROOMS"\n  [[categories.channels]]\n  name = "Deep Focus"\n  type = "voice"\n'
        assert _load(tmp_path, text).channels[0]["name"] == "Deep Focus"

    def test_webhook_only_on_text_channels(self, tmp_path):
        text = (
            '[[categories]]\nname = "🎧 ROOMS"\n'
            '  [[categories.channels]]\n  name = "Focus"\n  type = "voice"\n  webhook = "X"\n'
        )
        self._error(tmp_path, text, "webhook")

    def test_duplicate_webhook_name(self, tmp_path):
        text = MINIMAL.replace("read_only = true", 'read_only = true\n  webhook = "Pass"') + (
            '\n  [[categories.channels]]\n  name = "served"\n  type = "text"\n  webhook = "Pass"\n'
        )
        self._error(tmp_path, text, "duplicate webhook")

    def test_webhook_channel_name_must_be_unique_among_text_channels(self, tmp_path):
        # The webhook lookup reads webhooks per channel NAME; two text
        # channels with the same name would make that ambiguous.
        text = MINIMAL.replace("read_only = true", 'read_only = true\n  webhook = "Pass"') + (
            '\n[[categories]]\nname = "🧪 LAB"\n  [[categories.channels]]\n  name = "rules"\n  type = "text"\n'
        )
        self._error(tmp_path, text, "ambiguous")

    def test_two_bots_answering_everything_in_one_channel_is_rejected(self, tmp_path):
        text = MINIMAL.replace("read_only = true", 'answered_by = { waiter = "always", studio = "always" }')
        self._error(tmp_path, text, "two bots")

    def test_two_bots_on_mention_is_fine(self, tmp_path):
        text = MINIMAL.replace("read_only = true", 'answered_by = { waiter = "mention", studio = "mention" }')
        assert _load(tmp_path, text).answered_by[("rules", "📌 START")] == {"waiter": "mention", "studio": "mention"}

    def test_unknown_answer_mode(self, tmp_path):
        self._error(
            tmp_path, MINIMAL.replace("read_only = true", 'answered_by = { waiter = "sometimes" }'), "answered_by"
        )

    def test_bad_assign_to(self, tmp_path):
        self._error(tmp_path, MINIMAL.replace('assign_to = "owner"', 'assign_to = "someone"'), "assign_to")

    def test_assign_to_bot(self, tmp_path):
        loaded = _load(tmp_path, MINIMAL.replace('assign_to = "owner"', 'assign_to = "bot:WaiterBot"'))
        assert loaded.role_assignments == [{"role": "👑 Chef", "to": "bot:WaiterBot"}]

    def test_community_channel_must_exist(self, tmp_path):
        text = MINIMAL + '\n[community]\nrules_channel = "rules"\npublic_updates_channel = "nope"\n'
        self._error(tmp_path, text, "nope")

    def test_pinned_message_channel_must_exist(self, tmp_path):
        self._error(tmp_path, MINIMAL + '\n[[pinned_messages]]\nchannel = "nope"\ncontent = "x"\n', "nope")

    def test_delete_ids_must_be_snowflakes(self, tmp_path):
        self._error(tmp_path, MINIMAL + '\n[cleanup]\ndelete_channel_ids = ["general"]\n', "delete_channel_ids")

    def test_unknown_top_level_key_is_rejected(self, tmp_path):
        # A typo like [[role]] must fail loudly instead of silently doing nothing.
        self._error(tmp_path, MINIMAL + '\n[[role]]\nname = "x"\n', "unknown")

    def test_unknown_channel_key_is_rejected(self, tmp_path):
        self._error(tmp_path, MINIMAL.replace("read_only = true", "readonly = true"), "unknown")


def test_empty_topic_means_no_topic(tmp_path):
    # Discord returns null for an empty topic; "" would never converge.
    loaded = _load(tmp_path, MINIMAL.replace('topic = "Read me first."', 'topic = ""'))
    assert loaded.channels[0]["topic"] is None
