"""Immutable captured HCS026 profiles for offline regression only."""
import binascii
from rainpointd.pairing_protocol import (
    FRAME_BYTES, SYNC, TRAILER_RESIDUES, PairingProfile, PairingReplyStep, PairingTrigger,
)
from rainpointd.product_identity import HCS026_MODEL
COMPANION_ENDPOINT = bytes.fromhex("39840280")

def _frame(value: str) -> bytes:
    frame = bytes.fromhex(value)
    if len(frame) != FRAME_BYTES or not frame.startswith(SYNC):
        raise ValueError("pairing reply must be one normalized RainPoint frame")
    residual = binascii.crc_hqx(frame[:-2], 0) ^ int.from_bytes(frame[-2:], "big")
    if residual not in TRAILER_RESIDUES:
        raise ValueError("pairing reply has an unknown trailer residual")
    if frame[9:13] != COMPANION_ENDPOINT:
        raise ValueError("pairing reply does not use the companion endpoint")
    return frame


VALIDATED_HCS026_PROFILE = PairingProfile(
    profile_id="hcs026_15a98024_v1",
    model=HCS026_MODEL,
    factory_endpoint="15a98024",
    paired_endpoint="95a98024",
    evidence="controlled successful repeat enrollment captured 2026-08-11",
    steps=(
        PairingReplyStep(
            PairingTrigger.FACTORY_ANNOUNCEMENT,
            433_471_500,
            _frame(
                "79f4882f2895a98024398402808140880503827000fc760b0d010080000000000000000030c3"
            ),
        ),
        PairingReplyStep(
            PairingTrigger.PAIRED_MESSAGE_1,
            433_471_500,
            _frame(
                "79f4882f2895a980243984028081c18200009f800000000000000000000000000000000077dc"
            ),
        ),
        PairingReplyStep(
            PairingTrigger.PAIRED_MESSAGE_2_DATA,
            433_471_500,
            _frame(
                "79f4882f2895a980243984028082418100010000000000000000000000000000000000003622"
            ),
        ),
    ),
)


SENSOR_A_CANDIDATE_PROFILE = PairingProfile(
    profile_id="hcs026_1bce0024_candidate_v1",
    model=HCS026_MODEL,
    factory_endpoint="1bce0024",
    paired_endpoint="9bce0024",
    evidence="controlled successful local enrollment captured 2026-08-12",
    steps=(
        PairingReplyStep(
            PairingTrigger.FACTORY_ANNOUNCEMENT,
            433_471_484,
            _frame(
                "79f4882f289bce002439840280814088050304f000adf18a0d00808000000000000000004c41"
            ),
        ),
        PairingReplyStep(
            PairingTrigger.PAIRED_MESSAGE_1,
            434_021_457,
            _frame(
                "79f4882f289bce00243984028081c18200009f80000000000000000000000000000000003d14"
            ),
        ),
        PairingReplyStep(
            PairingTrigger.PAIRED_MESSAGE_2_DATA,
            434_021_457,
            _frame(
                "79f4882f289bce00243984028082418100010000000000000000000000000000000000007cea"
            ),
        ),
        PairingReplyStep(
            PairingTrigger.PAIRED_MESSAGE_2_SHORT,
            434_021_457,
            _frame(
                "79f4882f289bce00243984028082c18100010000000000000000000000000000000000004e6f"
            ),
        ),
    ),
    reply_delay_ms=10,
)


PAIRING_PROFILES = {
    VALIDATED_HCS026_PROFILE.profile_id: VALIDATED_HCS026_PROFILE,
    SENSOR_A_CANDIDATE_PROFILE.profile_id: SENSOR_A_CANDIDATE_PROFILE,
}


def pairing_profile(profile_id: str) -> PairingProfile:
    """Return an evidence-backed profile by stable protocol-profile ID."""
    try:
        return PAIRING_PROFILES[profile_id.lower()]
    except KeyError:
        raise KeyError(profile_id) from None


def pairing_profile_for_factory(factory_endpoint: str) -> PairingProfile:
    """Resolve an observed factory identity without treating it as a model."""
    normalized = factory_endpoint.lower()
    for profile in PAIRING_PROFILES.values():
        if profile.factory_endpoint == normalized:
            return profile
    raise KeyError(factory_endpoint)
