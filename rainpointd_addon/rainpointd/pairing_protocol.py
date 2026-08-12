"""Validated HCS026 pairing reply profiles and symbolic scheduling.

This module has no socket, serial, or radio dependency. It can describe what a
future transmitter must do, but cannot cause a transmission.
"""

from __future__ import annotations

import binascii
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

from .product_identity import HCS026_MODEL


SYNC = bytes.fromhex("79f4882f28")
COMPANION_ENDPOINT = bytes.fromhex("39840280")
FRAME_BYTES = 38
WAKE_SYMBOLS = 320
SYMBOL_RATE = 20_000
TRAILER_RESIDUES = {0xC713, 0x4F03}


class PairingTrigger(str, Enum):
    FACTORY_ANNOUNCEMENT = "factory_announcement"
    PAIRED_MESSAGE_1 = "paired_message_1"
    PAIRED_MESSAGE_2_DATA = "paired_message_2_data"
    PAIRED_MESSAGE_2_SHORT = "paired_message_2_short"
    PAIRED_MESSAGE_3 = "paired_message_3"


@dataclass(frozen=True)
class PairingReplyStep:
    trigger: PairingTrigger
    channel_center_hz: int
    frame: bytes
    wake_symbols: int = WAKE_SYMBOLS
    symbol_rate_sps: int = SYMBOL_RATE
    reply_deadline_ms: int = 250

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["trigger"] = self.trigger.value
        result["frame"] = self.frame.hex()
        result["waveform_duration_ms"] = round(
            (self.wake_symbols + len(self.frame) * 8)
            * 1_000
            / self.symbol_rate_sps,
            3,
        )
        return result


@dataclass(frozen=True)
class PairingProfile:
    profile_id: str
    model: str
    factory_endpoint: str
    paired_endpoint: str
    evidence: str
    steps: tuple[PairingReplyStep, ...]
    reply_delay_ms: int = 60
    completion_trigger: PairingTrigger = PairingTrigger.PAIRED_MESSAGE_3
    complete_after_final_reply: bool = False
    clock_lead_seconds: int = 240

    def as_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "model": self.model,
            "factory_endpoint": self.factory_endpoint,
            "paired_endpoint": self.paired_endpoint,
            "evidence": self.evidence,
            "transmit_enabled": False,
            "completion_trigger": self.completion_trigger.value,
            "complete_after_final_reply": self.complete_after_final_reply,
            "reply_delay_ms": self.reply_delay_ms,
            "clock_lead_seconds": self.clock_lead_seconds,
            "steps": [step.as_dict() for step in self.steps],
        }


AUTOMATIC_HCS026_PROFILE_ID = "hcs026_auto_v1"


def automatic_hcs026_profile_metadata() -> dict[str, Any]:
    """Describe model-level pairing without claiming a fixed RF transcript."""
    return {
        "profile_id": AUTOMATIC_HCS026_PROFILE_ID,
        "model": HCS026_MODEL,
        "factory_endpoint": None,
        "paired_endpoint": None,
        "evidence": (
            "common first-enrollment reply template across two independently "
            "validated HCS026 identities"
        ),
        "transmit_enabled": True,
        "automatic_discovery": True,
        "completion_trigger": PairingTrigger.PAIRED_MESSAGE_3.value,
        "reply_delay_ms": 10,
        "clock_lead_seconds": 240,
    }


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


class PairingPlanController:
    """Advance a profile from observed sensor frames, emitting symbols only."""

    def __init__(self, profile: PairingProfile) -> None:
        self.profile = profile
        self.next_step = 0
        self.failed = False
        self.failure_reason: str | None = None
        self.terminal_confirmed = False
        self.pending: PairingReplyStep | None = None
        self.pending_deadline_ms: int | None = None

    @property
    def complete(self) -> bool:
        return self.replies_complete and self.terminal_confirmed

    @property
    def replies_complete(self) -> bool:
        return self.next_step == len(self.profile.steps)

    def observe(
        self, trigger: PairingTrigger, *, now_ms: int
    ) -> PairingReplyStep | None:
        if self.failed or self.complete:
            return None
        if self.pending is not None:
            return (
                None
                if trigger == self.pending.trigger
                else self._fail("unexpected_trigger")
            )
        if self.replies_complete:
            if trigger == self.profile.completion_trigger:
                self.terminal_confirmed = True
                return None
            if trigger == PairingTrigger.PAIRED_MESSAGE_2_SHORT:
                return None
            if any(step.trigger == trigger for step in self.profile.steps):
                return None
            return self._fail("unexpected_trigger")
        expected = self.profile.steps[self.next_step]
        if trigger == expected.trigger:
            self.pending = expected
            self.pending_deadline_ms = now_ms + expected.reply_deadline_ms
            return expected
        # Duplicate observations are harmless; a future transmitter may hear
        # the sensor repeat while its prior reply is still being scheduled.
        if any(step.trigger == trigger for step in self.profile.steps[: self.next_step]):
            return None
        return self._fail("unexpected_trigger")

    def mark_dispatched(self, trigger: PairingTrigger, *, now_ms: int) -> bool:
        """Record a symbolic scheduler handoff before the reply deadline."""
        if (
            self.failed
            or self.pending is None
            or self.pending.trigger != trigger
            or self.pending_deadline_ms is None
            or now_ms > self.pending_deadline_ms
        ):
            self._fail("reply_deadline_missed")
            return False
        self.next_step += 1
        self.pending = None
        self.pending_deadline_ms = None
        if (
            self.replies_complete
            and self.profile.complete_after_final_reply
        ):
            self.terminal_confirmed = True
        return True

    def tick(self, *, now_ms: int) -> None:
        if (
            self.pending_deadline_ms is not None
            and now_ms > self.pending_deadline_ms
        ):
            self._fail("reply_deadline_missed")

    def interrupt(self) -> None:
        self._fail("interrupted")

    def _fail(self, reason: str) -> None:
        self.failed = True
        self.failure_reason = reason
        self.pending = None
        self.pending_deadline_ms = None
        return None

    def status(self) -> dict[str, Any]:
        if self.failed or self.complete:
            next_trigger = None
        elif self.replies_complete:
            next_trigger = self.profile.completion_trigger.value
        else:
            next_trigger = self.profile.steps[self.next_step].trigger.value
        return {
            "factory_endpoint": self.profile.factory_endpoint,
            "paired_endpoint": self.profile.paired_endpoint,
            "completed_steps": self.next_step,
            "step_count": len(self.profile.steps),
            "replies_complete": self.replies_complete,
            "terminal_trigger": self.profile.completion_trigger.value,
            "terminal_confirmed": self.terminal_confirmed,
            "next_trigger": next_trigger,
            "pending_trigger": (
                self.pending.trigger.value if self.pending is not None else None
            ),
            "pending_deadline_ms": self.pending_deadline_ms,
            "complete": self.complete,
            "failed": self.failed,
            "failure_reason": self.failure_reason,
            "transmit_enabled": False,
        }
