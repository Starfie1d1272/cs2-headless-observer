# Cross-process generation and transaction design

This is the observer's execution design derived from the maintained native contracts. The Python/Node protocol is our own; its identifiers and limits are not asserted to exist in CS2. No runtime changes or online acceptance are claimed here.

## Boundaries and owners

| Boundary | Source evidence | Preserve | Retire or reset |
|---|---|---|---|
| Actual SDK connection replacement | network channel constructor and Steam SDK ownership | immutable fixed-build definitions | channel sequence, ticket/connection handle, all world/parser state |
| Explicit retained-channel reconnect/changelevel | engine07e800/08aab0/0610c0; network0c4f40/0bb650 | current authenticated connection and actual sequence counters | unsent application controls, server count, initialization flags, world-dependent parser state and pending output |
| ClearAllStringTables | engine085d20 slot480→06bd20→0610c0, then060ec0 table-pointer writes | actual authenticated channel and sequence counters | same world-side ACK/init ownership plus indexed tables and table-derived projections |
| Full snapshot epoch restart | engine047960 | channel, current world/schema/table authority | obsolete frame history, baseline banks and pending entity transaction receipts |
| Missing delta baseline | engine047960/ForceFullUpdate07f1e0 | channel, world and current schema/table definitions | ability to ACK or project uncommitted new entity state; request normal full resync |
| Event descriptor replacement | client9f9580 | already decoded scalar events with their original descriptor identity | old lookup for new messages; raw deferred old-schema events require their retained descriptor or an explicit gap |
| Network clock regression alone | engine069cd0 | all ownership/generations and current authoritative snapshots | no lifecycle reset; update only message clock context |
| Optional replay split frame | engine021ba0 versus CInstantReplay04ca50 | ordinary forward state | no live reset or wait introduced by optional replay metadata |

The frozen prototype applies several changes only in one owner: driver blocks changelevel, parser clears tables independently, and bridge records have no world identity. Its event outlet and stream wrapper also reject any clock regression. Those behaviors are incompatible with the combined contracts even when an old single-map recording parses successfully.

## Ordered local envelope

Every submitted unit carries source instance, channel generation, world generation, monotonically increasing submission sequence and original receive/message ordinal. Each message retains its current source tick and reliable-filter context. A packet with Tick(A), event, Tick(B), entity cannot be relabeled entirely asB. Preserve packet boundaries separately from per-message context; changing Demo wrapper ticks must not reorder controls, descriptors or table updates around events.

The control owner processes reset boundaries in message order, splitting an incoming application packet at a boundary if needed. It advances the world identity before accepting later messages and retires any earlier pending acknowledgments. Each parser checkpoint/receipt/event echoes the identity from its own work item. The parent compares that identity before committing or emitting; a late old-world checkpoint cannot make new-world initialization ready or clear its recovery state.

Do not use stream checkpoint sequence alone as a world identifier. A new parser instance may restart a local sequence, while the parent generation remains distinct. Conversely a healthy retained parser may keep increasing a stream sequence across an explicit reset command. Select one implementation consistently; both require the same parent-side fence. Replacing the parser after a real world reset is acceptable local process ownership, provided the transport callback loop stays responsive and the new world input remains bounded.

## Commit and output ordering

Decode snapshot updates transactionally, publish a receipt only after the affected entities and metadata commit, and include snapshot epoch/tick/baseline ACK. A transport read, syntactically parsed protobuf, checkpoint or handled no-op is not such a receipt. A checkpoint confirms completion of prior ordered parser work; it cannot upgrade a failed entity decode into a valid snapshot.

Stage dependent event projections until their required world identity and usable committed state are established. Keep source event ordinal/tick rather than the final tick of a Demo packet. A later table/descriptor update must not silently change the identity of an earlier event in that same packet. Preserve decoded event fields and the matching identity evidence at observation time; unresolved identity stays explicit. After decode failure or lost process, emit one bounded discontinuity for the affected interval, discard retired-generation staged output and resume only from a valid new baseline. Missing discrete events are never reconstructed from a later full snapshot.

Schema/table processing checkpoints may satisfy initialization independently of a first full snapshot. LoadCompleted and SPAWN require logical world/decoder readiness, while FULL requires successful entity receipt. This avoids the initial-full circular wait described in WORLD-LIFECYCLE-CONTRACT.md.

## Backpressure and shutdown

Input/output/receipt queues and queued bytes are bounded independently. A full parser queue must not block SteamAPI_RunCallbacks or cause an already-assigned submission sequence to be mistaken for accepted work. Stop admitting parser-dependent data under a declared local overload policy; preserve the control loop long enough to report a gap and recover or close cleanly. Never silently drop selected entity deltas and continue ACKing later ticks as though their bases survived.

On shutdown or parser replacement, first fence the old generation, then close its pipes and owned process, drain/discard bounded retired output, and cancel only owned SDK tickets/connection when the actual channel ends. The SDK host currently holds one bridge per process, so the two requested source instances should be separate processes with distinct mutable queues and cursors. Shared fixed schema files may be read-only and version-keyed; no ticket, userinfo, baseline or cursor sharing.

## Directed verification required in the cohesive implementation

- Same-packet tick changes and descriptor/userinfo replacement preserve each event's original context.
- Old queued receipt arrives after retained-channel ClearAllStringTables: no stale ACK, no falseFULL, channel sequence retained.
- Clear duringCONNECTED and duringFULL takes the correct world-side transition and reinitializes once.
- Missing base, failed decode and old full receipt cannot escape the snapshot epoch fence.
- Parser input saturation, output saturation, process exit and cancellation keep the SDK callback loop bounded and release only owned handles.
- Both independent instances can use the same exact immutable schema profile without mutable state cross-talk.

These cases verify the observer execution design after implementation. They supplement the saved binary evidence; they cannot establish remote authentication acceptance or Windows game interoperability.
