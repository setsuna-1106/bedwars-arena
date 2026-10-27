# L1 P3：动作请求、控制和观测

P3 提供 [动作/反馈协议 v1](protocol-v1.md) 的内部进程接入：开轮、按玩家收包、封口、推进、读取独立观测和反馈。输入收集不推进 tick、不锁定或扣除资源；成功接收只表示 `accepted`，20 阶段成功应用才为 `applied`。世界快照保存封口状态、待处理请求、请求内容及反馈记录；P3 引擎版本显式拒绝 P2 快照，不隐式迁移。

- 每名存活玩家一包；封口前必须收到各必需包。`request_id` 按玩家、本局和完整绑定识别：相同内容重试返回已有状态，异内容拒绝；封口后新请求不进入旧轮。每组先去重，同轮不同 ID 超出上限时整组拒绝，不影响其他组。空包表示正常保持，缺包不自动视作保持。
- 20 阶段依次转向、切手、移动更新、交互更新，固定阵容顺序处理；无效更新保留原动作。正常省略保持；同语义移动不重启；显式取消只清对应通道/进度，不清击退。切手中断交互，持续交互在运动后重新核对距离、朝向、遮挡与目标实例；中断不自动恢复。合法启动攻击或破敌床时解除保护，启动非法不解除。
- 观测只从完整边界构造，逐玩家独立复制；包含 L1 公开地形、玩家、床和生成器时间，不含其他玩家未执行请求、任务队列、去重账本或随机流。反馈中动作结果记录实际处理 tick，持续动作中断另记结局。
- P4 已接入 `buy`、`drop_resource`、放置和拆除的实际结算，见 [P4](p4-economy.md)。近战伤害、死亡和终局仍归 P5，不视作已经完成。

```python
from bedwars_arena.core.definitions import load_l1_definitions
from bedwars_arena.core.world import WorldEngine

world = WorldEngine.create(load_l1_definitions(), seed=7, match_id="example")
world.open_round("round-1")
for player_id in ("red_1", "red_2", "blue_1", "blue_2"):
    observation = world.observe(player_id)
    requests = ([{"request_id": "move-1", "kind": "move", "payload": {"x": 1, "z": 0}}]
                if player_id == "red_1" else [])
    world.receive_actions({"protocol_version": 1, "match_id": "example", "player_id": player_id,
                           "decision_round_id": "round-1", "observed_tick": observation["observed_tick"],
                           "life_index": 1, "requests": requests})
world.seal_round()
world.step()
assert world.feedback("red_1")["request_results"][0]["status"] == "applied"
```

验证覆盖隔离观测、收包顺序、组冲突、坏子请求隔离、封口、旧生命、同 ID 重试/异内容冲突、封口快照恢复、取消/保持、切手中断，以及合法/非法攻击启动保护。购买/放置/丢弃的结算和不重复执行已在 P4 补充测试；Runner 的 k>1 集成仍归 P6。实验攻击与保护参数对应 BW-COMBAT-01、BW-LIFE-06，不能视为 Hypixel 现服实测。
