# L1 动作、反馈与观测协议 v1 规格

P0 冻结字段和语义；P3 已提供接收器、控制和观测基础，见 [P3](p3-actions.md)；经济、战斗和终局处理器仍待后续阶段。格式、原因码和行为的后续不兼容变更必须升各自协议版本。依据 [W08](../decisions/0013-world-engine-and-state.md)、[W11/W12](../decisions/0015-world-schedule-replay-failures-and-training.md) 与 [L1 参数](../rules/l1-experiment-parameters-v0.1.md)。

## 通用编码与轮次

JSON 对象字段封闭、不得重复；时间为非负安全整数 tick，坐标/方向为有限 binary64，整数与布尔不能互换，ID 为 1–128 字符且不含控制字符。方块位置是安全整数格坐标，目标层为 `bridge`（y=-1）或 `wall`（y=0）。长度单位是方块，速度单位为方块/tick；二维向量字段为 `{ "x": number, "z": number }`。数据量以每玩家每轮规范 UTF-8 JSON 最多 65536 字节计；完整类型/范围校验不能被大小检查取代。

Runner 绑定 `match_id`、`player_id`、`decision_round_id`、`observed_tick` 和该玩家 `life_index`；策略不能为其他玩家提交、创建合法资格、指定 `action_id`、运行进度或队列。动作包一次属于一个观察边界，收集完成后封口，在 `observed_tick+1` 控制阶段处理；已封口不再添加。`k>1` 仅第一个 tick 收集并提交一次。相同 `(match_id, player_id, request_id)` 且规范内容相同只返回既有状态；异内容拒绝，另一次购买使用新 ID。生命与轮次字段纳入内容比较，旧生命不能作用新生命。重试查询旧已记请求不因轮次关闭重做。

一个有效空 `requests` 数组表示正常无更新、持续动作保持；缺包/异常/软超时属于 W12，Runner 使用备用双通道取消，不得当作空包。下面示例由 Runner 绑定身份：

```json
{
  "protocol_version": 1,
  "match_id": "match-1", "player_id": "red_1",
  "decision_round_id": "round-1", "observed_tick": 0, "life_index": 1,
  "requests": [
    {"request_id": "move-1", "kind": "move", "payload": {"x": 1, "z": 0}},
    {"request_id": "face-1", "kind": "turn", "payload": {"x": 1, "z": 0}}
  ]
}
```

## 动作包及载荷

机器可读结构见 [l1-action-v1.schema.json](../../schemas/l1-action-v1.schema.json)。每个子请求仅含 `request_id`、`kind`、`payload`，每种 payload 字段封闭；缺失身份/包结构无效是整包错误，可独立解析的单项无效只拒绝该项。

| kind | payload | 组/语义 |
| --- | --- | --- |
| `turn` | 非零 `{x,z}` | 方向归一化；20 阶段转向。每轮至多一项 |
| `select_item` | `{item}`，键为 `iron/wool/wooden_sword/iron_sword/shears` | 20 阶段选择当前库存中可手持物品；每轮至多一项 |
| `move` | `{x,z}` | 移动通道；非零归一化、零方向停止主动移动，不清击退 |
| `attack` | `{player_id, life_index}` | 交互通道；绑定一个可见目标的具体生命，持续攻击 |
| `break_block` | `{x,z,layer,instance_id}` | 交互通道；引用观测中当前玩家放置方块实例，旧实例替换后失败/中断 |
| `break_bed` | `{team_id}` | 交互通道；目标由定义中的该队床确定，只能破敌床 |
| `place_block` | `{x,z,layer}` | 交互通道；一次放置，目标是格而非预先分配的实例 |
| `cancel` | `{channel}`，`movement` 或 `interaction` | 占对应通道本轮更新；取消当前动作，空通道为无变化 |
| `buy` | `{product}`，`wool/iron_sword/armor_1` | 40 阶段一笔报价单位购买，不接受外部数量/价格 |
| `drop_resource` | `{resource: "iron", quantity}` | 正整数、一次性，45 阶段结算；每轮独立至多一项 |

先按 ID 去重；同一通道不同 ID 更新超过一项，则该通道整组拒绝、保留原动作。`turn`、`select_item`、`buy`、`drop_resource` 分别属于单次上限组，冲突只拒绝各自整组。20 阶段依次转向、切手、移动、交互；40 购买、45 丢弃/完成放置、50 拆除、60 战斗。接收时不扣物、不预留、不担保后续成功；执行按机制复核。放置和拆除开始资格与最终结算分离。目标的实例 ID 是已公开对象引用，不是外部指定引擎 ID 分配器或进度；新建实例由引擎生成。

## 反馈及稳定原因码

结构见 [l1-feedback-v1.schema.json](../../schemas/l1-feedback-v1.schema.json)。发布反馈含 `protocol_version`、`match_id`、`player_id`、`published_tick`、`request_results[]`、`packet_errors[]`、`action_outcomes[]`。每个可识别请求的结果含 `request_id`、`decision_round_id`、状态、原因码、`processed_tick` 和 `action_id`；后两者无值用 `null`。不可识别的整包错误另记 `packet_errors`，不编造请求 ID。

| 状态 | 含义 | 时刻与 ID |
| --- | --- | --- |
| `rejected` | 接收阶段拒绝 | `processed_tick=null`，`action_id=null` |
| `accepted` | 已接收、等待执行，不保证成功 | `processed_tick=null`，`action_id=null` |
| `applied` | 已执行或确认保持/空取消无变化 | `processed_tick` 为实际处理 tick；新持续动作给 `action_id`，无变化为 null |
| `failed` | 接收后执行条件未满足 | `processed_tick` 为实际处理 tick，不创建成功动作 ID |

持续动作之后的 `completed/interrupted` 单独在 `action_outcomes` 中提供 `request_id`、`action_id`、`at_tick` 与原因，不改写原 `applied`。接收回执可即时返回；执行结果和动作结局仅完整 tick 边界发布，`k>1` 仍记录实际处理 tick。同内容重试不产生第二个事实或结算。

| 原因码 | 含义 |
| --- | --- |
| `OK`, `NO_CHANGE` | 已接收/正常应用；已保持同动作或取消空通道 |
| `MALFORMED`, `UNKNOWN_ACTION`, `UNSUPPORTED_PROTOCOL`, `INVALID_ID` | 字段/类型、动作类别、协议版本或 ID 格式错误 |
| `DUPLICATE_ID_CONFLICT`, `INVALID_BINDING`, `WRONG_LIFE`, `ROUND_CLOSED`, `STALE_OBSERVATION` | 身份内容冲突、绑定错误、旧生命、轮次封口或观测边界不一致 |
| `CHANNEL_CONFLICT`, `GROUP_LIMIT` | 同通道更新冲突或瞬时组超限 |
| `ITEM_NOT_HELD`, `OUT_OF_RANGE`, `BAD_FACING`, `OCCLUDED` | 手持、距离、朝向或遮挡条件不满足 |
| `INVALID_TARGET`, `TARGET_CHANGED`, `TARGET_GONE`, `FRIENDLY_TARGET` | 目标无效、实例替换、目标消失或目标属于友方 |
| `INVALID_LAYER`, `OUT_OF_BOUNDS`, `PROTECTED_REGION`, `OCCUPIED`, `UNSUPPORTED_BLOCK`, `WALL_ABOVE_BRIDGE` | 目标层、地图范围、保护区、占用或支撑失败 |
| `INSUFFICIENT_RESOURCE`, `INVENTORY_FULL`, `ALREADY_OWNED`, `INSUFFICIENT_QUANTITY` | 资金、容量、重复升级或实际持有数量不足 |

结局原因单独使用 `COMPLETED`、`CANCELLED`、`REPLACED`、`LIFE_ENDED`、`TARGET_INVALIDATED`、`HELD_ITEM_CHANGED`。调度任务取消、旧实例/旧生命、截止时刻变更等正常内部跳过，稳定诊断码分别为 `CANCELLED_TASK`、`STALE_INSTANCE`、`STALE_LIFE`、`STALE_DEADLINE`；它们不产生玩法成功事实。未知任务、预算超限、校验/处理器异常是引擎故障，不冒充普通请求失败或胜负。公开原因、目标与关联标识须通过同一可见性过滤；不应借详细原因泄露隐藏状态。

## 观测 v1 字段表

每位可行动玩家独立获得完整边界的深拷贝；等待复活/淘汰席位按 0015 生命周期处理，不把等待当永久终止。以下为公开字段规格，P3/P6 已实现生产与隔离：

| 字段 | 类型与内容 |
| --- | --- |
| `protocol_version`, `match_id`, `decision_round_id`, `observed_tick`, `self_player_id` | 协议版本、身份和本次共同边界 |
| `definitions` | profile/map 的 ID、内容版本及 SHA-256；场景身份和哈希用于追溯 |
| `map`, `rules` | 公布的固定地图与 L1 玩法参数，供策略导航和决策 |
| `terrain` | 地图范围、原始地面、公开的玩家方块 `{x,z,layer,instance_id}`，以及各队床格/是否存在 |
| `teams[]` | `team_id`、固定成员 ID、床状态、参赛/淘汰状态、已发布的有归属敌方破床数 |
| `players[]` | `player_id`、`team_id`、`life_index`、生命分支、已发布击杀/死亡统计；存活分支附下列字段 |
| 存活分支 | 位置 `{x,z}`、单位朝向、当前速度和击退速度、HP/最大 HP、防具等级、手持物或 null、背包数量表、公开动作种类/目标/进度、攻击/受击/出生保护剩余 tick |
| 等待复活/淘汰分支 | 分别为剩余复活 tick / 淘汰时刻与类别；不得保留有效的旧存活动作 |
| `ground_items[]` | 可见实体 ID、物品键、数量和位置 |
| `generators[]`, `schedule` | 固定定义引用、下一次尝试 tick；全局毁床与 Game End 的时刻/已发生状态 |
| `feedback` | 上述本玩家结果/动作结局的隔离副本；仍须过滤信息 |

不得提供未结算请求/其他玩家已提交内容、内部任务、ID 分配进度、RNG 或去重诊断。公开的方块/地面实体标识用于目标引用，不提供分配器内部状态。数值不加噪声，公开不等于允许策略持有引擎引用。
