"""Client for the local rainpointd API."""

from __future__ import annotations

from typing import Any

import aiohttp

from .const import API_VERSION


class RainPointLocalError(Exception):
    """Base API error."""


class RainPointLocalCannotConnect(RainPointLocalError):
    """The gateway could not be reached."""


class RainPointLocalInvalidResponse(RainPointLocalError):
    """The gateway returned an incompatible response."""


class RainPointLocalClient:
    """Small asynchronous client for rainpointd."""

    def __init__(
        self, host: str, port: int, session: aiohttp.ClientSession
    ) -> None:
        self._base_url = f"http://{host}:{port}/api/{API_VERSION}"
        self._session = session

    async def info(self) -> dict[str, Any]:
        """Return gateway metadata and verify API compatibility."""
        data = await self._get("info")
        if data.get("api_version") != API_VERSION or not data.get("gateway_id"):
            raise RainPointLocalInvalidResponse("incompatible rainpointd API")
        return data

    async def devices(self) -> list[dict[str, Any]]:
        """Return current device snapshots."""
        data = await self._get("devices")
        devices = data.get("devices")
        if not isinstance(devices, list):
            raise RainPointLocalInvalidResponse("devices response is not a list")
        return devices

    async def _get(self, path: str) -> dict[str, Any]:
        try:
            async with self._session.get(
                f"{self._base_url}/{path}",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                response.raise_for_status()
                payload = await response.json()
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise RainPointLocalCannotConnect(str(exc)) from exc
        except (ValueError, TypeError) as exc:
            raise RainPointLocalInvalidResponse(str(exc)) from exc
        if not isinstance(payload, dict):
            raise RainPointLocalInvalidResponse("response is not an object")
        return payload
