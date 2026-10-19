# Fixed-build string-table contract

Research only. Engine2 fixed manifest8766757721818354077. Sources: native ParseUpdate10a9f0, CreateStringTable085e00, UpdateStringTable0860f0, ClearAllStringTables060ec0→085d20; pinned s2sdk INetworkStringTable and independent Clarity/demoinfocs implementations.

## State and wire interpretation
- Retain every created table ID in creation order, including unprojected table types. Keep per-table indexed key/value state for the current generation.
- Entry index starts at-1 for each update blob. Increment bit means+1; otherwise unsigned varint+2 is added to previous index. Both native and reference parsers agree.
- Key history resets per update blob, holds32 entries, each stored as at most31 key bytes plus NUL in native32-byte slots. History references carry5-bit chronological slot and5-bit prefix length, followed by a NUL-terminated suffix.
- The key put into history is the **resolved actual table key** after applying the update, even when the update omits its key. Native existing-entry branch uses GetString(slot40), then unconditional history copy; Clarity also resolves name byindex then adds it tohistory. Therefore the frozen prototype's unconditional empty-string push for keyless updates is incomplete. demoinfocs's only-push-when-key-present implementation is not a complete native oracle either.
- Existing-entry updates retain the original key. New entries use the supplied key and AddString; native table API can impose additional index/count conditions. SetStringUserData(slot48→10b940→110450) receives a zero-length request when value is omitted: native clears prior nonempty data and marks change; already empty is unchanged. Preserve omitted-key separately from empty/omitted-value semantics; do not keep a stale baseline/userinfo payload just because no nonempty value was returned.
- Value-presence bit is independent of key-presence. Variable-size data optionally has a compression bit when flags&1, then UBitVar byte count or17-bit byte count according to table metadata. This build limits individual variable data to0x138800 bytes before reading/decompressing. Local bounds must also cap decompressed payload.
- Fixed-size data allocates UserDataSize bytes but reads **UserDataSizeBits** bits; validates byte capacity and zeroes the last byte before reading. Bit sizes need not be multiples of8. Clarity preserves this distinction. Frozen prototype uses userDataSize as bits and rejects non-byte-aligned values; independent demoinfocs reference also passes UserDataSize instead ofSizeBits. Correct from native evidence, not library consensus.
- CreateStringTable can decompress the whole blob; individual variable-size entries can separately be compressed. Keep these two operations distinct.
- ClearAllStringTables releases the current container, invalidates cached table handles, records map metadata, invokes game module cleanup, then installs an empty/default container. Do not preserve old-generation userinfo/baseline dictionaries after a clear.

## Projection
Userinfo update slot is the string-table entry index. CMsgPlayerInfo.userid is a different identity field; the frozen source comment treating userid as the slot is incorrect. Existing parser reference explicitly guards stale/reused userinfo against the current controller identity. Preserve SteamID/controller serial and generation checks instead of overwriting a new occupant with old cached info.

Instancebaseline needs indexed key retention so keyless updates can resolve the class key. Retain colon-qualified keys and indexed payloads. The frozen ordinary-viewer path already stores indexed alternate payloads separately in onlineBaselineEntries and resolves packet.alternate_baselines; its generic parser skips colon-key class-baseline projection. Preserve that existing distinction, and fix key-history/empty-data behavior without incorrectly claiming alternates are entirely absent.

This document identifies requirements for unified implementation; it does not claim those changes are implemented or tested live.

Native SetUserData empty-request behavior was independently run in isolated emulation for prior sizes0/1/16/128, using external-backed storage flags to avoid allocator operations. All four returned the expected changed flag, zero size and modification tick. No imported function was stubbed or executed. Evidence: stringtable-clear-emulation.json.
