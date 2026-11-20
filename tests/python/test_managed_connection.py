import io
import json
import unittest
from driver import read_managed_connection, connection_values


class ManagedConnectionTests(unittest.TestCase):
    def test_buffered_extra_input_is_observed_by_same_reader(self):
        from process_io import ManagedOwner

        owner = ManagedOwner(
            stream=io.BytesIO(b'{"endpoint":"127.0.0.1:27020","password":""}\nSTOP\n'),
            configuration_reader=read_managed_connection,
        )
        try:
            self.assertEqual(owner.configuration()[0], "127.0.0.1:27020")
            self.assertTrue(owner.stopped.wait(1))
        finally:
            self.assertTrue(owner.close())

    def test_final_unicode_budget_and_output_order(self):
        from process_io import PublicRecords, encode_record

        output = []
        emit = PublicRecords(output.append)
        emit(
            {
                "kind": "weapon_fire",
                "fields": {"weapon": "中" * 20000},
                "sequence": None,
            }
        )
        emit({"kind": "discontinuity", "world": 2, "sequence": None})
        self.assertLessEqual(len(encode_record(output[0])), 65536)
        self.assertEqual([r["sequence"] for r in output], [1, 2])
        from wire import ProbeError

        with self.assertRaisesRegex(ProbeError, "output-record-budget"):
            emit({"kind": "weapon_fire", "fields": {"weapon": "中" * 30000}})

    def test_unread_output_pipe_can_be_cancelled_without_waiting_for_consumer(self):
        from process_io import OutputWriter
        import os, time

        read_fd, write_fd = os.pipe()
        writer = OutputWriter(write_fd)
        try:
            for _ in range(32):
                writer.emit({"kind": "synthetic", "value": "x" * 60000})
            time.sleep(0.02)
            start = time.monotonic()
            self.assertTrue(writer.abort())
            self.assertLess(time.monotonic() - start, 2)
        finally:
            os.close(read_fd)
            os.close(write_fd)

    def test_output_pipe_preserves_utf8_and_one_lf(self):
        from process_io import OutputWriter, encode_record
        import os

        read_fd, write_fd = os.pipe()
        if os.name == "nt":
            import msvcrt

            msvcrt.setmode(
                write_fd, os.O_TEXT
            )  # Inherited stdio need not start in binary mode.
        writer = OutputWriter(write_fd)
        row = {"kind": "synthetic", "text": "中文\nsecond line"}
        try:
            writer.emit(row)
            self.assertTrue(writer.finish())
            os.close(write_fd)
            write_fd = None
            self.assertEqual(os.read(read_fd, 4096), encode_record(row))
        finally:
            os.close(read_fd)
            if write_fd is not None:
                os.close(write_fd)

    @unittest.skipUnless(
        __import__("os").environ.get("GOTV_ORDERED_WORKER"), "Set GOTV_ORDERED_WORKER"
    )
    def test_real_driver_worker_and_abandoned_process_pipes_clean_up(self):
        import os, subprocess, sys, tempfile, time, threading
        from pathlib import Path

        for mode in ("unread", "closed", "slow"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                marker = root / "sdk-cleanup.json"
                output = root / "run"
                helper = (
                    Path(__file__).resolve().parents[1]
                    / "support/managed_pipe_driver.py"
                )
                child = subprocess.Popen(
                    [
                        sys.executable,
                        "-B",
                        str(helper),
                        "--session-attempt",
                        "--native",
                        str(marker),
                        "--parser-worker",
                        os.environ["GOTV_ORDERED_WORKER"],
                        "--host-version",
                        "14193",
                        "--output",
                        str(output),
                    ],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                reader = None
                try:
                    child.stdin.write(
                        b'{"endpoint":"127.0.0.1:27020","password":"synthetic-only"}\n'
                    )
                    child.stdin.flush()
                    if mode == "closed":
                        child.stdout.close()
                    elif mode == "slow":

                        def slow():
                            while child.stdout.read(1024):
                                time.sleep(0.005)

                        reader = threading.Thread(target=slow, daemon=True)
                        reader.start()
                    deadline = time.monotonic() + 5
                    while (
                        not marker.with_suffix(".progress").exists()
                        and child.poll() is None
                        and time.monotonic() < deadline
                    ):
                        time.sleep(0.01)
                    child.stdin.close()
                    try:
                        child.wait(timeout=12)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=5)
                        self.fail(
                            "Synthetic cleanup stalled:\n"
                            + child.stderr.read().decode("utf-8", errors="replace")
                        )
                    self.assertIn(child.returncode, (1, 2))
                    cleanup = json.loads(marker.read_text())
                    self.assertEqual(cleanup["closed"], 1)
                    self.assertTrue({3, 4, 5}.issubset(cleanup["signonAcks"]))
                    if mode != "closed":
                        self.assertGreaterEqual(cleanup["floodFrames"], 3)
                    report = json.loads(
                        (output / "report.json").read_text(encoding="utf-8")
                    )
                    self.assertTrue(report["cleanupCompleted"])
                    self.assertIn(
                        report["reason"],
                        ("owner-stopped", "output-closed", "output-backpressure"),
                    )
                finally:
                    if child.poll() is None:
                        child.kill()
                        child.wait(timeout=5)
                    if not child.stdin.closed:
                        child.stdin.close()
                    if reader:
                        reader.join(timeout=2)
                    if not child.stdout.closed:
                        child.stdout.close()
                    child.stderr.close()

    def test_retired_managed_protocol_v1_is_rejected(self):
        from pathlib import Path
        import subprocess
        import sys
        import tempfile

        with tempfile.TemporaryDirectory() as temp:
            result = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve().parents[2] / "client/driver.py"),
                    "--managed",
                    "--managed-protocol",
                    "1",
                    "--native",
                    str(Path(temp) / "absent"),
                    "--host-version",
                    "14192",
                    "--output",
                    str(Path(temp) / "run"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("retired", result.stderr)

    def test_private_stdin_values(self):
        endpoint, password = read_managed_connection(
            io.BytesIO(b'{"endpoint":"127.0.0.1:27020","password":"fixture-only"}\n')
        )
        self.assertEqual(endpoint, "127.0.0.1:27020")
        self.assertEqual(password, bytearray(b"fixture-only"))
        password[:] = bytes(len(password))

    def test_empty_password_is_explicitly_supported(self):
        self.assertEqual(connection_values("[::1]:27020", "")[1], bytearray())

    def test_invalid_configuration_never_echoes_input(self):
        for raw in (
            b"{broken secret}",
            b" " * 4097,
            json.dumps({"endpoint": "not-a-host:27020", "password": "secret"}).encode(),
            json.dumps({"endpoint": "127.0.0.1:0", "password": "secret"}).encode(),
            json.dumps(
                {
                    "endpoint": "127.0.0.1:27020",
                    "password": "secret",
                    "token": "private",
                }
            ).encode(),
            json.dumps(
                {"endpoint": "127.0.0.1:27020", "password": "\u4e2d\u6587"}
            ).encode(),
            json.dumps({"endpoint": "127.0.0.1:27020", "password": "a" * 96}).encode(),
        ):
            with self.subTest(length=len(raw)):
                with self.assertRaisesRegex(ValueError, "^configuration-boundary$"):
                    read_managed_connection(io.BytesIO(raw))

    @unittest.skipUnless(
        __import__("os").environ.get("GOTV_ORDERED_WORKER"), "Set GOTV_ORDERED_WORKER"
    )
    def test_managed_start_failure_keeps_stdout_clean_and_does_not_capture(self):
        # Deliberately absent native library fails strict path resolution before any SDK load/socket.
        import os
        from pathlib import Path
        import subprocess
        import sys
        import tempfile

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "run"
            connection = {
                "endpoint": "127.0.0.1:27020",
                "password": "synthetic-private-value",
            }
            with subprocess.Popen(
                [
                    sys.executable,
                    str(Path(__file__).resolve().parents[2] / "client/driver.py"),
                    "--session-attempt",
                    "--native",
                    str(root / "absent-native-library"),
                    "--parser-worker",
                    os.environ["GOTV_ORDERED_WORKER"],
                    "--host-version",
                    "14191",
                    "--source-id",
                    "0123456789abcdef0123456789abcdef",
                    "--output",
                    str(output),
                    "--seconds",
                    "1",
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ) as process:
                process.stdin.write(json.dumps(connection) + "\n")
                process.stdin.flush()  # Keep the owner alive until the intentionally absent library fails.
                self.assertEqual(process.wait(timeout=10), 1)
                stdout, stderr = process.stdout.read(), process.stderr.read()
            self.assertEqual(stdout, "")
            self.assertNotIn(connection["password"], stderr)
            self.assertNotIn(connection["endpoint"], stderr)
            self.assertEqual(sorted(p.name for p in output.iterdir()), ["report.json"])
            report = json.loads((output / "report.json").read_text())
            self.assertEqual(report["outcome"], "failed")
            self.assertTrue(report["cleanupCompleted"])
            self.assertTrue(report["reportWritten"])
            self.assertEqual(report["finalization_failures"], [])

    def test_partial_config_write_close_does_not_hang(self):
        import os
        import time
        from process_io import ManagedOwner

        for close_writer in (True, False):
            with self.subTest(close_writer=close_writer):
                read_fd, write_fd = os.pipe()
                owner = ManagedOwner(
                    fd=read_fd, configuration_reader=read_managed_connection
                )
                try:
                    os.write(write_fd, b'{"endpoint":"127.0.0.1:27020"')
                    if close_writer:
                        os.close(write_fd)
                        write_fd = None
                    start = time.monotonic()
                    with self.assertRaisesRegex(ValueError, "^configuration-boundary$"):
                        owner.configuration(timeout=1 if close_writer else 0.05)
                    self.assertTrue(owner.close())
                    self.assertLess(time.monotonic() - start, 0.5)
                finally:
                    if write_fd is not None:
                        os.close(write_fd)
                    os.close(read_fd)

    def test_owner_eof_is_a_stop_signal_without_blocking_reader(self):
        import os
        from driver import ManagedOwner

        read_fd, write_fd = os.pipe()
        owner = ManagedOwner(read_fd)
        try:
            self.assertFalse(owner.is_set())
            os.close(write_fd)
            self.assertTrue(owner.stopped.wait(1))
            self.assertTrue(owner.is_set())
            self.assertTrue(owner.is_set())
        finally:
            os.close(read_fd)

    @unittest.skipUnless(
        __import__("os").environ.get("GOTV_ORDERED_WORKER"), "Set GOTV_ORDERED_WORKER"
    )
    def test_owner_stop_runs_driver_and_parser_finalization(self):
        # Real CLI/worker and pipe, but the SDK port is the existing in-memory fixture.
        import os
        from pathlib import Path
        import sys
        import tempfile
        from unittest.mock import patch
        import driver
        import sdk
        from support.sdk_port import Port

        read_fd, write_fd = os.pipe()
        writer_open = True
        port = Port()

        def fake_native(*args, **kwargs):
            nonlocal writer_open
            os.close(write_fd)
            writer_open = False
            return port

        try:
            os.write(
                write_fd,
                b'{"endpoint":"127.0.0.1:27020","password":"synthetic-only"}\n',
            )
            with (
                os.fdopen(read_fd, "r") as input_stream,
                tempfile.TemporaryDirectory() as temp,
            ):
                output = Path(temp) / "run"
                argv = [
                    "driver.py",
                    "--session-attempt",
                    "--native",
                    str(Path(temp) / "not-loaded"),
                    "--parser-worker",
                    os.environ["GOTV_ORDERED_WORKER"],
                    "--host-version",
                    "14191",
                    "--output",
                    str(output),
                    "--seconds",
                    "5",
                ]
                with (
                    tempfile.TemporaryFile(mode="w+") as stdout_file,
                    tempfile.TemporaryFile(mode="w+") as stderr_file,
                    patch.object(sys, "argv", argv),
                    patch.object(sys, "stdin", input_stream),
                    patch.object(sys, "stdout", stdout_file),
                    patch.object(sys, "stderr", stderr_file),
                    patch.object(sdk, "NativePort", fake_native),
                ):
                    result = driver.main()
                report = json.loads((output / "report.json").read_text())
                self.assertEqual(result, 2)
                self.assertEqual(report["reason"], "owner-stopped")
                self.assertEqual(port.closed, 1)
                self.assertFalse(port.ticket_requested)
                self.assertEqual(report["finalization_failures"], [])
                self.assertTrue(report["cleanupCompleted"])
        finally:
            if writer_open:
                os.close(write_fd)


class ManagedSupervisorTests(unittest.TestCase):
    def run_attempts(self, steps, *, follow=False, stop_in_wait=None):
        import json
        import os
        from pathlib import Path
        import sys
        import tempfile
        from types import SimpleNamespace
        from unittest.mock import patch

        from process_io import ManagedOwner
        import session_supervisor as supervisor

        fake = """
import json
from pathlib import Path
import sys
import time

_, attempt, output, source = sys.argv
config = json.loads(sys.stdin.buffer.readline())
if config != {"endpoint": "127.0.0.1:27020", "password": "test-only"}:
    sys.exit(3)
directory = Path(output)
directory.mkdir()
phase = "closed"
remote = 1038
native_failure = 7
last_sequence = 0
if attempt == "overload":
    sys.stdout.write('{"abandoned":')
    reason, code = "parser-residence-overload", 1
elif attempt in ("unavailable", "unknown-close", "silent-password"):
    phase = "connection" if attempt == "silent-password" else "transport"
    remote = 4002 if attempt == "unknown-close" else 5003
    reason = "phase-timeout" if attempt == "silent-password" else "native-session-closed"
    code = 1
else:
    row = dict(
        source=source, channel=1, world=1, sequence=1, kind="cursor",
        map="de_test", tick=44, committedTick=44, tickInterval=1 / 64,
        _attemptEmittedNs=time.monotonic_ns(), _attemptDraining=True,
    )
    print(json.dumps(row))
    row.update(sequence=2, kind="discontinuity", reason="source-hltv-stop")
    print(json.dumps(row))
    reason, code = "source-hltv-stop", 0
    last_sequence = 1 if attempt == "invalid" else 2
category = (
    "cleanup-failed"
    if attempt == "cleanup-failed"
    else "clean-source-stop"
    if not code
    else "source-unavailable"
    if attempt == "unavailable"
    else "transient-fault"
    if attempt == "overload"
    else "permanent-fault"
)
(directory / "report.json").write_text(json.dumps(dict(
    schema="cs2-observer-report/1", reportWritten=True, phase=phase,
    remote_end_reason=remote, native_failure=native_failure, reachedFull=not code,
    lastOutputSequence=last_sequence, reason=reason,
    cleanupCompleted=attempt != "cleanup-failed", drainCompleted=not code,
    outcome="closed" if not code else "failed",
    attemptResult=dict(
        schema="cs2-observer-attempt-result/1",
        category=category,
        outcome="closed" if not code else "failed",
        phase=phase,
        nativeState=3 if not code else 2,
        nativeFailure=native_failure,
        remoteEndReason=remote,
        reachedFull=not code,
        drainCompleted=not code,
        cleanupCompleted=attempt != "cleanup-failed",
        reportWritten=True,
        lastOutputSequence=last_sequence,
        validCompletion=not code,
    ),
)))
sys.exit(code)
"""
        with (
            tempfile.TemporaryDirectory() as temp,
            tempfile.TemporaryFile() as stdout,
            tempfile.TemporaryFile() as stderr,
        ):
            root = Path(temp)
            script = root / "attempt.py"
            script.write_text(fake, encoding="utf-8")
            output = root / "run"
            output.mkdir()
            source_id = "12" * 16
            args = SimpleNamespace(
                output=output,
                seconds=3 if stop_in_wait == "deadline" else 15,
                follow_source=follow,
                source_id=source_id,
                source_role="ahead",
                native="unused.dll",
                node="node",
                parser_worker="unused.mjs",
                steam_api=None,
                host_version=14198,
            )
            attempts = []
            real_attempt = supervisor.SessionAttempt
            real_health = supervisor.SessionSupervisor._health

            def fixture(command, directory, endpoint, private_password, progress):
                self.assertNotIn("--follow-source", command)
                self.assertNotIn("--seconds", command)
                step = steps[len(attempts)]
                attempts.append(directory)
                self.assertFalse(any(path.exists() for path in attempts[:-1]))
                return real_attempt(
                    [
                        sys.executable,
                        str(script),
                        step,
                        str(directory),
                        f"ahead:{source_id}",
                    ],
                    directory,
                    endpoint,
                    private_password,
                    progress,
                )

            def observe_health(instance, state, *args, **kwargs):
                nonlocal write_fd
                real_health(instance, state, *args, **kwargs)
                if (
                    state == "backoff"
                    and stop_in_wait == "eof"
                    and write_fd is not None
                ):
                    os.close(write_fd)
                    write_fd = None

            read_fd, write_fd = os.pipe()
            with os.fdopen(read_fd, "rb") as stdin:
                os.write(
                    write_fd,
                    b'{"endpoint":"127.0.0.1:27020","password":"test-only"}\n',
                )
                owner = ManagedOwner(
                    stream=stdin if stop_in_wait == "eof" else None,
                    configuration_reader=read_managed_connection,
                )
                try:
                    endpoint, password = (
                        owner.configuration()
                        if stop_in_wait == "eof"
                        else ("127.0.0.1:27020", bytearray(b"test-only"))
                    )
                    with (
                        patch.object(supervisor, "SessionAttempt", side_effect=fixture),
                        patch.object(
                            supervisor.random,
                            "uniform",
                            side_effect=lambda lower, upper: (lower + upper) / 2,
                        ),
                        patch.object(
                            supervisor,
                            "FOLLOW_INITIAL_SECONDS",
                            5 if stop_in_wait else 0.01,
                        ),
                        patch.object(
                            supervisor.SessionSupervisor, "_health", observe_health
                        ),
                        patch.object(sys, "stdout", stdout),
                        patch.object(sys, "stderr", stderr),
                    ):
                        result = supervisor.run(args, owner, endpoint, password)
                finally:
                    if write_fd is not None:
                        os.close(write_fd)
                    owner.close()
            self.assertEqual(password, bytearray(len(password)))
            stdout.seek(0)
            records = [json.loads(line) for line in stdout]
            self.assertEqual({r["source"] for r in records}, {f"ahead:{source_id}"})
            report = json.loads((output / "report.json").read_text())
            stderr.seek(0)
            diagnostics = [json.loads(line) for line in stderr]
            self.assertEqual(len(attempts), len(steps))
            self.assertEqual(list(output.iterdir()), [output / "report.json"])
            return result, records, report, diagnostics

    def test_reconnect_isolates_partial_output_and_resequences(self):
        result, records, report, _ = self.run_attempts(["overload", "closed"])
        self.assertEqual(result, 0)
        self.assertEqual(
            [(r["kind"], r["channel"], r["sequence"]) for r in records],
            [
                ("session-start", 1, 1),
                ("discontinuity", 1, 2),
                ("session-start", 2, 3),
                ("cursor", 2, 4),
                ("discontinuity", 2, 5),
            ],
        )
        self.assertEqual(records[1]["scope"], "connection")
        self.assertIsInstance(records[3]["supervisorForwardUs"], int)
        self.assertNotIn("_attemptEmittedNs", records[3])
        self.assertEqual(report["outcome"], "closed")
        self.assertEqual(report["health"]["reconnects"], 1)
        self.assertEqual(report["health"]["followAttempts"], 0)
        self.assertEqual(report["health"]["sourceEnds"], 1)
        self.assertEqual(report["health"]["output"]["lastDeliveredSequence"], 5)
        self.assertEqual(report["faults"][0]["reason"], "parser-residence-overload")

    def test_follow_survives_unavailability_and_stops_on_ambiguous_password(self):
        steps = ["closed", *(["unavailable"] * 6), "closed", "silent-password"]
        result, records, report, diagnostics = self.run_attempts(steps, follow=True)
        self.assertEqual(result, 1)
        self.assertEqual(report["reason"], "phase-timeout")
        self.assertEqual([r["sequence"] for r in records], list(range(1, 21)))
        for channel, step in enumerate(steps, 1):
            rows = [r for r in records if r["channel"] == channel]
            expected = ["session-start", "discontinuity"]
            if step == "closed":
                expected.insert(1, "cursor")
                self.assertEqual(rows[-1]["reason"], "source-hltv-stop")
            self.assertEqual([r["kind"] for r in rows], expected)
            self.assertTrue(all(r["world"] == 1 for r in rows))
            self.assertEqual(rows[-1]["scope"], "connection")
        self.assertEqual(report["health"]["followAttempts"], 8)
        self.assertEqual(report["health"]["sourceEnds"], 2)
        self.assertEqual(report["health"]["reconnects"], 0)
        self.assertEqual([fault["channel"] for fault in report["faults"]], [9])
        waiting = [
            row for row in diagnostics if row.get("waitReason") == "follow-source"
        ]
        self.assertTrue(waiting)
        self.assertTrue(all(not row["ready"] for row in waiting))
        self.assertTrue(
            all(row["output"]["lastDeliveredCursor"] is None for row in waiting)
        )

    def test_follow_wait_stops_on_stdin_eof_or_total_duration(self):
        for stop, reason in (
            ("eof", "owner-stopped"),
            ("deadline", "duration-limit-incomplete"),
        ):
            with self.subTest(stop=stop):
                result, records, report, _ = self.run_attempts(
                    ["closed"], follow=True, stop_in_wait=stop
                )
                self.assertEqual(result, 2)
                self.assertEqual(report["reason"], reason)
                self.assertEqual(len(records), 3)
                self.assertEqual(report["health"]["sourceEnds"], 1)
                self.assertEqual(report["health"]["followAttempts"], 0)
                self.assertFalse(report["faults"])

    def test_follow_stops_on_unknown_native_close_or_invalid_completion(self):
        for steps, reason in (
            (["closed", "unknown-close"], "native-session-closed"),
            (["invalid"], "attempt-invalid-completion"),
            (["cleanup-failed"], "attempt-cleanup-failed"),
        ):
            with self.subTest(steps=steps):
                result, records, report, _ = self.run_attempts(steps, follow=True)
                self.assertEqual(result, 1)
                self.assertEqual(report["reason"], reason)
                self.assertEqual(
                    report["cleanupCompleted"], steps != ["cleanup-failed"]
                )
                self.assertEqual(report["health"]["sourceEnds"], steps.count("closed"))
                self.assertEqual(
                    sum(r.get("reason") == "source-hltv-stop" for r in records),
                    steps.count("closed"),
                )

    def test_permanent_and_consumer_failures_do_not_reconnect(self):
        from driver_support import classify_attempt_result
        from session_supervisor import decide_recovery

        for code in (
            "output-backpressure",
            "output-closed",
            "attempt-record-invalid",
            "connection-inner-prefix-or-budget",
            "ordered-parser-protocol-version",
        ):
            res = classify_attempt_result(
                {"outcome": "failed", "cleanupCompleted": True}, failure_code=code
            )
            self.assertEqual(
                decide_recovery(
                    res, following=False, follow_source=False, retry_streak=0
                ).action,
                "fail",
            )
        conn_timeout = classify_attempt_result(
            {"outcome": "failed", "cleanupCompleted": True, "phase": "connection"},
            failure_code="phase-timeout",
        )
        self.assertEqual(
            decide_recovery(
                conn_timeout, following=False, follow_source=False, retry_streak=0
            ).action,
            "fail",
        )
        chan_timeout = classify_attempt_result(
            {"outcome": "failed", "cleanupCompleted": True, "phase": "channel"},
            failure_code="phase-timeout",
        )
        self.assertEqual(
            decide_recovery(
                chan_timeout, following=False, follow_source=False, retry_streak=0
            ).action,
            "retry",
        )
        parser_exit = classify_attempt_result(
            {"outcome": "failed", "cleanupCompleted": True},
            failure_code="ordered-parser-exited",
        )
        self.assertEqual(
            decide_recovery(
                parser_exit, following=False, follow_source=False, retry_streak=0
            ).action,
            "retry",
        )
        unknown_follow_close = classify_attempt_result(
            {
                "outcome": "failed",
                "cleanupCompleted": True,
                "phase": "channel",
                "native_failure": 7,
                "remote_end_reason": None,
            },
            failure_code="native-session-closed",
        )
        self.assertEqual(
            decide_recovery(
                unknown_follow_close,
                following=True,
                follow_source=True,
                retry_streak=0,
            ).action,
            "fail",
        )

    def test_recovery_decision_ignores_diagnostic_reason_text(self):
        from driver_support import parse_attempt_result
        from session_supervisor import decide_recovery

        base = {
            "schema": "cs2-observer-report/1",
            "outcome": "failed",
            "phase": "transport",
            "cleanupCompleted": True,
            "reportWritten": True,
            "attemptResult": {
                "schema": "cs2-observer-attempt-result/1",
                "category": "source-unavailable",
                "outcome": "failed",
                "phase": "transport",
                "nativeState": 2,
                "nativeFailure": 7,
                "remoteEndReason": 5003,
                "reachedFull": False,
                "drainCompleted": False,
                "cleanupCompleted": True,
                "reportWritten": True,
                "lastOutputSequence": 0,
                "validCompletion": False,
            },
        }
        r1 = parse_attempt_result({**base, "reason": "arbitrary-display-text-1"})
        r2 = parse_attempt_result({**base, "reason": "output-backpressure"})
        self.assertEqual(
            decide_recovery(r1, following=True, follow_source=True, retry_streak=0),
            decide_recovery(r2, following=True, follow_source=True, retry_streak=0),
        )
        self.assertEqual(
            decide_recovery(
                r1, following=True, follow_source=True, retry_streak=0
            ).action,
            "follow",
        )

    def test_malformed_and_contradictory_attempt_result_fails_closed(self):
        from driver_support import parse_attempt_result

        base = {
            "schema": "cs2-observer-attempt-result/1",
            "category": "clean-source-stop",
            "outcome": "closed",
            "phase": "closed",
            "nativeState": 3,
            "nativeFailure": 7,
            "remoteEndReason": 1038,
            "reachedFull": True,
            "drainCompleted": True,
            "cleanupCompleted": True,
            "reportWritten": True,
            "lastOutputSequence": 1,
            "validCompletion": True,
        }
        cases = [
            {**base, "outcome": "unknown"},
            {**base, "lastOutputSequence": -1},
            {**base, "validCompletion": "yes"},
            {**base, "reachedFull": False},
            {**base, "drainCompleted": False},
            {**base, "category": "transient-fault"},
            {**base, "outcome": "failed"},
            {**base, "outcome": "incomplete", "category": "transient-fault"},
            {
                **base,
                "category": "transient-fault",
                "outcome": "failed",
                "validCompletion": True,
            },
            {**base, "category": []},
            {**base, "category": {"nested": 1}},
            {**base, "outcome": []},
            {k: v for k, v in base.items() if k != "validCompletion"},
            {**base, "validCompletion": False},
            {
                **base,
                "category": "source-unavailable",
                "outcome": "failed",
                "phase": "channel",
                "validCompletion": False,
            },
            {
                **base,
                "category": "cleanup-failed",
                "outcome": "failed",
                "cleanupCompleted": True,
                "validCompletion": False,
            },
        ]
        for bad in cases:
            with self.subTest(bad=bad):
                res = parse_attempt_result(
                    {"schema": "cs2-observer-report/1", "attemptResult": bad},
                    exit_code=0,
                    terminal_seen=True,
                    expected_sequence=2,
                )
                self.assertEqual(res.category, "invalid-completion")
                self.assertFalse(res.valid_completion)
        outer_mismatch = parse_attempt_result(
            {
                "schema": "cs2-observer-report/1",
                "outcome": "failed",
                "attemptResult": base,
            },
            exit_code=0,
            terminal_seen=True,
            expected_sequence=2,
        )
        self.assertEqual(outer_mismatch.category, "invalid-completion")
        self.assertFalse(outer_mismatch.valid_completion)

    def test_session_attempt_close_job_reap_failure_raises_cleanup_error(self):
        from unittest.mock import MagicMock, patch
        import os
        import session_supervisor as supervisor
        from wire import ProbeError

        attempt = supervisor.SessionAttempt.__new__(supervisor.SessionAttempt)
        attempt.stopping = __import__("threading").Event()
        attempt.forced = False
        attempt.threads = []
        attempt.job = MagicMock()
        attempt.job.reap.side_effect = ProbeError("attempt-job-reap-timeout")
        attempt.process = MagicMock()
        attempt.process.wait.return_value = 0

        with patch.object(os, "name", "nt"):
            with self.assertRaises(supervisor.AttemptCleanupError) as ctx:
                attempt.close()
        self.assertIn("attempt-job-reap-timeout", str(ctx.exception))
        attempt.job.close.assert_called_once()

    def test_supervisor_cleanup_failure_not_masked_by_owner_stop(self):
        from pathlib import Path
        import sys
        import tempfile
        from types import SimpleNamespace
        from unittest.mock import patch

        from process_io import ManagedOwner
        import session_supervisor as supervisor

        with (
            tempfile.TemporaryDirectory() as temp,
            tempfile.TemporaryFile() as stdout,
            tempfile.TemporaryFile() as stderr,
        ):
            output = Path(temp) / "run"
            output.mkdir()
            args = SimpleNamespace(
                output=output,
                seconds=5,
                follow_source=False,
                source_id="12" * 16,
                source_role="ahead",
                native="unused.dll",
                node="node",
                parser_worker="unused.mjs",
                steam_api=None,
                host_version=14198,
            )
            owner = ManagedOwner()
            owner.stopped.set()

            def fail_after_stop(self_sup, endpoint, password):
                self_sup.cleanup_failed = True
                raise supervisor.AttemptCleanupError("attempt-job-reap-timeout")

            with (
                patch.object(supervisor.SessionSupervisor, "connect", fail_after_stop),
                patch.object(sys, "stdout", stdout),
                patch.object(sys, "stderr", stderr),
            ):
                result = supervisor.run(
                    args, owner, "127.0.0.1:27020", bytearray(b"test-only")
                )
            report = json.loads((output / "report.json").read_text())
            self.assertEqual(result, 1)
            self.assertEqual(report["outcome"], "failed")
            self.assertFalse(report["cleanupCompleted"])
            self.assertEqual(report["reason"], "attempt-job-reap-timeout")

    def test_session_attempt_partial_init_assign_failure_cleans_up(self):
        from unittest.mock import MagicMock, patch
        import session_supervisor as supervisor
        from wire import ProbeError

        fake_proc = MagicMock()
        fake_proc.poll.return_value = None
        fake_job = MagicMock()
        fake_job.assign.side_effect = ProbeError("parser-job-assignment-failed")
        with (
            patch.object(supervisor, "ProcessJob", return_value=fake_job),
            patch.object(supervisor.subprocess, "Popen", return_value=fake_proc),
            patch.object(supervisor.SessionAttempt, "_kill_group") as kill_group,
        ):
            with self.assertRaisesRegex(ProbeError, "parser-job-assignment-failed"):
                supervisor.SessionAttempt(
                    ["unused"], None, "127.0.0.1:27020", bytearray(b"pw"), MagicMock()
                )
        fake_job.close.assert_called_once()
        fake_proc.stdin.close.assert_called_once()
        if __import__("os").name != "nt":
            kill_group.assert_called()

    def test_driver_report_write_failure_syncs_attempt_result(self):
        from pathlib import Path
        import sys
        import tempfile
        from types import SimpleNamespace
        from unittest.mock import patch
        import driver
        from process_io import ManagedOwner

        with (
            tempfile.TemporaryDirectory() as temp,
            tempfile.TemporaryFile(mode="w+") as stdout_file,
            tempfile.TemporaryFile(mode="w+") as stderr_file,
        ):
            output = Path(temp) / "run"
            output.mkdir()
            args = SimpleNamespace(
                native=Path(temp) / "not-loaded",
                steam_api=None,
                node="node",
                parser_worker=Path(temp) / "unused.mjs",
                source_role="ahead",
                source_id="12" * 16,
                managed=False,
                session_attempt=True,
                follow_source=False,
                host_version=14198,
                output=output,
                seconds=1,
                capture=False,
                capture_budget_mib=1,
            )
            owner = ManagedOwner()
            owner.stopped.set()
            with (
                patch.object(sys, "stdout", stdout_file),
                patch.object(sys, "stderr", stderr_file),
                patch.object(
                    driver, "write_report_file", side_effect=OSError("disk-full")
                ),
            ):
                code = driver.run_attempt(
                    args, owner, "127.0.0.1:27020", bytearray(b"test")
                )
            stderr_file.seek(0)
            lines = [
                json.loads(line) for line in stderr_file.read().splitlines() if line
            ]
            report = lines[-1]
            self.assertEqual(code, 1)
            self.assertFalse(report["reportWritten"])
            self.assertFalse(report["cleanupCompleted"])
            self.assertEqual(report["outcome"], "failed")
            self.assertEqual(report["attemptResult"]["category"], "cleanup-failed")
            self.assertEqual(report["attemptResult"]["outcome"], "failed")
            self.assertFalse(report["attemptResult"]["reportWritten"])
            self.assertFalse(report["attemptResult"]["cleanupCompleted"])
            self.assertFalse(report["attemptResult"]["validCompletion"])

    def test_session_attempt_init_cleanup_failure_marks_supervisor_cleanup_failed(
        self,
    ):
        from pathlib import Path
        import sys
        import tempfile
        from types import SimpleNamespace
        from unittest.mock import patch

        from process_io import ManagedOwner
        import session_supervisor as supervisor

        with (
            tempfile.TemporaryDirectory() as temp,
            tempfile.TemporaryFile() as stdout,
            tempfile.TemporaryFile() as stderr,
        ):
            output = Path(temp) / "run"
            output.mkdir()
            args = SimpleNamespace(
                output=output,
                seconds=5,
                follow_source=False,
                source_id="12" * 16,
                source_role="ahead",
                native="unused.dll",
                node="node",
                parser_worker="unused.mjs",
                steam_api=None,
                host_version=14198,
            )
            owner = ManagedOwner()
            with (
                patch.object(
                    supervisor,
                    "SessionAttempt",
                    side_effect=supervisor.AttemptCleanupError(
                        "attempt-io-close-timeout"
                    ),
                ),
                patch.object(sys, "stdout", stdout),
                patch.object(sys, "stderr", stderr),
            ):
                result = supervisor.run(
                    args, owner, "127.0.0.1:27020", bytearray(b"test-only")
                )
            report = json.loads((output / "report.json").read_text())
            self.assertEqual(result, 1)
            self.assertEqual(report["outcome"], "failed")
            self.assertFalse(report["cleanupCompleted"])
            self.assertEqual(report["reason"], "attempt-io-close-timeout")

    @unittest.skipUnless(
        __import__("os").environ.get("GOTV_ORDERED_WORKER"), "Set GOTV_ORDERED_WORKER"
    )
    def test_duration_limit_not_misclassified_as_owner_stopped(self):
        import os
        from pathlib import Path
        import sys
        import tempfile
        from unittest.mock import patch
        import driver
        import sdk
        from support.sdk_port import Port

        read_fd, write_fd = os.pipe()
        port = Port()
        try:
            os.write(
                write_fd,
                b'{"endpoint":"127.0.0.1:27020","password":"synthetic-only"}\n',
            )
            with (
                os.fdopen(read_fd, "r") as input_stream,
                tempfile.TemporaryDirectory() as temp,
            ):
                output = Path(temp) / "run"
                argv = [
                    "driver.py",
                    "--session-attempt",
                    "--native",
                    str(Path(temp) / "not-loaded"),
                    "--parser-worker",
                    os.environ["GOTV_ORDERED_WORKER"],
                    "--host-version",
                    "14191",
                    "--output",
                    str(output),
                    "--seconds",
                    "1",
                ]
                with (
                    tempfile.TemporaryFile(mode="w+") as stdout_file,
                    tempfile.TemporaryFile(mode="w+") as stderr_file,
                    patch.object(sys, "argv", argv),
                    patch.object(sys, "stdin", input_stream),
                    patch.object(sys, "stdout", stdout_file),
                    patch.object(sys, "stderr", stderr_file),
                    patch.object(sdk, "NativePort", return_value=port),
                ):
                    result = driver.main()
                report = json.loads((output / "report.json").read_text())
                self.assertEqual(result, 2)
                self.assertEqual(report["outcome"], "incomplete")
                self.assertEqual(report["reason"], "duration-limit-incomplete")
                self.assertEqual(report["attemptResult"]["category"], "duration-limit")
        finally:
            os.close(write_fd)
