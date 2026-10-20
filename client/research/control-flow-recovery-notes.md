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
| FullFrameSplit same tick, unexpected chunk index | 04ca50 clears pending assembly | Drop incomplete assembly; no partial state application |
| FullFrameSplit different tick | 04ca50 only replaces old assembly with chunk0; other indices ignored | Fence assembly by session generation and full-frame tick; never concatenate different frames |
| FullFrameSplit complete | 04ca50 concatenates sequential chunks, decompresses, parses PacketEntities;04e8c0 attaches replacement to existing queued tick containing a delta | Validate budgets; preserve queued tick/source ordering and replacement ownership; do not immediately replay it as an unrelated new tick |
| New event descriptor list | client9f9580 invalidates previous IDs and sets subscription dirty | Replace event schema generation; rebuild206 subscriptions from received IDs |
| CHANGELEVEL / reconnect | 060310 /07e800 distinguish states, counts and callbacks | Clear connection/world/schema/queued-event ownership at explicit boundary, not every clock change |

## Still to close

- Outgoing acknowledgment cadence after 0642d0; value is last_tick_recv, including -1. 061960 triggers ForceFullUpdate on a reported connection problem unless snapshot-unlimited mode disables it. Initial no-valid-snapshot handling still needs distinct scheduling.
- 04e8c0 delivery and failure behavior, fragment memory/timeout budgets and interactions with reliable ordering.
- Snapshot/entity identity lifecycle, serial reuse and world-group unload while delta work is pending.
- Full event queue replay/rewind policy and explicit downstream discontinuity markers.

## Deliberate observer constraints

Bounded allocations, nesting, fragment count and assembly lifetime are local resilience choices; do not label arbitrary chosen budgets as wire limits. Unknown required schema/negotiation must produce a precise unsupported cause, not a guessed decoder. Do not emulate renderer, user commands or execute server command strings unless a necessary observer state dependency is evidenced. Two source instances own separate mutable state, including all recovery generations.
