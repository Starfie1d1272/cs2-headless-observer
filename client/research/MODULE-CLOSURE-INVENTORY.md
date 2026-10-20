# Required-module closure inventory

Updated: 2026-10-20 14:50 Asia/Shanghai.

## Counting rules

The fixed binary scope is six files, verified against module-manifest.json in
this work period. A module means a DLL, not a source file, function, report or
test. Closure concerns the ordinary authorized forward observer's required
paths, not every feature of CS2. SDK integration, implementation correctness
and live acceptance are separate and cannot be counted as binary research.

States below are deliberately conservative. An indexed source contract is not
automatically a completed final review. A discovered gap must retain its exact
scope, rather than reclassify an entire previously studied DLL as unexplored.

Current bounded count: six studied DLLs; six necessary-path source reviews
reconciled; zero currently identified binary-research blockers in this defined
ordinary forward-observer scope. This is not a claim that an entire DLL was
reverse engineered, that every future source/plugin is supported, or that no
new discrepancy can arise during implementation. Any such discrepancy reopens
its specific evidence item. All six matching hashes and six relevant static
dispatch/identity validators were checked again in this period. Those checks
verify retained evidence, not live behavior.

## Networksystem.dll

Required paths:
- Application framing, sequence ownership, reliability filtering and send
  backpressure: TRANSPORT-CONTRACT.
- Versioned schema, primitive/custom/enum/boxed type selection, coordinate and
  quantizer configuration: SERIALIZER-CONTRACT.
- Field-path termination, container metadata, delta merge, pointer lifetime and
  malformed-input transaction boundaries: SERIALIZER-CONTRACT.
- Compression boundaries are specific to transport, manifests and string
  tables; Snappy raw fallback must not leak into the other two policies.

Current review: necessary-path source evidence reconciled for this scope.
This period closed two isolated model gaps: explicit recognized custom wire
authority and lookup-specific case behavior. All old fixture class roots now
construct, but that is not a full stream replay or live schema test.
Final review reconciled codec selection, graph/metadata authority and the
directed construction matrix. It additionally found and closed the actual
Huffman-codebook evidence gap: native heap ordering/table construction now
matches the pinned implementation, and actual-table termination/truncation
boundaries were checked. Direct opcode probes alone had not established that.
Transport compression review is reconciled with CHANNEL-EVIDENCE and
INITIALIZATION-EVIDENCE: channel tags 3/4 use bounded raw LZ4, logical manifests
use their LZSS envelope, and string-table compression has its own Snappy/raw
wrapper. These are not interchangeable formats.

## Engine2.dll

Required paths:
- CONNECTED/NEW/SPAWN/FULL progression, actual account/observer identity,
  ClientInfo, logical LoadCompleted and committed snapshot ACK.
- Full/delta distinction, create/update/leave/delete, field-length index,
  dual baselines and full-snapshot epoch reset.
- String table mutation and clear, world-group readiness/cancellation,
  retained-channel reconnect and owner replacement.
- Inbound optional controls versus necessary state changes.

Evidence: TRANSPORT, RECOVERY, STRINGTABLE, WORLD-LIFECYCLE,
INBOUND-CONTROL and GENERATION-TRANSACTION contracts.
Current review: necessary-path source evidence reconciled for this scope.
Do not resurrect optional InstantReplay backfill as a live prerequisite.
This period removed superseded general wording from the recovery table,
separated optional replay assembly from ordinary entity receipt, and aligned
the clear/changelevel row with retained-channel ownership. Static clear/world,
reliable-marker and entity-create anchors passed. Directed generation/receipt
checks are now recorded separately in cohesive-offline-integration.json; they
use synthetic inputs and do not establish live behavior.

## Client.dll

Required paths:
- Field/custom/type registration and compatibility callback semantics.
- Event descriptor replacement, subscription and wire event identity.
- Network entity create identity, world-local cleanup versus network deletion,
  and the exclusion of animation/rendering/prediction from this output scope.
- Chat user-message structure and explicit sender identity domain.

Evidence: SERIALIZER, EVENT-LIFECYCLE, WORLD-LIFECYCLE and INBOUND-CONTROL
contracts, plus the fixed-hash identity/registration records.
Current review: necessary-path source evidence reconciled for this scope.
This period traced m_hItem to its current CEntityHandle/ehandle constructor.
This supports the custom wire category; it does not invent a generic integer
alias or claim the native fake-field path accepts unknown raw types.
Final review aligned exact/prefix aliases, primitive/enum/boxed dictionaries
and pointer-name compatibility without indiscriminate case folding. The
unintegrated graph model and explicit negative cases agree with those decisions.

## Server.dll

Required paths:
- Independently cross-check field/custom/enum/boxed registration against the
  receive-side interpretation.
- Event field encoding, player-slot/pawn-handle identity and chat descriptors.

Evidence: matching fixed client/server catalogs, EVENT-LIFECYCLE and
INBOUND-CONTROL contracts. HLTV transport/send/ACK ownership implemented in
engine2 is attributed to engine2, not counted again as server.dll code.
Current review: necessary-path sender cross-check reconciled for this scope.
The20 named scalar registrations agree between client and server, including
ehandle's category/dimension. The two broader scan candidates retained as
unresolved in the raw report were independently identified as event-manager
FreeEvent calls, not network serializer registrations. This is not a blanket
claim that all arbitrary plugin callbacks were enumerated. Explicit custom
metadata is preserved by the inspected writer0ab720, not invented by the parser.

## Schemasystem.dll

Required paths:
- Module/global type scopes, lookup and type-token resolution needed to
  interpret generated registration evidence.
- Distinguish a module type-array index from a builtin type number.

Evidence: boxed-type-authority and fixed module scope/lookup analysis.
Current review: required supporting-path source evidence reconciled.
The model consumes received wire schema/name/version authority and does not
allocate live C++ schema objects. The class-root and nested-version choices
remain explicit in SERIALIZER-CONTRACT. Generated metadata used to establish
enum/boxed profiles is supporting evidence, not a replacement for received
field metadata.
Unrelated reflection/editor functionality is outside this observer's scope.

## Tier0.dll

Required paths:
- Origin coordinate defaults and quantizer metadata lookup used in field
  interpretation.
- Relevant imported string-comparison semantics where they determine matching.

Evidence: origin-tier0-profile, origin-cell-width evidence and the caller
comparisons documented in SERIALIZER-CONTRACT.
Current review: required supporting-path source evidence reconciled.
Fixed-build defaults remain distinct from negotiated wire data and arbitrary
plugin-modified globals. The exact origin-tier0 static verifier passed again.
No allocator, fatal-error or arbitrary OS import was executed to claim
successful coverage.

## Implementation/live work is not counted as an unread DLL

The cohesive decoder is now connected to the Python driver through an actual
local Node worker and generation-fenced bounded pipe. Synthetic end-to-end
checks cover initialization, full/delta recovery, clear/changelevel, subscriptions
and two independent processes. This is local runtime integration, not real
source acceptance. Windows SDK startup, current-build source replay, Mizar
consumer acceptance and authorized live observation remain separate work.
Do not describe these as additional unknown binary files, and do not describe
source-contract closure as successful deployment.

## Next work

Continue the same cohesive implementation through consumer integration and
full review. Schema/codec/path reader, transactional entities/string tables,
raw event projection, and driver/process generation ownership are connected
in the local implementation; see cohesive-offline-integration.json. The
integration cross-check directly revisited engine047960,044f10,088bf0,088f00,
044b10,103800,077630 and0775b0, and closed the newly identified distinctions
between baseline resets, sparse application, header formats and dormant
reconciliation. No additional unresolved required DLL path is currently listed. Preserve existing SDK
authentication and ordinary observer permissions. Do not produce an
intermediate user package. Full offline integration and authorized Windows/live
acceptance remain separate gates. This inventory is not an instruction to stop.
