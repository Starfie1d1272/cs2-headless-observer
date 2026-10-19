# Ordinary observer transport contract

Fixed networksystem manifest8766757721818354077, SHAbe7e13ad771b21c986e25d9469993a1225be5649473f3d722ca5eefe375d1bec. Reuse official Steam/GNS transport for legitimate identity, encryption, fragmentation and reliable delivery; Source2 application framing is a separate layer.

## Sequence ownership
Constructor/reset machine-code stores qword1 at+8da8, i.e. outgoingsequence1 and incomingsequence0; +8db0/+8db4 start0. Transmit0be6e0 writes own outgoing+8da8 then latestreceived+8dac into unreliableheader; after actual transmission it increments+8da8 and remembers acknowledged incoming+8db4. Receiver0c2230 reads peer outgoingsequence into+8dac and peer acknowledgment into+8db0. These four fields must not be conflated. Existing Python Feedback initial1/0 agrees; earlier CHANNEL-EVIDENCE phrasing that sender uses “corresponding fields” is too vague and does not identify the outgoing counter.

Receiver duplicate/out-of-order branch compares int32 incomingsequence<=lastreceived, not a modular half-range ordering rule. Therefore we have no basis to silently accept a positive-to-negative wrap as a new forwardsequence. Explicit local bounded reconnect before outgoing signed range exhaustion is a resilience choice, not an observed server requirement. Sequence reset belongs to a new channel generation.

## Application reliable filtering
PacketReliable61 controls an application-message filter independently of GNS delivery. Native engine08b010 andchannel0c0f80/0c1010/0c10b0 plusclientfilter08b0e0 show acovered reliable sequence blocksall subsequentmessages except61 until thefilterisremoved; a nonreliable61 removes it. Preserve this lifecycle and currentmessagecontext instead of treating61 asanignorednotification.

## Outgoing scheduling boundaries
Nativeengine0642d0 constructs CNETMsg_Tick only onceFULL andoutsideDemo; its tickvalue islastsuccessfullyreceivedentitysnapshot, including-1afterresync, not sourceclock. BeforeFULL,064ae0 flushes connecting/reliabledata whenCanPacketallows; no fabricatedvalidsnapshotACKisneeded. Native064120 useschannelcheckpoint→TransmitUpToCheckpoint andthenresetsper-sendstatistics. Native gameinput scheduling and command-history bookkeeping are separable from observer snapshotfeedback; no movement-command synthesis isnecessary for eventprojection. Cadence bounds should retainGNSbackpressure andchannelreadiness, and remain separate fromprotocolmessagecontents.

CanPacket atnetwork0bd150 rejects explicittransmit-suppression, a nonzero internal channel gate(+8fdc), or GNS queue-time>=0x8236 microseconds(33,334us); it refreshes realtimeconnectionstatus beforechecking. This is transport backpressure rather than a fixed “send onceeveryNseconds” wire rule. Native0c20f0 incrementsreceivedsequenceonlyforParseMessagesDemo; it is not an ordinary live receive counter update and must not be copied into live framing.

## Reconnect on a retained channel
Fixed CNetChan vtable2358a0 slots118/120 both resolve to0bb650. That routine resets three outbound bit buffers and their checkpoint markers plus8ce2; it does not touch sequence counters8da8/8dac or SDK connection ownership. Engine baseClear07b760 invokes118, andserverforcedReconnect0c4f40 invokes120 before sending SignonStateCONNECTED/-1. Thus the retained-channel world reset case preserves sequence ownership while clearing unsent application buffers. A newly constructed channel still starts1/0. Do not apply constructor initialization to every world/sign-on generation.

Server0c4f40 explicitly sends SignonState after changing toCONNECTED; the inspected reconnect mechanism needs no arbitrary server console execution. Ordinary StringCmd handler06a270→080480 queues text into the game's command interpreter, a broad gameplay/UI surface that the headless receiver does not reproduce. Keep any future necessary observer control command explicitly recognized and source-evidenced; never forward received strings to OS shell or a general console.
