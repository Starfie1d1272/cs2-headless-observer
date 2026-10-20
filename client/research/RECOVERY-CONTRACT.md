# Observer recovery contract, research draft

Fixed manifest: 8766757721818354077. This records verified control flow and proposed observer constraints separately. No implementation approval gate is marked complete by this document.

| Input / condition | Official evidence | Observer design consequence |
|---|---|---|
| CONNECTED state 2 | 060310 sends userinfo before general signon response | Send only truthful supported userinfo, then ACK; establish new session generation only for actual new connection/state cycle |
| NEW state 3 | 061460 invokes string table callbacks, 05ff20 sends ClientInfo, then signon response | Schema/table setup and actual SDK account identity precede response; preserve asynchronous dependency state |
| Tick regression alone | 069cd0 accepts clock change | Update clock context, retain entity baselines; do not invent a map transition |
| Delta before valid full | 06a960 ignores delta while last_tick_recv < 1 | Await full; do not publish entities or claim FULL |
| Delta references absent snapshot | 047960 cannot find delta_from and skips application | Do not decode against current unrelated snapshot; retain last valid state and enter bounded recovery policy |
| Future spawn creation sequence | 047960 rejects online snapshot beyond known sequence; special Demo full branch differs | Gate online entities on world-group creation evidence; no invented world group |
| Successful first full in SPAWN | 06a960 calls 047960 first, then 086220 advances 5→6 | Only successful entity application receipt permits FULL and updated acknowledged tick |
| Non-delta snapshot goes backward | 047960 removes frame history and clears dual baseline sets | Start new snapshot epoch, fence stale decode receipts; retain connection identity unless actual reconnect occurs |
| ForceFullUpdate | vtable100→07f1e0 clears dual baselines and sets last_tick_recv=-1 when previous value positive | Represent resynchronization distinctly; subsequent outgoing acknowledgment reflects absence of valid delta base |
| FullFrameSplit on ordinary forward receive | The ordinary message70 handler is021ba0, a successful no-op; optional CInstantReplay interception is separate | Do not block normal entities, replace live state, or add an independent ACK requirement |
| New event descriptor list | client9f9580 invalidates previous IDs and sets subscription dirty | Replace event schema generation; rebuild206 subscriptions from received IDs |
| CHANGELEVEL / reconnect | 060310 /07e800 distinguish states, counts and callbacks;08aab0 can restore an existing channel | Fence world/schema/queued-event ownership at the explicit boundary; retain authenticated channel and its counters when transferred, not on every clock change |

## Cross-contract reconciliation

- Outgoing ACK cadence and pre-FULL scheduling are resolved in TRANSPORT-CONTRACT.md; retain 061960 connection-problem resync handling.
- Optional replay full-frame attachment/cleanup behavior is resolved below. Ordinary forward receive does not use that replacement queue. Allocation/lifetime caps remain explicit observer bounds, not guessed native wire limits.
- Identity reuse and world unload are established below and in WORLD-LIFECYCLE-CONTRACT.md. GENERATION-TRANSACTION-CONTRACT.md defines the observer's cross-process fences and explicitly includes ClearAllStringTables as an engine Clear boundary.
- EVENT-LIFECYCLE-CONTRACT.md and GENERATION-TRANSACTION-CONTRACT.md define forward-event ordering and downstream discontinuities; interactive rewind remains outside the requested ordinary forward observer.

## Deliberate observer constraints

Bounded allocations, nesting, fragment count and assembly lifetime are local resilience choices; do not label arbitrary chosen budgets as wire limits. Unknown required schema/negotiation must produce a precise unsupported cause, not a guessed decoder. Do not emulate renderer, user commands or execute server command strings unless a necessary observer state dependency is evidenced. Two source instances own separate mutable state, including all recovery generations.

## HLTV sender ACK contract, fixed-build cross-check
HLTV viewer UpdateAcknowledgedFramecount122180 calls common0cb460 then tracks outstanding full-frame tick+c04. Equal ACK clears it; ACK beyond it discards cached split-full-frame chunks and marks rebuild. Common logic has explicit pending-full-update state+9dc and current delta ACK+15c: while waiting, intermediate/duplicate -1 values don't repeatedly reset; outside waiting, -1 requests resync, monotonic ACKs advance, decreasing nonnegative ACKs can be rejected/disconnected according to server policy. Hence observer ACK must be the successfully committed snapshot tick; never emit a regressed ACK merely because network clock or a source event regressed. Reconnect/source generation reset is a separate lifecycle transition. Preserving server behavior needs no server cvar changes.

## Delta classification: fixed-build presence, not legacy boolean
Cross-check against generated protobuf parser160d00 establishes PacketEntities wirefield6(delta_from) writes protobuf+80 and sets hasbits+10 mask0800; wirefield3(legacy_is_delta) writes a separate bool+7c and mask0100. The network wrapper adds30 bytes: this exactly matches engine047960 reading wrapper+40 mask0800 and delta_from+b0. Its entire full/delta branch, missing-frame lookup and rollback branch therefore use **presence of delta_from**, not legacy_is_delta's value. Field3 remains in the schema for compatibility and must not control ordinary fixed-build receive state.

The frozen OnlineEntityState.begin currently derives delta solely fromlegacy_is_delta. The old Demo can carry both fields and hide this mismatch. Unified ordinary-viewer implementation must preserve protobuf presence and classify delta from field6 presence; a full snapshot omits field6. Validate delta_from<current committed-context tick and require the referenced frame. Do not silently reinterpret an explicitly present negative delta_from as a full snapshot; native marks it delta and its frame path applies. Legacy Demo compatibility must be version-specific and separate from ordinary network semantics.

## serialized_entities is an entity field-length index
Native103b20 decodes PacketEntities.serialized_entities(field13) as a byte stream of unsigned varints into a vector.104100 also copies the repeated(entity_index,baseline_index) override pairs. On entity creation0464f0, a nonempty length vector supplies the next field-bit-length; the engine records the current bit cursor and cursor+length, copies bounded readers into a work item, advances the main cursor bylength, then046120 can schedule parallel field decoding. Without lengths it directly runs ReadFields to discover consumed length. The bytes are not an alternative entity snapshot to parse as another protobuf. A lightweight sequential observer can use the normal field decoder while checking declared lengths against actual consumption and packet bounds; it need not replicate native parallel jobs. It must still consume exactly one length per applicable entity work item, including update paths, and not conflate the vector index with entity ID. Native046a00 confirms the same cursor/vector-index operation for updates. Preserve/leave/delete paths do not consume these field-length entries.


## Optional replay assembly cleanup and ordinary entity identity

The assembly paragraphs in this section describe CInstantReplay only.
Same-tick unexpected chunk indices clear its assembly; different-tick input
replaces it only when the new chunk index is zero. A complete optional assembly
is attached to an eligible queued replay tick, not committed as a new live
snapshot. The entity create/preserve rules below are ordinary receive rules.
04ca50 releases all retained fragment message objects and clears its vector before decompression/PacketEntities parsing. Decompression failure or protobuf parse failure therefore leaves no complete pending fragment assembly; neither calls 04e8c0 nor applies entities. The handler returns handled=1 even on these failures, which must not be mistaken for a committed snapshot. Different-tick nonzero chunks are ignored while an assembly exists; same-tick unexpected index clears it. The inspected function has no wall-clock deadline. Observer memory/time budgets are deliberate resilience policy.

04e8c0 attaches a cloned full PacketEntities only to an existing queued matching tick containing a delta (field6 presence). Missing tick or eligible delta is a no-op; replacing an attached full destroys its prior clone. The clone receives queued tick and message context field+1c. Source event ordering must remain associated with that queued tick.

0464f0 checks both existing class identity and serial against the incoming create. Same class+serial may reuse the existing object; differing class or serial calls0463f0 before creation. 0463f0 removes normal client entities through the entity-system callback or deletes fake replay entries from their separate map. Observer identity is therefore connection/snapshot epoch plus entity index and serial, with class checked on create, never index alone. 046d50 preserve does not consume a new entity payload; it validates existing objects when diagnostics are enabled. None of these render callbacks is required for a headless logical state store, but their ownership effects are.


## Scope correction: FullFrameSplit is intercepted replay buffering
RTTI identifies 04d5b0 as CInstantReplay's message interception vtable entry (539018), not the ordinary CNetworkGameClient handler. Its initial guards require client HLTV-related state, replay buffering configuration and a valid entity system. The ordinary inbound registry maps message70 to021ba0 (shared no-op handler). Accordingly 04ca50/04e8c0 describe the replay buffer's optional full-frame backfill, not an unconditional requirement to replace every live received delta. The headless event receiver does not need to simulate interactive rewind merely because the server sends a split full frame. The source-side ACK consequence was resolved by the ordinary snapshot and sender checks in the following paragraph; it is not an outstanding prerequisite for forward observation.

04d1d0 limits stored replay history using configured duration converted to ticks, selects an eligible full checkpoint and releases older attachment/message records; it preserves message45 string-table updates. This is history retention, not a per-fragment wall-clock timeout. Native replay playback and live entity receipt therefore have different ownership and ordering requirements.

The no-op mapping is verified at the machine-code level: engine021ba0 is mov al,1; ret. HLTV122500 still serializes ordinary PacketEntities before its independent cached full-frame chunk send block;122180's normal snapshot ACK updates clear/rebuild its ancillary pending full-frame state. No distinct client FullFrameSplit ACK message appears in that inspected path. For the authorized forward-only observer, preserve ordinary committed-snapshot ACK and treat replay backfill as optional, without replacing already committed live state. Interactive rewind remains outside the event receiver requirement. An actual unsupported source behavior must be diagnosed from a capture, not “fixed” by accepting a regressed ordinary snapshot ACK.

## Signon validation versus world reset
082b60 forwards the received state and spawn count to virtual430. Base07e800 validates range<8, progression for states>=3 and compatible server count (unknown -1 is explicitly allowed); it then writes state and notifies listeners. It does not itself clear all world state. Clear0610c0 calls07b760, removes frame history and resets interpolation/auxiliary state; when state>CONNECTED it lowers local state to2. Base07b760 resets server_count and last_tick_recv to-1, clears both entity baseline storage regions and pause state. Treat these as an application/world generation boundary, independent of transport connection identity.

FinishChangeLevel08aab0 can transfer an existing channel from its transition object, restore its timeout, register callbacks via07d000, and re-enterCONNECTED with unknown spawn count. Therefore changelevel must not unconditionally reset GNS authentication or application transport sequence counters as though a brand-new channel were created. New ServerInfo/schema/stringtables establish the new world; fence delayed parser receipts and event identities from the prior world while keeping the actual surviving channel lifecycle. True disconnect068840 reaches base07f570 andClear0610c0; SDK connection close still owns transport/ticket cleanup. These paths are distinct from a regressed net_Tick or same-map round restart.

## Lightweight frame/state separation
Pinned SDK CClientFrame exposes transmit/nontransmit/out-of-PVS sets separately from its snapshot pointer. Fixed receive046a00 resolves the existing client entity, builds a field-decode work item and applies changed fields; it does not restore every current property from an arbitrary historical property clone before each delta. The forward observer should retain bounded frame membership/dormancy plus the two explicit baseline banks and current per-entity state. Transaction rollback can copy only affected entities/metadata; cloning all entities for every tick would add memory and CPU without a demonstrated requirement. Historical rewind reconstruction remains outside the forward receiver scope.

## Cohesive snapshot-owner application cross-check (2026-10-20)

047960 has two distinct non-delta effects: frame history removal is conditional
on a full snapshot going backward, whereas both instance-baseline banks are
cleared on EVERY non-delta snapshot. The transactional owner must not clear
committed banks during begin/decode; it stages that reset and publishes only
when the whole packet succeeds. This rollback discipline is an observer design
choice, not a claim that native code uses an immutable transaction.

The apply work-item path045730→044f10 distinguishes update and create. Update
applies an alternate baseline when present, then changed fields. Create first
selects the same-class instance baseline only for delta packets; otherwise it
uses088f00 class baseline resolution. The alternate index is consumed by the
update branch, not the inspected create branch. With update_baseline it merges
the baseline and incoming serialized fields into the opposite bank through
088620 and serializer slot58, then applies the merged result. Without it, it
applies baseline followed by incoming fields. Same-class/same-serial object
reuse does not itself clear all omitted logical fields. A sparse baseline must
therefore be applied to that existing logical object rather than substituting
an arbitrary historical whole-object property clone. Newly created identities
start empty. Renderer callbacks and native job parallelism are not replicated.

08b660 also retains a trailing-delete compatibility branch when the
non_transmitted_entities presence bit is absent and its packet context is delta;
this must not be guessed from legacy_is_delta. Native presence-bit provenance
and exact branch selection remain the authority when connecting the wire
adapter. The cohesive adapter now follows these distinctions and is connected
to the local ordered worker/driver; its synthetic integration evidence is in
cohesive-offline-integration.json, not a real server acceptance result.

088f00 resolves the decimal class key in instancebaseline and delegates to
088bf0 by the resolved string-table entry index. 088bf0 requires a registered
baseline handle, nonempty user data and successful field decoding; missing or
empty data does not become an empty successful baseline. It caches decoded
serialized data by entry index, not by entity ID. The observer can cache by
world/schema/table-entry revision to avoid stale index reuse after updates.
These functions have now been inspected directly for the wire adapter.

Out-of-PVS fields update the new frame's separate+1020 bitset. 08b110's
nontransmitted reconciliation tests transmitted+20, dormant+820 and already
scheduled deletions(context+e0), not that out-of-PVS bitset. Consequently the
observer must not use an out-of-PVS update alone as a permanent retention grant
when an explicit nontransmitted reconciliation is present. Directed adapter
cases now cover out-of-PVS data with dormant retention and with authoritative
dormant removal. These are synthetic source-conformance checks, not live tests.

The fixed ordinary iterator is constructor103ce0's vtable556bf8→103800.
044b10 reads the increasing UBitVar entity index and dispatches that iterator;
103800 consumes exactly two command bits (update/create/leave/delete). It does
not consult has_pvs_vis_bits_deprecated or consume a second old-demo PVS pair.
The out-of-PVS iterator547df8→077630 consumes one bit (update/create), and the
nontransmitted iterator547e08→0775b0 consumes one dormant bit. The fixed-profile
adapter deliberately does not inherit the frozen legacy demo PVS branch.
