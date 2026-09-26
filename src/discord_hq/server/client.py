"""Thin client for the Discord API v10. The only module that speaks HTTP to
the bot API, so rate limits, headers and error formats live in one place.

Errors never carry the token or the request URL: `requests` puts the URL in
its exception messages, so network errors are re-raised without chaining."""

from __future__ import annotations

import time
from typing import Any

import requests

from discord_hq import __version__

API_BASE = "https://discord.com/api/v10"
USER_AGENT = f"DiscordBot (https://github.com/FabianoArthur/claude-code-discord-hq, {__version__})"
TIMEOUT_SECONDS = 15
MAX_RATE_LIMIT_RETRIES = 10


class DiscordAPIError(RuntimeError):
    def __init__(self, status: int, body: Any):
        super().__init__(f"Discord API {status}")
        self.status = status
        self.body = body


class DiscordClient:
    def __init__(self, token: str, sleep_fn=time.sleep):
        self._token = token
        self._sleep = sleep_fn

    def __repr__(self) -> str:
        return "DiscordClient(<token hidden>)"

    def _headers(self) -> dict:
        return {"Authorization": f"Bot {self._token}", "User-Agent": USER_AGENT, "Content-Type": "application/json"}

    def _send(self, method: str, path: str, **kwargs):
        try:
            return requests.request(
                method, f"{API_BASE}{path}", headers=self._headers(), timeout=TIMEOUT_SECONDS, **kwargs
            )
        except requests.RequestException:
            raise DiscordAPIError(0, f"network error on {method} {path}") from None

    def _request(self, method: str, path: str, **kwargs) -> Any | None:
        for _attempt in range(MAX_RATE_LIMIT_RETRIES):
            response = self._send(method, path, **kwargs)
            if response.status_code != 429:
                break
            try:
                retry_after = (response.json() if response.content else {}).get("retry_after")
            except ValueError:
                retry_after = None
            if retry_after is None:
                retry_after = response.headers.get("Retry-After", 1)
            self._sleep(float(retry_after))
        else:
            raise DiscordAPIError(429, "gave up after repeated rate limits")

        if response.status_code >= 400:
            try:
                body = response.json() if response.content else response.text
            except ValueError:
                body = response.text
            raise DiscordAPIError(response.status_code, body)
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def get(self, path: str) -> Any:
        return self._request("GET", path)

    def post(self, path: str, json: dict | None = None) -> Any:
        return self._request("POST", path, json=json or {})

    def patch(self, path: str, json: dict) -> Any:
        return self._request("PATCH", path, json=json)

    def put(self, path: str, json: dict | None = None) -> Any:
        return self._request("PUT", path, json=json or {})

    def delete(self, path: str) -> None:
        return self._request("DELETE", path)
