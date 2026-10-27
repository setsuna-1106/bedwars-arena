# 文档索引

- [L1 完整实现规划](l1-implementation-plan.md)：实际代码基线、P0–P9 工作包、依赖/阶段映射及验收；P0–P4 已完成，P5–P9 未实施。

- [四层平台与 L1 范围](decisions/0016-four-level-platform-and-l1.md)：已采用的二维 2v2 最小闭环、工具拆除返还与继承边界；未实现完整 L1。
- [L1 实验参数表 v0.1](rules/l1-experiment-parameters-v0.1.md)：地图坐标、经济、物品/工具、拆建返还、物理战斗、保护、赛程、观测与验收参数已采用；P0–P2 已提供静态定义、世界基础和二维运动；经济/战斗等仍未实现。
- [P0 定义](l1/p0-definitions.md)、[P1 世界基础](l1/p1-world-foundation.md)、[P2 二维运动](l1/p2-physics.md)、[P3 动作观测](l1/p3-actions.md)、[P4 经济与拆建](l1/p4-economy.md)、[协议规格](l1/protocol-v1.md)与[验收场景](l1/acceptance-scenarios.md)：定义已加载校验，动作/反馈/观测实现和玩法场景仍待后续阶段。

- [core 设计断点](core-design-checkpoint.md)：精简上下文、已确认约束与当前世界引擎讨论续接入口。
- [项目整体待确定事项](project-open-questions.md)：按范围、地图/玩法、接口训练、实现验收及 Hypixel 核验区分当前空缺，附建议讨论顺序。
- [W10–W12 与训练衔接决策](decisions/0015-world-schedule-replay-failures-and-training.md)：赛程/终局、快照重放、故障处理和首版训练方向已整组采用；参数和实现待落实。
- [W09 地面物品、容器与独立实体决策](decisions/0014-w09-world-objects.md)：七组设计已整组采用；参数、地图资产及处理器尚未实现。
- [世界引擎与 WorldState 决策](decisions/0013-world-engine-and-state.md)：W01–W09 已列逻辑设计及 W10 基础；后续补充见 0014/0015，完整世界引擎尚未实现。
- [物理与药效确认清单](physics-effects-confirmation.md)：P/F/V 已整组采用；R 继续核验，完整处理器尚未实现。
- [物理与药效参数说明](rules/physics-effects-parameters.md)：具体数值、单位/公式、固定代码来源及证据分层；机器可读目录保留未知值与模拟差异，不自动作为运行配置。
- [Hypixel Bed Wars 规则参考](rules/hypixel-bedwars.md)：现实参照、规则编号、商店/升级/时间表、证据状态和待核对案例。
- [生成器满额计时定向核对](../reports/2026-10-26-generator-timing-review.md)：O11/O15 容量相关证据、已采用的满额计时/积累统计/首次生成与升级启停实验方案及仍待核实的现服一致性。
- [Game End 定向证据](../reports/2026-10-27-game-end-evidence.md)：2025 工作人员关于存活人数与破床优先级的历史说明及未核验边界。
- [拾取与生成器分享定向核对](../reports/2026-10-27-pickup-sharing-review.md)：历史 splitting 讨论的边界、已采用的拾取实验规则及尚未确认的分享资格/产量。
- [架构与目录职责](architecture.md)：当前工程选择、模块边界与依赖方向。
- [接口与时序草案](contracts.md)：已确定的进程内接入边界与实现首个对局前待确定的契约。
- [PlayerState 已确认设计总览](player-state.md)：玩家各层数据归属、生命周期、派生防具及剩余事项；逻辑设计已汇总，L1 玩家状态及二维运动部分已实现。
- [TeamState 已确认设计总览](team-state.md)：五字段与主要行为已设计并实现纯转换，类型/编码与排序见 0012；完整世界集成和 Hypixel 核验仍待完成。
- [TeamState 类型、参考参数与排序实现](decisions/0012-team-core-types-and-ordering.md)：v1 类型/Schema、参数证据、纯转换与事件排序；已实现部分 core，完整世界与 Q15 核验尚未完成。
- [首版策略接入决策](decisions/0002-in-process-agent-interface.md)：Python 进程内调用及未来独立进程适配条件；已接受、待实现。
- [空间表示决策](decisions/0003-grid-terrain-continuous-players.md)：三维方块网格、连续移动、轴对齐矩形及玩家可互相穿过；正式平面加高度 B，前期严格二维 A 实验限制单一行走层。方块单位、水平 `(x, z)` 中心与 `y` 脚底高度已接受；L1 固定地图、二维尺寸与碰撞已实现；三维高度仍待实现。
- [死亡资源与统计决策](decisions/0004-death-resources-and-statistics.md)：携带的铁/金/钻石/绿宝石结算、击杀归属与本局统计跨死亡保留；已接受、待实现，归因窗口与结算边界待定。
- [携带物品与购买进度决策](decisions/0005-inventory-and-progression.md)：背包数量表、容量、手持规则、购买进度四字段、派生防具及死亡分类；已接受、待实现，具体类型、装备属性映射、容量数值及同刻时序等细则待定。
- [生命状态决策](decisions/0006-vitality-and-absorption.md)：普通/吸收生命、伤害消耗次序与复活重置；已接受、待实现，数值和效果细则待定。
- [临时效果决策](decisions/0007-temporary-effects.md)：基础六字段、死亡清理、药水覆盖、来源合并及周期机制；已接受、待实现，具体类型、特殊效果和部分时序待定。
- [冷却与保护决策](decisions/0008-cooldowns-and-protection-effects.md)：主动冷却在玩家外层按组保存、组规则指定死亡清除/保留，保护复用效果记录；已接受、待实现，具体组选择、机制与数值待核对。
- [动作双通道决策](decisions/0009-movement-and-interaction-channels.md)：基础七字段、双通道、持续执行、指令替换、条件失效中断及死亡清空/复活不恢复；已接受、待实现，W08 已补显式取消及输入时序语义；具体类型/编码和未列动作细节继续落实。
- [玩家生命周期结构决策](decisions/0010-player-lifecycle-branches.md)：三分支、公共数据、生命序号、等待/淘汰字段、复活资格、每队固定出生点及出生保护；已接受、待实现，完整字段/类型和转换细节待定。
- [TeamState 基础决策](decisions/0011-team-state.md)：五字段及归属、床/升级/陷阱机制、队伍生命周期与标准初始化；逻辑设计已收尾，共享冷却与触发机制待 Hypixel 核验（Q15），具体类型/数值/全局时序仍待定，尚未实现。
- [开发阶段](roadmap.md)：当前完成范围与后续验收入口。
- [决策记录](decisions/README.md)：工程选择与待决问题。
- [开发指南](../CONTRIBUTING.md)：安装、检查和构建。
- [历史调研](../reports/2026-10-25-project-survey.md)：固定来源及候选比较，不代表最终选型。
