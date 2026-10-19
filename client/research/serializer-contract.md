# Field construction contract, research draft

Fixed module build14191/10924; manifest8766757721818354077. No client implementation changes in this research phase.

## Construction order supported by native evidence

0779c0 recognizes vector-container prefixes and element type, fixed array suffix, aliases (bounded native resolution loop), explicit enum signedness, nested serializer references, primitive category, custom var_serializer override, then encoder and quantization configuration. 079ff0 resolves nested references using name plus version; 077240 includes polymorphic candidate references. This order must be represented explicitly rather than collapsed into field-name exceptions.

- Dynamic vector prefixes: CNetworkUtlVectorBase, CUtlVectorEmbeddedNetworkVar, C_NetworkUtlVectorBase, C_UtlVectorEmbeddedNetworkVar, CUtlVector.
- char[N>1] is specialized as string in0eada0; a scalar char and an arbitrary fixed array are different.
- CStrongHandle maps to uint64; CNetworkedQuantizedFloat to float32.
- Unknown custom name can fall back to recognized native type/registered callback; do not guess an unknown required category or encoder.
- Keep raw wire value, logical field value and derived player/event projection distinct. Signed fixed8/fixed32 already sign-extend in their native wire decoder; do not defer that conversion to a later storage cast.

## Custom scalar accessors inspected

All listed names are registered by both client/server with matching categories and dimensions in the scanned fixed-build registration sites. This is not a claim that arbitrary modules/plugins register no additional names.

| Serializer | Wire family / components | Logical observation |
|---|---|---|
| animTimeSerializer | unsigned /1 | seconds→int(seconds*64+0.5); receive count/64 |
| simulationTimeSerializer | unsigned /1 | same fixed-build time conversion |
| funcRotatingSimulationTimeSerializer | unsigned /1 | sending object flag can force0; receive count/64 |
| ClampHealth | signed /1 | sender clamps nonpositive to0; receiver stores32-bit value |
| minusone | unsigned /1 | sender adds1; receiver subtracts1 |
| angle_normalize_positive | float /1 | sender normalizes angle; receiver storesfloat |
| StepSimulationFuncRotatingAnglesSerializer | float /3 | sender normalizes components; receiver storestriple |
| cellx/celly/cellz | signed /1 | wireinteger is narrowed ushort; derived coordinates use configured cellwidth/range |
| posx/posy/posz | float /1 | fractional position with quantizer bounds, distinct from absoluteposition |
| gameSceneNode | unsigned /1 | includes upper32 node identity; preserve64-bit value |
| gameSceneNodeStepSimulationAnglesSerializer | float /3 | received angles saved directly |
| gameSceneNodeStepSimulationOriginSerializer | float /3 | received triple saved; native local notifications update derivedcoordinates |
| fish_pos_x/y/z | float /1 | sender emits relative offset; receiver callback copies object origin. Additional callback semantics remain open; retain raw value for unused rendering fields |
| ehandle | unsigned /1 | wire14-bit index+10-bit serial; invalid0xffffff. Native handle restoration additionally consults current entity identity |

Accessor addresses are catalogued locally against fixed modules. The primitive type/encoder catalogs already committed in research/ remain authoritative for family and dimension enumeration. Color is a registered primitive unsigned family; an old fixture custom name color alone is not evidence of an unsupported current-build category.

## Reference coverage and old fixture

The old sample has268 serializers with versions0–5, three repeated names across versions, and3 polymorphic entries. Current prototype keys serializer map byname and omits nested version/custom field12/polymorphic metadata at construction. Treat this as a unified schema-model gap; do not apply isolated field patches or claim existing event values are all wrong without a reference-specific comparison.

## Remaining before implementation

Native fake-field reads now confirm pointer presence1bit then (if present/polymorphic) UBitVar 1-based candidate selector, and varuint array length (12 isolated cases). Forty field-path operations match the prototype on1,780 valid-domain examples. Still close versioned forward references, multi-type state replacement, invalid-path handling and full-stream field-path reset. Preserve exact bit alignment even for unprojected fields. Data size, recursion and allocation limits must be explicit local bounds, with a typed failure rather than a guessed skip.

## Quantizer construction correction

Expanded native initialization matrix:160 configurations, with only the diagnostic void Warning import stubbed in emulator memory where required. The frozen parser differs on46 configurations; this is a configuration discrepancy count, not46 independently confirmed live bugs. An independently derived research model now reproduces all160 native outputs, including effective width/flags, float32 low/high, decode multiplier and range multiplier.

Rules needed in the unified implementation: float32 intermediate rounding; native signed32 shift/subtraction behavior; exact-integer strictly-next-power-of-two range and < width-growth comparison; multiplier correction by successive float ULP rather than coarse decimal factors; +0.5 quantization used in sentinel elision. Preserve warned derived-width>31 cases as a separate compatibility boundary. Existing client files remain frozen.
