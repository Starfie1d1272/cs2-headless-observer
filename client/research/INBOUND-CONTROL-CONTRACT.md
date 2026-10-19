# Ordinary observer inbound control contract

Research baseline: official engine2 SHA6456df18d8f954394024c2c07da8c848df15a5ace74ce7390d78970ceb39ee21 from manifest8766757721818354077. Addresses below are module RVAs. The binding inventory is `engine-inbound-bindings.json`; it includes internal callbacks, not only wire messages. Native code and binaries remain local.

## Cvar query and replicated settings

Message58 maps to engine089160, which constructs message25 (CCLCMsg_RespondCvarValue), copies the request cookie/name, initializes an empty value and NotFound status1, then looks up the local console registry. A matching command yields status2. A matching queryable variable yields status0 and its current string value; registry flag bit26 yields protected status3. The native outgoing message is sent on the selected channel via slot138. These observations establish a required query/response behavior, not permission to expose arbitrary host configuration.

Unified implementation: maintain a bounded explicit registry of this observer's actually supported settings. Preserve cookie and exact requested name. Reply NotFound1 and empty value for unknown names, status2 only for an actual registered command, status3 for deliberately protected entries, and status0 only for an actual supported value. Never fabricate the full game's values or query environment variables, files, passwords or credentials. Bounds and rate limits are local resilience policy; authentication and source policy remain unchanged.

Message6 maps to engine0825e0. It skips missing/invalid registry entries and variables without FCVAR_REPLICATED bit13, then parses recognized values through the registry. A headless receiver may retain only explicitly supported replicated settings with known consumers. It must not create arbitrary variables, run callbacks from downloaded data, or execute server text as operating-system commands. Existing StringCmd5 interpreter scope is separately recorded in TRANSPORT-CONTRACT.md.

## Optional envelopes and metadata

- EncryptedData78: engine089df0 delegates to235320. Without payload or an authorized configured local key, the inspected path succeeds without nested delivery. A configured key requires structural/block-length validation before nested parsing; nested messages inherit the original receive context. Do not guess keys or promote unparsed ciphertext to a valid entity/event receipt.
- SetPause43: engine085d10 records pause state. Continue consuming authoritative incoming messages; do not freeze transport or invent elapsed game ticks.
- ServerSteamID63: engine08b0d0 stores server identity metadata; this is not a substitute for the authenticated transport identity.
- CmdKeyValues52: engine089c80 parses binary KeyValues and forwards to the client callback/event path. The inspected path has no independent protocol reply. The receiver does not execute these values or synthesize gameplay state from them.
- RconServerDetails71: engine089e70 forwards optional administrative data to an interface. Ordinary observation does not initiate RCON or publish payloads.
- PeerList60: engine0845c0 forwards to clientb7a3e0, which manages Steam peer connection metadata. This is separate from player userinfo/stringtables and entity identity; the observer does not initiate player-peer connections.
- SplitScreen54: engine0899f0 manages additional local-player channels. The single ordinary viewer does not negotiate split players or mix auxiliary identities into its snapshots.
- UserCommands76: engine089f70 forwards to clientb7cb80, updating per-controller command history/baselines. The observer consumes authoritative entity snapshots and game events, not local movement prediction. Keep the framed message bounded and distinct from event207; no fabricated movement commands or derived kills.

## Replay and presentation

Fixed-build ID74 is CSVCMsg_HltvReplay, not the historical parser enum's Broadcast_Command name. Engine060f00 records delay, primary target, stop tick and optional slowdown parameters, notifies client slot520 and resets interpolation when delay changes. Treat these as source replay metadata. Do not reject every nonzero delay or confuse these fields with the configured120-second separation between two GOTV sources. Ordinary forward observation does not request interactive replay; source tick/generation and actual full/delta receipts remain authoritative.

The ordinary engine handlers for46/47/49/50/56/57/62/70 resolve to021ba0, a successful no-op. This proves only this engine receiver's behavior, not absence of game-level audio/presentation consumers. Optional70 CInstantReplay buffering has separate ownership documented in RECOVERY-CONTRACT.md and cannot block normal entity reception.

Internal packet-start/end IDs1073741824/1073741825 and unresolved registration sentinels4294967295 are not wire IDs to add to the protocol registry. Their callbacks delimit native processing; the receiver must preserve its own explicit packet/message boundaries.

This inventory supplements, rather than replaces, transport, world, serializer, stringtable, entity and event contracts. Protocol constants must be resolved from the fixed binary registry before reusing older parser definitions. The observations above do not establish live server acceptance or complete game reconstruction.
