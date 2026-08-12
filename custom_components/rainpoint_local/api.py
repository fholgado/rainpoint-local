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


class RainPointLocalUnauthorized(RainPointLocalError):
    """The gateway rejected an authenticated operation."""


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

    async def nodes(self) -> list[dict[str, Any]]:
        """Return custom local radio-node snapshots."""
        data = await self._get("nodes")
        nodes = data.get("nodes")
        if not isinstance(nodes, list):
            raise RainPointLocalInvalidResponse("nodes response is not a list")
        return nodes

    async def receivers(self) -> list[dict[str, Any]]:
        """Return persistent physical-receiver coverage metrics."""
        data = await self._get("receivers")
        receivers = data.get("receivers")
        if not isinstance(receivers, list):
            raise RainPointLocalInvalidResponse(
                "receivers response is not a list"
            )
        return receivers

    async def pairing(self) -> dict[str, Any]:
        """Return sensor-pairing progress."""
        return await self._get("pairing")

    async def authenticate(self, token: str) -> None:
        """Verify a gateway management credential without changing state."""
        await self._post("auth/check", {}, token)

    async def register_radio_node(
        self,
        token: str,
        *,
        node_id: str,
        node_token: str,
        name: str,
        area: str | None,
    ) -> dict[str, Any]:
        """Register a provisioned custom local radio node."""
        return await self._post(
            "nodes/register",
            {
                "node_id": node_id,
                "token": node_token,
                "name": name,
                "area": area,
            },
            token,
        )

    async def identify_radio_node(
        self, token: str, node_id: str, duration_seconds: int = 15
    ) -> dict[str, Any]:
        """Request a bounded status-LED blink on one adopted node."""
        return await self._post(
            f"nodes/{node_id}/identify",
            {"duration_seconds": duration_seconds},
            token,
        )

    async def start_radio_node_adoption(
        self,
        token: str,
        *,
        node_id: str,
        name: str,
        area: str | None,
        duration_seconds: int = 300,
    ) -> dict[str, Any]:
        """Create a temporary gateway credential for an adoptable node."""
        return await self._post(
            "nodes/adoptions/start",
            {
                "node_id": node_id,
                "name": name,
                "area": area,
                "duration_seconds": duration_seconds,
            },
            token,
        )

    async def radio_node_adoption(
        self, token: str, node_id: str
    ) -> dict[str, Any]:
        """Return adoption progress without exposing its credential."""
        return await self._post(
            "nodes/adoptions/status", {"node_id": node_id}, token
        )

    async def cancel_radio_node_adoption(
        self, token: str, node_id: str
    ) -> dict[str, Any]:
        """Invalidate an unfinished node adoption."""
        return await self._post(
            "nodes/adoptions/cancel", {"node_id": node_id}, token
        )

    async def start_pairing(
        self,
        token: str,
        duration_seconds: int = 120,
        *,
        node_id: str,
        profile_id: str = "hcs026_15a98024_v1",
    ) -> dict[str, Any]:
        """Open pairing and arm one authenticated local radio node."""
        return await self._post(
            "pairing/start",
            {
                "duration_seconds": duration_seconds,
                "node_id": node_id,
                "profile_id": profile_id,
            },
            token,
        )

    async def stop_pairing(self, token: str) -> dict[str, Any]:
        """Close the current pairing window."""
        return await self._post("pairing/stop", {}, token)

    async def forget_sensor(
        self, token: str, device_id: str
    ) -> dict[str, Any]:
        """Forget one local sensor association without sending RF."""
        return await self._post(f"devices/{device_id}/forget", {}, token)

    async def complete_pairing(
        self,
        token: str,
        *,
        endpoint: str,
        name: str,
        area: str | None,
    ) -> dict[str, Any]:
        """Persist human-facing metadata for a proven paired sensor."""
        return await self._post(
            "pairing/complete",
            {"endpoint": endpoint, "name": name, "area": area},
            token,
        )

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

    async def _post(
        self, path: str, payload: dict[str, Any], token: str
    ) -> dict[str, Any]:
        try:
            async with self._session.post(
                f"{self._base_url}/{path}",
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status in {401, 403}:
                    raise RainPointLocalUnauthorized(
                        "the gateway rejected the registry token"
                    )
                response.raise_for_status()
                result = await response.json()
        except RainPointLocalUnauthorized:
            raise
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise RainPointLocalCannotConnect(str(exc)) from exc
        except (ValueError, TypeError) as exc:
            raise RainPointLocalInvalidResponse(str(exc)) from exc
        if not isinstance(result, dict):
            raise RainPointLocalInvalidResponse("response is not an object")
        return result


class RainPointNodeCommissioningClient:
    """Client for a factory node's temporary LAN adoption service."""

    def __init__(self, host: str, session: aiohttp.ClientSession) -> None:
        self._base_url = f"http://{host}/api/v1"
        self._session = session

    async def info(self) -> dict[str, Any]:
        """Return public adoption state."""
        return await self._request("GET", "info")

    async def identify(self) -> dict[str, Any]:
        """Start a bounded LED-identification window."""
        return await self._request("POST", "identify")

    async def adopt(
        self, *, gateway_host: str, gateway_port: int, token: str
    ) -> dict[str, Any]:
        """Deliver a gateway-issued credential after physical confirmation."""
        return await self._request(
            "POST",
            "adopt",
            data={
                "host": gateway_host,
                "port": str(gateway_port),
                "token": token,
            },
        )

    async def _request(
        self, method: str, path: str, *, data: dict[str, str] | None = None
    ) -> dict[str, Any]:
        try:
            async with self._session.request(
                method,
                f"{self._base_url}/{path}",
                data=data,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                response.raise_for_status()
                payload = await response.json()
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise RainPointLocalCannotConnect(str(exc)) from exc
        except (ValueError, TypeError) as exc:
            raise RainPointLocalInvalidResponse(str(exc)) from exc
        if not isinstance(payload, dict):
            raise RainPointLocalInvalidResponse(
                "node commissioning response is not an object"
            )
        return payload
