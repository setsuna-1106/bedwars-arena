# 格式与协议

已有 [TeamState v1 Schema](team-state-v1.schema.json)，对应完整内部状态，不是对手可直接访问的观测或完整 Agent 消息协议。Python 编解码还检查规则上限、局内实例唯一性及队伍关联，Schema 不替代这些检查。

L1 profile/map/scenario 的机器可读定义见[P0 说明](../docs/l1/p0-definitions.md)；[动作](l1-action-v1.schema.json)和[反馈](l1-feedback-v1.schema.json) Schema 是规格，接收/发布尚未实现。完整 WorldState 快照和回放格式仍待设计；当前事件队列恢复协议见 [0012](../docs/decisions/0012-team-core-types-and-ordering.md)。

先按 [接口与时序草案](../docs/contracts.md) 确定语义，再增加 schema 版本、合法/非法样例与兼容策略。
