# L1 P6：Runner 与首场完整 2v2

P6 提供无界面 L1 2v2 Runner、两种进程内脚本策略及单局/批量 CLI。它完成的是 [L1 规划](../l1-implementation-plan.md)的 G1；二维回放、完整输入重放验证、训练和 40 局端到端验收分别留在 P7–P9。

```bash
# 标准初始状态；结束或达到 episode 上限后写入新目录
bedwars-arena run-l1 --seed 101 --red attack --blue defend --output artifacts/standard-101 --json

# 受控验收预置：红队预持铁和一档防具，蓝队初始 HP 降低
bedwars-arena run-l1 --seed 101 --preset examples/l1-controlled-2v2.json \
  --episode-limit 1100 --progress-every 100 --output artifacts/controlled-101 --json

# 逐局递增 seed；每局有独立目录与汇总
bedwars-arena batch-l1 --games 2 --seed 101 --output artifacts/batch-101 --json
```

输出目录必须不存在，防止覆盖已有记录。每局包含 `manifest.json`、完整 `definitions.json`、`initial-snapshot.json`、`final-snapshot.json`、`inputs.jsonl`、`events.jsonl` 和每 200 tick 的周期快照。记录写入临时目录，完成后再发布。清单包含种子、固定席位及策略版本、定义哈希、代码内容哈希、Python 环境、决策间隔、时限、备用决策数量所需输入记录与结果。新 episode 从已有快照继续时记录来源及新时限基准；本 episode 的事件从其起始边界记录。

`MatchRunner` 先为全部可行动席位生成同一完整边界的独立观测，再调用各自策略，绑定身份/轮次/生命并封口；之后始终逐 tick 推进。`k>1` 只在首 tick 提交一次，提前自然结束立即停。等待复活不调用策略但保留会话；淘汰玩家作为无行动席位保留至对局结束并获得队伍终局奖励。

策略异常、回调返回后发现软超时、或必需包缺失时，Runner 记录原因并提交两个通道的取消；不清已有击退。正常空请求表示保持，独立子请求非法按 P3 单项处理。进程内调用无法强制中止卡住的回调。自然终局与外部时限同 tick 时两个标志均为 true，奖励使用自然结果；单独截断不构造世界结果，奖励为 0。

`EconomicAttacker` 和 `DefensiveCounterattacker` 使用公开地图、规则、玩家、物品和地形观测导航、购羊毛、搭桥、破床与近战；策略不读取 `WorldState`。它们是确定性功能脚本，不代表训练好的策略或合理平衡。策略版本在每局固定，训练器及模型/优化器状态不由世界重置。

受控场景是用于覆盖玩法的预置，不是双方对称的竞技评估；红队资源/防具与蓝队血量不同。实际验收以记录中的购物、方块放置、玩家破床、最终淘汰和自然终局事实为准，不以等待 Game End 的平局充当完成玩法。P6 快照与运行清单绑定 `l1-p6-1`、包内容 SHA-256 和 Python 版本；较早引擎版本快照明确拒绝。

## 受控验收记录

使用内置实验档案、`examples/l1-controlled-2v2.json` 和 seed 101，正式 CLI 在 tick 752 自然结束，红队获胜；记录包含 6 次购买、22 次放置、1 次玩家破床、2 次最终淘汰和 1 个终局事实，没有策略备用动作。已检查定义哈希、输入/事实计数与初始、最终及 tick 200/400/600 快照的可恢复性。结果仅证明该不对称受控场景的功能闭环，不是策略强度或训练效果评估。本机记录在 `artifacts/l1-p6-acceptance-v2/`，该目录按项目约定不进入 Git。
