# Hypixel Bed Wars 规则调研与模拟参照

调研日期：2026-10-25（北京时间）。用户已明确：**本项目的现实参照是 Hypixel 的 Minecraft Bed Wars**。本文是规则资料与待核对清单；没有实现引擎，没有进入 Hypixel 实测，也没有把候选数值加载为项目配置。

后续常用入口为[Hypixel Bed Wars 规则参考](../docs/rules/hypixel-bedwars.md)，已按机制与规则编号整理；本文保留调研过程与证据边界。

## 1. 调研结论与证据边界

Hypixel 的核心闭环是：保护床维持复活资格，收集资源购买装备与团队升级，搭桥争夺区域，破坏敌床，再淘汰敌方玩家。**破床本身不等于立即消灭存活玩家；最后一张床存在也不自动意味着胜利。** [官方玩法简介](https://hypixel.net/play/#games)

它不是一份无版本差异的“通用起床战争规则”。模拟实验至少要固定：规则版本、模式、地图、商店与升级表、轮换物品、挑战/私人房间修饰器，以及三维玩法转成二维时的改动。

本次查到的最新官方 Bed Wars 补丁为 **v1.11.3，发布于 2026-09-29**；这表示公开补丁检索的截止点，不代表取得了线上服务器的完整配置。2026 年 v1.11 系列仍修改了越界伤害、末影珍珠、隐身线索和资源归属等玩法细节。[官方补丁目录](https://hypixel.net/forums/bed-wars-patch-notes.262/)、[v1.11.3](https://hypixel.net/threads/bed-wars-v1-11-3-balancing-qol-bug-fixes.6115422/)

本文使用三类标记：

- **O：官方直接证据。** 官方介绍或发布者的更新首帖。补丁只直接证明对应版本的变更，不能独自保证多年后参数未变。
- **C：社区候选。** 社区 Wiki、资料表或玩家记录，可补全细节，未在本轮实测确认。论坛域名是 hypixel.net 也不等于作者是官方。
- **D：本项目的适配建议。** 对工程与二维抽象的建议，不是 Hypixel 原规则。

Fandom 页面本轮直接访问失败，但搜索服务返回了索引正文；该页自标版本 v1.11.1，并提示内容过时。本文将其作为 C 类参考。第三方插件与 Blockyard 源码不能升级为 Hypixel 的官方证据。来源与争议登记见[来源清单](2026-10-25-hypixel-sources.json)。

## 2. 模式必须分别处理

| 模式 | 队伍数 × 每队人数上限 | 总人数上限 | 模拟时的区别 |
| --- | --- | --- | --- |
| Solo | 8 × 1 | 8 | 单人决策与经济，无队内配合 |
| Doubles | 8 × 2 | 16 | 通常与 Solo 共用地图组，但增加队内协作 |
| 3v3v3v3 | 4 × 3 | 12 | 四队竞争，商店/升级价格与八队模式部分不同 |
| 4v4v4v4 | 4 × 4 | 16 | 四队、每队四人，不等于下列 4v4 |
| 4v4 | 2 × 4 | 8 | 独立模式，不能直接套用四队时间与物品表 |

队伍与人数表由[社区模式资料](https://breezil.github.io/Breezil-Hypixel-Utils/reference/bedwars/game)和[社区 Wiki](https://hypixel.fandom.com/wiki/Bed_Wars)补全，标记 C。人数是容量，不是开局人数门槛，也不规定本项目必须全规模模拟。

O：2019 年官方引入的 4v4 明确是两队四人，并规定移除黑曜石、以收缩边界替代龙、加快比赛及资源速度。2025 年 v1.10 又修复了 4v4 使用旧商店价格的问题。因此它不能只靠把队伍数从四改成二来表达；当前精确参数仍待核对。[4v4 发布说明](https://hypixel.net/threads/bed-wars-v1-6-pop-up-tower-4v4-mode-voidless-new-maps-and-more.2034329/)、[v1.10](https://hypixel.net/threads/bed-wars-v1-10-one-block-bed-wars-community-suggestions-and-more.5961701/)

Dreams 是改变机制的模式集合：例如 Voidless 去掉虚空，Castle 是大规模多床团队战，Swappage 会交换队伍位置，One Block 使用随机物品和极简初始场地。Challenges 也会额外限制购买、资源或行动；私人房间还能改变事件速度等条件。这些都应单独建规则档案，不能混进普通模式基准。[Voidless](https://hypixel.net/threads/bed-wars-v1-6-pop-up-tower-4v4-mode-voidless-new-maps-and-more.2034329/)、[Challenges 与 Swappage](https://hypixel.net/threads/bed-wars-update-challenges-bug-fixes-more.4585683/)、[One Block](https://hypixel.net/threads/bed-wars-v1-10-one-block-bed-wars-community-suggestions-and-more.5961701/)

**D：首版可优先对齐普通模式的共有机制，具体选择 Solo、Doubles 或四队团队模式仍待决定。**

## 3. 床、死亡、复活、淘汰与胜负

| 情况 | 应区分的含义 | 证据 |
| --- | --- | --- |
| 玩家存活，床还在 | 正常行动；死亡后通常可复活 | O 官方玩法简介 |
| 玩家存活，床被拆 | 当前生命继续；后续死亡可能成为最终死亡 | O 官方玩法简介 |
| 玩家死亡，已进入复活等待 | 暂时不能正常行动，不等于永久淘汰 | C：普通等待时间通常为 5 秒 |
| 等待复活时床被拆 | 不能直接照搬“取消复活并淘汰” | O：v0.3 明确改为不因此淘汰；当前边界时序待实测 |
| 无复活资格时死亡 | 最终死亡，结束该玩家参赛生命周期 | O 核心目标；具体归因规则待核对 |
| 队伍所有成员永久淘汰 | 队伍出局 | 由核心胜负目标推导；断线/空队例外待定义 |
| 只剩一个未淘汰队伍 | 正常胜利判定的核心条件 | O 目标 + D 状态表示 |

复活通常为 5 秒的资料来自[社区 Wiki](https://hypixel.fandom.com/wiki/Bed_Wars)，本轮没有线上计时。**普通死亡倒计时、重连倒计时、复活后保护是三个不同参数。** 官方 2021 年补丁为离开后重连加入了 10 秒复活计时；2017 年 v0.6 将出生无敌改为 3 秒，但另一份玩家描述为 5 秒，不能把任一值直接写成已确认的当前参数。[重连变更](https://hypixel.net/threads/bed-wars-update-challenges-bug-fixes-more.4585683/)、[历史出生保护](https://hypixel.net/threads/new-bed-wars-patch-v0-6-is-now-live.1085173/)、[玩家讨论（非官方）](https://hypixel.net/threads/upcoming-bed-wars-update-what-do-you-want-to-see.5735415/post-40400940)

### 必须修正的第三方参照差异

Hypixel **2017-01-24 的 v0.3 官方补丁**明确说明：玩家已死亡时床被拆，不再因此淘汰。这提供了“先死亡取得本次复活资格，随后丢床”的历史官方依据。[原始公告](https://hypixel.net/threads/new-bed-wars-patch-v0-3-now-live-in-the-ptl.979320/)

前轮验证发现 Blockyard 的 destroyBed 会清除等待复活者并永久淘汰。**该段代码适合帮助识别状态，但不能作为 Hypixel 行为照搬。** 未来需覆盖：先死亡后破床、先破床后死亡、同 tick 事件、复活结束瞬间破床及全队等待中破床。当前服务器是否存在特殊例外需实测；本轮未完成。[Blockyard 对应代码](https://github.com/Potrock/blockyard/blob/7daddbec178997236d664bc29975d49801574332/src/games/bedwars/server.ts#L220-L251)

胜负统计中的普通击杀、最终击杀、破床、胜利应分别记录。它们不是同一种奖励；智能体训练的奖励函数属于本项目实验设计，不能冒充游戏原规则。所有床消失后仍可能有多队存活；同时团灭、超时、断线和无人队伍的处理需单列。

## 4. 地图、移动、建造与战斗

O：游戏在岛屿间进行，放置方块可以保护床并建立通路。普通地图包含队伍基地和可争夺区域；资源布局、距离和高度会直接影响经济与进攻成本。官方仍在修复具体地图的铁生成速度和禁建区域，所以不应假定所有地图完全同构。[玩法简介](https://hypixel.net/play/#games)、[v1.11 地图与规则修复](https://hypixel.net/threads/bed-wars-v1-11-dreamfeast.6003011/)

C：需要表达玩家放置的可拆方块、受保护的原始地图方块、基地床、虚空、禁建区与建筑高度。战斗同时涉及伤害和击退，坠入虚空可导致死亡；工具/附魔/状态会改变拆除效率。不能把所有地形统一设成可破坏，也不能仅用两者血量比较替代桥上击退。

O：官方早期补丁就对火球能否破坏末地石等材料作过限制，v1.2 引入了抗 TNT 的防爆玻璃；伤害、拆块和位移不是一个统一的“爆炸半径伤害”规则。[火球与材料](https://hypixel.net/threads/new-bed-wars-patch-v0-6-is-now-live.1085173/)、[防爆玻璃](https://hypixel.net/threads/bed-wars-update-1-2.1369753/)

O：2026 年 v1.11 对高于建筑上限超过一格、累计超过 30 秒的玩家施加逐渐增强的伤害；v1.11.1 又说明计时会逐渐回落，死亡后完全重置。珍珠传送也改为寻找最后安全的两格高位置，虚空例外另行处理。这些是版本相关机制，不应默认沿用原版 Minecraft 的全部行为。[v1.11](https://hypixel.net/threads/bed-wars-v1-11-dreamfeast.6003011/)、[v1.11.1](https://hypixel.net/threads/bed-wars-v1-11-1-changes-bug-fixes.6100154/)

**D：二维化需要明确损失了什么。** 俯视网格可表达岛屿、桥和资源，但高低差、向上搭建、跳跃、坠落、火球跳和床防护层需要补充表示或明确简化。2D 视图也不能直接等同于玩家能看到整张地图。首版若简化伤害、击退或拆块时间，应分别记为模拟假设，并预留校准参数。

本轮没有证据可给出完整、当前、线上一致的伤害公式、无敌帧、攻击距离、击退向量、方块拆除时间或碰撞模型。

## 5. 资源、生成器与存储

| 资源 | 常见来源 | 核心用途 |
| --- | --- | --- |
| 铁 | 基地生成器 | 方块、低阶装备、工具和部分功能物品 |
| 金 | 基地生成器 | 武器、防具、TNT、补给等 |
| 钻石 | 外围独立资源点 | 团队升级与陷阱 |
| 绿宝石 | 中部独立资源点；升级后的基地 Forge 也可产出 | 高阶装备、珍珠、药水、黑曜石等 |

四种资源是 O 类官方确认；位置与用途细分由 C 类[社区规则资料](https://hypixel.fandom.com/wiki/Bed_Wars)补全。钻石不是一切高级物品的通用货币；绿宝石也不是只有地图中心这一种来源。

应分别管理玩家携带、地面掉落物、队伍箱、末影箱、生成器积累和持久升级。团队升级受益于全队，不表示所有携带资源自动进入公用钱包。多人同时站在基地生成器附近的分资源机制，也不能简单等同于按人数分摊一个固定产量。

**目前不宜写死的生成器参数：**

- 铁/金基础产出速度、每次产量、开局加速、地图差异。
- 每种资源的堆积上限，达到上限时是否暂停、清空后如何恢复。
- 基地多人拾取复制/分资源的范围、金币与铁的差别；钻石/绿宝石是否同样适用。
- 物品合并、掉落物自然消失、击杀资源归属、虚空死亡的资源转移。

O：2023 官方补丁确认 Forge 升级会提高可积累资源上限；当时仅表示将尝试统一地图生成速度，不能据此认定已经全部统一。2026 官方仍修复某地图生成器速度。[2023 说明](https://hypixel.net/threads/bed-wars-update-new-practice-modes-qol-changes-more.5339873/)、[2026 说明](https://hypixel.net/threads/bed-wars-v1-11-dreamfeast.6003011/)

C 类资料中的钻石三级周期常写为 30/24/12 秒。一份资料将绿宝石统一写为 56/40/28 秒，另一份历史指南却区分八队的 65/50/35 秒与四队的 56/40/28 秒；因此此处登记为**模式混用风险与待测值**，不选择其中一组作为全局参数。[资料表](https://breezil.github.io/Breezil-Hypixel-Utils/reference/bedwars/game)、[历史模式差异记录](https://hypixel.net/threads/guide-bedwars-everything-you-need-to-know.1203017/)

存储也有版本行为：官方 2024 年加入击打箱子快速存入，2025 年改成普通击打只存手持一组、潜行击打存同类全部组；2026 年 v1.11.1 修复敌人坠入虚空后退出导致击杀者拿不到资源的问题。箱子交互与死亡归属值得独立验证。[箱子变更](https://hypixel.net/threads/bed-wars-v1-9-3-new-settings-menu-other-changes.5828709/)、[资源归属修复](https://hypixel.net/threads/bed-wars-v1-11-1-changes-bug-fixes.6100154/)

## 6. 商店与死亡后的保留规则

### 6.1 常用物品的候选价格

下表面向普通 Solo/Doubles 与 3v3v3v3/4v4v4v4；**不覆盖独立 4v4、Dreams、私人修饰器和轮换物品。** “O+C”表示历史官方变更与社区现表吻合，仍未完成 2026 线上菜单核对；“C”仅为候选资料值。

| 商品与一次购买数量 | Solo/Doubles | 三人/四人四队 | 证据 |
| --- | --- | --- | --- |
| 羊毛 ×16 | 4 铁 | 4 铁 | C |
| 硬化黏土 ×16 | 12 铁 | 12 铁 | O+C，v1.2 |
| 木板 ×16 | 4 金 | 4 金 | C |
| 防爆玻璃 ×4 | 12 铁 | 12 铁 | C；v1.2 原公告曾写 ×6，不能沿用旧数量 |
| 末地石 ×12 | 24 铁 | 24 铁 | C |
| 梯子 ×8 | 4 铁 | 4 铁 | O+C，2021 从 ×16 改为 ×8 |
| 黑曜石 ×4 | 4 绿宝石 | 4 绿宝石 | C |
| 石剑 / 铁剑 | 10 铁 / 7 金 | 相同 | O+C，历史 v0.6 |
| 钻石剑 | 4 绿宝石 | 3 绿宝石 | O+C，v1.4 BETA 曾区分模式 |
| 击退棒 | 5 金 | 5 金 | O+C，v1.6 |
| 永久锁链 / 铁 / 钻石防具 | 24 铁 / 12 金 / 6 绿宝石 | 相同 | 锁链 O+C，其余 C |
| 永久剪刀 | 20 铁 | 20 铁 | O+C，v1.4 BETA |
| 弓 / 力量 I 弓 / 力量 I 冲击 I 弓 | 12 金 / 20 金 / 6 绿宝石 | 相同 | 力量 I 价格 O+C，其余 C |
| 箭 ×6 | 2 金 | 2 金 | O+C，2021 |
| 速度 II 45 秒 / 跳跃 V 45 秒 | 各 1 绿宝石 | 相同 | C |
| 隐身 30 秒 | 2 绿宝石 | 2 绿宝石 | 时长 O 历史修复；价格 O+C |
| 金苹果 | 3 金 | 3 金 | C |
| 火球 | 40 铁 | 40 铁 | O+C，v1.4 BETA |
| TNT | 4 金 | 8 金 | C，必须按模式区分 |
| 末影珍珠 | 4 绿宝石 | 4 绿宝石 | C |
| 水桶 | 2 金 | 3 金 | O+C，2023 |
| 搭桥蛋 | 1 绿宝石 | 1 绿宝石 | O+C，v1.6 + 2021 |
| 魔法牛奶 | 4 金 | 4 金 | O+C；效果与持续时间另见下节 |
| 蠹虫 / 铁傀儡 | 24 铁 / 120 铁 | 相同 | 蠹虫 O+C，其余 C |

候选表对照了[社区 Wiki 的物品表](https://hypixel.fandom.com/wiki/Bed_Wars)与[社区商店资料](https://breezil.github.io/Breezil-Hypixel-Utils/reference/bedwars/shop)。主要官方价格变更来源：[v1.4 BETA](https://hypixel.net/threads/bed-wars-v1-4-beta-capture-mode-new-maps-more.1527824/)、[v1.6](https://hypixel.net/threads/bed-wars-v1-6-pop-up-tower-4v4-mode-voidless-new-maps-and-more.2034329/)、[2021](https://hypixel.net/threads/bed-wars-update-challenges-bug-fixes-more.4585683/)、[2023](https://hypixel.net/threads/bed-wars-update-new-practice-modes-qol-changes-more.5339873/)。表为常用物品摘录，不是完整商品目录。

### 6.2 持久性不能统一成“死后清空”

- O：剪刀永久保留；斧/镐购买后分级，死亡降一级，最低级永久保留。这是 v1.2 官方明确的重做方向；后续工具材质/附魔又有变化，不能用 2017 初版工具表补齐现版。[工具系统](https://hypixel.net/threads/bed-wars-update-1-2.1369753/)
- C：购买的锁链/铁/钻石防具是永久升级；主要升级腿部与靴子，不能按全套同材质直接计算护甲。武器、弓、方块、药水与普通消耗品通常不永久保留。
- C：团队升级通常跨死亡保留；陷阱则属于可触发消耗的队伍资产。箱子库存与身上背包是不同存储。
- 待实测：逐项死亡丢失、工具降级对应附魔、掉落后拾回、快捷栏替换、资源转给击杀者与地面掉落的区别。

## 7. 团队升级、陷阱与隐身

### 7.1 升级与候选费用

下表为 C 类社区现表的逐级费用；升级要依次购买，列出的不是累计总价。机制与名称需配合后续官方补丁理解。[升级表](https://breezil.github.io/Breezil-Hypixel-Utils/reference/bedwars/shop)

| 升级 | 效果概要 | Solo/Doubles（钻石） | 四队团队模式（钻石） |
| --- | --- | --- | --- |
| Sharpened Swords | 锋利 I，作用于剑和斧 | 4 | 8 |
| Reinforced Armor I–IV | 保护 I–IV | 2 / 4 / 8 / 16 | 5 / 10 / 20 / 30 |
| Maniac Miner I–II | 急迫 I–II | 2 / 4 | 4 / 6 |
| Forge I–IV | 增产；后续解锁基地绿宝石 | 2 / 4 / 6 / 8 | 4 / 8 / 12 / 16 |
| Heal Pool | 基地范围回复 | 1 | 3 |
| Cushioned Boots I–II | 摔落保护附魔 | 1 / 2 | 2 / 4 |
| 陷阱队列第 1/2/3 槽 | 按排队占用计价的候选规则 | 1 / 2 / 4 | 相同 |

**O：2025-01-29 已用 Cushioned Boots I/II 替换 Dragon Buff；Miner Fatigue Trap 持续时间改为 8 秒。** 同时将旧名 Its a trap! 改为 Blindness Trap，将 Alarm Trap 改为 Reveal Trap。不要把旧攻略的 Dragon Buff 和旧挖掘疲劳时长混入现版。[官方 v1.9.3](https://hypixel.net/threads/bed-wars-v1-9-3-new-settings-menu-other-changes.5828709/)

### 7.2 陷阱需建成独立系统

候选种类包括致盲、挖掘疲劳、揭隐警报和防守反击。官方历史说明存在队列、进入基地范围触发与消耗机制；2024 年加入手动移除且不退款，2025 年限制只能移除自己购买的陷阱。[队列的历史设计](https://hypixel.net/threads/bed-wars-v1-4-beta-capture-mode-new-maps-more.1527824/)、[移除不退款](https://hypixel.net/threads/bed-wars-v1-9-2-new-maps-qol-changes.5790365/)、[购买者限制](https://hypixel.net/threads/bed-wars-v1-9-3-new-settings-menu-other-changes.5828709/)

当前需核对的细节包括触发半径、两次触发冷却、多名敌人同时进入时的目标、重复种类能否入队、已有状态覆盖方式，以及床丢失后是否仍可触发。仅有一个布尔值 has_trap 不够表达这些情况。

魔法牛奶的资料有版本冲突：v1.4 BETA 写 60 秒并说明仍有警报，v1.6 则修复描述为 30 秒；玩家资料还对“阻止陷阱触发”和“只免疫负面效果”存在不同表述。**本轮采用“存在绕过陷阱机制”这一确定的设计事实，持续时间、揭隐交互与是否消耗陷阱列为待测，不把 60 秒写成现版。** [历史介绍](https://hypixel.net/threads/bed-wars-v1-4-beta-capture-mode-new-maps-more.1527824/)、[官方描述修正](https://hypixel.net/threads/bed-wars-v1-6-pop-up-tower-4v4-mode-voidless-new-maps-and-more.2034329/)

### 7.3 隐身不能等同于完全不可知

O：v0.3 已明确隐身会对敌人隐藏护甲、受伤会移除效果；v1.2 加入脚步粒子，v1.4 BETA 增大脚步声，v1.6 处理了身上插箭的暴露问题，2021 年修复被玩家击中后未移除隐身的问题。[初始隐身修正](https://hypixel.net/threads/new-bed-wars-patch-v0-3-now-live-in-the-ptl.979320/)、[脚步线索](https://hypixel.net/threads/bed-wars-update-1-2.1369753/)、[声音](https://hypixel.net/threads/bed-wars-v1-4-beta-capture-mode-new-maps-more.1527824/)、[后续修复](https://hypixel.net/threads/bed-wars-update-challenges-bug-fixes-more.4585683/)

O：2026-06 的 v1.11.2 为新版客户端在隐身玩家脚下显示菌丝粒子，以补偿 Minecraft 移除了脚步粒子。**是否能观察到隐身线索还与客户端表现有关。** [最新线索变更](https://hypixel.net/threads/bed-wars-v1-11-2-changes-bug-fixes.6101931/)

C：手持物、拆块动作/声音和环境变化也可能暴露进攻者。精确可见范围、遮挡、粒子频率、队友视角、饮奶后揭隐陷阱、受伤种类需要测试。

**D：API 应区分实体可见、脚步/声音等匿名线索和历史记忆。不能一边隐藏模型，一边在合法动作列表、info、伤害来源或全局坐标里直接暴露隐身目标。若模拟要简化感知，应单列为观测模型，而不是宣称 Hypixel 原生视野规则。**

## 8. 对局时间与事件

普通模式资料常列出以下相对开局时间（C，来源为[事件资料表](https://breezil.github.io/Breezil-Hypixel-Utils/reference/bedwars/game)）：

| 经过时间 | 事件 |
| --- | --- |
| 06:00 | 钻石 II |
| 12:00 | 绿宝石 II |
| 18:00 | 钻石 III |
| 24:00 | 绿宝石 III |
| 30:00 | 所有剩余床摧毁 |
| 40:00 | Sudden Death |
| 50:00 | Game End |

该表不是所有模式的通用时间线，精确切换 tick、倒计时显示、50 分钟终局判法尚未实测。特别是 4v4 有加速与边界变体，Dreams 和私人房间也可有不同阶段。

O：2025 年更换 Dragon Buff 时规定 Sudden Death 经过 5 分钟再为每支存活队增加第二条龙；2026 v1.11 修复了该时点没有生成额外龙的问题。模拟若覆盖长局，应固定实际采用的补丁，而不照搬早期无限周期刷龙描述。[2025 设计](https://hypixel.net/threads/bed-wars-v1-9-3-new-settings-menu-other-changes.5828709/)、[2026 修复](https://hypixel.net/threads/bed-wars-v1-11-dreamfeast.6003011/)

## 9. 哪些内容影响本项目

| 需要保存的博弈机制 | 二维模拟需要明确的表示 |
| --- | --- |
| 床与复活资格 | 当前生命、待复活资格、永久淘汰、床状态分别记录 |
| 路线与地图争夺 | 路径距离、桥梁、虚空、阻挡和建造消耗；高度如何处理 |
| 四币经济 | 各自生成、库存、拾取、转移、支出与死亡损失 |
| 装备/工具/团队升级 | 各自持久性、附魔、成本与拆床效率 |
| 战斗 | 伤害、击退、出界；需要哪些接近原游戏的细节 |
| 隐身攻防 | 玩家能看到的实体与线索；揭隐/牛奶/陷阱交互 |
| 阶段事件 | 统一仿真时钟、资源升级、强制破床与长局结束 |
| 复现实验 | 同一规则档案、地图、种子、动作顺序与运行记录 |

D：皮肤、星级、票券、Slumber Hotel、Dreamfeast 的局外收集与装饰，目前没有必要成为首版规则。轮换物品会改变战术，应以“关闭或固定清单”的方式显式记录；这是一项待确认的实验范围建议，不代表用户已决定全部排除。

O：2022 官方说明轮换物品希望成为长期系统，并会持续调整；2025 v1.10 继续加入轮换物品。只记录补丁版本而不记录物品池，仍不足以描述一场对局。[轮换说明](https://hypixel.net/threads/bed-wars-update-item-rotation-and-bug-fixes.5180486/)、[v1.10](https://hypixel.net/threads/bed-wars-v1-10-one-block-bed-wars-community-suggestions-and-more.5961701/)

## 10. 实现前最有价值的核对清单

这些是后续校准建议，本轮未实测，不是已确认排期。

1. **版本/模式/地图**：选择一个普通模式和地图作为第一份规则档案，记录是否启用轮换与挑战。
2. **复活边界**：死亡后破床是否保留本次复活；同 tick 排序；保护时长与主动攻击取消保护。
3. **资源经济**：按模式/地图测初次产出、三级周期、上限、多人拾取、Forge 前后变化。
4. **购买与持久性**：核对菜单价格和批次数量；逐类死亡；防具部位、镐/斧降级与附魔。
5. **隐身/陷阱/牛奶**：分别核对可见线索、揭隐、触发与消耗、冷却和持续时间。
6. **战斗/拆块/爆炸**：同装备伤害、受击间隔、击退、虚空归因；不同工具对不同材料的拆除；水/玻璃/黑曜石的保护边界。
7. **终局**：全员等待时是否仍存活；所有床摧毁后的继续战斗；同时团灭与最大时长判法。

在完成这些验证前，可以说本项目“以 Hypixel 为规则参照”，不能说“已精确复现 Hypixel”。当前足以开始写最小规则草案；尚不足以把全部参数认定为线上事实。
