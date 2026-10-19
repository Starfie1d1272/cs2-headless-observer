# Forward observer event and generation contract

Scope: authorized ordinary GOTV viewer, no rendering or interactive replay; two independent source instances. Source evidence and observer choices are deliberately distinguished.

## Source facts
- Fixed client9f9580 replaces game event descriptor IDs and marks subscription state dirty; after signon>3 the client builds message206 from the current event manager's IDs.
- Event207 receive9f8a90 and deferred drain9aee70 deserialize through the event manager and dispatch. Deferred rendering drain iterates backwards, so its traversal order is not a wire-order contract.
- HLTV124d40/137450 captures messages into shared signon/reliable/unreliable frame buffers, and122500 forwards them to viewers. The inspected forwarding path does not classify207 by each viewer's individual subscription bitmap.
- Network tick context can change per application message. Tick regression alone neither replaces schema nor establishes a new world. Snapshot receipt ACK belongs only to successfully committed PacketEntities.
- Stringtable userinfo index is the player slot; the stored user ID is a different identifier. Entity identity also includes serial/class and world generation.
- World clear and retained-channel changelevel are distinct from constructor/new transport; see RECOVERY-CONTRACT.md. Optional InstantReplay state is not the forward observer's event source.

## Observer output policy
These are explicit consumer semantics, not claims about renderer dispatch timing:
1. Assign source instance ID, channel generation, world generation, descriptor generation, source message tick and receive ordinal before decoding. Keep original source tick even when it regresses; do not manufacture wall-clock alignment.
2. Preserve wire receive ordinal for equal/source-adjacent events. If exposing a committed-state projection, hold only until the associated world has a usable committed snapshot; never silently project an event against a later unrelated world or an old reused entity index.
3. Bound deferred event storage. Overflow, missing schema, missing required identity or unresolvable snapshot dependencies produce an explicit gap/unknown identity rather than fabricated players or replayed events. Consuming a full snapshot cannot recreate missing discrete kills/chats.
4. Replace descriptor lookup on each authoritative descriptor list; already-decoded events retain their own schema generation. Raw deferred messages must retain the descriptor generation or be discarded with an explicit discontinuity when the old schema is unavailable.
5. Disconnect/changelevel/actual source restart fences asynchronous parser receipts and outstanding events. Discard stale-generation work before state commit or emission. A same-map round restart follows observed game events and snapshot facts; do not reset transport sequences or Steam authentication from a clock regression.
6. Two instances share immutable schema definitions only if keyed by exact schema/build identity. Mutable userinfo, metadata, baselines, clocks, event queues, authentication/tickets and output cursors remain per instance.
7. Ahead and delayed roles remain explicit. Default configured separation120s is configuration, not measured lag or permission to mix future information into delayed public output.

No user-command prediction, renderer, audio, navigation, animation reconstruction or arbitrary server command interpreter is needed for the requested snapshot/event projection. If an output later requires those semantics, scope and proof must be revisited rather than guessed.
