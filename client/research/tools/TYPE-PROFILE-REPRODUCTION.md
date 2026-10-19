# Reproduce fixed-build type evidence

Read-only analysis of the locally obtained official modules. Do not publish raw modules or execute them as OS programs. Native function emulation uses isolated Unicorn memory and controlled dictionary lookups.

Tools: Python3.12, capstone5.0.6, unicorn2.1.4. Install research dependencies only in a dedicated environment.

- `python extract-enum-profile.py /path/to/client.dll client-enum-registration-evidence.json`
- `python extract-enum-profile.py /path/to/server.dll server-enum-registration-evidence.json`
- `python emulate-type-selection.py /path/to/networksystem.dll primitive-type-catalog.json native-type-selection-emulation.json`

Use the hashes in module-manifest.json and manifest8766757721818354077. Compare normalized enum base names and explicit signedness across both modules; preserve array bounds separately. The extractor reports unresolved constant arguments instead of inventing them. Constructor width may be array storage width, so it is evidence, not a decoder bit-width parameter.

For boxed type origin, follow the concrete generated constructor and module type-array addresses in boxed-type-authority.json. The model input flags in scalar emulation are not a substitute for that constructor evidence.

For the separately pinned resource manifest2520908610273941189, `read-vpk-resource.py /path/to/pak01_dir.vpk replay_compat /private/output.txt` locates the entry and checks CRC when the matching numbered archive is present. Inspect core and csgo mounts separately. The factual profile records hashes and sections; RenamedTypes and FieldTypeAliases have different native purposes.

## Workspace layout for the saved codec harnesses

Run the harnesses from a workspace root with research files at `.agent-tmp/gotv-research-plan`, the exact official modules under `.agent-tmp/gotv-tools/cs2/game`, and the pinned comparison parser checkout at `.agent-tmp/gotv-parser-audit`. These are local inputs, never downloaded or executed by the harnesses. Python helper imports resolve beside the saved script; no `/tmp` helper source or machine-specific `/workspace` prefix is required.

For field paths, first run `node .agent-tmp/gotv-research-plan/tools/gotv-fieldpath-model.mjs`, which writes `field-path-model-cases.json` in the research directory, then run the corresponding `gotv-emulate-fieldpaths.py` using the dedicated Python environment. The comparison model remains the pinned parser source, not the new implementation being tested.

The string-table empty-data harness uses engine2, so its reused PE loader checks the engine2 hash rather than the networksystem hash. Geometry, coordinate, matrix-coordinate, angle and metadata lookup harnesses use the fixed networksystem loader. Native imports are not enabled by moving these helper paths.

The comparison checkout is osztenkurden/cs2parser commit deced963b86d3ec26b28a225824130fdf9fe3167 with the frozen observer patch from this repository before unified implementation. Patch SHA256:0548399a63d7b24048b4cc7ab0a6108d0386a126c5149ba6674eafc1b4f68532. Its required comparison source hashes are:
- quantizedFloat.ts:f4d02d9df49ec3226aab87ae5df9a481ebcf4baeb80898fecb2581d4ae037df3
- fieldPathOps.ts:ae0cf5b57cb2d5c54af96b222bded0f97a0d3a1d784268bc338e8b4320161eda
- ubitreader.ts:bb314d2f45692f90cdc23c48a5a555d79c88497b0e201a30465b2ddace877bbb

After removing temporary helper imports, the locally rerun native evidence remained: field paths1780/1780, empty string-table data4/4, normal/precise geometry352/352, coordinates144/144, integral coordinates96/96, matrix coordinate input/consumption384/384, angle bitcounts90/90 and metadata lookup5/5. Matrix verification stops before rendering conversion; no live, DLL-loader or Windows game claim is implied. Generated-type classifier and Python syntax checks also completed. The older quantizer comparison scripts intentionally report mismatches with the frozen parser; those findings are not a passing current implementation test.

Integral aggregate cross-check: run tools/gotv-emulate-integral-coordinate-aggregate.py from the documented workspace root. The fixed networksystem hash is enforced by the shared aggregate loader. Expected result:1024/1024; dimension8 stops before matrix conversion.

Configured float read matrix: run gotv-emulate-quantized-configured-read.py to create local native vectors, then node tools/verify-quantized-configured-read.mjs. The harness uses the saved native configuration bytes and emits a canonical full-vector hash; the standalone research model is saved beside the verifier. The pinned reader hash is checked before use. Expected:194 configurations,5400 native reads and5400 exact output/consumption matches. The large generated vector file is reproducible locally and is not required as a published client artifact.
