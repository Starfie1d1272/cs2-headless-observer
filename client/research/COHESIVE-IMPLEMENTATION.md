# Cohesive ordinary observer implementation

Updated 2026-10-20 14:50 Asia/Shanghai. Work remains on the existing research
branch, not main. No release or Windows package was produced.

## Connected path

The pinned cs2parser source patch now contains the fixed-profile schema, field
codec, Huffman path reader, transactional entity fields, sparse baseline
application, dual-bank/frame owner, PacketEntities adapter, indexed string
tables, event identity projection and ordered protobuf core. Mature parser
bit readers, generated protobuf decoders and Snappy decoder remain reused.

`parser_worker.mjs` now bundles the ordered core, not a fabricated Demo stream.
`ordered_parser_bridge.py` carries source/channel/world identities and ordered
message numbers over a bounded local pipe. The actual Python driver uses this
worker; receipts, descriptor subscriptions and checkpoints remain distinct.
Queue admission reserves identities only after success, old-world outputs are
retired, and actual connection/transport counters survive a world clear.

The driver also uses the verified application reliable marker, truthful local
userinfo before CONNECTED, bounded cvar query responses, native-style clock
regressions, independent world creation watermarks, explicit changelevel/client
owner replacement, and committed-snapshot-only feedback. Existing SDK ticket
and peer identity checks remain; the missing challenge ID fallback no longer
incorrectly rejects a genuine authenticated Steam-auth peer.

## Evidence and limits

`cohesive-offline-integration.json` records the clean pinned-source patch/build,
full-source locked-toolchain typecheck, component evidence and 53 Python tests.
The end-to-end tests run the actual Node worker and pipe with a synthetic SDK
port. They cover first full, missing base/resync, new full, clear/reinitialize,
changelevel, event subscription, backpressure, retired receipts and independent
sources. No network socket, real account or live game server is exercised by
these tests. Earlier legacy adapter tests remain compatibility checks only;
their old Demo conventions are not the fixed-build ordinary runtime authority.

`verify_cohesive_parser.mjs` reproduces seven component suites against the same
patched source. The compressed field-path fixture is synthetic model output,
not a game binary, and its decompressed SHA-256 is checked before use.

Remaining work includes consumer review/integration, diagnostic completeness,
current-build source replay when available, Windows SDK startup and authorized
real-source acceptance. The sole existing Demo fixture is an older build and
cannot substitute for current-build online evidence. A successful synthetic
signon is never labeled a successful GOTV connection.

This is not a stopping gate. Continue the authorized engineering work without
producing intermediate user packages or repeatedly requesting a test match.

## 2026-10-20 15:24 correction

The archive review found that receive-message metadata had been conflated with
the game network clock. Driver now derives it per frame and per message before
reliable filtering; the pipe and core preserve it explicitly. A clean pinned
source checkout accepts the regenerated patch and full locked-toolchain
typecheck/build. All54 Python tests and195 component assertions pass, as do
5582 path-opcode and56 path-boundary cases. See message-context-integration.json.
The earlier53-test record remains historical rather than being silently rewritten.

## 2026-10-20 16:47 managed consumer integration

Ordered core records now preserve each type9 controller-slot identity alongside
the actual userinfo userid, Steam64 and controller serial. The bounded Python
bridge forwards13 supported Mizar event names plus round start/end, keeping the
legacy kind/actor/target fields. Recovery clears the cursor throttle baseline,
so a new accepted full below the prior tick immediately restores a cursor.

Managed CLI mode takes one bounded private stdin connection record, publishes
event-only stdout, does not save event/channel captures, and keeps the final
report off that stream. Source identity may be allocated by the owning process.
The current decoder explicitly accepts hostVersion14191 only. No installed
production source is automatically enabled by these changes.

Clean pinned-source patch/typecheck/build and58 Python tests pass;203 component
assertions and5582 opcode/56 boundary cases pass. A built Mizar pipe reader,
existing source owner and consumer accept the actual generated worker/bridge
output and retire readiness on EOF. Managed SDK-start failure is tested using
an absent native library, before any SDK load or socket. All inputs are synthetic.
No game binary, Windows account/session, real GOTV source, package or release
was used for these new integration checks.

## 2026-10-20 17:08 owner-directed normal shutdown

The managed owner keeps stdin open after the single connection record. EOF is
the stop signal; no server/OS commands are accepted on this channel. The driver
polls its owned pipe in the main loop, exits and runs normal SDK/parser
finalization. POSIX uses zero-timeout select; Windows uses PeekNamedPipe with
no competing reader. No blocking reader thread survives shutdown. Windows
runtime behavior is not verified by these Linux fixtures. The consumer retires
event delivery first, sends EOF, then uses bounded termination only as fallback.

All60 Python tests pass. The CLI/actual parser worker plus the existing in-memory
SDK fixture confirms owner-stopped, one port close, no requested ticket and no
finalization errors. This is not a real Steam shutdown rehearsal. Six Mizar
owned-process checks pass; normal cancellation requires exitcode2 from the
synthetic child, rather than accepting a signal-killed process as graceful.
