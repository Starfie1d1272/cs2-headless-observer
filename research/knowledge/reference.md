# 已核实结论参考

## 版本与取证

### BUILD-001 · 用摘要绑定研究对象

地址与调用关系绑定各模块 SHA-256；PE 时间戳、PatchVersion、ClientVersion、SourceRevision、引擎构建号及 Steam build ID 是不同标识，不能互换。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：engine2, networksystem, client, server, schemasystem, tier0。

证据：[MODULE-CLOSURE-INVENTORY.md](../references/MODULE-CLOSURE-INVENTORY.md)；[module-manifest.json](../data/module-manifest.json)。

### BUILD-002 · 内容资源独立固定版本

兼容配置来自内容 depot2347770/manifest2520908610273941189；模块来自二进制 depot2347771/manifest8766757721818354077。两个来源分别记录版本，VPK 条目按 CRC 核验。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：client。

证据：[SERIALIZER-CONTRACT.md](../../docs/protocol/SERIALIZER-CONTRACT.md)；[replay-compat-resource-profile.json](../data/replay-compat-resource-profile.json)。

### BUILD-003 · 旧录像不是新构建判据

已有录像的 patch/build 为14178/10896，固定研究模块为14191/10924。旧样本的完整重放一致性只证明该样本回归，不能证明新构建全部分支。

适用范围：既有 Demo 样本14178/10896与固定研究模块14191/10924的版本比较

验证方式：fixture-observation；涉及模块：engine2, networksystem。

证据：[SERIALIZER-CONTRACT.md](../../docs/protocol/SERIALIZER-CONTRACT.md)；[fixture-type-authority.json](../data/fixture-type-authority.json)。

## 类型与 schema

### TYPE-001 · 类型、编码器与逻辑转换分层

固定目录包含32个原始类型条目和20个编码器条目。类型类别与维数、字段指定 encoder、自定义 serializer、应用后的逻辑值是不同层。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：networksystem。

证据：[SERIALIZER-CONTRACT.md](../../docs/protocol/SERIALIZER-CONTRACT.md)；[primitive-type-catalog.json](../data/primitive-type-catalog.json)；[encoder-family-catalog.json](../data/encoder-family-catalog.json)。

### TYPE-002 · 嵌套引用按名称和版本解析

嵌套及多态 serializer 引用按名称与接收版本共同查找；该固定兼容元数据路径的类根选(className,0)。只按名称覆盖会合并本来不同的定义。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：networksystem。

证据：[SERIALIZER-CONTRACT.md](../../docs/protocol/SERIALIZER-CONTRACT.md)；[fixture-type-authority.json](../data/fixture-type-authority.json)。

### TYPE-003 · 不同名字表有不同大小写规则

primitive、enum、boxed、custom serializer 的相应查找不区分大小写；资源别名的 prefix 规则不区分大小写、exact 规则区分；PointerFieldTypes 按字段名精确匹配。不能统一小写化所有字符串。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：networksystem, client。

证据：[SERIALIZER-CONTRACT.md](../../docs/protocol/SERIALIZER-CONTRACT.md)；[lookup-case-authority.json](../data/lookup-case-authority.json)；[pointer-compat-dispatch.json](../data/pointer-compat-dispatch.json)；[custom-wire-authority-review.json](../data/custom-wire-authority-review.json)。

### TYPE-004 · 显式自定义 serializer 的权限范围

真实 compiled-field 选择器先解析已注册自定义 serializer，再做 primitive 回退；fake-field 构造顺序不同。识别 ehandle 的显式 wire 类别不等于给所有未知 CEntityHandle 类型添加整数别名。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：networksystem, client, server。

证据：[SERIALIZER-CONTRACT.md](../../docs/protocol/SERIALIZER-CONTRACT.md)；[custom-wire-authority-review.json](../data/custom-wire-authority-review.json)。

### TYPE-005 · 动态容器不能丢掉元素类型

识别五种已证实 vector 前缀，保留容器形状；有多个模板参数时，该 native 路径选第一个元素类型部分，不把 NetworkVar 附加参数当元素名。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：networksystem, client, server。

证据：[SERIALIZER-CONTRACT.md](../../docs/protocol/SERIALIZER-CONTRACT.md)；[native-boxed-type-profile.json](../data/native-boxed-type-profile.json)。

### TYPE-006 · char 数组有专门规则

char[N>1] 在真实 compiled-field 路径是单个字符串访问器，绕开普通固定数组 serializer；char[1] 不在这个特例内。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static+isolated；涉及模块：networksystem。

证据：[SERIALIZER-CONTRACT.md](../../docs/protocol/SERIALIZER-CONTRACT.md)；[fixed-array-boundary-emulation.json](../data/fixed-array-boundary-emulation.json)。

### TYPE-007 · 兼容配置不是一张万能别名表

FieldTypeAliases、RenamedTypes、PointerFieldTypes、UserDefinedSerializerLookup 分工不同。类型替换最多16次；不能把重命名匹配关系全部当作 decoder 类型别名。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：client, networksystem。

证据：[SERIALIZER-CONTRACT.md](../../docs/protocol/SERIALIZER-CONTRACT.md)；[replay-compat-resource-profile.json](../data/replay-compat-resource-profile.json)。

### TYPE-008 · boxed 类型有原生网络映射依据

两游戏模块的签名匹配构造器集合各83次调用、9个基础类型；包括 GameTime_t→float32、GameTick_t/CEntityIndex/CPlayerSlot/HSequence→int32、ResourceId_t→uint64。映射来自生成字段注册，不只来自 C++ 存储声明。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：client, server, schemasystem, networksystem。

证据：[SERIALIZER-CONTRACT.md](../../docs/protocol/SERIALIZER-CONTRACT.md)；[native-boxed-type-profile.json](../data/native-boxed-type-profile.json)；[boxed-type-authority.json](../data/boxed-type-authority.json)。

### TYPE-009 · enum 有符号性不能猜

两游戏模块匹配集合各37项注册、36种基础 enum，符号性一致。收到的 var_enum_info 优先；固定注册事实可补已证实的未注释名字，不能对所有未知名字默认 unsigned。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static+isolated；涉及模块：client, server, networksystem。

证据：[SERIALIZER-CONTRACT.md](../../docs/protocol/SERIALIZER-CONTRACT.md)；[native-enum-type-profile.json](../data/native-enum-type-profile.json)；[native-type-selection-emulation.json](../data/native-type-selection-emulation.json)。

### TYPE-010 · 数组总宽度不是元素位宽

生成注册器的宽度参数可表示整个数组；例如 MedalRank_t 六元素构造宽度24。元素类型和数组长度要分别保留。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：client, server。

证据：[SERIALIZER-CONTRACT.md](../../docs/protocol/SERIALIZER-CONTRACT.md)；[client-enum-registration-evidence.json](../data/client-enum-registration-evidence.json)；[server-enum-registration-evidence.json](../data/server-enum-registration-evidence.json)。

### TYPE-011 · 模块类型令牌不是 builtin ID

F000…类型令牌通过模块提供的类型数组替换；不能直接把末尾索引解释为 schemasystem builtin 编号。GameTime_t/GameTick_t 的模块数组和 builtin 名称表已交叉核对。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：client, schemasystem。

证据：[SERIALIZER-CONTRACT.md](../../docs/protocol/SERIALIZER-CONTRACT.md)；[boxed-type-authority.json](../data/boxed-type-authority.json)。

## 标量与量化

### SCALAR-001 · 有符号定宽值在 wire 解码时扩展

signed fixed8 的0xff在解码阶段已是-1；fixed32 同样按有符号语义处理，不能先当255/无符号值再假设存储层会修正。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-isolated；涉及模块：networksystem。

证据：[SERIALIZER-CONTRACT.md](../../docs/protocol/SERIALIZER-CONTRACT.md)；[scalar-codec-emulation.json](../data/scalar-codec-emulation.json)。

### SCALAR-002 · float64 默认 wire 并非64位

该固定默认 float64 路径先读取 float32 再扩为 double。类型名称不等于 wire 位宽。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-isolated；涉及模块：networksystem。

证据：[SERIALIZER-CONTRACT.md](../../docs/protocol/SERIALIZER-CONTRACT.md)；[scalar-codec-emulation.json](../data/scalar-codec-emulation.json)。

### SCALAR-003 · 聚合维数与存储布局分离

Quaternion 默认4分量，CTransform/CTransformWS 默认中间表示6分量，matrix3x4系列默认8维；不能直接按 C++ 内存大小消费位流。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static+isolated；涉及模块：networksystem。

证据：[SERIALIZER-CONTRACT.md](../../docs/protocol/SERIALIZER-CONTRACT.md)；[aggregate-codec-emulation.json](../data/aggregate-codec-emulation.json)；[primitive-type-catalog.json](../data/primitive-type-catalog.json)。

### SCALAR-004 · 二进制块允许目录维数0

CUtlBinaryBlock 为类别6、目录维数0；读取 varuint 字节长度并复制对应字节，不走普通标量维数校验。72个跨位对齐原生用例验证了输出和游标。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-isolated；涉及模块：networksystem。

证据：[SERIALIZER-CONTRACT.md](../../docs/protocol/SERIALIZER-CONTRACT.md)；[binary-field-emulation.json](../data/binary-field-emulation.json)。

### QF-001 · 量化上下界必须保留字段 presence

省略 low/high 时先使用 native sentinel，再按位宽初始化；省略 high 不恒为1或0。8位默认255、16位65535、31位经float32为2147483648；显式 low=high=0 是非法范围。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static+isolated；涉及模块：networksystem。

证据：[SERIALIZER-CONTRACT.md](../../docs/protocol/SERIALIZER-CONTRACT.md)；[quantizer-native-default-bounds.json](../data/quantizer-native-default-bounds.json)；[quantizer-default-bounds-comparison.json](../data/quantizer-default-bounds-comparison.json)。

### QF-002 · 量化运算需要原生舍入次序

float32 中间舍入、有符号32位 shift/subtraction、整数范围严格下一次幂、位宽增长的<比较、倍率逐ULP下调及+0.5量化判定均会影响结果，不能统一改为JavaScript双精度数学。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static+isolated；涉及模块：networksystem。

证据：[SERIALIZER-CONTRACT.md](../../docs/protocol/SERIALIZER-CONTRACT.md)；[quantizer-research-model-comparison.json](../data/quantizer-research-model-comparison.json)；[quantizer-javascript-model-comparison.json](../data/quantizer-javascript-model-comparison.json)。

### QF-003 · 初始化与读值需要分别验证

已保存194种配置下5400次原生读值的输出字节及位消费对照；初始化参数一致本身并不能证明实际读值算术一致。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-isolated；涉及模块：networksystem。

证据：[SERIALIZER-CONTRACT.md](../../docs/protocol/SERIALIZER-CONTRACT.md)；[quantized-configured-read-summary.json](../data/quantized-configured-read-summary.json)；[quantized-configured-read-comparison.json](../data/quantized-configured-read-comparison.json)。

### QF-004 · 原生警告产生的超宽配置有明确边界

已观察到某些配置派生33/34/42/48位；不能将它们不加区分传给32位读取器，也不能把这些构造用例称为实际比赛已发生的故障。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-isolated；涉及模块：networksystem。

证据：[SERIALIZER-CONTRACT.md](../../docs/protocol/SERIALIZER-CONTRACT.md)；[quantizer-javascript-model-comparison.json](../data/quantizer-javascript-model-comparison.json)。

## 坐标与几何

### COORD-001 · 坐标配置整体缺失与部分缺失不同

六个接收宽度均须在1..31，且max(integer,integer_mp)+3+max(fraction,fraction_mp)<=32。整个配置缺失时，固定client给出14,5,11,3,11,20；已出现但缺字段不能用该默认逐项补齐。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：engine2, client, networksystem。

证据：[SERIALIZER-CONTRACT.md](../../docs/protocol/SERIALIZER-CONTRACT.md)；[coordinate-default-profile.json](../data/coordinate-default-profile.json)。

### COORD-002 · normal 重建有 float32 与边界裁剪

normal向量按接收profile读取，重建Z时保留float32中间舍入；X²+Y²至少为1时Z幅度裁为0。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-isolated；涉及模块：networksystem。

证据：[SERIALIZER-CONTRACT.md](../../docs/protocol/SERIALIZER-CONTRACT.md)；[geometry-codec-emulation.json](../data/geometry-codec-emulation.json)；[geometry-profile-boundary-emulation.json](../data/geometry-profile-boundary-emulation.json)。

### COORD-003 · 普通坐标聚合不是逐分量同编码

coord维数1/3/6受支持；6维先三条普通坐标，再三位存在掩码和第二组三条条件坐标。8维到矩阵转换入口前也使用这两组三维输入；这里记录的是wire输入，不是最终渲染矩阵。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-isolated；涉及模块：networksystem。

证据：[SERIALIZER-CONTRACT.md](../../docs/protocol/SERIALIZER-CONTRACT.md)；[coordinate-codec-emulation.json](../data/coordinate-codec-emulation.json)；[matrix-coordinate-wire-emulation.json](../data/matrix-coordinate-wire-emulation.json)。

### COORD-004 · 整数坐标的第二组三维仍可含小数

coord积分编码的6/8维仅前三分量为integral；第二组三维使用存在掩码及普通带小数坐标。1024个原生样例验证了两个输入三元组及位消费。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-isolated；涉及模块：networksystem。

证据：[SERIALIZER-CONTRACT.md](../../docs/protocol/SERIALIZER-CONTRACT.md)；[integral-coordinate-aggregate-emulation.json](../data/integral-coordinate-aggregate-emulation.json)。

### ANGLE-001 · 三个零位宽角度路径不同

qangle bitcount0使用三位分量存在掩码后读取普通坐标；qangle_precise0使用profile角度分量；qangle_pitch_yaw的0与32读取两个原始float32并补零roll。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-isolated；涉及模块：networksystem。

证据：[SERIALIZER-CONTRACT.md](../../docs/protocol/SERIALIZER-CONTRACT.md)；[qangle-zero-emulation.json](../data/qangle-zero-emulation.json)；[angle-zero-config-emulation.json](../data/angle-zero-config-emulation.json)。

### ANGLE-002 · profile宽度和字段bitcount不是同一个来源

精确角度profile31按360/2^31构造；显式字段bitcount32走另一个标量读取分支。不能因数字接近而共用一条shift规则。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static+isolated；涉及模块：engine2, networksystem。

证据：[SERIALIZER-CONTRACT.md](../../docs/protocol/SERIALIZER-CONTRACT.md)；[geometry-profile-boundary-emulation.json](../data/geometry-profile-boundary-emulation.json)；[angle-bitcount-emulation.json](../data/angle-bitcount-emulation.json)；[angle-bitcount-emulation.json](../data/angle-bitcount-emulation.json)。

### ORIGIN-001 · cell位宽由量化配置决定

原生origin回调读量化配置byte1e上位；非零时为cell shift，零时回退10。range512得到9，range1024得到10，不能通用硬编码9。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static+isolated；涉及模块：client, networksystem, tier0。

证据：[SERIALIZER-CONTRACT.md](../../docs/protocol/SERIALIZER-CONTRACT.md)；[origin-cell-width-comparison.json](../data/origin-cell-width-comparison.json)；[origin-cell-native-configurations.json](../data/origin-cell-native-configurations.json)。

### ORIGIN-002 · 网络origin与渲染绝对位置分开

固定默认g_nConfigMaxCoord/g_flConfigMaxCoord为16384；cell先缩为ushort，再按原生int32/float32次序与fraction合成。缺cell/fraction不补零；未应用父变换的结果只称网络origin。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：client, tier0。

证据：[SERIALIZER-CONTRACT.md](../../docs/protocol/SERIALIZER-CONTRACT.md)；[origin-tier0-profile.json](../data/origin-tier0-profile.json)。

## 字段路径

### PATH-001 · 深度上限10不是结构存储容量12

固定CFieldPath普通协议深度为10，结构inline short容量12不等于可用深度；旧解析器七项tuple也不是native上限。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static+isolated；涉及模块：networksystem。

证据：[SERIALIZER-CONTRACT.md](../../docs/protocol/SERIALIZER-CONTRACT.md)；[field-path-depth-emulation.json](../data/field-path-depth-emulation.json)；[field-path-depth-limit-probe.json](../data/field-path-depth-limit-probe.json)。

### PATH-002 · 完整列表以根32767终止

完整字段列表在操作分派后、追加字段前检查根32767；不仅opcode39能终止，PlusN也能产生该根哨兵。子分量32767不能被一概当终止。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-isolated；涉及模块：networksystem。

证据：[SERIALIZER-CONTRACT.md](../../docs/protocol/SERIALIZER-CONTRACT.md)；[field-path-codebook-boundaries.json](../data/field-path-codebook-boundaries.json)；[field-path-termination-probe.json](../data/field-path-termination-probe.json)。

### PATH-003 · Huffman同频节点次序影响码表

固定40权重先至少取1；小权重优先，同频以更大序号优先；第一次弹出为左子、第二次为右子。原生派生40码字与成熟解析器全部17位前缀表一致，最大码长17。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static+isolated+reference；涉及模块：networksystem。

证据：[SERIALIZER-CONTRACT.md](../../docs/protocol/SERIALIZER-CONTRACT.md)；[huffman-codebook-authority.json](../data/huffman-codebook-authority.json)；[huffman-reference-comparison.json](../data/huffman-reference-comparison.json)。

### PATH-004 · 操作返回值不能代替溢出检查

底层路径增量使用有符号16位存储，部分运算会环绕；截断可能留下部分修改。五字节varint的native容忍行为不等于合法最终路径，发布实体前须检查完整解码成功。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-isolated；涉及模块：networksystem。

证据：[SERIALIZER-CONTRACT.md](../../docs/protocol/SERIALIZER-CONTRACT.md)；[field-path-invalid-probe.json](../data/field-path-invalid-probe.json)。

## 容器与对象

### CONTAINER-001 · 固定长度与动态长度分开

普通固定数组访问器在encoded-size=false时使用声明extent且不读长度payload；动态大小读取varuint。fake-field容器统一读取路径不能直接替代普通固定数组规则。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-isolated；涉及模块：networksystem。

证据：[SERIALIZER-CONTRACT.md](../../docs/protocol/SERIALIZER-CONTRACT.md)；[fixed-array-boundary-emulation.json](../data/fixed-array-boundary-emulation.json)；[container-codec-emulation.json](../data/container-codec-emulation.json)。

### CONTAINER-002 · 多态候选是1起始

指针存在位后，存在且多态时读取UBitVar候选号，按1起始选表项。该选择随实体/序列化状态保留，不能写回所有实例共享的schema字段。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static+isolated；涉及模块：networksystem。

证据：[SERIALIZER-CONTRACT.md](../../docs/protocol/SERIALIZER-CONTRACT.md)；[container-codec-emulation.json](../data/container-codec-emulation.json)；[metadata-lookup-emulation.json](../data/metadata-lookup-emulation.json)。

### CONTAINER-003 · 数组缩小要删除越界字段

MergeDeltas按新数组长度裁去越界旧字段；仅更新length属性会残留错误数据。旧序列化metadata中未被覆盖的记录仍可保留，不能把保留metadata等同活对象字段。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static+synthetic-integration；涉及模块：networksystem。

证据：[SERIALIZER-CONTRACT.md](../../docs/protocol/SERIALIZER-CONTRACT.md)；[metadata-lookup-emulation.json](../data/metadata-lookup-emulation.json)；[native-entity-fields-comparison.json](../data/native-entity-fields-comparison.json)。

### CONTAINER-004 · 指针消失或换类会销毁逻辑后代

ordinary Decode中，指针变空销毁对象；同类保持对象；多态类变化销毁再创建。fake serializer跳过实际分配不意味着普通逻辑字段可以继续显示旧后代。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static+synthetic-integration；涉及模块：networksystem。

证据：[SERIALIZER-CONTRACT.md](../../docs/protocol/SERIALIZER-CONTRACT.md)；[native-entity-fields-comparison.json](../data/native-entity-fields-comparison.json)。

### CONTAINER-005 · metadata查找有明确优先级

当前临时记录优先，其次可选外部metadata helper，最后保留的序列化metadata。已单独验证没有外部helper时的覆盖/回退；helper分支依据静态代码。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static+isolated；涉及模块：networksystem。

证据：[SERIALIZER-CONTRACT.md](../../docs/protocol/SERIALIZER-CONTRACT.md)；[metadata-lookup-emulation.json](../data/metadata-lookup-emulation.json)。

## 自定义字段

### CUSTOM-001 · 计数、自增和身份转换各自独立

固定animTime/simulationTime接收计数按1/64还原；minusone接收减1；gameSceneNode包含64位节点身份。不要将这些规则缩减为某一个字段名的补丁。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：client, server, networksystem。

证据：[SERIALIZER-CONTRACT.md](../../docs/protocol/SERIALIZER-CONTRACT.md)；[client-custom-type-candidates.json](../data/client-custom-type-candidates.json)；[server-custom-type-candidates.json](../data/server-custom-type-candidates.json)。

### CUSTOM-002 · fish位置回调不等于最终画面坐标

三轴serialize回调输出字段减去对象基准；两个注册receive变体都把相应对象基准复制到目标，而不把输入scalar直接写入目标。检查型变体要求类别3/维数1，否则不写入。45次隔离执行证明这些回调事实；不把它命名成完整鱼群动画模型。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static+isolated；涉及模块：client。

证据：[SERIALIZER-CONTRACT.md](../../docs/protocol/SERIALIZER-CONTRACT.md)；[fish-position-callbacks.json](../data/fish-position-callbacks.json)。

### CUSTOM-003 · 同一虚表偏移不能证明接口身份

server中180ddb248与180dde7be两处slot0x50调用属于IGameEventManager2::FreeEvent，分别释放hltv_title与hltv_chat事件；并非自定义序列化注册。以调用接收者、数据流及接口声明排除，不能仅靠虚表偏移计数。

适用范围：固定server.dll SHA-256 09e8c04c5f44040155d04fa79a3f43491d542a386f45807ed77785729e5925a9

验证方式：native-static；涉及模块：server。

证据：[custom-registration-exclusions.json](../data/custom-registration-exclusions.json)。

## 实体与快照

### ENTITY-001 · 类ID位宽取ServerInfo

类ID读取位宽由ServerInfo.max_classes的log2+1确定；ClassInfo独立按自己宣布的类数分配并检查索引。后续create读17位serial和一个varuint。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：engine2。

证据：[SERIALIZER-CONTRACT.md](../../docs/protocol/SERIALIZER-CONTRACT.md)；[entity-create-identity.json](../data/entity-create-identity.json)。

### ENTITY-002 · 同槽位不等于同实体

create同时比较类和17位serial；只有两者相同才可复用对象，任一变化先删除再创建。实体索引本身不足以确定玩家身份。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：engine2, client。

证据：[RECOVERY-CONTRACT.md](../../docs/protocol/RECOVERY-CONTRACT.md)；[EVENT-LIFECYCLE-CONTRACT.md](../../docs/protocol/EVENT-LIFECYCLE-CONTRACT.md)；[entity-create-identity.json](../data/entity-create-identity.json)。

### ENTITY-003 · delta_from的presence决定当前协议增量

固定ordinary接收按字段6(delta_from)是否出现分支，而非legacy_is_delta布尔值。显式负delta_from也不是省略该字段。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：engine2。

证据：[RECOVERY-CONTRACT.md](../../docs/protocol/RECOVERY-CONTRACT.md)；[delta-classification-sites.json](../data/delta-classification-sites.json)。

### ENTITY-004 · serialized_entities是字段位长索引

字段13是varuint字节流，依次给适用create/update工作项的字段payload位长；leave/delete/preserve不消费该项，不能把它当另一个实体快照protobuf。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static+synthetic-integration；涉及模块：engine2。

证据：[RECOVERY-CONTRACT.md](../../docs/protocol/RECOVERY-CONTRACT.md)；[native-packet-entities-comparison.json](../data/native-packet-entities-comparison.json)。

### ENTITY-005 · full清基线与倒退full清历史是两件事

每个non-delta都清双实例基线；只有full tick倒退的独立条件才清frame历史。不能合并成每个full清所有历史，也不能只在倒退full清基线。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static+synthetic-integration；涉及模块：engine2。

证据：[RECOVERY-CONTRACT.md](../../docs/protocol/RECOVERY-CONTRACT.md)；[native-snapshot-transactions.json](../data/native-snapshot-transactions.json)。

### ENTITY-006 · 基线是稀疏应用不是整对象替换

create在delta中优先取同类实例基线，缺失取类基线；update的备用基线按表索引取。保存更新基线时合并到另一bank；复用对象上遗漏字段不因稀疏基线被整体擦掉。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static+synthetic-integration；涉及模块：engine2, networksystem。

证据：[RECOVERY-CONTRACT.md](../../docs/protocol/RECOVERY-CONTRACT.md)；[native-packet-entities-comparison.json](../data/native-packet-entities-comparison.json)。

### ENTITY-007 · 当前逻辑字段与历史帧成员集分离

native update修改当前对象字段，不在每个delta前从任意旧帧复制全部属性；历史frame的传输/休眠/视野外集合与双实例基线有不同职责。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：engine2。

证据：[RECOVERY-CONTRACT.md](../../docs/protocol/RECOVERY-CONTRACT.md)；[native-snapshot-transactions.json](../data/native-snapshot-transactions.json)。

### ENTITY-008 · 视野外更新本身不保证实体永久保留

out-of-PVS写独立+1020集合；明确non-transmitted对账按transmitted、dormant及已安排删除判定，不把一次out-of-PVS更新单独当保活许可。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static+synthetic-integration；涉及模块：engine2。

证据：[RECOVERY-CONTRACT.md](../../docs/protocol/RECOVERY-CONTRACT.md)；[native-packet-entities-comparison.json](../data/native-packet-entities-comparison.json)。

### ENTITY-009 · 当前包头不能照搬旧Demo附加PVS位

普通命令迭代器读两位；out-of-PVS读一位create/update；non-transmitted读一位休眠状态。该固定普通路径不再因has_pvs_vis_bits_deprecated增加旧式两位payload。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：engine2。

证据：[RECOVERY-CONTRACT.md](../../docs/protocol/RECOVERY-CONTRACT.md)；[native-packet-entities-comparison.json](../data/native-packet-entities-comparison.json)。

### ENTITY-010 · 缺增量引用不能套当前无关帧

引用帧找不到时native不应用该snapshot；ForceFullUpdate清实例基线并把last_tick_recv置-1。full恢复前忽略delta，ACK来自成功实体提交而非protobuf读取。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：engine2。

证据：[RECOVERY-CONTRACT.md](../../docs/protocol/RECOVERY-CONTRACT.md)；[native-snapshot-transactions.json](../data/native-snapshot-transactions.json)；[cohesive-offline-integration.json](../data/cohesive-offline-integration.json)。

## 字符串表

### TABLE-001 · 表ID包括未投影的表

按创建次序保留所有表及ID，不只计算userinfo/instancebaseline；每个update blob的索引从-1起，递增位为+1，否则varuint+2。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：engine2。

证据：[STRINGTABLE-CONTRACT.md](../../docs/protocol/STRINGTABLE-CONTRACT.md)；[native-string-tables-comparison.json](../data/native-string-tables-comparison.json)。

### TABLE-002 · 历史保存的是解析后的实际key

每个blob独立32项历史，native每项最多31字节加NUL。已有entry更新保留原key，缺key的更新也把解析后的原key加入历史。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：engine2。

证据：[STRINGTABLE-CONTRACT.md](../../docs/protocol/STRINGTABLE-CONTRACT.md)；[native-string-tables-comparison.json](../data/native-string-tables-comparison.json)。

### TABLE-003 · 省略value会清除旧userdata

value presence与key独立；省略value调用零长度SetStringUserData，清除已有非空userdata，而不是沿用旧baseline/userinfo。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static+isolated；涉及模块：engine2。

证据：[STRINGTABLE-CONTRACT.md](../../docs/protocol/STRINGTABLE-CONTRACT.md)；[stringtable-clear-emulation.json](../data/stringtable-clear-emulation.json)。

### TABLE-004 · 固定userdata字节容量与位长不同

固定表分配UserDataSize字节，但读取UserDataSizeBits位，末字节先清零，允许非8倍数位长。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：engine2。

证据：[STRINGTABLE-CONTRACT.md](../../docs/protocol/STRINGTABLE-CONTRACT.md)；[native-string-tables-comparison.json](../data/native-string-tables-comparison.json)。

### TABLE-005 · 压缩表的raw fallback有特定前提

整个表和单entry压缩分别处理；native先验证raw Snappy结构。有效block按声明长度和容量解压；无效Snappy且raw能容纳时复制raw。有效但过大不准改作raw解释。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static+isolated；涉及模块：networksystem, engine2。

证据：[STRINGTABLE-CONTRACT.md](../../docs/protocol/STRINGTABLE-CONTRACT.md)；[table-decompression-emulation.json](../data/table-decompression-emulation.json)。

### TABLE-006 · 普通与备用baseline保留不同索引

类基线通过instancebaseline中的十进制类key定位，备用基线使用表entry index；冒号key不能强行转普通class ID。空userdata不等于成功的空类基线。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：engine2。

证据：[STRINGTABLE-CONTRACT.md](../../docs/protocol/STRINGTABLE-CONTRACT.md)；[RECOVERY-CONTRACT.md](../../docs/protocol/RECOVERY-CONTRACT.md)；[native-string-tables-comparison.json](../data/native-string-tables-comparison.json)；[native-packet-entities-comparison.json](../data/native-packet-entities-comparison.json)。

## 事件与身份

### IDENTITY-001 · userinfo槽位与userid分离

userinfo的table entry index是槽位，CMsgPlayerInfo.userid是另一个身份字段；不能借userid替代槽位来更新表中玩家。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：engine2, client。

证据：[STRINGTABLE-CONTRACT.md](../../docs/protocol/STRINGTABLE-CONTRACT.md)；[EVENT-LIFECYCLE-CONTRACT.md](../../docs/protocol/EVENT-LIFECYCLE-CONTRACT.md)；[event-identity-layout.json](../data/event-identity-layout.json)。

### IDENTITY-002 · 事件type8和type9有不同身份域

固定事件type8 strict_ehandle写val_long，type9 playercontroller写val_short。type9按short -1哨兵或低字节槽位解释，不等于旧userid域。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：client, server。

证据：[EVENT-LIFECYCLE-CONTRACT.md](../../docs/protocol/EVENT-LIFECYCLE-CONTRACT.md)；[event-identity-layout.json](../data/event-identity-layout.json)。

### IDENTITY-003 · 事件handle不是字段压缩ehandle

事件native32位handle为15位索引+17位serial，拒绝0xffffffff/0xfffffffe并比对完整身份；字段ehandle是14位索引+10位serial，invalid0xffffff。不能共用&0x7ff或截短serial。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：client, server。

证据：[EVENT-LIFECYCLE-CONTRACT.md](../../docs/protocol/EVENT-LIFECYCLE-CONTRACT.md)；[SERIALIZER-CONTRACT.md](../../docs/protocol/SERIALIZER-CONTRACT.md)；[event-identity-layout.json](../data/event-identity-layout.json)；[entity-create-identity.json](../data/entity-create-identity.json)。

### IDENTITY-004 · 描述表更换不能重新解释旧事件

事件描述列表替换ID查找并使订阅变脏；已解码事件保留当时描述表/身份。native渲染延后队列可反向遍历，不是源消息顺序的保证。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：client。

证据：[EVENT-LIFECYCLE-CONTRACT.md](../../docs/protocol/EVENT-LIFECYCLE-CONTRACT.md)；[client-event-graph.tsv](../data/client-event-graph.tsv)。

### EVENT-001 · 订阅固定512位且带分配槽位

客户端206清空并序列化16个uint32，按当前服务器event ID置位，附本地分配的playerslot。不能用Steam账号或userinfo userid作为playerslot。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：client, server。

证据：[EVENT-LIFECYCLE-CONTRACT.md](../../docs/protocol/EVENT-LIFECYCLE-CONTRACT.md)；[event-identity-layout.json](../data/event-identity-layout.json)。

### EVENT-002 · 玩家连接订阅与GOTV转发分层

game server校验玩家槽位并注册监听；所检查HLTV forwarding路径把事件保存在signon/reliable/unreliable帧缓冲，不按每个viewer的订阅bitmap逐个过滤。不能直接把两层当同一连接。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：engine2, client, server。

证据：[EVENT-LIFECYCLE-CONTRACT.md](../../docs/protocol/EVENT-LIFECYCLE-CONTRACT.md)；[server-client-handler-comparison.json](../data/server-client-handler-comparison.json)；[hltv-forwarding-edges.txt](../data/hltv-forwarding-edges.txt)。

## 聊天与用户消息

### CHAT-001 · 聊天并非gameevent207

固定client/server嵌入usermessages.proto逐字一致：SayText117、SayText2 118、SayTextChannel119、TextMsg124。解析它们要按各自消息字段，而不是从事件207或控制台画面猜。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：client, server。

证据：[INBOUND-CONTROL-CONTRACT.md](../../docs/protocol/INBOUND-CONTROL-CONTRACT.md)；[client-chat-descriptor.json](../data/client-chat-descriptor.json)；[server-chat-descriptor.json](../data/server-chat-descriptor.json)。

### CHAT-002 · 聊天发送者与模板语义保留原域

SayText2.entityindex是CEntityIndex，默认-1；文本模板与param1..4分别保留，不能认定param2永远是玩家发言。TextMsg是通用文本目标消息，不自动等于玩家聊天。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：client, server。

证据：[INBOUND-CONTROL-CONTRACT.md](../../docs/protocol/INBOUND-CONTROL-CONTRACT.md)；[client-chat-descriptor.json](../data/client-chat-descriptor.json)。

## 消息时间与恢复

### TIME-001 · 网络时钟与snapshot ACK各有权威

net_Tick回退本身不建立新世界或清实体；last_tick_recv来自成功snapshot。不能回显最后一次网络时钟当有效实体ACK。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：engine2。

证据：[TRANSPORT-CONTRACT.md](../../docs/protocol/TRANSPORT-CONTRACT.md)；[RECOVERY-CONTRACT.md](../../docs/protocol/RECOVERY-CONTRACT.md)；[cohesive-offline-integration.json](../data/cohesive-offline-integration.json)。

### TIME-002 · 消息上下文在帧内逐条演进

接收方向启用bit1时，可靠帧hint提供初始上下文，不可靠帧从0开始；正net_Tick或PacketEntities.server_tick在分派前更新上下文并写各消息metadata，可靠重复过滤在后。不能把整包标成最后一个Tick。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：networksystem, engine2。

证据：[GENERATION-TRANSACTION-CONTRACT.md](../../docs/protocol/GENERATION-TRANSACTION-CONTRACT.md)；[TRANSPORT-CONTRACT.md](../../docs/protocol/TRANSPORT-CONTRACT.md)；[message-context-integration.json](../data/message-context-integration.json)。

### TIME-003 · 普通前向接收不等待InstantReplay分片

普通ID70 handler021ba0成功no-op；04ca50/04e8c0属于可选CInstantReplay拦截和回填。其组装/挂载不能变成ordinary live的强制独立ACK或阻塞队列。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：engine2。

证据：[RECOVERY-CONTRACT.md](../../docs/protocol/RECOVERY-CONTRACT.md)。

## 世界与资源

### WORLD-001 · ClearAllStringTables也是世界边界

085d20经slot480→06bd20→0610c0进入共同Clear；重置server_count、last_tick_recv、双基线和frame history，并在原状态大于CONNECTED时降为2。false参数不取消这些重置。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：engine2。

证据：[STRINGTABLE-CONTRACT.md](../../docs/protocol/STRINGTABLE-CONTRACT.md)；[GENERATION-TRANSACTION-CONTRACT.md](../../docs/protocol/GENERATION-TRANSACTION-CONTRACT.md)；[clear-world-dispatch.json](../data/clear-world-dispatch.json)。

### WORLD-002 · 世界组就绪不能等待首次实体full

LoadCompleted针对真实非零handle及当前channel；逻辑世界须有完整manifest、父依赖和decoder准备。SPAWN后才有首次full，把full设为LoadCompleted前提会循环等待。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：engine2, client。

证据：[WORLD-LIFECYCLE-CONTRACT.md](../../docs/protocol/WORLD-LIFECYCLE-CONTRACT.md)；[RECOVERY-CONTRACT.md](../../docs/protocol/RECOVERY-CONTRACT.md)；[clear-world-dispatch.json](../data/clear-world-dispatch.json)。

### WORLD-003 · 创建水位与单组就绪分开

SetCreationTick可在具体组不存在时仍提高全局creation sequence最大值；该最大值不能替代某个组manifest/父依赖已就绪。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：engine2。

证据：[WORLD-LIFECYCLE-CONTRACT.md](../../docs/protocol/WORLD-LIFECYCLE-CONTRACT.md)。

### WORLD-004 · 普通世界卸载不批量制造网络实体死亡

Unload记录destruction tick并取消加载；普通force=false游戏层清理只删除索引大于0x3fff的client-local实体，网络实体由snapshot生命周期处理。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：engine2, client。

证据：[WORLD-LIFECYCLE-CONTRACT.md](../../docs/protocol/WORLD-LIFECYCLE-CONTRACT.md)；[clear-world-dispatch.json](../data/clear-world-dispatch.json)。

### WORLD-005 · manifest资源名只是数据

SpawnGroup manifest外层1位压缩标记+24位长度，压缩是LZSS；内层三个uint16计数及扩展名/目录字典组合资源名。读资源名不等于加载图形，更不是执行文件路径。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：engine2。

证据：[WORLD-LIFECYCLE-CONTRACT.md](../../docs/protocol/WORLD-LIFECYCLE-CONTRACT.md)；[INITIALIZATION-EVIDENCE.md](../../archive/docs/INITIALIZATION-EVIDENCE.md)；[resource-manifest-offline.json](../evidence/resource-manifest-offline.json)。

## 传输与SDK

### NET-001 · 传输压缩不可借用Demo外壳

Source2内层tag1/3可靠、2/4不可靠；3/4用raw LZ4。字符串表的Snappy/raw规则、manifest的LZSS与Demo压缩外壳是不同层。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：networksystem。

证据：[TRANSPORT-CONTRACT.md](../../docs/protocol/TRANSPORT-CONTRACT.md)；[STRINGTABLE-CONTRACT.md](../../docs/protocol/STRINGTABLE-CONTRACT.md)；[CHANNEL-EVIDENCE.md](../../archive/docs/CHANNEL-EVIDENCE.md)。

### NET-002 · 消息ID与protobuf长度允许非字节对齐

普通消息先UBitVar ID，再VarInt32长度和protobuf字节；循环在不足8位时结束，末字节补位不能冒充另一消息。GNS重传/分片不由此消息切分器实现。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：networksystem。

证据：[TRANSPORT-CONTRACT.md](../../docs/protocol/TRANSPORT-CONTRACT.md)；[CHANNEL-EVIDENCE.md](../../archive/docs/CHANNEL-EVIDENCE.md)。

### NET-003 · 四个通道序号各自独立

新channel outgoing=1、incoming=0，peer ACK与last-acknowledged incoming另有字段；接收重复判断为signed int32比较，不是无依据的模半区间回绕算法。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：networksystem。

证据：[TRANSPORT-CONTRACT.md](../../docs/protocol/TRANSPORT-CONTRACT.md)。

### NET-004 · PacketReliable是应用过滤器

61的state=true且tick不新时安装过滤器，过滤除61外的消息；state=false移除。新的true marker更新marker但本身不移除已安装过滤器。它与GNS可靠性和snapshot ACK都不同。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：engine2, networksystem。

证据：[TRANSPORT-CONTRACT.md](../../docs/protocol/TRANSPORT-CONTRACT.md)；[reliable-marker-ownership.json](../data/reliable-marker-ownership.json)。

### NET-005 · 换世界、换client和换channel三种寿命不同

世界Clear保留client可靠marker及实际channel序号；真正changelevel可转移channel后重建client，marker归零但channel序号保留。注册dispatcher也不自动清filter。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：engine2, networksystem。

证据：[TRANSPORT-CONTRACT.md](../../docs/protocol/TRANSPORT-CONTRACT.md)；[reliable-marker-ownership.json](../data/reliable-marker-ownership.json)。

### NET-006 · 原生发送门禁包含GNS排队时间

CanPacket检查显式抑制、内部channel gate及GNS队列时间约33334微秒；固定发送频率并不等于完整原生流控条件。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：networksystem。

证据：[TRANSPORT-CONTRACT.md](../../docs/protocol/TRANSPORT-CONTRACT.md)。

### AUTH-001 · 认证分支由实际服务器challenge选择

auth2与auth3均从正常GNS上下文建立；auth3仍使用合法用户SDK票据。challenge缺服务器ID时，两分支都可由已认证GNS peer补齐，不是允许伪造身份或强制降级。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：engine2, networksystem。

证据：[TRANSPORT-CONTRACT.md](../../docs/protocol/TRANSPORT-CONTRACT.md)。

### AUTH-002 · 直连IP复用官方接口

固定IPv4地址路径构造SteamNetworkingIPAddr并调用SDK1.65 ConnectByIPAddress、零per-connection overrides；P2P和HostedDedicated是另两条地址类型分支。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：networksystem。

证据：[TRANSPORT-CONTRACT.md](../../docs/protocol/TRANSPORT-CONTRACT.md)。

## 初始化与控制

### SIGNON-001 · CONNECTED先userinfo再应答

客户端CONNECTED发送userinfo后再Signon ACK；服务器在CONNECTED应答后提供ServerInfo。只等ServerInfo再首次应答会循环等待，单独ACK也不是完整初始化。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：engine2。

证据：[RECOVERY-CONTRACT.md](../../docs/protocol/RECOVERY-CONTRACT.md)；[TRANSPORT-CONTRACT.md](../../docs/protocol/TRANSPORT-CONTRACT.md)。

### SIGNON-002 · 零CRC是完整schema请求

NEW阶段字符串表回调→ClientInfo→NEW应答；实际server_count/account ID与零send-table CRC请求完整表，非零CRC仅用于真实匹配缓存。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：engine2。

证据：[RECOVERY-CONTRACT.md](../../docs/protocol/RECOVERY-CONTRACT.md)；[INITIALIZATION-EVIDENCE.md](../../archive/docs/INITIALIZATION-EVIDENCE.md)。

### SIGNON-003 · 首个成功full推动SPAWN到FULL

普通06a960先完成实体处理，再086220推进5→6并更新last_tick_recv；不必等待远端另发FULL，也不能只靠远端FULL宣称实体已初始化。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：engine2。

证据：[RECOVERY-CONTRACT.md](../../docs/protocol/RECOVERY-CONTRACT.md)；[cohesive-offline-integration.json](../data/cohesive-offline-integration.json)。

### CONTROL-001 · cvar查询状态有明确区分

消息58响应25复制cookie/name；未知值NotFound1，命令2，受保护3，实际可查询变量0。SetConVar只作用于已注册并标记replicated的变量；服务器文本不授权读取本机秘密或执行系统命令。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：engine2。

证据：[INBOUND-CONTROL-CONTRACT.md](../../docs/protocol/INBOUND-CONTROL-CONTRACT.md)。

### CONTROL-002 · 可选消息不能伪造成新游戏事实

Pause保存暂停状态；ServerSteamID是元数据而非认证依据；PeerList管理peer联系而非玩家userinfo；UserCommands管理命令历史而非事件207。固定74为HltvReplay，不是旧枚举名字Broadcast_Command。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：engine2, client。

证据：[INBOUND-CONTROL-CONTRACT.md](../../docs/protocol/INBOUND-CONTROL-CONTRACT.md)。

### CONTROL-003 · 内部包回调不是隐藏ACK屏障

1073741824/1073741825包回调映射至CDemoRecorder开始/结束记录边界；它们和0xffffffff注册哨兵都不是待发送的公共wire ID，也不是额外实体提交ACK。

适用范围：固定 Windows x64 构建 14191/10924；二进制 manifest 8766757721818354077

验证方式：native-static；涉及模块：engine2。

证据：[INBOUND-CONTROL-CONTRACT.md](../../docs/protocol/INBOUND-CONTROL-CONTRACT.md)；[engine-inbound-bindings.json](../data/engine-inbound-bindings.json)。

