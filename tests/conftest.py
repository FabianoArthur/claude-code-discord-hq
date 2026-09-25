import pytest

from discord_hq import config

MENTION_ID = "100000000000000042"


@pytest.fixture
def settings(tmp_path):
    return config.load_settings(
        {
            "HOME": str(tmp_path / "home"),
            "DISCORD_HQ_CONFIG_DIR": str(tmp_path / "cfg"),
            "DISCORD_HQ_MENTION_USER_ID": MENTION_ID,
        }
    )
