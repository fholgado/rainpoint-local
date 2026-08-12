"""Evidence-based RainPoint product and protocol identification.

Retail model names belong in this catalog, not in packet-ingestion branches.
An RF protocol signature can establish compatibility before a packet provides
enough evidence to identify the exact retail model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


HCS02X_PROTOCOL = "rainpoint_hcs02x"
HTV_PROTOCOL = "rainpoint_htv"
HCS026_MODEL = "HCS026FRF"
HTV145_MODEL = "HTV145FRF"
GENERIC_HCS02X_MODEL = "HCS02x-compatible soil sensor"


@dataclass(frozen=True)
class ProductModel:
    """One catalogued RainPoint product identity."""

    model: str
    device_kind: str
    protocol: str
    model_code: int
    product_code: int


PRODUCT_MODELS = (
    ProductModel(
        model=HCS026_MODEL,
        device_kind="soil_sensor",
        protocol=HCS02X_PROTOCOL,
        model_code=0x013D,
        product_code=0x48,
    ),
    ProductModel(
        model=HTV145_MODEL,
        device_kind="irrigation_valve",
        protocol=HTV_PROTOCOL,
        model_code=0x012E,
        product_code=0x1F,
    ),
)

_BY_PRODUCT_CODE = {
    (item.device_kind, item.product_code): item for item in PRODUCT_MODELS
}
_BY_MODEL_CODE = {
    (item.device_kind, item.model_code): item for item in PRODUCT_MODELS
}
_KNOWN_PRODUCT_CODES = {item.product_code for item in PRODUCT_MODELS}
_KNOWN_MODEL_CODES = {item.model_code for item in PRODUCT_MODELS}
_BY_MODEL = {item.model: item for item in PRODUCT_MODELS}


@dataclass(frozen=True)
class ProductIdentity:
    """A model decision plus the evidence that supports it."""

    model: str
    device_kind: str
    protocol: str
    source: str
    product_code: int | None = None
    model_code: int | None = None

    @property
    def exact_model(self) -> bool:
        """Return whether the evidence identifies a catalogued retail model."""
        return self.model in _BY_MODEL

    def state_fields(self) -> dict[str, Any]:
        """Return transport-neutral identity diagnostics for device state."""
        result: dict[str, Any] = {
            "device_kind": self.device_kind,
            "rf_protocol_family": self.protocol,
            "product_model_source": self.source,
            "product_model_exact": self.exact_model,
        }
        if self.product_code is not None:
            result["rf_product_code"] = self.product_code
        if self.model_code is not None:
            result["rf_model_code"] = self.model_code
        return result


def product_for_model(model: str | None) -> ProductModel | None:
    """Return catalog metadata for an exact retail model name."""
    return _BY_MODEL.get(model or "")


def product_from_codes(
    device_kind: str,
    *,
    product_code: int | None = None,
    model_code: int | None = None,
) -> tuple[ProductModel, str] | None:
    """Resolve compatible RF identifiers and reject contradictory codes."""
    candidates: list[tuple[ProductModel, str]] = []
    if product_code is not None:
        product = _BY_PRODUCT_CODE.get((device_kind, product_code))
        if product is not None:
            candidates.append((product, "rf_product_code"))
        elif product_code in _KNOWN_PRODUCT_CODES:
            return None
    if model_code is not None:
        product = _BY_MODEL_CODE.get((device_kind, model_code))
        if product is not None:
            candidates.append((product, "rf_model_code"))
        elif model_code in _KNOWN_MODEL_CODES:
            return None
    if not candidates or len({item.model for item, _ in candidates}) != 1:
        return None
    product = candidates[0][0]
    source = (
        "rf_product_and_model_codes"
        if len(candidates) == 2
        else candidates[0][1]
    )
    return product, source


def hcs02x_identity(
    decoded: Mapping[str, Any], *, trusted_model: str | None = None
) -> ProductIdentity:
    """Identify an HCS02x-family sensor without overstating packet evidence."""
    product_code = decoded.get("product_code")
    model_code = decoded.get("model_code")
    identified = product_from_codes(
        "soil_sensor",
        product_code=product_code if isinstance(product_code, int) else None,
        model_code=model_code if isinstance(model_code, int) else None,
    )
    if identified is not None:
        product, source = identified
        return ProductIdentity(
            model=product.model,
            device_kind=product.device_kind,
            protocol=product.protocol,
            source=source,
            product_code=(
                product_code if isinstance(product_code, int) else None
            ),
            model_code=model_code if isinstance(model_code, int) else None,
        )

    trusted = product_for_model(trusted_model)
    if trusted is not None and trusted.protocol == HCS02X_PROTOCOL:
        return ProductIdentity(
            model=trusted.model,
            device_kind=trusted.device_kind,
            protocol=trusted.protocol,
            source="trusted_metadata",
        )

    return ProductIdentity(
        model=GENERIC_HCS02X_MODEL,
        device_kind="soil_sensor",
        protocol=HCS02X_PROTOCOL,
        source="rf_protocol_signature",
    )


def is_hcs02x_sensor(*, model: str | None, protocol: str | None = None) -> bool:
    """Return whether persisted metadata selects the HCS02x driver."""
    if protocol == HCS02X_PROTOCOL:
        return True
    if model == GENERIC_HCS02X_MODEL:
        return True
    product = product_for_model(model)
    return product is not None and product.protocol == HCS02X_PROTOCOL
