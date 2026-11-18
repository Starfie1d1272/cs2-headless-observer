"""Managed v2 lifecycle owner. Each attempt runs the existing one-shot driver."""

from collections import deque
import io
import json
import os
from pathlib import Path
import queue
import random
import signal
import subprocess
import sys
import tempfile
import threading
import time

from process_io import (
    DRAIN_TIMEOUT_MS,
    HARD_AGE_US,
    HEALTH_INTERVAL_NS,
    MAX_RECORD_BYTES,
    SOFT_AGE_US,
    OutputWriter,
    PublicRecords,
    cancel_io,
    private_file,
    source_age_us,
)
from process_job import ProcessJob
from wire import ProbeError

RETRY_LIMIT = 5
STABLE_NS = 30_000_000_000
ATTEMPT_STOP_SECONDS = 8
HEALTH_TIMEOUT_NS = 15_000_000_000
WAIT_SECONDS = 0.02
RETRY_REASONS = frozenset(
    {
        "sdk-receive-overload",
        "receive-staging-overload",
        "parser-residence-overload",
        "ordered-parser-input-backpressure",
        "source-residence-overload",
        "initialization-timeout",
        "native-receive-failed",
        "native-send-failed",
        "ordered-parser-exited",
        "ordered-parser-not-running",
        "attempt-crashed",
        "attempt-unresponsive",
    }
)


def retryable(report):
    reason = report["reason"]
    if reason in RETRY_REASONS:
        return True
    if reason == "phase-timeout":
        # A silent response after sending credentials is ambiguous. Do not retry it.
        return report.get("phase") in ("transport", "challenge", "channel")
    if reason == "native-session-closed":
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
    stage, _, error = reason.partition(": ")
    return stage in (
        "ordered-parser-input-failed",
        "ordered-parser-output-failed",
    ) and error in (
        "OSError",
        "BrokenPipeError",
        "ConnectionResetError",
    )


class SessionAttempt:
    """Own a single driver, its pipes, and the directory of its temporary report."""

    def __init__(self, command, directory, endpoint, password, progress):
        self.directory = directory
        self.progress = progress
        self.records = queue.Queue(maxsize=64)
        self.health = self.terminal_report = None
        self.health_ns = time.monotonic_ns()
        self.eof = threading.Event()
        self.stopping = threading.Event()
        self.bad_line = None
        self.forced = False
        self.job = ProcessJob()
        self.process = None
        self.threads = []
        try:
            self.process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                start_new_session=os.name != "nt",
            )
            # The child waits for configuration before starting Steam or Node.
            self.job.assign(self.process)
            for stream, target in (
                (self.process.stdout, self._read),
                (self.process.stderr, self._diagnostics),
            ):
                thread = threading.Thread(target=target, args=(stream,), daemon=True)
                thread.start()
                self.threads.append(thread)
            config = bytearray(
                json.dumps(
                    {"endpoint": endpoint, "password": password.decode("ascii")}
                ).encode("ascii")
            )
            config.append(10)
            try:
                if self.process.stdin.write(config) != len(config):
                    raise ProbeError("attempt-configuration-write")
            finally:
                config[:] = bytes(len(config))
        except BaseException:
            self.close()
            raise

    def _read(self, stream):
        try:
            with io.BufferedReader(stream) as reader:
                while not self.stopping.is_set():
                    line = reader.readline(MAX_RECORD_BYTES + 1)
                    if not line:
                        break
                    if len(line) > MAX_RECORD_BYTES:
                        self.bad_line = "attempt-record-budget"
                        break
                    if not line.endswith(b"\n"):
                        self.bad_line = "attempt-record-truncated"
                        break
                    received_ns = time.monotonic_ns()
                    try:
                        row = json.loads(line)
                    except ValueError:
                        self.bad_line = "attempt-record-invalid"
                        break
                    if not isinstance(row, dict):
                        self.bad_line = "attempt-record-invalid"
                        break
                    while not self.stopping.is_set():
                        try:
                            self.records.put((row, received_ns), timeout=WAIT_SECONDS)
                            self.progress.set()
                            break
                        except queue.Full:
                            continue
        except OSError:
            self.bad_line = "attempt-output-read"
        finally:
            self.eof.set()
            self.progress.set()

    def _diagnostics(self, stream):
        try:
            with io.BufferedReader(stream) as reader:
                while not self.stopping.is_set():
                    line = reader.readline(MAX_RECORD_BYTES + 1)
                    if not line:
                        return
                    if len(line) > MAX_RECORD_BYTES:
                        while line and not line.endswith(b"\n"):
                            line = reader.readline(MAX_RECORD_BYTES + 1)
                        continue
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(row, dict):
                        if row.get("type") == "cs2-observer-health/1":
                            self.health = row
                            self.health_ns = time.monotonic_ns()
                        elif row.get(
                            "schema"
                        ) == "cs2-observer-report/1" and isinstance(
                            row.get("reason"), str
                        ):
                            self.terminal_report = row
        except OSError:
            pass

    def backlog(self, now_ns):
        with self.records.mutex:
            pending = self.records.queue
            return dict(
                pendingRecords=len(pending),
                oldestAgeUs=max(0, now_ns - pending[0][1]) // 1000 if pending else None,
            )

    def report(self):
        try:
            with (self.directory / "report.json").open("rb") as stream:
                data = stream.read(128 * 1024 + 1)
            if len(data) <= 128 * 1024:
                row = json.loads(data)
                if isinstance(row, dict) and isinstance(row.get("reason"), str):
                    return row
        except (OSError, ValueError):
            pass
        return self.terminal_report or {}

    def close(self):
        process = self.process
        if process is None:
            self.job.close()
            return
        self.stopping.set()
        try:
            process.stdin.close()
            try:
                process.wait(timeout=ATTEMPT_STOP_SECONDS)
            except subprocess.TimeoutExpired:
                self.forced = True
                if os.name == "nt":
                    self.job.reap()
                    if process.poll() is None:
                        process.kill()
                else:
                    self._kill_group()
                process.wait(timeout=2)
            if os.name == "nt":
                self.job.reap()
            else:
                self._kill_group()
        finally:
            self.job.close()
            deadline = time.monotonic() + 1
            for thread in self.threads:
                while thread.is_alive() and time.monotonic() < deadline:
                    cancel_io(thread)
                    thread.join(WAIT_SECONDS)
            if any(thread.is_alive() for thread in self.threads):
                raise ProbeError("attempt-io-close-timeout")
            process.stdout.close()
            process.stderr.close()

    def _kill_group(self):
        try:
            os.killpg(self.process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


class SessionSupervisor:
    def __init__(self, args, owner, output, diagnostics, progress):
        self.args = args
        self.owner = owner
        self.output = output
        self.diagnostics = diagnostics
        self.progress = progress
        self.public = PublicRecords(self._write, encoded=True)
        self.source = f"{args.source_role}:{args.source_id}"
        self.channel, self.world = 0, 1
        self.ready_since = self.cursor_sequence = None
        self.deadline = time.monotonic() + args.seconds if args.seconds else None
        self.retry_streak = self.reconnects = 0
        self.faults = deque(maxlen=8)
        self.health = None
        self.next_health = 0
        self.last_attempt_health = None
        self.last_forward_us = self.max_forward_us = None

    def _write(self, row, data):
        cursor = None
        age = None
        if "supervisorForwardUs" in row:
            age = source_age_us(row)
            if age is not None:
                age += row["supervisorForwardUs"]
        if self.output.age_limit_us != HARD_AGE_US:
            age = None  # Normal source tail has its own drain deadline.
        if row["kind"] == "cursor":
            cursor = {
                key: row[key]
                for key in ("channel", "world", "committedTick", "sequence")
            }
        self.output.emit_encoded(
            data, cursor=cursor, source_age_us=age, sequence=row["sequence"]
        )

    def _stop_reason(self):
        if self.owner.is_set():
            return "owner-stopped"
        if self.deadline is not None and time.monotonic() >= self.deadline:
            return "duration-limit-incomplete"
        return None

    def wait_output(self):
        while self.output.pending_bytes:
            if self._stop_reason():
                return False
            self.output.check()
            self.progress.wait(WAIT_SECONDS)
            self.progress.clear()
        return not self._stop_reason()

    def _boundary(self, kind, **fields):
        if not self.wait_output():
            return False
        self.ready_since = self.cursor_sequence = None
        self.output.age_limit_us = HARD_AGE_US
        self.public(
            dict(
                kind=kind,
                source=self.source,
                channel=self.channel,
                world=self.world,
                **fields,
            )
        )
        return True

    def _health(self, state, attempt=None, *, force=False, retry_ms=None):
        now = time.monotonic_ns()
        if not force and now < self.next_health:
            return
        self.next_health = now + HEALTH_INTERVAL_NS
        if (
            attempt
            and attempt.health
            and (
                attempt.health.get("source") == self.source
                and attempt.health.get("world") == self.world
            )
        ):
            self.last_attempt_health = {**attempt.health, "channel": self.channel}
            delivered = (attempt.health.get("output") or {}).get("lastDeliveredCursor")
            if delivered:
                self.last_attempt_health["output"] = {
                    **self.last_attempt_health["output"],
                    "lastDeliveredCursor": {**delivered, "channel": self.channel},
                }
        output = self.output.status()
        cursor = output["lastDeliveredCursor"]
        if cursor and (cursor["channel"], cursor["world"]) != (
            self.channel,
            self.world,
        ):
            output["lastDeliveredCursor"] = None
        backlog = attempt.backlog(now) if attempt else None
        queued_ages = (
            output["oldestAgeUs"],
            backlog["oldestAgeUs"] if backlog else None,
        )
        if state == "connected" and any(
            age is not None and age >= SOFT_AGE_US for age in queued_ages
        ):
            state = "catching-up"
        self.health = dict(
            type="cs2-observer-health/2",
            source=self.source,
            channel=self.channel,
            world=self.world,
            state=state,
            ready=self.ready_since is not None,
            reconnects=self.reconnects,
            retryInMs=retry_ms,
            lastFault=self.faults[-1] if self.faults else None,
            attempt=self.last_attempt_health,
            output=output,
            forwarding=backlog,
            forwardLastUs=self.last_forward_us,
            forwardMaxUs=self.max_forward_us,
        )
        if force:
            return
        try:
            self.diagnostics.emit(self.health)
        except ProbeError:
            pass

    def _forward(self, row, received_ns):
        kind, world = row.get("kind"), row.get("world")
        emitted_ns = row.pop("_attemptEmittedNs", None)
        draining = row.pop("_attemptDraining", None)
        now = time.monotonic_ns()
        if (
            row.get("source") != self.source
            or row.get("channel") != 1
            or type(world) is not int
            or world < self.world
            or not isinstance(kind, str)
            or not kind
            or kind == "session-start"
            or (world != self.world and kind != "discontinuity")
            or type(emitted_ns) is not int
            or not 0 < emitted_ns <= received_ns
            or type(draining) is not bool
        ):
            raise ProbeError("attempt-record-identity")
        age = source_age_us(row)
        forward_us = (now - emitted_ns) // 1000
        if not draining and (
            forward_us >= HARD_AGE_US
            or (age is not None and age + forward_us >= HARD_AGE_US)
        ):
            return False
        if draining and forward_us >= DRAIN_TIMEOUT_MS * 1000:
            raise ProbeError("output-drain-timeout")
        self.output.age_limit_us = DRAIN_TIMEOUT_MS * 1000 if draining else HARD_AGE_US
        self.last_forward_us = forward_us
        self.max_forward_us = max(self.max_forward_us or 0, forward_us)
        if kind == "discontinuity":
            row["scope"] = "world" if world != self.world else "snapshot"
            self.ready_since = self.cursor_sequence = None
            self.last_attempt_health = None
        self.world = world
        if kind == "cursor":
            if (
                type(row.get("committedTick")) is not int
                or row["committedTick"] < 1
                or row.get("tick") != row["committedTick"]
                or type(row.get("tickInterval")) not in (float, int)
                or not 0 < row["tickInterval"] <= 1
                or not isinstance(row.get("map"), str)
                or not row["map"]
            ):
                raise ProbeError("attempt-record-cursor")
            if self.cursor_sequence is None:
                self.cursor_sequence = self.public.sequence + 1
        self.public({**row, "channel": self.channel, "supervisorForwardUs": forward_us})
        return True

    def _channel(self, attempt):
        expected_sequence = 1
        terminal_seen = False
        eof_deadline = None
        while True:
            self.progress.clear()
            stop = self._stop_reason()
            if stop:
                self.output.abort()
                return {"reason": stop}
            self.output.check()
            now = time.monotonic_ns()
            if (
                self.cursor_sequence
                and self.output.last_delivered_sequence >= self.cursor_sequence
            ):
                if self.ready_since is None:
                    self.ready_since = now
                if now - self.ready_since >= STABLE_NS:
                    self.retry_streak = 0
            exit_code = attempt.process.poll()
            if exit_code not in (None, 0):
                report = attempt.report()
                return report or {
                    "reason": "attempt-crashed"
                    if exit_code != 2
                    else "attempt-incomplete"
                }
            self._health(
                "connected" if self.ready_since is not None else "initializing", attempt
            )
            if not self.output.pending_bytes:
                try:
                    row, received_ns = attempt.records.get_nowait()
                except queue.Empty:
                    pass
                else:
                    if row.get("sequence") != expected_sequence or terminal_seen:
                        raise ProbeError("attempt-record-order")
                    expected_sequence += 1
                    terminal_seen = (
                        row.get("reason") == "source-hltv-stop"
                        and row.get("kind") == "discontinuity"
                    )
                    if terminal_seen:
                        # Publish the terminal boundary once the clean exit is confirmed.
                        if (
                            row.get("source") != self.source
                            or row.get("channel") != 1
                            or row.get("world") != self.world
                        ):
                            raise ProbeError("attempt-record-identity")
                    elif not self._forward(row, received_ns):
                        return {"reason": "source-residence-overload"}
                    continue
            if attempt.eof.is_set():
                if attempt.bad_line and attempt.bad_line != "attempt-record-truncated":
                    raise ProbeError(attempt.bad_line)
                if eof_deadline is None:
                    eof_deadline = time.monotonic() + ATTEMPT_STOP_SECONDS
                if exit_code == 0 and attempt.records.empty():
                    report = attempt.report()
                    if (
                        terminal_seen
                        and attempt.bad_line is None
                        and report.get("outcome") == "closed"
                        and report.get("drainCompleted")
                        and report.get("cleanupCompleted")
                    ):
                        if report["reason"] != "source-hltv-stop":
                            raise ProbeError("attempt-invalid-completion")
                        return report
                    raise ProbeError("attempt-invalid-completion")
                if time.monotonic() >= eof_deadline:
                    return {"reason": "attempt-crashed"}
            if exit_code is None and now - attempt.health_ns >= HEALTH_TIMEOUT_NS:
                return {"reason": "attempt-unresponsive"}
            self.progress.wait(WAIT_SECONDS)

    def connect(self, endpoint, password):
        while True:
            stop = self._stop_reason()
            if stop:
                return "incomplete", stop
            self.channel += 1
            self.world = 1
            self.last_attempt_health = None
            if not self._boundary("session-start", protocol=2):
                return "incomplete", self._stop_reason()
            with tempfile.TemporaryDirectory(
                prefix=".attempt-", dir=self.args.output
            ) as folder:
                directory = Path(folder) / "session"
                command = [
                    sys.executable,
                    "-B",
                    str(Path(__file__).with_name("driver.py")),
                    "--managed",
                    "--session-attempt",
                    "--managed-protocol",
                    "1",
                    "--native",
                    str(self.args.native),
                    "--node",
                    self.args.node,
                    "--parser-worker",
                    str(self.args.parser_worker),
                    "--source-id",
                    self.args.source_id,
                    "--source-role",
                    self.args.source_role,
                    "--host-version",
                    str(self.args.host_version),
                    "--output",
                    str(directory),
                ]
                if self.args.steam_api is not None:
                    command.extend(("--steam-api", str(self.args.steam_api)))
                attempt = SessionAttempt(
                    command, directory, endpoint, password, self.progress
                )
                try:
                    report = self._channel(attempt)
                    if not self.wait_output():
                        self.output.abort()
                except BaseException:
                    self.output.abort()
                    raise
                finally:
                    attempt.close()
                if attempt.forced or attempt.report().get("cleanupCompleted") is False:
                    report = {
                        "reason": "attempt-cleanup-failed",
                        "cleanupCompleted": False,
                    }
                if attempt.health and attempt.health.get("source") == self.source:
                    self._health("retiring", attempt, force=True)
            stop = self._stop_reason()
            if stop:
                return "incomplete", stop
            reason = report["reason"][:256]
            if not self._boundary("discontinuity", reason=reason, scope="connection"):
                return "incomplete", self._stop_reason()
            if report.get("outcome") == "closed":
                return "closed", reason
            self.faults.append(
                {
                    "channel": self.channel,
                    "reason": reason,
                    "nativeFailure": report.get("native_failure"),
                    "remoteEndReason": report.get("remote_end_reason"),
                }
            )
            if not retryable(report) or report.get("cleanupCompleted") is False:
                return "failed", reason
            if self.retry_streak >= RETRY_LIMIT:
                return "failed", "reconnect-budget-exhausted"
            delay = (0.5 * 2**self.retry_streak) * random.uniform(0.8, 1.2)
            self.retry_streak += 1
            until = time.monotonic() + delay
            while time.monotonic() < until and not self._stop_reason():
                self.output.check()
                remaining = until - time.monotonic()
                self._health("backoff", retry_ms=max(0, round(remaining * 1000)))
                self.owner.stopped.wait(max(0, min(remaining, 0.1)))
            if not self._stop_reason():
                self.reconnects += 1


def run(args, owner, endpoint, password):
    progress = threading.Event()
    output = OutputWriter(
        sys.stdout.fileno(), max_records=1, age_limit_us=HARD_AGE_US, progress=progress
    )
    diagnostics = OutputWriter(
        sys.stderr.fileno(), max_records=1, max_bytes=MAX_RECORD_BYTES
    )
    supervisor = SessionSupervisor(args, owner, output, diagnostics, progress)
    try:
        outcome, reason = supervisor.connect(endpoint, password)
    except KeyboardInterrupt:
        outcome, reason = "incomplete", "owner-stopped"
        owner.stopped.set()
    except (OSError, ProbeError, subprocess.SubprocessError, ValueError) as error:
        outcome = "failed"
        reason = (
            str(error)
            if isinstance(error, ProbeError)
            else "supervisor-operation-failed"
        )
    finally:
        password[:] = bytes(len(password))
    try:
        if (
            not output.cancelled.is_set()
            and not output.failure
            and supervisor.wait_output()
        ):
            finished = output.finish(timeout=1)
        else:
            finished = output.abort()
        if not finished:
            outcome, reason = "failed", output.failure or "output-drain-timeout"
    except ProbeError as error:
        outcome, reason = "failed", str(error)
        output.abort()
    stop = supervisor._stop_reason()
    if stop:
        outcome, reason = "incomplete", stop
    cleanup = (
        owner.close()
        and not output.thread.is_alive()
        and not reason.startswith(
            ("attempt-cleanup-", "attempt-job-", "attempt-io-close-")
        )
    )
    if not cleanup and outcome != "failed":
        outcome, reason = "failed", "supervisor-cleanup-failed"
    if (
        outcome == "failed"
        and reason != "reconnect-budget-exhausted"
        and (not supervisor.faults or supervisor.faults[-1]["reason"] != reason)
    ):
        supervisor.faults.append({"channel": supervisor.channel, "reason": reason})
    supervisor.ready_since = None
    supervisor._health("stopped", force=True)
    report = dict(
        schema="cs2-observer-report/2",
        outcome=outcome,
        reason=reason,
        cleanupCompleted=cleanup,
        reportWritten=True,
        lastOutputSequence=supervisor.public.sequence,
        health=supervisor.health,
        faults=list(supervisor.faults),
    )
    temporary = args.output / "report.json.tmp"
    try:
        with private_file(temporary, "w") as handle:
            json.dump(report, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        temporary.replace(args.output / "report.json")
    except OSError:
        report.update(outcome="failed", reason="write-report", reportWritten=False)
    try:
        diagnostics.emit(report)
        diagnostics.finish(timeout=1)
    except ProbeError:
        diagnostics.abort()
    return {"closed": 0, "failed": 1, "incomplete": 2}[report["outcome"]]
