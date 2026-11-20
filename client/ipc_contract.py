"""Explicit ordered IPC protocol=4 contract, credit ledger, and commit tracker."""

from collections import deque
from dataclasses import dataclass
import time

from wire import ProbeError

IPC_PROTOCOL_VERSION = 4

WORKER_RECORD_TYPES = frozenset(
    {
        "initialized",
        "world-reset",
        "creation-sequence-admitted",
        "checkpoint",
        "receipt",
        "cursor",
        "raw-event",
        "gap",
        "recovery",
        "blocked",
        "event-subscriptions",
        "diagnostic",
        "batch-complete",
    }
)

FORWARDED_EVENTS = frozenset(
    {
        "player_death",
        "player_hurt",
        "weapon_fire",
        "grenade_thrown",
        "bomb_beginplant",
        "bomb_abortplant",
        "bomb_planted",
        "bomb_begindefuse",
        "bomb_abortdefuse",
        "bomb_defused",
        "bomb_exploded",
        "bomb_dropped",
        "bomb_pickup",
        "round_start",
        "round_end",
        "round_prestart",
        "round_poststart",
        "round_freeze_end",
        "round_officially_ended",
        "round_announce_warmup",
        "begin_new_match",
        "round_announce_match_start",
        "cs_win_panel_round",
        "cs_win_panel_match",
    }
)

PUBLIC_COMMON_FIELDS = (
    "tick",
    "tickInterval",
    "contextTick",
    "committedTick",
    "map",
    "warmup",
    "round",
    "weapon",
    "actor",
    "target",
    "source",
    "channel",
    "world",
    "sequence",
    "descriptorGeneration",
    "eventServerTick",
    "networkTick",
    "identityResolved",
)

PUBLIC_RAW_EVENT_FIELDS = ("type", "name", "fields", "players", "pawns")


@dataclass(frozen=True)
class Envelope:
    actions: list
    dequeued_ns: int
    sdk_age_us: int | None


@dataclass(frozen=True)
class InputBatch:
    number: int
    first: int
    last: int
    raw_bytes: int
    submitted_ns: int
    world: int
    envelopes: list  # (last parser sequence, dequeue time, SDK age)


class CreditLedger:
    """Owns inflight batch credit, high/low watermarks, and envelope residence timing.

    Credit is released strictly on ordered worker batch-complete, never on pipe write.
    """

    HIGH_BATCHES, LOW_BATCHES = 16, 8
    HIGH_MESSAGES, LOW_MESSAGES = 8192, 4096
    HIGH_BYTES, LOW_BYTES = 4 * 1024**2, 2 * 1024**2

    def __init__(self):
        self.inflight: deque[InputBatch] = deque()
        self.pending_messages = 0
        self.pending_bytes = 0
        self.peak_messages = 0
        self.peak_bytes = 0
        self.peak_batches = 0
        self.throttled = False
        self.processed_bytes = 0

    @property
    def caught_up(self) -> bool:
        return not self.inflight

    def has_credit(self) -> bool:
        if self.throttled:
            self.throttled = (
                len(self.inflight) > self.LOW_BATCHES
                or self.pending_messages > self.LOW_MESSAGES
                or self.pending_bytes > self.LOW_BYTES
            )
        else:
            self.throttled = (
                len(self.inflight) >= self.HIGH_BATCHES
                or self.pending_messages >= self.HIGH_MESSAGES
                or self.pending_bytes >= self.HIGH_BYTES
            )
        return not self.throttled

    def record_batch(self, batch: InputBatch) -> None:
        count = batch.last - batch.first + 1
        self.inflight.append(batch)
        self.pending_messages += count
        self.pending_bytes += batch.raw_bytes
        self.peak_messages = max(self.peak_messages, self.pending_messages)
        self.peak_bytes = max(self.peak_bytes, self.pending_bytes)
        self.peak_batches = max(self.peak_batches, len(self.inflight))

    def complete_batch(
        self, batch_number: int, world: int, sequence: int, completed_sequence: int
    ) -> None:
        if not self.inflight:
            raise ProbeError("ordered-parser-unexpected-completion")
        batch = self.inflight[0]
        if (
            batch_number != batch.number
            or world != batch.world
            or sequence != batch.last
            or completed_sequence != batch.last
        ):
            raise ProbeError("ordered-parser-batch-order")
        self.inflight.popleft()
        self.pending_messages -= batch.last - batch.first + 1
        self.pending_bytes -= batch.raw_bytes
        self.processed_bytes += batch.raw_bytes

    def oldest_age_us(self, now_ns: int) -> int | None:
        if self.inflight:
            return (now_ns - self.inflight[0].envelopes[0][1]) // 1000
        return None

    def backlog(self, now_ns: int) -> dict:
        return dict(
            pendingBatches=len(self.inflight),
            pendingMessages=self.pending_messages,
            pendingBytes=self.pending_bytes,
            peakBatches=self.peak_batches,
            peakMessages=self.peak_messages,
            peakBytes=self.peak_bytes,
            oldestAgeUs=self.oldest_age_us(now_ns),
        )

    def timing_for(self, sequence: int, observed_ns: int) -> dict:
        now = time.monotonic_ns()
        if not self.inflight:
            raise ProbeError("ordered-parser-result-without-input")
        batch = self.inflight[0]
        if batch.first <= sequence <= batch.last:
            for last, dequeued, sdk_age in batch.envelopes:
                if sequence <= last:
                    return dict(
                        sdkQueueAgeUs=sdk_age,
                        dequeueToSubmitUs=(batch.submitted_ns - dequeued) // 1000,
                        submitToObservedUs=(now - batch.submitted_ns) // 1000,
                        resultQueueUs=(now - observed_ns) // 1000,
                    )
        raise ProbeError("ordered-parser-result-without-input")


class GenerationCommitTracker:
    """Owns current-world checkpoint watermark, receipt release, and event subscriptions.

    Retired worlds cannot advance checkpoints, receipts, or ACK eligibility.
    """

    def __init__(self):
        self.completed_sequence = 0
        self.processed_messages = 0
        self.decode_us = 0
        self.checkpoint: dict | None = None
        self._pending_controls: deque[dict] = deque()
        self._receipts: deque[dict] = deque()
        self._subscriptions: dict | None = None

    def reset_generation(self) -> None:
        self.checkpoint = None
        self._pending_controls.clear()
        self._receipts.clear()
        self._subscriptions = None

    def advance_processed(
        self, sequence: int, decode_us: int, ledger: CreditLedger
    ) -> None:
        if (
            not ledger.inflight
            or sequence is None
            or not self.completed_sequence < sequence <= ledger.inflight[0].last
        ):
            raise ProbeError("ordered-parser-checkpoint-order")
        if type(decode_us) is not int or decode_us < 0:
            raise ProbeError("ordered-parser-checkpoint-duration")
        self.processed_messages += sequence - self.completed_sequence
        self.decode_us += decode_us
        self.completed_sequence = sequence

    def accept_current_world(
        self, row: dict, sequence: int | None, diagnostics: deque
    ) -> None:
        kind = row["type"]
        if kind == "checkpoint":
            if (
                type(row.get("sequence")) is not int
                or type(row.get("schemaReady")) is not bool
                or type(row.get("serverInfo")) is not bool
                or type(row.get("stringTables")) is not int
                or row["stringTables"] < 0
                or type(row.get("schemaFields")) is not int
                or row["schemaFields"] < 0
                or type(row.get("classCount")) is not int
                or row["classCount"] < 0
            ):
                raise ProbeError("ordered-parser-checkpoint-shape")
            self.checkpoint = row
            while (
                self._pending_controls
                and self._pending_controls[0]["sequence"] <= sequence
            ):
                self._receipts.append(self._pending_controls.popleft())
            return
        if kind == "diagnostic":
            diagnostics.append({key: row.get(key) for key in ("reason", "eventId")})
            return
        if kind == "receipt":
            if (
                type(row.get("sequence")) is not int
                or type(row.get("tick")) is not int
                or row["tick"] < 1
                or type(row.get("epoch")) is not int
                or row["epoch"] < 0
                or type(row.get("full")) is not bool
                or "baselineAck" not in row
                or (
                    row["baselineAck"] is not None
                    and (
                        type(row["baselineAck"]) is not int
                        or row["baselineAck"] not in (0, 1)
                    )
                )
            ):
                raise ProbeError("ordered-parser-receipt-shape")
        if kind == "recovery":
            if (
                type(row.get("sequence")) is not int
                or type(row.get("reason")) is not str
                or type(row.get("snapshotEpoch")) is not int
                or row["snapshotEpoch"] < 0
                or type(row.get("worldReinitialization")) is not bool
                or ("request" in row and type(row["request"]) is not bool)
            ):
                raise ProbeError("ordered-parser-recovery-shape")
        if kind in ("receipt", "recovery"):
            if len(self._pending_controls) + len(self._receipts) >= 4096:
                raise ProbeError("ordered-parser-receipt-budget")
            self._pending_controls.append(row)
        if kind == "recovery" and row.get("worldReinitialization"):
            raise ProbeError(
                "ordered-parser-world-reinitialization: "
                + str(row.get("reason", "unknown"))[:1024]
            )
        if kind == "event-subscriptions":
            ids = row.get("ids")
            if (
                type(row.get("sequence")) is not int
                or not isinstance(ids, list)
                or len(ids) > 512
                or any(type(eid) is not int or not 0 <= eid < 512 for eid in ids)
                or len(set(ids)) != len(ids)
            ):
                raise ProbeError("ordered-parser-subscriptions-shape")
            self._subscriptions = row

    def pop_receipts(self) -> list[dict]:
        result = list(self._receipts)
        self._receipts.clear()
        return result

    def pop_subscriptions(self) -> dict | None:
        result = self._subscriptions
        if result is not None and (
            self.checkpoint is None or self.checkpoint["sequence"] < result["sequence"]
        ):
            return None
        self._subscriptions = None
        return result


def validate_worker_record(
    row: dict, *, source: str, channel: int, max_world: int, max_sequence: int
) -> tuple[int, int | None]:
    if not isinstance(row, dict):
        raise ProbeError("ordered-parser-output-type")
    kind = row.get("type")
    if type(kind) is not str or kind not in WORKER_RECORD_TYPES:
        raise ProbeError("ordered-parser-output-type")
    if row.get("source") != source or row.get("channel") != channel:
        raise ProbeError("ordered-parser-output-owner")
    world = row.get("world")
    if type(world) is not int or not 1 <= world <= max_world:
        raise ProbeError("ordered-parser-output-world")
    sequence = row.get("sequence")
    require_seq = kind not in (
        "initialized",
        "world-reset",
        "creation-sequence-admitted",
    )
    if require_seq:
        if type(sequence) is not int or not 0 <= sequence <= max_sequence:
            raise ProbeError("ordered-parser-output-sequence")
    elif sequence is not None and (
        type(sequence) is not int or not 0 <= sequence <= max_sequence
    ):
        raise ProbeError("ordered-parser-output-sequence")
    if kind == "initialized" and row.get("protocol") != IPC_PROTOCOL_VERSION:
        raise ProbeError("ordered-parser-protocol-version")
    if kind == "world-reset" and "reason" in row and type(row["reason"]) is not str:
        raise ProbeError("ordered-parser-record-shape")
    if kind == "creation-sequence-admitted" and (
        "creationSequence" in row
        and (type(row["creationSequence"]) is not int or row["creationSequence"] < 0)
    ):
        raise ProbeError("ordered-parser-record-shape")
    if kind == "batch-complete" and (
        type(row.get("batch")) is not int or row["batch"] < 1
    ):
        raise ProbeError("ordered-parser-record-shape")
    if kind in ("gap", "diagnostic") and type(row.get("reason")) is not str:
        raise ProbeError("ordered-parser-record-shape")
    if kind == "cursor" and (
        type(row.get("committedTick")) is not int
        or row["committedTick"] < 1
        or type(row.get("tickInterval")) not in (int, float)
        or not 0 < row["tickInterval"] <= 1
        or (row.get("map") is not None and type(row.get("map")) is not str)
    ):
        raise ProbeError("ordered-parser-record-shape")
    if kind == "raw-event" and (
        type(row.get("name")) is not str
        or not row["name"]
        or not isinstance(row.get("fields"), dict)
    ):
        raise ProbeError("ordered-parser-record-shape")
    return world, sequence


def format_public_record(row: dict, timing: dict) -> dict:
    updated = {**row, "contextTick": row["tick"]}
    if updated["type"] == "cursor":
        updated["tick"] = updated["committedTick"]
    return dict(
        **timing,
        kind="cursor" if updated["type"] == "cursor" else updated["name"],
        **(
            {"roundClock": updated.get("roundClock")}
            if updated["type"] == "cursor" and "roundClock" in updated
            else {}
        ),
        **(
            {key: updated.get(key) for key in PUBLIC_RAW_EVENT_FIELDS}
            if updated["type"] == "raw-event"
            else {}
        ),
        **{key: updated.get(key) for key in PUBLIC_COMMON_FIELDS},
    )
