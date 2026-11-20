"""Shared AttemptResult contract, failure classification, and fail-closed parser."""

from dataclasses import dataclass

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


def _is_transient_failure_code(code, report, *, failure_transient=False):
    if failure_transient:
        return True
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


def classify_attempt_result(
    report,
    *,
    failure_code=None,
    failure_transient=False,
    owner_stopped=False,
):
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
    elif _is_transient_failure_code(
        failure_code, report, failure_transient=failure_transient
    ):
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
        return AttemptResult.synthetic(
            "cleanup-failed",
            phase=report.get("phase") if isinstance(report, dict) else None,
            native_failure=report.get("native_failure")
            if isinstance(report, dict)
            else None,
            remote_end_reason=report.get("remote_end_reason")
            if isinstance(report, dict)
            else None,
            cleanup_completed=False,
            report_written=bool(
                isinstance(report, dict) and report.get("reportWritten") is True
            ),
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
        return AttemptResult.synthetic(category)
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
