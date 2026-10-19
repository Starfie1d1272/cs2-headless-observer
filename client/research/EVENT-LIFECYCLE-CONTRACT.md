# Forward observer event and generation contract

Scope: authorized ordinary GOTV viewer, no rendering or interactive replay; two independent source instances. Source evidence and observer choices are deliberately distinguished.

## Source facts
- Fixed client9f9580 replaces game event descriptor IDs and marks subscription state dirty; after signon>3 the client builds message206 from the current event manager's IDs.
- Clienta1eb50 explicitly clears16 uint32 words, sets each subscribed server event ID's bit, and serializes all16 words into206.eventarraybits. Its playerslot is obtained from the engine's local-slot lookup, not the Steam account ID or a string-table user ID. Use the assigned observer slot and a512-bit subscription domain for this fixed build; validate descriptor IDs before indexing rather than extending an inferred bitmap arbitrarily. This is the subscription container's observed bound, not a claim that protobuf int32 itself is limited to511.
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

## Event player and pawn identity are different wire domains

Fixed server event type table18193c6d0 identifies type8 as strict_ehandle and type9 as playercontroller. CGameEventManager SerializeEventc1dd90 serializes type8 via GetInt into val_long and type9 via GetInt into val_short. It does not apply the flattened entity-field ehandle compressor to these event values. The public pinned s2sdk IGameEvent interface supplies an independent method-layout reference; fixed vtables and constants are checked by tools/verify-event-identity-layout.py.

CGameEvent SetPlayer(slot),c22080, resolves a controller when available and otherwise stores the supplied slot (or0xffff for-1). SetPlayer(entity),c21e10, and SetPlayerRaw,c22130, store controller entity index minus1 for the player field and a separate native pawn handle under the _pawn key. Native GetPlayerSlot,bfb630, reads a short, returns-1 for short-1, otherwise its low byte. This is distinct from string-table CMsgPlayerInfo.userid; match a type9 event against the player slot identity captured at that message's world/ordinal, not against a later reused slot.

The pawn event value uses the native32-bit handle layout: index mask0x7fff and serial in the remaining17 bits. GetEntityIndex,bf9ca0, applies that mask; GetEntity,bf9cf0, rejects0xffffffff/0xfffffffe and compares the entire stored entity identity handle before returning the entity. SetPlayer's identity path adjusts the serial by the entity identity flag before constructing the handle. Preserve the event's raw uint32 bit pattern even when its protobuf int32 representation is negative.

Do not use the flattened field ehandle's14-bit index/10-bit serial layout for type8 events, and do not reuse the old helper's userid_pawn &0x7ff fallback. That helper can alias distinct indices and never checks the serial. The pinned demoinfocs FindByPawnHandle also compares an extracted index only, so it is a useful compatibility reference rather than a complete stale-identity oracle. The observer must require a matching current/retained pawn identity and world generation; if the event references a previous pawn after respawn, use retained matching identity evidence or leave it unresolved. Never attach it to a newly created pawn with the same index.

This closes another projection boundary before unified implementation; it makes no assertion that every historical event descriptor uses type9 rather than an older short/user-ID convention. Dispatch identity interpretation by the received descriptor and fixed-build profile, preserving the raw event fields.

The receiving client independently agrees: CGameEvent vtable1c315c0 slot68→9e46d0 validates the complete native handle, slot70→9e4680 extracts0x7fff, and slot78→9e8a50 maps the short player value to low-byte slot with-1 sentinel. These receiving paths close the server-write→event-protobuf→client-identity interpretation chain.
