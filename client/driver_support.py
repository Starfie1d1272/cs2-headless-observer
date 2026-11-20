"""CLI parsing, AttemptResult contract, health snapshots, and report assembly."""

import argparse
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from process_io import HEALTH_INTERVAL_NS, SOFT_AGE_US

ATTEMPT_RESULT_SCHEMA = "cs2-observer-attempt-result/1"
# SteamNetworkingSockets end reasons Remote_Timeout and Misc_Timeout.
TRANSPORT_TIMEOUT_CODES = frozenset({4001, 5003})
TRANSIENT_FAILURE_CODES = frozenset(
    {
        "sdk-receive-overload",
        "receive-staging-overload",
        "parser-residence-overload",
        "source-residence-overload",
        "ordered-parser-input-backpressure",
        "initialization-timeout",
        "native-receive-failed",
        "native-send-failed",
        "ordered-parser-exited",
        "ordered-parser-not-running",
    }
)
VALID_ATTEMPT_CATEGORIES = frozenset(
    {
        "clean-source-stop",
        "source-unavailable",
        "transient-fault",
        "permanent-fault",
        "owner-stopped",
        "duration-limit",
        "cleanup-failed",
        "invalid-completion",
    }
)


@dataclass(frozen=True)
class AttemptResult:
    schema: str
    category: str
    outcome: str
    phase: str | None
    native_state: int | None
    native_failure: int | None
    remote_end_reason: int | None
    reached_full: bool
    drain_completed: bool
    cleanup_completed: bool
    report_written: bool
    last_output_sequence: int
    valid_completion: bool

    @classmethod
    def synthetic(
        cls,
        category,
        *,
        outcome="failed",
        phase=None,
        native_state=None,
        native_failure=None,
        remote_end_reason=None,
        reached_full=False,
        drain_completed=False,
        cleanup_completed=True,
        report_written=False,
        last_output_sequence=0,
        valid_completion=False,
    ):
        return cls(
            schema=ATTEMPT_RESULT_SCHEMA,
            category=category,
            outcome=outcome,
            phase=phase,
            native_state=native_state,
            native_failure=native_failure,
            remote_end_reason=remote_end_reason,
            reached_full=reached_full,
            drain_completed=drain_completed,
            cleanup_completed=cleanup_completed,
            report_written=report_written,
            last_output_sequence=last_output_sequence,
            valid_completion=valid_completion,
        )

    def to_dict(self):
        return {
            "schema": self.schema,
            "category": self.category,
            "outcome": self.outcome,
            "phase": self.phase,
            "nativeState": self.native_state,
            "nativeFailure": self.native_failure,
            "remoteEndReason": self.remote_end_reason,
            "reachedFull": self.reached_full,
            "drainCompleted": self.drain_completed,
            "cleanupCompleted": self.cleanup_completed,
            "reportWritten": self.report_written,
            "lastOutputSequence": self.last_output_sequence,
            "validCompletion": self.valid_completion,
        }


def _is_transient_failure_code(code, report):
    if code in TRANSIENT_FAILURE_CODES:
        return True
    if code == "phase-timeout":
        # A silent response after sending credentials is ambiguous. Do not retry it.
        return report.get("phase") in ("transport", "challenge", "channel")
    if code == "native-session-closed":
        remote = report.get("remote_end_reason")
        if remote == 1038:
            return False
        if report.get("phase") in ("connection", "ticket"):
            return (
                report.get("native_failure") == 7
                and isinstance(remote, int)
                and 3000 <= remote < 6000
            )
        return report.get("native_failure") in (3, 6, 7)
    if isinstance(code, str):
        stage, _, error = code.partition(": ")
        return stage in (
            "ordered-parser-input-failed",
            "ordered-parser-output-failed",
        ) and error in ("OSError", "BrokenPipeError", "ConnectionResetError")
    return False


def _is_source_unavailable(code, report):
    if (
        report.get("phase") != "transport"
        or report.get("outcome") != "failed"
        or report.get("cleanupCompleted") is not True
    ):
        return False
    if code == "phase-timeout":
        # State 2 means GNS is connecting. State 1 is still local authentication.
        return report.get("native_state") == 2
    if code != "native-session-closed":
        return False
    if report.get("native_failure") == 6:
        return any(
            stage.get("stage") == "sdk-state" and stage.get("value") == 2
            for stage in report.get("stages", ())
        )
    return (
        report.get("native_failure") == 7
        and report.get("remote_end_reason") in TRANSPORT_TIMEOUT_CODES
    )


def classify_attempt_result(report, *, failure_code=None, owner_stopped=False):
    outcome = report.get("outcome", "failed")
    cleanup = report.get("cleanupCompleted") is True
    reached_full = report.get("reachedFull") is True
    drain_completed = report.get("drainCompleted") is True
    report_written = report.get("reportWritten") is True
    phase = report.get("phase")
    native_state = report.get("native_state")
    native_failure = report.get("native_failure")
    remote_end_reason = report.get("remote_end_reason")
    last_seq = report.get("lastOutputSequence", 0)
    if not cleanup:
        category = "cleanup-failed"
    elif (
        outcome == "closed"
        and reached_full
        and drain_completed
        and phase == "closed"
        and remote_end_reason == 1038
    ):
        category = "clean-source-stop"
    elif outcome == "incomplete":
        category = "owner-stopped" if owner_stopped else "duration-limit"
    elif _is_source_unavailable(failure_code, report):
        category = "source-unavailable"
    elif _is_transient_failure_code(failure_code, report):
        category = "transient-fault"
    else:
        category = "permanent-fault"
    return AttemptResult(
        schema=ATTEMPT_RESULT_SCHEMA,
        category=category,
        outcome=outcome,
        phase=phase,
        native_state=native_state if type(native_state) is int else None,
        native_failure=native_failure if type(native_failure) is int else None,
        remote_end_reason=remote_end_reason if type(remote_end_reason) is int else None,
        reached_full=reached_full,
        drain_completed=drain_completed,
        cleanup_completed=cleanup,
        report_written=report_written,
        last_output_sequence=last_seq if type(last_seq) is int else 0,
        valid_completion=category == "clean-source-stop",
    )


def parse_attempt_result(
    report,
    *,
    exit_code=None,
    forced_kill=False,
    terminal_seen=False,
    expected_sequence=1,
    bad_line=None,
):
    """Validate versioned AttemptResult from child report; fail closed on missing/invalid facts."""
    if forced_kill or (
        isinstance(report, dict) and report.get("cleanupCompleted") is False
    ):
        return AttemptResult(
            schema=ATTEMPT_RESULT_SCHEMA,
            category="cleanup-failed",
            outcome="failed",
            phase=report.get("phase") if isinstance(report, dict) else None,
            native_state=None,
            native_failure=report.get("native_failure")
            if isinstance(report, dict)
            else None,
            remote_end_reason=report.get("remote_end_reason")
            if isinstance(report, dict)
            else None,
            reached_full=False,
            drain_completed=False,
            cleanup_completed=False,
            report_written=bool(
                isinstance(report, dict) and report.get("reportWritten") is True
            ),
            last_output_sequence=0,
            valid_completion=False,
        )
    raw = report.get("attemptResult") if isinstance(report, dict) else None
    if (
        not isinstance(raw, dict)
        or raw.get("schema") != ATTEMPT_RESULT_SCHEMA
        or type(raw.get("category")) is not str
        or raw.get("category") not in VALID_ATTEMPT_CATEGORIES
        or type(raw.get("outcome")) is not str
        or raw.get("outcome") not in ("closed", "failed", "incomplete")
        or type(raw.get("cleanupCompleted")) is not bool
        or type(raw.get("reportWritten")) is not bool
        or type(raw.get("reachedFull")) is not bool
        or type(raw.get("drainCompleted")) is not bool
        or type(raw.get("lastOutputSequence")) is not int
        or raw.get("lastOutputSequence") < 0
        or type(raw.get("validCompletion")) is not bool
    ):
        category = (
            "transient-fault"
            if exit_code not in (None, 0, 2) and not report
            else "invalid-completion"
        )
        return AttemptResult(
            schema=ATTEMPT_RESULT_SCHEMA,
            category=category,
            outcome="failed",
            phase=None,
            native_state=None,
            native_failure=None,
            remote_end_reason=None,
            reached_full=False,
            drain_completed=False,
            cleanup_completed=True,
            report_written=False,
            last_output_sequence=0,
            valid_completion=False,
        )
    category = raw["category"]
    valid_clean = (
        exit_code == 0
        and terminal_seen
        and bad_line is None
        and category == "clean-source-stop"
        and report.get("schema") == "cs2-observer-report/1"
        and raw.get("outcome") == "closed"
        and raw.get("phase") == "closed"
        and raw.get("remoteEndReason") == 1038
        and raw.get("lastOutputSequence") == expected_sequence - 1
        and raw.get("reportWritten") is True
        and raw.get("reachedFull") is True
        and raw.get("drainCompleted") is True
        and raw.get("cleanupCompleted") is True
        and raw.get("validCompletion") is True
    )
    outer_mismatch = any(
        key in report and report.get(key) != raw.get(key)
        for key in (
            "outcome",
            "phase",
            "reachedFull",
            "drainCompleted",
            "cleanupCompleted",
            "reportWritten",
            "lastOutputSequence",
        )
    )
    contradictory = (
        outer_mismatch
        or (
            category == "clean-source-stop"
            and (
                raw.get("outcome") != "closed"
                or raw.get("phase") != "closed"
                or raw.get("remoteEndReason") != 1038
                or not raw["reachedFull"]
                or not raw["drainCompleted"]
                or not raw["reportWritten"]
                or not raw["cleanupCompleted"]
                or raw["validCompletion"] is not True
            )
        )
        or (raw.get("outcome") == "closed" and category != "clean-source-stop")
        or (
            raw.get("outcome") == "incomplete"
            and category not in ("owner-stopped", "duration-limit")
        )
        or (
            category in ("owner-stopped", "duration-limit")
            and raw.get("outcome") != "incomplete"
        )
        or (
            category in ("transient-fault", "permanent-fault", "source-unavailable")
            and raw.get("outcome") != "failed"
        )
        or (
            category == "source-unavailable"
            and (raw.get("phase") != "transport" or not raw["cleanupCompleted"])
        )
        or (category == "cleanup-failed" and raw["cleanupCompleted"])
        or (raw["validCompletion"] is True and category != "clean-source-stop")
    )
    if contradictory or (exit_code == 0 and not valid_clean):
        category = "invalid-completion"
    elif exit_code not in (None, 0) and (
        raw.get("outcome") == "closed" or category == "clean-source-stop"
    ):
        category = "invalid-completion"
    elif not raw["cleanupCompleted"]:
        category = "cleanup-failed"
    return AttemptResult(
        schema=ATTEMPT_RESULT_SCHEMA,
        category=category,
        outcome=str(raw.get("outcome", "failed")),
        phase=raw.get("phase") if isinstance(raw.get("phase"), str) else None,
        native_state=raw.get("nativeState")
        if type(raw.get("nativeState")) is int
        else None,
        native_failure=raw.get("nativeFailure")
        if type(raw.get("nativeFailure")) is int
        else None,
        remote_end_reason=raw.get("remoteEndReason")
        if type(raw.get("remoteEndReason")) is int
        else None,
        reached_full=raw["reachedFull"],
        drain_completed=raw["drainCompleted"],
        cleanup_completed=raw["cleanupCompleted"],
        report_written=raw["reportWritten"],
        last_output_sequence=raw["lastOutputSequence"],
        valid_completion=valid_clean
        and not contradictory
        and category == "clean-source-stop",
    )


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
    snap = driver.health_snapshot_inputs()
    elapsed = now - snap["last_health_ns"]
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
    sdk_sample_ns = snap["sdk_sample_ns"]
    sdk_recent = sdk_sample_ns is not None and now - sdk_sample_ns < HEALTH_INTERVAL_NS
    receive_backlog = getattr(driver.port, "receive_backlog", None)
    staging = receive_backlog(now) if receive_backlog else {"oldestAgeUs": None}
    ages = (
        snap["window_sdk_age_us"],
        staging["oldestAgeUs"],
        backlog["oldestAgeUs"],
        output["oldestAgeUs"],
    )
    state, reason = "unknown", "awaiting-continuous-cursor"
    if snap["health_reason"]:
        state, reason = "overloaded", snap["health_reason"]
    elif driver.done or driver.reason or snap["gap"] or snap["recovery_pending"]:
        state, reason = "discontinuity", driver.reason or "world-or-snapshot-gap"
    elif snap["draining"]:
        reason = "source-draining"
    elif not snap["full_sent"]:
        reason = "initializing"
    elif any(age is not None and age >= SOFT_AGE_US for age in ages) or getattr(
        parser, "throttled", False
    ):
        state, reason = "catching-up", "local-backlog"
    elif not sdk_recent or snap["last_sdk_age_us"] is None:
        reason = "sdk-receive-age-unavailable"
    elif (
        delivered
        and snap["last_cursor"]
        and delivered["sequence"] == snap["last_cursor"][4]
        and snap["cursor_rate"] is not None
        and now - snap["last_cursor"][2] <= 2_500_000_000
    ):
        state, reason = "live", "local-ordered-progress"
    totals = snap["totals"]
    window = dict(
        zip(
            (
                "receivedMessages",
                "receivedBytes",
                "processedMessages",
                "processedBytes",
                "workerDecodeUs",
            ),
            (new - old for new, old in zip(totals, snap["last_health_totals"])),
        )
    )
    window["durationUs"] = elapsed // 1000 if snap["last_health_ns"] else None
    health = dict(
        type="cs2-observer-health/1",
        **parser.identity,
        state=state,
        reason=reason,
        upstreamFreshness="unknown",
        window=window,
        sdkQueueAgeUs=snap["last_sdk_age_us"] if sdk_recent else None,
        sdkWindowMaxAgeUs=snap["window_sdk_age_us"],
        sdkMaxAgeUs=snap["max_sdk_age_us"],
        receiveStaging=staging,
        parser={**backlog, "maxAgeUs": snap["max_parser_age_us"]},
        output=output,
        receiveBudgetExhausted=snap["receive_budget_exhausted"],
        resultBudgetExhausted=snap["result_budget_exhausted"],
        contextTick=checkpoint.get("tick"),
        networkTick=checkpoint.get("networkTick"),
        committedTick=checkpoint.get("committedTick"),
        committedTicksPerSecond=snap["cursor_rate"] if state == "live" else None,
    )
    if not force:
        driver.record_health_window(totals, now)
    return health


def build_attempt_report(driver):
    snap = driver.report_snapshot()
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
        "challenge_requests": snap["challenge_requests"],
        "outgoing_channel_feedback_frames": snap["feedback_sent"],
        "last_received_channel_sequence": driver.feedback.received,
        "channel_frames": driver.channel_frames,
        "channel_bytes": driver.channel_bytes,
        "channel_receive_span_ms": span,
        "received_signon_state": driver.signon.received_state,
        "effective_signon_state": driver.signon.state,
        "full_snapshot_processed": snap["full_snapshot_processed"],
        "stages": list(driver.stages),
        "reachedFull": snap["ever_full"],
        "lastProcessedSequence": driver.parser.completed_sequence
        if driver.parser
        else 0,
        "lastOutputSequence": driver.emit.sequence,
        "drainCompleted": driver.drain_completed,
        "health": driver.health,
        "parser_checkpoint": driver.parser.checkpoint if driver.parser else None,
        "parser_failure": getattr(driver.parser, "failure_details", None),
        "parserDiagnostics": list(getattr(driver.parser, "diagnostics", [])),
        "last_processed_entity_tick": snap["processed_entity_tick"],
        "last_acknowledged_entity_tick": snap["ack_tick"],
        "full_update_requests": snap["recovery_requests"],
        "baseline_ack_count": snap["baseline_ack_count"],
        "net_message_counts": driver.decoder.counts,
        "initialization_blockers": (
            [] if snap["full_sent"] else [driver.reason or "signon-in-progress"]
        ),
    }
