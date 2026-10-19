# Ordinary observer unified design: research gates

Fixed-build research and implementation basis. Runtime implementation was frozen during the binary audit. An isolated local workset was prepared on 2026-10-19 at22:36 UTC for the eventual cohesive implementation. Its quantizer/profile models are not connected to the runtime. Whole-design review remains active: the coordinate aggregate audit subsequently established a mixed integral/fractional rule that the scalar-only evidence had not covered. Preparation is not a declaration that every necessary path is already proven, and no new client artifact accompanies it.

## Evidence scope
Fixed Valve depot manifest 8766757721818354077; engine2/networksystem/client/server/schemasystem module hashes in module-manifest.json. Original binaries and decompiled output remain local. Source observations do not establish Perfect World live acceptance.

## Separate responsibilities
1. Transport: ordinary authorized observer identity, handshake, reliability, fragmentation, compression, per-message tick context.
2. Session state: signon generation, userinfo, spawn groups, class/serializer/string tables, FULL transition, reconnect and map change.
3. Decode: schema-driven primitive/aggregate codecs, full/delta baseline lifecycle, bounded reads, unsupported negotiated forms reported precisely.
4. Event projection: descriptor IDs, source event tick, entity/user identity, ordered emission and recovery discontinuities.
5. Consumer: independent ahead/delayed instances, explicit source identity and configured offset; no renderer/gameplay simulation unless research proves a dependency.

## Closed observations relevant to the design
- Net clock can regress; entity full-snapshot recovery is distinct from arbitrary net_Tick regression.
- Reliable frame tick metadata evolves per message and cannot be replaced by the last tick in an entire packet.
- CONNECTED userinfo precedes final ACK. Server CONNECTED marker and userinfo-initialized marker have separate writers.
- ID41 is a wire-compatible serializer wrapper; ID74 is replay state in the fixed build. ID75 is CCLCMsg_HltvFixupOperatorTick in the fixed binary registry, a client-to-server operator message; the HLTV viewer server handler is a stub. The old parser schema naming it server-to-client status is not the fixed-build protocol definition.
- Scalar codec selection includes explicit signed enum metadata, fixed widths, coordinate profiles and aggregate dimension. CTransform defaults to six float-family components, not seven raw memory floats.
- Game-server event subscription and HLTV shared capture/forwarding are distinct. Capture wrapper classification does not mark event207 specially in inspected callback.

## Required contracts for centralized implementation

Use the maintained contracts rather than historical phase summaries:
- TRANSPORT-CONTRACT.md: official SDK ownership, application framing/sequence/reliable filtering and send backpressure.
- RECOVERY-CONTRACT.md: initialization/ACK, current-build delta presence, split-frame replacement, entity field-length index and snapshot epochs.
- WORLD-LIFECYCLE-CONTRACT.md: parent/manifest readiness, cancellation, destruction ticks and network-versus-client-local entity cleanup.
- STRINGTABLE-CONTRACT.md: indexed persistent keys/data, key history, exact fixed-size bit lengths, clearing and user identity.
- SERIALIZER-CONTRACT.md: immutable versioned schema, complete codec selection, custom field metadata, per-entity polymorphism and transaction failure.
- INBOUND-CONTROL-CONTRACT.md: query/response settings, optional envelopes, metadata and replay/presentation classification.
- GENERATION-TRANSACTION-CONTRACT.md: cross-owner reset boundaries, parser receipt fences, per-message clock context and bounded output ownership.
- SOURCES.md in the pinned reference collection: explicit reuse/cross-check boundaries.

Existing evidence closes normal userinfo→ClientInfo→ACK ordering, event207 descriptor/subscription/HLTV delivery, static codec families and current-build full/delta classification. Lifecycle consumers and cross-owner failure paths are now represented by explicit contracts: retained transport versus client/world ownership, parser receipt fencing, raw event ordering and identity domains, and bounded resource failure. Optional rendering, interactive replay and unrecognized extension semantics are outside the ordinary forward event receiver; their raw fields must still be consumed according to supported wire metadata or rejected explicitly. Packet-local/persistent polymorphic merge and logical pointer replacement now have separate native evidence. Full-frame replacement cleanup is resolved and belongs to the optional CInstantReplay buffering path, not the ordinary live PacketEntities handler. World unload cancellation and the network/local entity cleanup boundary now have cross-module evidence. Do not replace a concrete unknown with a test count or a broad “module done” claim. Once all necessary paths have explicit source-backed behavior, implement the contracts together rather than create another intermediate client package.

## Verification order after the gates
Unified implementation against fixed schema/transport contract → offline full trace plus required synthesized branches → runnable private artifact on GitHub → authorized ordinary observer live test. No intermediate package splitting. Record live signon, sustained receive, entities/events, recovery and two independent sources separately.

## Refined scope: wire correctness versus presentation reconstruction
For scalar/vector/matrix fields not consumed by event projection, the requirement is correct schema-driven bit consumption and retained raw values when requested. Reconstructing a render-ready matrix or simulating player movement is not a prerequisite for a snapshot/event observer. The 32-type catalog and encoder selection must still be complete enough to consume those fields without misalignment. Keep geometry conversion explicitly unimplemented if no output requires it; do not guess memory layout.

Confirmed ordinary client behavior: after signon > 3, a connected client checks dirty event subscriptions and emits message206 using server-supplied event IDs. The unified design should preserve this bounded behavior, even though a particular GOTV source may forward the same shared event set regardless of individual subscriptions. Source-side policy remains respected.

Keep wire decoding separate from logical field interpretation. Integer encoder families return wide values; a narrow primitive accessor may subsequently narrow/sign-extend storage. Correction after native emulation and assembly review at15:38 UTC: signed fixed8 already sign-extends during the wire decoder (0xff→-1); the earlier claim that this decoder yields255 was wrong. The frozen prototype expectation for signed fixed8 must be corrected during unified implementation. Prove conversions for fields projected to output; preserve explicit raw/typed distinction for unused fields. This is a design review item, not a new patch.

Custom serializer metadata (protobuf field 12) participates in wire-category selection even for fake schemas. Keep this separate from nested serializer names and encoder names. Fixed-build anim/simulation time accessor conversion is seconds ↔ unsigned 64 Hz count; it is not the network message context tick. The existing Demo fixture is patch14178/build10896, whereas analyzed modules are14191/10924; offline parity against that fixture is regression evidence, not a current-build semantic oracle.

Native emulation extended configuration coverage and exposed quantizer gaps before implementation: exact-integer range/bit-count rules, 31-bit JavaScript shift arithmetic, and float32-sensitive sentinel retention. Eight initial matching configurations did not close the full matrix. All160 configurations were observed after stubbing only the fixed-build void diagnostic Warning import in simulated memory;46 differ from the frozen prototype, including warned out-of-normal-budget cases that must remain separately classified. No production parser edits.
