"""Network-only base transport for gateways using remote radio nodes."""

from __future__ import annotations


class NetworkTransport:
    """No-op local transport; authenticated Wi-Fi nodes provide RF frames."""

    def seed(self) -> None:
        """Never seed synthetic devices into a production gateway."""

    def start(self) -> None:
        """The separate node server owns network receiver lifecycle."""

    def stop(self) -> None:
        """The separate node server owns network receiver lifecycle."""
