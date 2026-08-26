"""Client for the local rainpointd API."""

from __future__ import annotations

from typing import Any

import aiohttp

from .const import API_VERSION
from .api_models import APIModelError, GatewayMetadata, validate_object_list


class RainPointLocalError(Exception):
    """Base API error."""


class RainPointLocalCannotConnect(RainPointLocalError):
    """The gateway could not be reached."""


class RainPointLocalInvalidResponse(RainPointLocalError):
    """The gateway returned an incompatible response."""


class RainPointLocalUnauthorized(RainPointLocalError):
    """The gateway rejected an authenticated operation."""


class RainPointLocalCommandRejected(RainPointLocalError):
    """The gateway safely rejected a valid authenticated command."""


class RainPointLocalClient:
    """Small asynchronous client for rainpointd."""

    def __init__(
        self, host: str, port: int, session: aiohttp.ClientSession
    ) -> None:
        self._base_url = f"http://{host}:{port}/api/{API_VERSION}"
        self._session = session

    async def info(self) -> GatewayMetadata:
        """Return gateway metadata and verify API compatibility."""
        data = await self._get("info")
        try:
            info = GatewayMetadata.from_payload(data)
        except APIModelError as exc:
            raise RainPointLocalInvalidResponse(str(exc)) from exc
        if info.api_version != API_VERSION:
            raise RainPointLocalInvalidResponse("incompatible rainpointd API")
        return info

    async def devices(self) -> list[dict[str, Any]]:
        """Return current device snapshots."""
        data = await self._get("devices")
        try:
            return validate_object_list(data, "devices", "device_id")
        except APIModelError as exc:
            raise RainPointLocalInvalidResponse(str(exc)) from exc

    async def nodes(self) -> list[dict[str, Any]]:
        """Return custom local radio-node snapshots."""
        data = await self._get("nodes")
        try:
            return validate_object_list(data, "nodes", "node_id")
        except APIModelError as exc:
            raise RainPointLocalInvalidResponse(str(exc)) from exc

    async def receivers(self) -> list[dict[str, Any]]:
        """Return persistent physical-receiver coverage metrics."""
        data = await self._get("receivers")
        receivers = data.get("receivers")
        if not isinstance(receivers, list):
            raise RainPointLocalInvalidResponse(
                "receivers response is not a list"
            )
        return receivers

    async def events(
        self, since: int, *, wait_seconds: int = 25
    ) -> tuple[list[dict[str, Any]], int]:
        """Wait for gateway events and return the next durable cursor."""
        data = await self._get(
            f"events?since={since}&wait={max(0, min(wait_seconds, 30))}",
            timeout_seconds=wait_seconds + 10,
        )
        events = data.get("events")
        next_since = data.get("next_since")
        if not isinstance(events, list) or not isinstance(next_since, int):
            raise RainPointLocalInvalidResponse("invalid events response")
        return events, next_since

    async def pairing(self) -> dict[str, Any]:
        """Return sensor-pairing progress."""
        return await self._get("pairing")

    async def authenticate(self, token: str) -> None:
        """Verify a gateway management credential without changing state."""
        await self._post("auth/check", {}, token)

    async def claim(self, setup_code: str) -> str:
        """Exchange a standalone gateway's one-time setup code."""
        result = await self._post("auth/claim", {"setup_code": setup_code})
        token = result.get("registry_write_token")
        if not isinstance(token, str) or not token:
            raise RainPointLocalInvalidResponse("claim response has no token")
        return token

    async def rotate_management_token(self, token: str) -> str:
        """Rotate and return the gateway management credential once."""
        result = await self._post("auth/rotate", {}, token)
        replacement = result.get("registry_write_token")
        if not isinstance(replacement, str) or not replacement:
            raise RainPointLocalInvalidResponse("rotation response has no token")
        return replacement

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

    async def update_radio_node_metadata(
        self,
        token: str,
        node_id: str,
        *,
        name: str,
        area: str | None,
    ) -> dict[str, Any]:
        """Persist a managed radio node's friendly name and area."""
        return await self._post(
            f"nodes/{node_id}/metadata",
            {"name": name, "area": area},
            token,
        )

    async def revoke_radio_node(
        self, token: str, node_id: str
    ) -> dict[str, Any]:
        """Revoke one node credential from the custom local gateway."""
        return await self._post(f"nodes/{node_id}/revoke", {}, token)

    async def install_radio_node_firmware(
        self,
        token: str,
        *,
        node_id: str,
        release_id: str,
        public_host: str,
    ) -> dict[str, Any]:
        """Install a gateway-catalogued release on one adopted radio node."""
        return await self._post(
            f"nodes/{node_id}/firmware-update",
            {"release_id": release_id, "public_host": public_host},
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
        profile_id: str = "hcs026_auto_v1",
        factory_endpoint: str | None = None,
        valve_route: str | None = None,
        companion_endpoint: str | None = None,
        known_rejoin: bool = False,
    ) -> dict[str, Any]:
        """Open pairing and arm one authenticated local radio node."""
        payload: dict[str, Any] = {
            "duration_seconds": duration_seconds,
            "node_id": node_id,
            "profile_id": profile_id,
        }
        if factory_endpoint is not None:
            payload["factory_endpoint"] = factory_endpoint
        if valve_route is not None:
            payload["valve_route"] = valve_route
        if companion_endpoint is not None:
            payload["companion_endpoint"] = companion_endpoint
        if known_rejoin:
            payload["known_rejoin"] = True
        return await self._post(
            "pairing/start",
            payload,
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

    async def forget_device(
        self, token: str, device_id: str
    ) -> dict[str, Any]:
        """Forget one supported local device without sending RF."""
        return await self._post(f"registry/{device_id}/forget", {}, token)

    async def complete_pairing(
        self,
        token: str,
        *,
        endpoint: str,
        name: str,
        area: str | None,
    ) -> dict[str, Any]:
        """Persist human-facing metadata for a proven paired device."""
        return await self._post(
            "pairing/complete",
            {"endpoint": endpoint, "name": name, "area": area},
            token,
        )

    async def open_htv405_zone(
        self,
        token: str,
        *,
        device_id: str,
        zone: int,
        duration_seconds: int,
    ) -> dict[str, Any]:
        """Request one duration-bounded four-zone valve run."""
        return await self._post(
            f"devices/{device_id}/valve/open",
            {"zone": zone, "duration_seconds": duration_seconds},
            token,
        )

    async def close_htv405_zone(
        self, token: str, *, device_id: str, zone: int
    ) -> dict[str, Any]:
        """Request an early stop for a confirmed active zone."""
        return await self._post(
            f"devices/{device_id}/valve/close",
            {"zone": zone},
            token,
        )

    async def _get(
        self, path: str, *, timeout_seconds: int = 10
    ) -> dict[str, Any]:
        try:
            async with self._session.get(
                f"{self._base_url}/{path}",
                timeout=aiohttp.ClientTimeout(total=timeout_seconds),
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
        self, path: str, payload: dict[str, Any], token: str | None = None
    ) -> dict[str, Any]:
        try:
            async with self._session.post(
                f"{self._base_url}/{path}",
                json=payload,
                headers=(
                    {"Authorization": f"Bearer {token}"} if token else {}
                ),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status == 401:
                    raise RainPointLocalUnauthorized(
                        "the gateway rejected the registry token"
                    )
                if response.status >= 400:
                    try:
                        error_payload = await response.json()
                    except (aiohttp.ContentTypeError, ValueError):
                        error_payload = {}
                    detail = error_payload.get("error")
                    raise RainPointLocalCommandRejected(
                        str(
                            detail
                            or f"gateway rejected command ({response.status})"
                        )
                    )
                response.raise_for_status()
                result = await response.json()
        except (RainPointLocalCommandRejected, RainPointLocalUnauthorized):
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
