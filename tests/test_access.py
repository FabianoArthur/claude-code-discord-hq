from discord_hq.server import access, design


def _design():
    return design.parse_design(
        {
            "categories": [
                {
                    "name": "🛎️ COUNTER",
                    "channels": [
                        {"name": "table", "type": "text", "answered_by": {"waiter": "always"}},
                        {"name": "quiet", "type": "text"},
                    ],
                },
                {
                    "name": "🧪 LAB",
                    "channels": [
                        {"name": "orders", "type": "forum", "answered_by": {"waiter": "mention", "station": "mention"}}
                    ],
                },
            ]
        }
    )


STATE = {"channels": {"table (🛎️ COUNTER)": "200000000000000001", "orders (🧪 LAB)": "200000000000000002"}}


def test_always_channels_get_no_mention_flag():
    commands, missing = access.access_commands(_design(), STATE, "waiter")
    assert "/discord:access group add 200000000000000001 --no-mention" in commands
    assert missing == []


def test_mention_channels_require_a_mention():
    commands, _ = access.access_commands(_design(), STATE, "station")
    assert commands == ["/discord:access group add 200000000000000002"]


def test_channels_not_answered_by_the_bot_are_left_out():
    commands, _ = access.access_commands(_design(), STATE, "waiter")
    assert len(commands) == 2
    assert all("quiet" not in c for c in commands)


def test_unknown_ids_are_reported_as_missing():
    commands, missing = access.access_commands(_design(), {}, "waiter")
    assert commands == []
    assert missing == ["table (🛎️ COUNTER)", "orders (🧪 LAB)"]


def test_known_bots_are_listed():
    assert access.bots_in(_design()) == ["station", "waiter"]
