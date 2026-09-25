from unittest.mock import MagicMock, patch

import pytest

from discord_hq.server import client


def _response(status, body=None, content=None, headers=None, text=""):
    response = MagicMock(status_code=status, text=text)
    response.content = content if content is not None else (b"{}" if body is not None else b"")
    if isinstance(body, Exception):
        response.json.side_effect = body
    else:
        response.json.return_value = body
    response.headers = headers or {}
    return response


def test_waits_and_retries_on_429():
    waits = []
    api = client.DiscordClient("tok", sleep_fn=waits.append)
    with patch.object(
        client.requests, "request", side_effect=[_response(429, {"retry_after": 0.2}), _response(200, {"id": "1"})]
    ):
        assert api.get("/guilds/1") == {"id": "1"}
    assert waits == [0.2]


def test_other_4xx_raises_discord_api_error():
    api = client.DiscordClient("tok")
    with patch.object(client.requests, "request", return_value=_response(403, {"message": "Missing Permissions"})):
        with pytest.raises(client.DiscordAPIError) as exc:
            api.get("/guilds/1")
    assert exc.value.status == 403


def test_token_never_appears_in_errors():
    api = client.DiscordClient("secret-token")
    with patch.object(client.requests, "request", return_value=_response(401, {"message": "401: Unauthorized"})):
        with pytest.raises(client.DiscordAPIError) as exc:
            api.get("/guilds/1")
    assert "secret-token" not in str(exc.value)
    assert "secret-token" not in repr(exc.value.body)


def test_network_error_does_not_leak_the_token_or_url():
    # requests exceptions include the full URL; webhook-style URLs carry a
    # token, so the client re-raises without chaining the original message.
    api = client.DiscordClient("secret-token")
    boom = client.requests.ConnectionError("https://discord.com/api/v10/guilds/1 secret-token")
    with patch.object(client.requests, "request", side_effect=boom):
        with pytest.raises(client.DiscordAPIError) as exc:
            api.get("/guilds/1")
    assert "secret-token" not in str(exc.value)
    assert exc.value.__cause__ is None


def test_delete_returns_none_on_204():
    api = client.DiscordClient("tok")
    with patch.object(client.requests, "request", return_value=_response(204)):
        assert api.delete("/channels/1") is None


def test_429_with_non_json_body_uses_retry_after_header():
    waits = []
    api = client.DiscordClient("tok", sleep_fn=waits.append)
    rate_limited = _response(
        429, ValueError("not json"), content=b"<html>rate limited</html>", headers={"Retry-After": "0.1"}
    )
    with patch.object(client.requests, "request", side_effect=[rate_limited, _response(200, {"id": "1"})]):
        assert api.get("/guilds/1") == {"id": "1"}
    assert waits == [0.1]


def test_error_with_non_json_body_does_not_break():
    api = client.DiscordClient("tok")
    bad_gateway = _response(
        502, ValueError("not json"), content=b"<html>Bad Gateway</html>", text="<html>Bad Gateway</html>"
    )
    with patch.object(client.requests, "request", return_value=bad_gateway):
        with pytest.raises(client.DiscordAPIError) as exc:
            api.get("/guilds/1")
    assert exc.value.status == 502
    assert exc.value.body == "<html>Bad Gateway</html>"


def test_gives_up_after_too_many_429():
    api = client.DiscordClient("tok", sleep_fn=lambda s: None)
    with patch.object(client.requests, "request", return_value=_response(429, {"retry_after": 0.01})):
        with pytest.raises(client.DiscordAPIError) as exc:
            api.get("/guilds/1")
    assert exc.value.status == 429


def test_sends_bot_authorization_and_user_agent():
    api = client.DiscordClient("tok")
    with patch.object(client.requests, "request", return_value=_response(200, {})) as request:
        api.get("/users/@me")
    headers = request.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bot tok"
    assert headers["User-Agent"].startswith("DiscordBot (")
    assert request.call_args.kwargs["timeout"] <= 15
