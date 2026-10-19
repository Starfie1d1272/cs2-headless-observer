# Ordinary forward GOTV observer: unified design

Target: a lightweight authorized ordinary viewer that exposes current snapshot state and source game events, with independent ahead/delayed instances. Fixed research baseline is Valve manifest8766757721818354077. This design does not claim Windows/live interoperability from static evidence.

## Existing foundation and ownership
- Retain official Steam/GNS SDK bridge for login identity, connection authentication/encryption, transport reliability and packet delivery. Keep ticket callbacks/cancellation and SDK handles per instance. Do not implement a parallel authentication protocol or use relay identity.
- Retain the existing Python connection/driver and bounded Node parser bridge, but reconcile their control state with the contracts before producing any new package.
- Reuse pinned cs2parser bitstream/entity foundation and licensed protocol definitions. Compare Clarity/demoinfocs for independent semantics; native fixed-build evidence wins where their behavior differs. Do not replace the whole stack merely to avoid repairing an identified contract.
- A single private artifact eventually includes the reconciled parser and bridge. No intermediate six-package delivery or installation on the user's Mac.

## Independent state owners
1. Transport generation: SDK connection, outgoing/incoming sequence, reliable framing contexts, callback lifecycle. Only a new actual channel initializes sequence1/0.
2. World generation: server count, class/schema graphs, stringtables, spawn groups, entity frame history, descriptor IDs and parser receipt fence. Retained-channel reconnect/changelevel clears this world without inventing new Steam authentication.
3. Entity snapshot transaction: referenced baseline, index/serial/class identity, immutable field data and entity-local container/polymorphic metadata. Commit only after bounded decode succeeds. Keep frame membership separate from current entity properties; copy-on-write only affected entities for rollback, rather than cloning the whole world each tick.
4. Event projection: original source tick/ordinal, descriptor generation and identity evidence. Wire-order output and bounded waiting follow EVENT-LIFECYCLE-CONTRACT.md.
5. Consumer role: ahead/delayed designation and configured120s separation. This is not measured latency; no cross-instance mutable state or leakage of ahead data into delayed output.

## Control flow
Connection challenge selects the observed auth2/auth3 path. Authentication failure closes the attempt with its real cause; there is no password guessing or security downgrade. CONNECTED sends legitimate userinfo before signon response. NEW sends real account identity, server count and CRC0 when no matching cache exists, then responds. Complete schema/ClassInfo/table parser receipts plus logical group registration gate later signon; initial successful full snapshot advances localFULL. ACK uses only committed snapshot tick; -1 is a distinct resync request, with bounded pending state and transport backpressure.

Game network clock is separate from last committed snapshot. Duplicate/old packets, missing delta bases, failed decode, disconnect, world reset and parser process failure cannot produce a false receipt. Application PacketReliable filtering remains separate from GNS reliability. Unknown framed presentation messages may be skipped only when no required state owner depends on them; unknown required schema/control is a typed unsupported error.

Forward live receive does not enter CInstantReplay playback. Message70 full-frame backfill can be retained as a bounded optional replay facility later, but cannot replace live committed state or block ordinary deltas merely because pending_full_frame is set. The fixed ordinary handler is a successful no-op. Initial/missing-base recovery still uses the normal full PacketEntities path and normal ACK contract.

## Schema and decode
- Build complete immutable serializer graph by(case-insensitive name,version), selecting class roots atversion0 and retaining explicit nested/poly versions, resolving nested and polymorphic references in a bounded second pass. Preserve valid pointer/reference graph cycles without eagerly expanding them; bound actual field paths and reject impossible by-value cycles. Resolve type aliases, container/fixed-array shape, explicit enum signedness, custom var_serializer category/dimension, then encoder configuration in native order.
- Live entity-create headers use the received ServerInfo.max_classes bit width and17-bit create serial; validate ClassInfo IDs and keep any Demo fallback explicit.
- Preserve protobuf presence: field6 delta_from presence identifies delta in this build. Keep legacy Demo profile handling separate. Seven previously identified legacy-boolean decision sites must agree on one classifier.
- Primitive dispatch uses fixed-build catalog: signed fixed-width sign extension, uint64 preservation, fixed32 versus precise-angle behavior, exact coordinate and quantizer rules. Use saved independent native vectors as expected evidence, not regenerated expectations from the implementation.
- ReadFields starts fresh path decoding per entity. Invalid path, overread, invalid variant or budget violation fails that entity transaction and fences its snapshot commit. Field13 supplies optional per-work-item bit lengths, not another protobuf snapshot; a sequential decoder validates exact consumption.
- Dynamic arrays preserve existing in-range state and discard removed descendants; pointer absence/type replacement clears logical children, unchanged type preserves them. Persistent serialized metadata is old+delta keyed merge, distinct from logical descendants. Immutable schema must never carry an entity's active variant.
- Keep raw wire values and accessor-normalized output separate. Required position/identity/event fields apply proven accessors; unused rendering-only fields need correct consumption, not simulation of their callbacks.

## Stringtables and world dependencies
Retain indexed keys and exact byte/bit lengths. Every entry updates the32-entry key history with its resolved actual key, including keyless updates; native history strings are bounded. Fixed userdata reads SizeBits, not SizeBytes. Omitted/empty userdata clears old data. Whole-table and per-entry compression have separate budgets. Clear table generation invalidates cached userinfo/baseline views; alternate indexed baselines stay indexed rather than flattened into a class-only map.

Spawn-group manifest parsing is bounded logical registration, not rendering or arbitrary file execution. Parent/owner dependencies and creation sequence must be satisfied before applicable snapshots. Cancelled loading groups cannot emit late ready ACKs. Ordinary group unload respects destruction tick and does not invent deletion of authoritative network entities; explicit entity lifecycle or whole-world reset owns those removals.

## Failure and resource policy
All limits are identified as local resilience policy unless native wire bounds are proven. Bound queued SDK packets, parser in-flight receipts, schema graph/path depth, decompression, snapshots, event wait and fragment history. On process loss or failed commit, emit one discontinuity and require a fresh usable baseline; do not replay stale output. Backpressure must still pump SDK callbacks. Shutdown cancels only owned pending tickets, closes owned connection and parser, and flushes bounded diagnostics. Store no passwords/tickets in reports.

## Acceptance evidence after implementation
- Independent saved native bit/codec/configuration vectors and directed ownership-transition cases.
- Existing full recorded stream regression, explicitly labeled old-build fixture; no unchanged repeated long runs without a relevant change.
- End-to-end real parser subprocess with generation fences, failure/resync and schema/stringtable cases, preserving event identity semantics.
- Windows executable start and ordinary authorized source: signon, sustained packets, snapshot/event output, reconnect/changelevel and clean shutdown.
- Two simultaneous independent sources and measured CPU/RSS. Any live failure retains exact diagnosis; static tests do not imply99/100 percent live success.

Before implementation, reconcile this design against all maintained contracts and actual prototype owners, then make a cohesive change set. Do not treat this document itself as an implementation or live-acceptance milestone.

## Inbound control reconciliation

INBOUND-CONTROL-CONTRACT.md records the remaining engine receiver classifications. Preserve the actual GetCvarValue58→RespondCvarValue25 reply using a truthful bounded local registry, independently of entity/event decoding. Known unsupported presentation envelopes do not become snapshot receipts. Fixed-build ID74 replay metadata is separate from both the old parser's Broadcast_Command name and the configured120-second two-source offset. Internal callback sentinels are excluded from the wire registry. Type resolution also consumes the separately pinned replay-compat resource profile and demonstrated boxed/enum registration profiles from SERIALIZER-CONTRACT.md; no generic unsigned fallback is authoritative.
