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
(directory / "report.json").write_text(json.dumps(dict(
    schema="cs2-observer-report/1", reportWritten=True, phase=phase,
    remote_end_reason=remote, native_failure=native_failure, reachedFull=not code,
    lastOutputSequence=last_sequence, reason=reason,
    cleanupCompleted=attempt != "cleanup-failed", drainCompleted=not code,
    outcome="closed" if not code else "failed",
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
        from session_supervisor import retryable

        for reason in (
            "output-backpressure",
            "output-closed",
            "attempt-record-invalid",
            "connection-inner-prefix-or-budget",
            "ordered-parser-protocol-version",
        ):
            self.assertFalse(retryable({"reason": reason}))
        self.assertFalse(retryable({"reason": "phase-timeout", "phase": "connection"}))
        self.assertTrue(retryable({"reason": "phase-timeout", "phase": "channel"}))
        self.assertTrue(retryable({"reason": "ordered-parser-exited"}))
