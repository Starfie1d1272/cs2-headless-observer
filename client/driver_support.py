"""CLI parsing, health snapshots, and report assembly for single-attempt driver."""

import argparse
from pathlib import Path
from uuid import UUID

from process_io import HEALTH_INTERVAL_NS, SOFT_AGE_US


def parse_driver_args(argv=None, *, doc=None):
    from host_version import discover_host, host_version

    def positive(value):
        result = int(value)
        if result < 1:
            raise ValueError("positive-integer-required")
        return result

    ap = argparse.ArgumentParser(description=doc)
    ap.add_argument("--native", type=Path, required=True)
    ap.add_argument("--steam-api", type=Path)
    ap.add_argument("--node", default="node")
    ap.add_argument(
        "--parser-worker",
        type=Path,
        default=Path(__file__).with_name("parser_worker.mjs"),
    )
    ap.add_argument("--source-role", choices=("ahead", "delayed"), default="ahead")
    ap.add_argument("--source-id", type=lambda value: UUID(value).hex)
    ap.add_argument("--managed", action="store_true")
    ap.add_argument(
        "--managed-protocol",
        help="Managed JSON contract (only 2 is supported; 1 is retired)",
    )
    ap.add_argument("--session-attempt", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument(
        "--follow-source",
        action="store_true",
        help="Managed v2 only: wait and reconnect to the same source after normal completion",
    )
    ap.add_argument(
        "--host-version",
        type=host_version,
        help="Actual source host; otherwise suggest from local steam.inf",
    )
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument(
        "--seconds",
        type=positive,
        help="Total diagnostic duration, including managed v2 retries and waits",
    )
    ap.add_argument(
        "--capture",
        action="store_true",
        help="Opt in to private raw/event capture; unavailable in managed mode",
    )
    ap.add_argument("--capture-budget-mib", type=positive, default=256)
    args = ap.parse_args(argv)
    if args.session_attempt:
        if (
            args.managed
            or args.managed_protocol is not None
            or args.follow_source
            or args.capture
        ):
            ap.error("Invalid internal session attempt")
    else:
        if args.managed_protocol == "1":
            ap.error(
                "Managed protocol 1 has been retired; migrate to managed protocol 2 (--managed)"
            )
        if not args.managed and args.managed_protocol is not None:
            ap.error("Managed protocol selection requires --managed")
        if args.managed_protocol not in (None, "2"):
            ap.error("Unsupported --managed-protocol (expected 2)")
        if args.follow_source and not args.managed:
            ap.error("--follow-source requires --managed")
        if args.managed and args.capture:
            ap.error("Managed mode never captures raw traffic or event files")
    if args.host_version is None:
        try:
            args.host_version = discover_host(
                args.steam_api.resolve().parents[2] / "csgo/steam.inf"
            )
        except (ValueError, OSError, AttributeError, IndexError):
            ap.error(
                "Supply the actual source --host-version; local version discovery unavailable"
            )
    return args


def build_attempt_health(driver, writer, now, *, force=False):
    elapsed = now - driver._last_health_ns
    if not force and elapsed < HEALTH_INTERVAL_NS:
        return None
    parser = driver.parser
    output = writer.status()
    backlog = parser.backlog(now)
    checkpoint = parser.checkpoint or {}
    delivered = output["lastDeliveredCursor"]
    if delivered and delivered["world"] != parser.identity["world"]:
        delivered = None
    output["lastDeliveredCursor"] = delivered
    sdk_recent = (
        driver._sdk_sample_ns is not None
        and now - driver._sdk_sample_ns < HEALTH_INTERVAL_NS
    )
    receive_backlog = getattr(driver.port, "receive_backlog", None)
    staging = receive_backlog(now) if receive_backlog else {"oldestAgeUs": None}
    ages = (
        driver._window_sdk_age_us,
        staging["oldestAgeUs"],
        backlog["oldestAgeUs"],
        output["oldestAgeUs"],
    )
    state, reason = "unknown", "awaiting-continuous-cursor"
    if driver._health_reason:
        state, reason = "overloaded", driver._health_reason
    elif driver.done or driver.reason or driver._gap or driver._recovery_pending:
        state, reason = "discontinuity", driver.reason or "world-or-snapshot-gap"
    elif driver._drain_deadline is not None:
        reason = "source-draining"
    elif not driver._full_sent:
        reason = "initializing"
    elif (
        any(age is not None and age >= SOFT_AGE_US for age in ages)
        or not parser.has_credit()
    ):
        state, reason = "catching-up", "local-backlog"
    elif not sdk_recent or driver._last_sdk_age_us is None:
        reason = "sdk-receive-age-unavailable"
    elif (
        delivered
        and driver._last_cursor
        and delivered["sequence"] == driver._last_cursor[4]
        and driver._cursor_rate is not None
        and now - driver._last_cursor[2] <= 2_500_000_000
    ):
        state, reason = "live", "local-ordered-progress"
    totals = (
        driver.received,
        driver._received_bytes,
        parser.processed_messages,
        parser.processed_bytes,
        parser.decode_us,
    )
    window = dict(
        zip(
            (
                "receivedMessages",
                "receivedBytes",
                "processedMessages",
                "processedBytes",
                "workerDecodeUs",
            ),
            (new - old for new, old in zip(totals, driver._last_health_totals)),
        )
    )
    window["durationUs"] = elapsed // 1000 if driver._last_health_ns else None
    health = dict(
        type="cs2-observer-health/1",
        **parser.identity,
        state=state,
        reason=reason,
        upstreamFreshness="unknown",
        window=window,
        sdkQueueAgeUs=driver._last_sdk_age_us if sdk_recent else None,
        sdkWindowMaxAgeUs=driver._window_sdk_age_us,
        sdkMaxAgeUs=driver._max_sdk_age_us,
        receiveStaging=staging,
        parser={**backlog, "maxAgeUs": driver._max_parser_age_us},
        output=output,
        receiveBudgetExhausted=driver._receive_budget_exhausted,
        resultBudgetExhausted=driver._result_budget_exhausted,
        contextTick=checkpoint.get("tick"),
        networkTick=checkpoint.get("networkTick"),
        committedTick=checkpoint.get("committedTick"),
        committedTicksPerSecond=driver._cursor_rate if state == "live" else None,
    )
    if not force:
        driver._last_health_totals = totals
        driver._last_health_ns = now
        driver._window_sdk_age_us = None
    return health


def build_attempt_report(driver):
    span = (
        None
        if driver.first_channel_ms is None
        else driver.last_channel_ms - driver.first_channel_ms
    )
    return {
        "phase": driver.phase,
        "reason": driver.reason,
        "received_messages": driver.received,
        "host_version": driver.host_version,
        "native_state": driver.port.state,
        "native_failure": getattr(driver.port, "failure", None),
        "remote_end_reason": getattr(driver.port, "remote_end_reason", None),
        "world_creation_watermark": driver.decoder.max_creation_sequence,
        "world_creation_sequences": sorted(
            group["creation_sequence"] or 0
            for group in driver.decoder.spawn_groups.values()
        ),
        "challenge_metadata": driver.challenge_metadata,
        "challenge_requests": driver._challenge_requests,
        "outgoing_channel_feedback_frames": driver._feedback_sent,
        "last_received_channel_sequence": driver.feedback.received,
        "channel_frames": driver.channel_frames,
        "channel_bytes": driver.channel_bytes,
        "channel_receive_span_ms": span,
        "received_signon_state": driver.signon.received_state,
        "effective_signon_state": driver.signon.state,
        "full_snapshot_processed": driver._full_snapshot_processed,
        "stages": list(driver.stages),
        "reachedFull": driver._ever_full,
        "lastProcessedSequence": driver.parser.completed_sequence
        if driver.parser
        else 0,
        "lastOutputSequence": driver.emit.sequence,
        "drainCompleted": driver.drain_completed,
        "health": driver.health,
        "parser_checkpoint": driver.parser.checkpoint if driver.parser else None,
        "parser_failure": getattr(driver.parser, "failure_details", None),
        "parserDiagnostics": list(getattr(driver.parser, "diagnostics", [])),
        "last_processed_entity_tick": driver._processed_entity_tick,
        "last_acknowledged_entity_tick": driver._ack_tick,
        "full_update_requests": driver._recovery_requests,
        "baseline_ack_count": driver._baseline_ack_count,
        "net_message_counts": driver.decoder.counts,
        "initialization_blockers": (
            [] if driver._full_sent else [driver.reason or "signon-in-progress"]
        ),
    }
