# Network world lifecycle and renderer boundary

Fixed manifest8766757721818354077; engine2 andclient hashes in module-manifest.json. Reference interfaces pinned toAlliedModders/s2sdk5864d8d.

## Load/readiness
Maintain per-group handle, parent, manifest-complete state, creation tick/sequence and current session ownership. Engine080b60 ignores alreadyloaded/loading duplicates;083690 only appends toknown incomplete manifests;083a30 can advance globalcreation sequence even when its specific group isunknown. A globalmaximum is not per-group readiness.
SDK SpawnGroupState_t names state8 asentities-spawned. Native05ac30 sets8; its completion chain can call080760, which sends reliable LoadCompleted13 only for a validnonzerohandle and currentchannel. Parent/child prerequisites returnwait/satisfied/failed; canceled/missing parent fails. The observer's substitute is a network-data world, with serializer/table/entity prerequisites resolved. It doesnotclaim toload graphicsassets.

## Unload and cancellation
Engine083d60 records destructiontick from the Unload message through virtuale0→05ac70(group+284), then081410 removes/deactivates the activegroup. For a still-loadinggroup, it sets cancellationflag8; previously inspected prerequisitefunctions see this flag andreturnfailed, so a stale async completion must never sendready afterward. Unknown groups arediagnosed/ignored andmustnot create newstate.

Client CSpawnGroupMgrGameSystem interface is mapped fromSDK toRTTI primaryvtable181b0a6f8. UnloadSpawnGroup3ef0a0 queues auniquegroup handle. SpawnGroupShutdown3eb360 marks pendingcleanup andrecords the group. Frameprocessing3b25d0 checks GetDestructionTick(slot78→engine0597c0) against the suppliedcurrenttick; only then calls3e9ee0 with force=false. Assembly at3b2a33 explicitlyzerosR8, proving this flag. Forcedflush3e8950 passestrue.

3e9ee0 enumerates entities belonging to the group, but ordinary(force=false) cleanup deletes only client-local entityindices above0x3fff; network entityindices areleft to their network lifecycle. Forcedshutdown can deleteboth. Therefore a headless observer must not invent bulknetwork entitydeaths/deletions on ordinaryworldUnload. Retire/cancelworld jobs, preserve destructiontick, and let authoritative snapshotleave/delete/serialreplacement rules own networkentities. Connection/map reset stillclears the wholeoldgeneration.

This is the specific cross-module basis for avoiding rendering/precache implementation while keeping networkentitiescorrect. It doesnot assert allclient.dll gameplay/rendering functions wereanalyzed. No nativegameclient waslaunched and no liveacceptance is claimed.
