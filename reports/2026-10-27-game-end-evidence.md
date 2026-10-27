# Hypixel Bed Wars Game End：定向证据记录

记录日期：2026-10-27。用途：为 [BW-END-02](../docs/rules/hypixel-bedwars.md) 和 [0015 平台终局设计](../docs/decisions/0015-world-schedule-replay-failures-and-training.md)保留证据边界。本记录不是运行规则表，也不代表实机验证。

## O19：工作人员关于比较优先级的历史说明

- 来源：[“Fix The Game End Logic” 论坛讨论](https://hypixel.net/threads/important-fix-the-game-end-logic.5984093/)，定位 **第 20 楼、MotorGorilla（Hypixel Staff / Game Designer）、2025-09-11**。
- 内容：工作人员说明，当天上线的调整将存活队员数的优先级置于破床数之前。
- 核查方式：2026-10-27 的网页检索结果回显了该账号身份、日期、楼层和原发言；直接打开原帖在本次检索中返回 503，未保存完整网页快照，也未进行 Hypixel 游戏内测试。
- 证据边界：这支持**当时**存活队员数优先于破床数；不独立证明完整同分顺序、等待复活者的计数方式、各模式适用范围或 2026-10-27 现服配置。帖内玩家在调整前提出的更长比较链属于社区测试，不能自动当作调整后的官方规则。

## 与平台设计的关系

0015 已按用户选择采用平台实验比较：`Alive + Respawning` 人数、再比较有玩家归属的敌方破床数、最高分并列判平局。其第二项衔接、等待复活口径与最终平局是平台选择，不应引用 O19 声称官方已经完整确认。全局定时破床不增加玩家归属的破床统计。

06:00–50:00 时间表与生成周期仍为 [C03 社区候选](https://breezil.github.io/Breezil-Hypixel-Utils/reference/bedwars/game)；45:00 第二批龙是候选 40:00 加上 [2025 官方历史五分钟间隔](https://hypixel.net/threads/bed-wars-v1-9-3-new-settings-menu-other-changes.5828709/)的推导，不是独立的现服实测。该记录保留 [2026-10-25 原始来源清单](2026-10-25-hypixel-sources.json)不变，新增 O19 由本文件单独维护。
