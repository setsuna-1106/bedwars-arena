# L1 P2：二维几何、承载与运动

P2 使用 [L1 实验档案](../rules/l1-experiment-parameters-v0.1.md)实现严格俯视、单行走层运动。地图仍是固定定义，局内地形使用稀疏非空气格；桥面在 `y=-1`，墙体在 `y=0`，床是否存在只从 `TeamState` 读取。查询不缓存第二份可变真值。当前几何是平台选择，BW-WORLD-02、BW-COMBAT-01 的具体几何、速度和击退仍未作为 Hypixel 现服实测。

- `core.geometry` 提供二维向量、矩形、点到矩形距离和射线进入实体内部的判断。格归属使用 `floor` 和半开区间，碰撞则允许表面接触；仅贴墙边的视线不算遮挡。
- `core.terrain` 从世界当前地形和床状态构造不可变查询，提供碰撞、正面积承载、遮挡和掉落位置安全检查。地面移除后再次查询自然反映变化；没有把玩家作为碰撞障碍。
- `core.physics` 每 tick 归一化主动方向，按照档案的速度、P07 反向/侧向上限合成击退，再以玩家完整 AABB 扫掠墙和床。最早接触后的切向位移继续，时间容差内的同时接触合并；受阻的击退分量移除，余量按档案衰减。达到迭代上限时保守停止剩余位移并记录诊断。接触修正只沿法线向障碍外侧调整可能的浮点舍入误差。
- 路径承载以身体投影和地面的**正面积**重叠为准，连续检查整段运动，不能跨越中途空隙。30 阶段产生 `void_death_candidate` 意图，60 阶段暂存到可恢复的 `execution.pending_deaths`。P5 已将候选接入同 tick 的统一死亡批次。
- 玩家动作接收已由 P3 提供。P2 内部运动处理器消费已存在的 `movement` 动作，空通道为零主动方向；直接调用几何/物理函数及受控测试可验证路径，不能把这个内部接口当成外部策略 API。P4 已接入生成器与经济处理器；战斗和死亡结算已由 P5 接入。

示例：

```python
from bedwars_arena.core.definitions import load_l1_definitions
from bedwars_arena.core.geometry import Vec2
from bedwars_arena.core.physics import move_player
from bedwars_arena.core.terrain import Terrain
from bedwars_arena.core.world import WorldEngine

definitions = load_l1_definitions()
world = WorldEngine.create(definitions, seed=17, match_id="physics-example")
terrain = Terrain.from_world(world.state, definitions.map.data)
result = move_player(position=Vec2(-25, 0), direction=Vec2(1, 1),
                     knockback=Vec2(0, 0), terrain=terrain,
                     physics=definitions.profile.data["physics"])
assert not result.void_candidate
```

测试覆盖直行/斜行等速、负坐标、贴墙、同时碰撞、较大位移扫掠、可复现随机障碍、浮点接触边界、击退反向/侧向限制及撞墙消除、路径跨空隙、床状态与玩家互穿。受控世界测试核对候选的阶段转交、快照恢复、生命隔离和无虚假死亡事实。快照运行信息增加了 `world_engine_revision=l1-p2-1`；P1 引擎版本的旧快照会明确拒绝，不静默套用新的运动规则。碰撞尺寸、速度、击退与容差均是已采用的 L1 实验值；没有实现三维高度、跳跃或完整 Runner 对局。
