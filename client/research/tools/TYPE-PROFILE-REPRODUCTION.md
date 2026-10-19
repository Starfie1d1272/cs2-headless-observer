# Reproduce fixed-build type evidence

Read-only analysis of the locally obtained official modules. Do not publish raw modules or execute them as OS programs. Native function emulation uses isolated Unicorn memory and controlled dictionary lookups.

Tools: Python3.12, capstone5.0.6, unicorn2.1.4. Install research dependencies only in a dedicated environment.

- `python extract-enum-profile.py /path/to/client.dll client-enum-registration-evidence.json`
- `python extract-enum-profile.py /path/to/server.dll server-enum-registration-evidence.json`
- `python emulate-type-selection.py /path/to/networksystem.dll primitive-type-catalog.json native-type-selection-emulation.json`

Use the hashes in current-module-manifest.json and manifest8766757721818354077. Compare normalized enum base names and explicit signedness across both modules; preserve array bounds separately. The extractor reports unresolved constant arguments instead of inventing them. Constructor width may be array storage width, so it is evidence, not a decoder bit-width parameter.

For boxed type origin, follow the concrete generated constructor and module type-array addresses in boxed-type-authority.json. The model input flags in scalar emulation are not a substitute for that constructor evidence.

For the separately pinned resource manifest2520908610273941189, `read-vpk-resource.py /path/to/pak01_dir.vpk replay_compat /private/output.txt` locates the entry and checks CRC when the matching numbered archive is present. Inspect core and csgo mounts separately. The factual profile records hashes and sections; RenamedTypes and FieldTypeAliases have different native purposes.
