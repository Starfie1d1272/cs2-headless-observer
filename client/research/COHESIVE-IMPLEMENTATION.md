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
