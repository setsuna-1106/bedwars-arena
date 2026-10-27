# 0012：TeamState 类型、参考参数与事件排序 v1

日期：2026-10-26。状态：按用户“具体数值、类型编码及全局时序，根据 Hypixel 规则实现”的要求落地。

## 范围与证据边界

实现已确认的 TeamState、序列化、纯状态转换、参考规则档案与统一事件排序基础。完整 WorldState、玩家物理、商店距离、药效应用、策略接入和训练器没有因此完成。实现入口见 [core](../../src/bedwars_arena/core/)，规则核对见[本次记录](../../reports/2026-10-26-team-rule-verification.md)。

Hypixel 公共补丁没有公开服务器内部字段类型或完整同 tick 流水线。以下类型与排序为本平台 v1 工程约定，不能标成 Hypixel 原生协议。用户已明确的不可主动移除陷阱、允许同种重复、持续停留触发等项目取舍继续保留。

## 类型与编码

- 时间使用每秒 20 tick 的整数仿真时钟，每 tick 为 50 ms；这是本平台名义时间单位，不模拟实际服务器卡顿，也不是对 Hypixel 服务器实时 TPS 的测量。
- tick、数量和等级拒绝 bool、浮点数、负数和超出 JSON 安全整数范围的值；等级从 1 开始，未购升级不保存。秒转换必须精确落在 tick 边界，不隐式取整。
- ID 为 1–128 字符的不透明字符串，不含控制字符；不依赖对象身份、哈希随机化或进程内地址。
- 床编码为 `present` / `destroyed`；存在时 `destroyed_at` 为 JSON `null`，摧毁时为整数 tick。
- 玩家生命投影编码为 `alive` / `respawning` / `eliminated`。`MemberView` 只供 core 从玩家状态构造内部只读投影，不是独立持久化的第二份队员状态。
- 升级和陷阱使用 `UpgradeId` / `TrapType` 的稳定小写字符串。实际名称、历史别名与规则参数分别管理。
- `TeamState` 保留五字段，内部复制输入映射并使用只读映射和元组；`to_dict()` 输出独立的 JSON 值，`from_dict()` 严格检查字段和编码。
- v1 形状见 [JSON Schema](../../schemas/team-state-v1.schema.json)。规则上限、全局实例唯一性、购买者所属队伍还须运行 `validate_team_state()` / `validate_match_teams()`；Schema 本身不代替这些规则检查。

## 数值档案

[内置档案](../../src/bedwars_arena/core/data/hypixel_team_reference_v1.json) 分开保存来源状态，不声明完整现服已核实：

- 历史官方队列档位费用为 1 / 2 / 4 钻石，本参考档案容量为 3；来源为 v1.4 BETA。将其用于参考配置不等于确认当前服务器全模式容量/价格。
- 官方历史效果持续时间：致盲陷阱 8 秒、疲劳陷阱 8 秒、反击陷阱 15 秒、魔法牛奶 30 秒。它们仅作为效果时长目录，不是共享触发冷却，也不代表已实现这些效果的应用。
- 四种常规模式明确区分 Solo/Doubles 与 3v3v3v3/4v4v4v4 的升级费用；独立 4v4 不套用。现有完整升级价格表仍是社区候选，默认不能执行升级购买，只有调用 `load_team_rules(..., accept_community_prices=True)` 才显式使用研究参考值。
- 共享触发冷却继续为未知值 `None`。触发前必须通过 `with_cooldown(ticks, origin=...)` 指定实验/核验值并记录来源，否则抛出 `UnresolvedRuleError`，不会消费陷阱。没有自动填入 20 秒、30 秒或零。
- 实验应保存 `TeamRules.to_dict()`，记录模式、档案版本、社区价格启用标记及冷却覆盖值/来源。恢复时使用 `TeamRules.from_dict()`，不能只保存 seed 或档案名。

## 统一事件顺序 v1

完整排序键为 `(tick, phase, actor_order, event_id)`。`actor_order` 来自开局固定玩家/队伍顺序；`event_id` 为稳定的局内唯一请求/事件标识。它们都不能使用策略调用或字典到达顺序生成优先权。

| phase | 顺序 | 影响 |
| --- | --- | --- |
| `effect_expiration` | 0 | 预留效果到期处理位置 |
| `respawn` | 10 | 已取得的复活资格先处理，不在此按当前床重新撤销 |
| `controls` | 20 | 转向、手持等控制更新位置 |
| `movement` | 30 | 预留移动更新位置 |
| `purchases` | 40 | 同时购买按稳定顺序逐笔重查当前状态/价格 |
| `bed_destruction` | 50 | 已校验的床摧毁结算 |
| `damage_and_death` | 60 | 同刻破床先于死亡，本次死亡依据结算时床状态判断 |
| `team_elimination` | 70 | 从成员状态派生队伍淘汰并记录转换 |
| `traps` | 80 | 仅存活且通过空间/效果资格的敌人参与触发 |
| `outcome` | 90 | 预留世界终局位置，不在这里猜定平局或胜负规则 |

这一顺序解决平台的可重复性；不是 Hypixel 精确内部流水线的核实结论。队列已实现排序/恢复/去重，各 phase 的完整世界处理器尚未实现。

`EventQueue` 不自行运行墙钟。pop 后不能插入排序键落在已提交游标之前的事件；已执行 ID 的去重历史和待执行事件一起保存。相同 ID/相同内容重试不重复执行，相同 ID/不同内容拒绝，不同 ID 即使内容相同也保留为不同请求。

## 状态转换接口与集成要求

- `purchase_upgrade` / `purchase_trap` 返回新 TeamState、支付后的完整库存和成功事件；拒绝时不改变原值或产生成功事件。调用方须把返回结果作为同一次世界提交，不能只提交扣款或等级的一半。
- 库存沿用数量表，支付键为 `diamond`；未修改的物品原样保留，不新增第二份钱包。这里没有完整 PlayerState 的手持与物理处理器。
- `trigger_trap` 返回触发意图，含触发者和 `life_index`，不直接应用尚未定义的药效；完整世界引擎必须将出队/冷却更新与对应结果的应用一起提交。
- `eligible_player_ids`、`can_shop` 和已校验的破床来源是 core 内部规则输入，不能让外部策略直接声明。范围/牛奶/遮挡/商店资格处理器尚未实现，调用者须先计算它们。
- 破床的状态/时刻/事件一次生成，重复破床不重复触发；死亡目的分支在死亡时查询，已等待复活者不再次调用该查询来撤销资格。
- `settle_elimination` 比较同一固定阵容更新前后状态，只在参赛转淘汰时生成事件，保留队伍记录；已淘汰队伍触发/购买被拒绝。
- 新局与快照恢复分别处理；全局恢复至少保存规则、TeamState、玩家/库存、固定阵容顺序与事件队列。当前没有宣称完整 WorldState 快照格式已经落地。

## 验证

标准库 unittest 覆盖价格变化、同等级并发购买、重复陷阱/容量、未知冷却、持续停留与截止边界、丢床/淘汰、全队等待复活、JSON 隔离与恢复、跨队实例 ID 校验、事件到达顺序、重试去重和同刻破床/死亡。

这些是本平台实现测试，不代替 Hypixel 线上实测；Q15 仍待验证。

2026-10-26 实际检查结果：17 项 unittest 在开发安装与仓库外全新 wheel 安装中均通过；语法/JSON/本地链接/CLI 检查、`git diff --check` 通过。已构建 sdist 并从 sdist 构建 wheel，确认包内参考 JSON 随 wheel 安装后可加载。完整对局/训练/物理/药效应用未测，也未进行 Hypixel 线上实测。

可运行的纯转换示例见 [team_transactions.py](../../examples/team_transactions.py)。它要求显式传入实验冷却与来源，没有隐式的 Hypixel 冷却默认值：

```bash
python examples/team_transactions.py --trap-cooldown-ticks 40 --cooldown-origin experiment-only
```

上面的 40 tick 只是示例实验输入，不是 Hypixel 参数；输出为交易/触发意图和规则记录，不运行完整对局。
