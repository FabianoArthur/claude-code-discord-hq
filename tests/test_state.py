from discord_hq.server import state


def test_missing_file_loads_empty(tmp_path):
    assert state.load_state(tmp_path / "state.json") == {}


def test_round_trip(tmp_path):
    path = tmp_path / "state.json"
    data = {"roles": {"👑 Chef": "111"}, "channels": {"rules (📌 START)": "222"}}
    state.save_state(path, data)
    assert state.load_state(path) == data


def test_saved_file_is_sorted_and_readable(tmp_path):
    path = tmp_path / "state.json"
    state.save_state(path, {"b": 1, "a": 2})
    text = path.read_text()
    assert text.index('"a"') < text.index('"b"')
    assert "\n" in text


def test_creates_parent_directories(tmp_path):
    path = tmp_path / "nested" / "more" / "state.json"
    state.save_state(path, {"x": 1})
    assert path.exists()


def test_never_persists_secrets(tmp_path):
    path = tmp_path / "state.json"
    state.save_state(
        path,
        {
            "webhooks": {
                "Pass": {"id": "1", "token": "tok-secret", "url": "https://discord.com/api/webhooks/1/tok-secret"}
            }
        },
    )
    text = path.read_text()
    assert "tok-secret" not in text
    assert state.load_state(path) == {"webhooks": {"Pass": {"id": "1"}}}
