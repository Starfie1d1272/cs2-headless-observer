"""CLI argument parsing, single-attempt runner, and terminal report finalization."""

import argparse
import getpass
import json
from pathlib import Path
import struct
import sys
from uuid import UUID, uuid4

from attempt_contract import classify_attempt_result
from driver import DriverError, Duty, ObserverDriver, clock_ms
from host_version import discover_host, host_version
from node_runtime import inspect_node
from ordered_parser_bridge import OrderedParserBridge
from process_io import (
    DRAIN_TIMEOUT_MS,
    HARD_AGE_US,
    MAGIC,
    CaptureBudget,
    CaptureWriter,
    ManagedOwner,
    OutputWriter,
    connection_values,
    emit_terminal_report,
    private_file,
    read_managed_connection,
    write_report_file,
)
import sdk
from wire import ProbeError


def parse_driver_args(argv=None, *, doc=None):
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


def run_attempt(args, owner, endpoint, password):
    driver = native = parser = samples = events = writer = diagnostics = capture = None
    budget = CaptureBudget(args.capture_budget_mib * 1024**2)
    report, failure_code, failure_transient, finalization = (
        {
            "schema": "cs2-observer-report/1",
            "reachedFull": False,
            "drainCompleted": False,
            "lastProcessedSequence": 0,
        },
        None,
        False,
        [],
    )

    try:
        writer = OutputWriter(sys.stdout.fileno(), age_limit_us=HARD_AGE_US)
        diagnostics = OutputWriter(sys.stderr.fileno(), max_records=1, max_bytes=65536)
        if args.capture:
            events = private_file(args.output / "events.jsonl", "wb")
            samples = private_file(args.output / "channel.frames", "wb")
            capture = CaptureWriter(budget)
            capture.emit(samples, MAGIC)
        parser = OrderedParserBridge(
            source=args.source_role + ":" + (args.source_id or uuid4().hex),
            channel=1,
            world=1,
            node=args.node,
            worker=args.parser_worker,
        )
        if owner.is_set():
            raise KeyboardInterrupt()
        native = sdk.NativePort(
            args.native, endpoint, clock_ms(), steam_api=args.steam_api
        )
        del endpoint

        def emit_event(event, data):
            cursor = (
                {key: event[key] for key in ("world", "committedTick", "sequence")}
                if event["kind"] == "cursor"
                else None
            )
            if driver._drain_deadline is not None:
                writer.age_limit_us = DRAIN_TIMEOUT_MS * 1000
            writer.emit_encoded(data, cursor=cursor, sequence=event["sequence"])
            if capture:
                capture.emit(events, data)

        def capture_sample(data, reliable, elapsed_ms):
            if not budget.truncated:
                capture.emit(
                    samples,
                    struct.pack("<IQB", len(data), elapsed_ms, int(reliable)) + data,
                )

        driver = ObserverDriver(
            native,
            host_version=args.host_version,
            password=password,
            emit=emit_event,
            encoded_output=True,
            supervised=args.session_attempt,
            capture=capture_sample if capture else None,
            now_ms=clock_ms(),
            parser=parser,
        )
        stop = clock_ms() + args.seconds * 1000 if args.seconds else None
        idle_ms = 1
        while (
            not driver.done
            and (stop is None or clock_ms() < stop)
            and not owner.is_set()
        ):
            writer.check()
            result = driver.step(clock_ms(), clock=clock_ms, cancelled=owner.is_set)
            health = driver.update_health(writer)
            if health is not None:
                try:
                    diagnostics.emit(health)
                except ProbeError:
                    pass  # A stalled diagnostics reader never gates game records.
            if result.received or result.results:
                idle_ms = 1
            if result.duty is Duty.BUDGET:
                continue
            if result.duty is Duty.STOPPED:
                break
            parser.wait_for_progress(driver.wait_timeout(clock_ms(), idle_ms, stop))
            idle_ms = min(8, idle_ms * 2)
        if not driver.done:
            driver.reason = (
                "owner-stopped" if owner.is_set() else "duration-limit-incomplete"
            )
        driver.update_health(writer, force=True)
        report.update(driver.report())
    except BaseException as error:
        if isinstance(error, KeyboardInterrupt):
            owner.stopped.set()
            report["reason"] = "owner-stopped"
        else:
            if isinstance(error, sdk.NativeStartError):
                failure_code = "native-start-failed"
                reason_text = failure_code
                report["native_boot_code"], report["steam_init_result"] = (
                    error.boot_code,
                    error.init_result,
                )
            elif isinstance(error, ProbeError):
                failure_code = error.code
                failure_transient = error.transient
                reason_text = str(error)
            elif isinstance(error, DriverError):
                failure_code = error.code
                reason_text = str(error)
            else:
                failure_code = "operation-failed-details-omitted"
                reason_text = failure_code
            report["reason"] = reason_text
        if driver is not None:
            driver.reason = report["reason"]
            if failure_code and (
                failure_code.endswith("-overload")
                or failure_code
                in (
                    "output-backpressure",
                    "output-closed",
                    "ordered-parser-input-backpressure",
                )
            ):
                driver._health_reason = failure_code
            driver.update_health(writer, force=True)
            report.update(driver.report())
    finally:
        owner_stopped = owner.is_set()
        password[:] = bytes(len(password))
        # Retire public delivery before joining parser pipes on owner cancellation.
        # Normal source completion still flushes the accepted final records below.
        output_closed = (
            writer.abort() if writer and (failure_code or owner_stopped) else None
        )
        for stage, action in [
            (
                "close-session",
                driver.close if driver else native.close if native else None,
            ),
            ("close-parser", parser.close if parser else None),
            ("close-capture", capture.finish if capture else None),
        ]:
            if action:
                try:
                    action()
                except BaseException:
                    finalization.append(stage)
        if not capture or not capture.thread.is_alive():
            for handle in (events, samples):
                if handle:
                    try:
                        handle.close()
                    except OSError:
                        budget.truncated = True
                        finalization.append("close-capture-file")
        if writer:
            completed = output_closed if output_closed is not None else writer.finish()
            if not completed:
                finalization.append("close-output")
                if driver and not failure_code and not owner_stopped:
                    failure_code = writer.failure or "output-drain-timeout"
                    driver.reason = driver._health_reason = failure_code
            if driver:
                driver.update_health(writer, force=True)
                report["health"] = driver.health
                report["reason"] = driver.reason
        if not owner.close():
            finalization.append("close-input")
        report.update(
            finalization_failures=finalization,
            cleanupCompleted=not finalization,
            capture={
                "enabled": args.capture,
                "bytes": budget.written,
                "budget": budget.maximum,
                "truncated": budget.truncated,
            },
        )
        report["outcome"] = (
            "failed"
            if failure_code or finalization
            else "closed"
            if driver is not None
            and driver.phase == "closed"
            and driver.drain_completed
            else "incomplete"
        )
        report["reportWritten"] = True
        report["attemptResult"] = classify_attempt_result(
            report,
            failure_code=failure_code,
            failure_transient=failure_transient,
            owner_stopped=owner_stopped,
        ).to_dict()
        if len(json.dumps(report).encode()) > 30000:
            report["stages"] = report.get("stages", [])[-32:]
            report["net_message_counts"] = dict(
                list(report.get("net_message_counts", {}).items())[:128]
            )
            report["diagnosticTruncated"] = True
        try:
            write_report_file(args.output, report)
        except BaseException:
            report["reportWritten"] = False
            finalization.append("write-report")
            report.update(outcome="failed", cleanupCompleted=False)
            report["attemptResult"] = classify_attempt_result(
                report,
                failure_code=failure_code or "write-report",
                failure_transient=failure_transient,
                owner_stopped=owner_stopped,
            ).to_dict()
        emit_terminal_report(diagnostics, report)
    return (
        1
        if report["outcome"] == "failed"
        else 0
        if report["outcome"] == "closed"
        else 2
    )


def main(*, doc=None):
    args = parse_driver_args(doc=doc or __doc__)

    inspect_node(args.node)
    private_stdin = args.managed or args.session_attempt
    if private_stdin:
        try:
            stdin_fd = sys.stdin.fileno()
        except (OSError, ValueError, AttributeError):
            owner = ManagedOwner(
                stream=sys.stdin.buffer, configuration_reader=read_managed_connection
            )
        else:
            owner = ManagedOwner(
                fd=stdin_fd, configuration_reader=read_managed_connection
            )
    else:
        owner = ManagedOwner()
    password = bytearray()
    try:
        if private_stdin:
            endpoint, password = owner.configuration()
        else:
            endpoint, password = connection_values(
                getpass.getpass("Authorized GOTV numeric IP:port: "),
                getpass.getpass("Ordinary spectator password: "),
            )
    except ValueError:
        owner.close()
        raise SystemExit("configuration-boundary") from None
    try:
        args.output.mkdir(mode=0o700)
    except OSError:
        password[:] = bytes(len(password))
        owner.close()
        raise SystemExit("output-directory-unavailable") from None
    try:
        if args.managed:
            from session_supervisor import run

            args.source_id = args.source_id or uuid4().hex
            return run(args, owner, endpoint, password)
        return run_attempt(args, owner, endpoint, password)
    finally:
        password[:] = bytes(len(password))
        owner.close()
