# L1 P1：世界状态与事务基础

P1 提供标准 2v2 世界的构造、可恢复执行状态及完整 tick 边界快照。它是内部引擎基础，尚不能运行完整对局；P2–P5 继续接入运动、动作、经济、战斗和终局。

- `WorldEngine.create` 接受已校验的 `L1Definitions`、无符号 64 位 seed 和可选的 match ID；默认生成唯一 match ID。标准局及训练预置走同一构造和校验。预置当前支持固定阵容内的位置、朝向、击退、HP、背包、手持、防具、保护剩余时间、床状态和生成器首次截止；仍关闭的机制和地面实体不能作为预置。所有实例 ID 与任务由构造器分配。
- 玩家存活、等待复活、淘汰为互斥结构；阵容、TeamState、原始地形、生成器计划、初始背包、保护和赛程任务均在初始 tick 0 固定。`engine.state` 和快照返回独立副本。
- `ScheduledTask`、`Intent`、`FactEvent` 分开表示。内部 `ChangeSet` 随一次提交校验玩家/地形、任务、消息去重、ID 和事实；失败不会修改输入状态。空阶段也推进独立游标。同一任务 ID 和内容重复是幂等的，不同内容拒绝；取消、正常失效与日志游标可恢复。
- 快照仅取完整边界，显式记录 schema、固定定义哈希、包与 CPython 版本、RNG 流状态、游标和去重账本。旧 EventQueue schema 1 不能直接作为世界快照。随机流按 0015 的 SHA-256 命名空间派生；承诺只限固定代码和环境，尚未做完整输入重放。
- 引擎故障后不发布半个 tick、不输出其事实、不能继续推进；可从此前完整快照显式恢复。无整 tick 自动回滚承诺。

当前保护到期和 P4 资源生成已接入；赛程处理器已由 [P5](p5-combat.md) 接入。等待复活和淘汰结构已可校验，死亡与复活转换已由 P5 接入；玩家的动作记录结构已预留，外部请求接收和观测已按 P3 接入。预置引用的几何只作出生合法性校验，完整碰撞和运动属于 P2。

```python
from bedwars_arena.core.definitions import load_l1_definitions
from bedwars_arena.core.world import WorldEngine
from bedwars_arena.replay.snapshot import dumps_snapshot, restore_snapshot

definitions = load_l1_definitions()
world = WorldEngine.create(definitions, seed=17, match_id="example")
world.step()                         # 发布 tick 1
snapshot = dumps_snapshot(world.snapshot())
restored = restore_snapshot(snapshot, definitions)
assert restored.state == world.state
```

验证包括标准/训练新局、浮点与 RNG 往返、任务去重及恢复、空阶段游标、旧生命失效、提交故障和未实现任务停止。对应规则采用平台实验档案；地图碰撞与出生保护的参考规则见 BW-WORLD-02、BW-LIFE-06，相关具体值不能作为 Hypixel 现服实测。
