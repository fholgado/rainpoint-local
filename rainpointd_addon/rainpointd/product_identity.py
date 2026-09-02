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


@dataclass(frozen=True)
class ProductFamily:
    """A shared functional family represented by one product code."""

    product_code: int
    device_kind: str
    protocol: str
    generic_model: str
    catalog_capabilities: tuple[str, ...]


PRODUCT_FAMILIES = (
    ProductFamily(
        product_code=0x48,
        device_kind="soil_sensor",
        protocol=HCS02X_PROTOCOL,
        generic_model=GENERIC_HCS02X_MODEL,
        catalog_capabilities=("soil_moisture", "battery", "signal_strength"),
    ),
    ProductFamily(
        product_code=0x1F,
        device_kind="irrigation_valve",
        protocol=HTV_PROTOCOL,
        generic_model="RainPoint-compatible irrigation valve",
        catalog_capabilities=(
            "water_control",
            "battery",
            "signal_strength",
            "work_state",
            "alarm",
            "duration",
        ),
    ),
)


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

_FAMILY_BY_PRODUCT_CODE = {
    (item.device_kind, item.product_code): item for item in PRODUCT_FAMILIES
}
_BY_MODEL_CODE = {
    (item.device_kind, item.model_code): item for item in PRODUCT_MODELS
}
_KNOWN_PRODUCT_CODES = {item.product_code for item in PRODUCT_FAMILIES}
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
    catalog_capabilities: tuple[str, ...] = ()

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
        if self.catalog_capabilities:
            result["product_family_capabilities"] = list(
                self.catalog_capabilities
            )
        return result


def product_for_model(model: str | None) -> ProductModel | None:
    """Return catalog metadata for an exact retail model name."""
    return _BY_MODEL.get(model or "")


def family_from_product_code(
    device_kind: str, product_code: int | None
) -> ProductFamily | None:
    """Resolve shared functionality without claiming an exact model."""
    if product_code is None:
        return None
    return _FAMILY_BY_PRODUCT_CODE.get((device_kind, product_code))


def product_from_codes(
    device_kind: str,
    *,
    product_code: int | None = None,
    model_code: int | None = None,
) -> tuple[ProductModel, str] | None:
    """Resolve compatible RF identifiers and reject contradictory codes."""
    if model_code is None:
        return None
    product = _BY_MODEL_CODE.get((device_kind, model_code))
    if product is None:
        return None
    if product_code is not None and product.product_code != product_code:
        return None
    source = (
        "rf_product_and_model_codes"
        if product_code is not None
        else "rf_model_code"
    )
    return product, source


def hcs02x_identity(
    decoded: Mapping[str, Any], *, trusted_model: str | None = None
) -> ProductIdentity:
    """Identify an HCS02x-family sensor without overstating packet evidence."""
    product_code = decoded.get("product_code")
    model_code = decoded.get("model_code")
    product_code = product_code if isinstance(product_code, int) else None
    model_code = model_code if isinstance(model_code, int) else None
    identified = product_from_codes(
        "soil_sensor",
        product_code=product_code,
        model_code=model_code,
    )
    if identified is not None:
        product, source = identified
        family = family_from_product_code(
            product.device_kind, product.product_code
        )
        return ProductIdentity(
            model=product.model,
            device_kind=product.device_kind,
            protocol=product.protocol,
            source=source,
            product_code=product_code,
            model_code=model_code,
            catalog_capabilities=(
                family.catalog_capabilities if family is not None else ()
            ),
        )

    model_for_kind = (
        _BY_MODEL_CODE.get(("soil_sensor", model_code))
        if model_code is not None
        else None
    )
    if (
        (model_code in _KNOWN_MODEL_CODES and model_for_kind is None)
        or (
            model_for_kind is not None
            and product_code is not None
            and model_for_kind.product_code != product_code
        )
        or (
            product_code in _KNOWN_PRODUCT_CODES
            and family_from_product_code("soil_sensor", product_code) is None
        )
    ):
        return ProductIdentity(
            model=GENERIC_HCS02X_MODEL,
            device_kind="soil_sensor",
            protocol=HCS02X_PROTOCOL,
            source="rf_identifier_conflict",
            product_code=product_code,
            model_code=model_code,
        )

    trusted = product_for_model(trusted_model)
    family = family_from_product_code("soil_sensor", product_code)
    if (
        trusted is not None
        and trusted.protocol == HCS02X_PROTOCOL
        and (family is None or trusted.product_code == family.product_code)
        and model_code is None
    ):
        return ProductIdentity(
            model=trusted.model,
            device_kind=trusted.device_kind,
            protocol=trusted.protocol,
            source="trusted_metadata",
            product_code=product_code,
            catalog_capabilities=(
                family.catalog_capabilities if family is not None else ()
            ),
        )

    if family is not None:
        return ProductIdentity(
            model=family.generic_model,
            device_kind=family.device_kind,
            protocol=family.protocol,
            source="rf_product_code_family",
            product_code=product_code,
            model_code=model_code,
            catalog_capabilities=family.catalog_capabilities,
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
