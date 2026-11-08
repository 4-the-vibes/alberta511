"""Async client for the 511 Alberta REST API."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from typing import Any

import aiohttp

from .const import API_CALLS_PER_WINDOW, API_WINDOW_SECONDS, BASE_URL

_LOGGER = logging.getLogger(__name__)

USER_AGENT = "HomeAssistant-Alberta511/1.0"
_TIMEOUT = aiohttp.ClientTimeout(total=45)
_IMAGE_TIMEOUT = aiohttp.ClientTimeout(total=20)
_IMAGE_MAGIC = (b"\xff\xd8\xff", b"\x89PNG", b"GIF8", b"RIFF")


class Alberta511Error(Exception):
    """Generic API failure."""


class Alberta511AuthError(Alberta511Error):
    """Missing or invalid developer key."""


class Alberta511NotFound(Alberta511Error):
    """Collection not published by this deployment."""


class Alberta511Client:
    """Thin client with a client-side throttle matching the API's 10 calls/60 s."""

    def __init__(self, session: aiohttp.ClientSession, api_key: str | None) -> None:
        self._session = session
        self._api_key = (api_key or "").strip() or None
        self._calls: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def _throttle(self) -> None:
        async with self._lock:
            now = time.monotonic()
            while self._calls and now - self._calls[0] >= API_WINDOW_SECONDS:
                self._calls.popleft()
            if len(self._calls) >= API_CALLS_PER_WINDOW:
                wait = API_WINDOW_SECONDS - (now - self._calls[0]) + 0.5
                _LOGGER.debug("511 Alberta throttle: waiting %.1fs", wait)
                await asyncio.sleep(wait)
                self._calls.popleft()
            self._calls.append(time.monotonic())

    async def async_get(self, collection: str) -> Any:
        await self._throttle()
        params = {"format": "json", "lang": "en"}
        if self._api_key:
            params["key"] = self._api_key
        url = f"{BASE_URL}/{collection}"
        try:
            async with self._session.get(
                url,
                params=params,
                headers={"Accept": "application/json", "User-Agent": USER_AGENT},
                timeout=_TIMEOUT,
            ) as resp:
                if resp.status in (401, 403):
                    raise Alberta511AuthError(f"{collection}: HTTP {resp.status}")
                if resp.status == 404:
                    raise Alberta511NotFound(collection)
                if resp.status == 429:
                    raise Alberta511Error(f"{collection}: rate limited by 511 Alberta")
                if resp.status >= 400:
                    raise Alberta511Error(f"{collection}: HTTP {resp.status}")
                text = await resp.text()
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise Alberta511Error(f"{collection}: {err}") from err

        try:
            data = json.loads(text)
        except ValueError as err:
            lowered = text[:500].lower()
            if "key" in lowered and ("invalid" in lowered or "required" in lowered):
                raise Alberta511AuthError(text[:200]) from err
            raise Alberta511Error(f"{collection}: response was not JSON") from err

        # Some CARS deployments return 200 with an error object for bad keys.
        if isinstance(data, dict) and not any(isinstance(v, list) for v in data.values()):
            message = str(data.get("Message") or data.get("message") or data)
            if "key" in message.lower():
                raise Alberta511AuthError(message)
            raise Alberta511Error(f"{collection}: {message[:200]}")
        return data

    async def async_fetch_image(self, url: str) -> bytes:
        try:
            async with self._session.get(
                url,
                headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"},
                timeout=_IMAGE_TIMEOUT,
            ) as resp:
                if resp.status >= 400:
                    raise Alberta511Error(f"image HTTP {resp.status}")
                body = await resp.read()
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise Alberta511Error(f"image: {err}") from err
        if not body.startswith(_IMAGE_MAGIC):
            raise Alberta511Error("image URL did not return an image")
        return body
