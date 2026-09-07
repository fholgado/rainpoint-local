"""Explicit historical installation fixture for captured-protocol regressions."""
from rainpointd.device_catalog import DeviceCatalog, SensorDefinition, ValveDefinition
from rainpointd.gateway import Gateway as ProductionGateway
from rainpointd.rf import normalize_row as production_normalize_row

# Historical capture identities are explicit test inputs, never runtime defaults.
CAPTURED_INSTALLATION_CATALOG = DeviceCatalog(
    sensors=(
        SensorDefinition("c4e50024", "soil-left-bed", "Left Bed"),
        SensorDefinition("ce628024", "soil-front-1", "Front Yard Sensor 1"),
        SensorDefinition("d1e28024", "soil-front-2", "Front Yard Sensor 2"),
        SensorDefinition("9ce58024", "soil-right-bed", "Right Bed"),
    ),
    valves=(
        ValveDefinition(
            "b42d008f",
            "b9840280",
            "valve-1",
            "Garden Valve",
        ),
    ),
    hcs026_pairing_peers=frozenset(("b9840280",)),
)

class CapturedInstallationGateway(ProductionGateway):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("catalog", CAPTURED_INSTALLATION_CATALOG)
        super().__init__(*args, **kwargs)


def captured_normalize_row(*args, **kwargs):
    kwargs.setdefault("catalog", CAPTURED_INSTALLATION_CATALOG)
    return production_normalize_row(*args, **kwargs)


def observe_captured_sensor_route(gateway, endpoint="9bce0024"):
    """Supply an explicit accepted association before testing ACK ownership."""
    gateway.observe_decoded(
        device_id=f"hcs026-{endpoint}", name="Captured sensor", model="HCS026FRF",
        frame="captured-association", state={"rf_endpoint": endpoint,
            "rf_endpoint_a": "b9840280", "rf_endpoint_b": endpoint,
            "rf_frame_accepted": True, "rf_trailer_valid": True,
            "rf_pairing_state": "paired"})
