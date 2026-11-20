"""Pure health and terminal report projection from explicit typed snapshots."""

from dataclasses import dataclass

from process_io import HEALTH_INTERVAL_NS, SOFT_AGE_US


@dataclass(frozen=True)
class HealthInputs:
    done: bool
    reason: str | None
    last_health_ns: int
    last_health_totals: tuple[int, int, int, int, int]
    sdk_sample_ns: int | None
    last_sdk_age_us: int | None
    window_sdk_age_us: int | None
    max_sdk_age_us: int | None
    max_parser_age_us: int | None
    health_reason: str | None
    gap: bool
    recovery_pending: bool
    draining: bool
    full_sent: bool
    last_cursor: tuple | None
    cursor_rate: float | None
    receive_budget_exhausted: int
    result_budget_exhausted: int
    totals: tuple[int, int, int, int, int]


@dataclass(frozen=True)
class ReportInputs:
    phase: str
    reason: str | None
    received_messages: int
    host_version: int
    native_state: int | None
    native_failure: int | None
    remote_end_reason: int | None
    world_creation_watermark: int
    world_creation_sequences: list[int]
    challenge_metadata: dict | None
    challenge_requests: int
    feedback_sent: int
    last_received_channel_sequence: int
    channel_frames: int
    channel_bytes: int
    channel_receive_span_ms: int | None
    received_signon_state: int
    effective_signon_state: int
    full_snapshot_processed: bool
    stages: list[dict]
    ever_full: bool
    last_processed_sequence: int
    last_output_sequence: int
    drain_completed: bool
    health: dict | None
    parser_checkpoint: dict | None
    parser_failure: dict | None
    parser_diagnostics: list[dict]
    last_processed_entity_tick: int | None
    last_acknowledged_entity_tick: int | None
    full_update_requests: int
    baseline_ack_count: int
    net_message_counts: dict
    full_sent: bool


def build_attempt_health(
    inputs: HealthInputs,
    *,
    parser_identity: dict,
    parser_backlog: dict,
    parser_checkpoint: dict | None,
    parser_throttled: bool,
    writer_status: dict,
    staging_backlog: dict,
    now: int,
    force: bool = False,
) -> dict | None:
    elapsed = now - inputs.last_health_ns
    if not force and elapsed < HEALTH_INTERVAL_NS:
        return None
    checkpoint = parser_checkpoint or {}
    output = dict(writer_status)
    delivered = output["lastDeliveredCursor"]
    if delivered and delivered["world"] != parser_identity["world"]:
        delivered = None
    output["lastDeliveredCursor"] = delivered
    sdk_sample_ns = inputs.sdk_sample_ns
    sdk_recent = sdk_sample_ns is not None and now - sdk_sample_ns < HEALTH_INTERVAL_NS
    ages = (
        inputs.window_sdk_age_us,
        staging_backlog["oldestAgeUs"],
        parser_backlog["oldestAgeUs"],
        output["oldestAgeUs"],
    )
    state, reason = "unknown", "awaiting-continuous-cursor"
    if inputs.health_reason:
        state, reason = "overloaded", inputs.health_reason
    elif inputs.done or inputs.reason or inputs.gap or inputs.recovery_pending:
        state, reason = "discontinuity", inputs.reason or "world-or-snapshot-gap"
    elif inputs.draining:
        reason = "source-draining"
    elif not inputs.full_sent:
        reason = "initializing"
    elif (
        any(age is not None and age >= SOFT_AGE_US for age in ages) or parser_throttled
    ):
        state, reason = "catching-up", "local-backlog"
    elif not sdk_recent or inputs.last_sdk_age_us is None:
        reason = "sdk-receive-age-unavailable"
    elif (
        delivered
        and inputs.last_cursor
        and delivered["sequence"] == inputs.last_cursor[4]
        and inputs.cursor_rate is not None
        and now - inputs.last_cursor[2] <= 2_500_000_000
    ):
        state, reason = "live", "local-ordered-progress"
    window = dict(
        zip(
            (
                "receivedMessages",
                "receivedBytes",
                "processedMessages",
                "processedBytes",
                "workerDecodeUs",
            ),
            (new - old for new, old in zip(inputs.totals, inputs.last_health_totals)),
        )
    )
    window["durationUs"] = elapsed // 1000 if inputs.last_health_ns else None
    return dict(
        type="cs2-observer-health/1",
        **parser_identity,
        state=state,
        reason=reason,
        upstreamFreshness="unknown",
        window=window,
        sdkQueueAgeUs=inputs.last_sdk_age_us if sdk_recent else None,
        sdkWindowMaxAgeUs=inputs.window_sdk_age_us,
        sdkMaxAgeUs=inputs.max_sdk_age_us,
        receiveStaging=staging_backlog,
        parser={**parser_backlog, "maxAgeUs": inputs.max_parser_age_us},
        output=output,
        receiveBudgetExhausted=inputs.receive_budget_exhausted,
        resultBudgetExhausted=inputs.result_budget_exhausted,
        contextTick=checkpoint.get("tick"),
        networkTick=checkpoint.get("networkTick"),
        committedTick=checkpoint.get("committedTick"),
        committedTicksPerSecond=inputs.cursor_rate if state == "live" else None,
    )


def build_attempt_report(inputs: ReportInputs) -> dict:
    return {
        "phase": inputs.phase,
        "reason": inputs.reason,
        "received_messages": inputs.received_messages,
        "host_version": inputs.host_version,
        "native_state": inputs.native_state,
        "native_failure": inputs.native_failure,
        "remote_end_reason": inputs.remote_end_reason,
        "world_creation_watermark": inputs.world_creation_watermark,
        "world_creation_sequences": inputs.world_creation_sequences,
        "challenge_metadata": inputs.challenge_metadata,
        "challenge_requests": inputs.challenge_requests,
        "outgoing_channel_feedback_frames": inputs.feedback_sent,
        "last_received_channel_sequence": inputs.last_received_channel_sequence,
        "channel_frames": inputs.channel_frames,
        "channel_bytes": inputs.channel_bytes,
        "channel_receive_span_ms": inputs.channel_receive_span_ms,
        "received_signon_state": inputs.received_signon_state,
        "effective_signon_state": inputs.effective_signon_state,
        "full_snapshot_processed": inputs.full_snapshot_processed,
        "stages": inputs.stages,
        "reachedFull": inputs.ever_full,
        "lastProcessedSequence": inputs.last_processed_sequence,
        "lastOutputSequence": inputs.last_output_sequence,
        "drainCompleted": inputs.drain_completed,
        "health": inputs.health,
        "parser_checkpoint": inputs.parser_checkpoint,
        "parser_failure": inputs.parser_failure,
        "parserDiagnostics": inputs.parser_diagnostics,
        "last_processed_entity_tick": inputs.last_processed_entity_tick,
        "last_acknowledged_entity_tick": inputs.last_acknowledged_entity_tick,
        "full_update_requests": inputs.full_update_requests,
        "baseline_ack_count": inputs.baseline_ack_count,
        "net_message_counts": inputs.net_message_counts,
        "initialization_blockers": (
            [] if inputs.full_sent else [inputs.reason or "signon-in-progress"]
        ),
    }
