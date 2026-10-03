"""Explicit dry-control experiments layered on the ordinary HTV213 journal.

Counter-boundary jumps and corrected-frame retries are research operations,
not model control or recovery policy. Both adapters share the existing records;
there is no copy, reset or migration when an association changes callers.
"""
from __future__ import annotations

import copy
import re
import uuid
from datetime import datetime, timezone

from .htv213_control import ControlJournal as ModelControlJournal


class ControlJournal(ModelControlJournal):
    def reserve(self, key, *, action, port, seconds, dry_confirmed):
        if dry_confirmed is not True:
            raise ValueError("dry test confirmation required")
        return super().reserve(key, action=action, port=port, seconds=seconds)

    def reserve_boundary_probe(self, key, *, prior_command_id, authorization_id, port,
                               seconds, dry_confirmed):
        """Once-only 62,63,0,1 dry experiment; never a normal recovery policy.

        Preserve the real prior next phase instead of fabricating a successful
        seed. Each step needs the previous genuine ACK, idle and summary. An
        uncertain send cannot advance, restart this sequence or reuse its phase.
        """
        if (dry_confirmed is not True or type(port) is not int or port not in (1, 2)
                or type(seconds) is not int or seconds != 60):
            raise ValueError("counter boundary requires one-minute dry controls")
        for value in (prior_command_id, authorization_id):
            if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value):
                raise ValueError("explicit prior transaction and authorization required")
        records = self._records()
        record = records[key]
        prior = record["transaction"]
        if (record["state"] != "complete" or not prior or
                prior["command_id"] != prior_command_id or
                not all(prior.get(f) for f in ("acknowledged", "idle", "summary"))):
            raise ValueError("prior boundary step must be genuinely complete")
        boundary = record.get("counter_boundary")
        if boundary is None:
            boundary = dict(authorization_id=authorization_id, port=port,
                            origin_next_phase=record["next_phase"], reserved_steps=0, complete=False)
        elif (boundary["authorization_id"] != authorization_id or boundary["port"] != port
              or boundary["reserved_steps"] >= 4 or boundary["complete"]):
            raise ValueError("counter-boundary authorization exhausted or changed")
        step = boundary["reserved_steps"]
        phase = (62, 63, 0, 1)[step]
        tx = dict(command_id=uuid.uuid4().hex, phase=phase, action="open", port=port,
                  requested_seconds=seconds, reserved_at=datetime.now(timezone.utc).isoformat(),
                  acknowledged=False, idle=False, summary=False,
                  counter_boundary=dict(authorization_id=authorization_id, step=step,
                                        prior_next_phase=record["next_phase"]))
        record["history"].append(prior)
        boundary["reserved_steps"] += 1
        record.update(transaction=tx, state="reserved", next_phase=phase + 1, counter_boundary=boundary)
        self._save(records)
        return copy.deepcopy(tx)

    def reserve_crc_retrial(self, key, *, prior_command_id, evidence_sha256,
                            authorization_id, port, seconds, dry_confirmed):
        """One manual corrected-frame experiment, never recovery policy.

        Admission requires a separately reviewed capture proving the original
        CRC was malformed. Keep the original attempt and its phase reservation;
        this tests the same command with the corrected physical final symbol.
        The digest is an audit reference, not automatic RF proof validation.
        """
        if (dry_confirmed is not True or type(port) is not int or port not in (1, 2)
                or type(seconds) is not int or not 1 <= seconds <= 120):
            raise ValueError("bounded dry retrial required")
        for value, length in ((prior_command_id, 32), (evidence_sha256, 64), (authorization_id, 32)):
            if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{%d}" % length, value):
                raise ValueError("explicit prior attempt, CRC evidence and authorization required")
        records = self._records()
        record = records[key]
        prior = record["transaction"]
        if (record["state"] != "indeterminate" or not prior
                or prior["command_id"] != prior_command_id or prior["action"] != "open"
                or prior["acknowledged"] or prior["port"] != port
                or prior["requested_seconds"] != seconds or prior.get("crc_retrial")
                or any(tx.get("crc_retrial") for tx in record["history"])):
            raise ValueError("CRC retrial requires the original unconfirmed open; once only")
        tx = copy.deepcopy(prior)
        tx.update(command_id=uuid.uuid4().hex, crc_retrial={
            "prior_command_id": prior_command_id, "evidence_sha256": evidence_sha256,
            "authorization_id": authorization_id})
        record["history"].append(prior)
        record["transaction"] = tx
        record["state"] = "reserved"
        self._save(records)
        return copy.deepcopy(tx)
