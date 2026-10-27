# TeamState 实现前规则复核

日期：2026-10-26。方法：重新读取官方补丁首帖，检查版本变化；未登录游戏实测，未取得 Hypixel 服务端配置或源码。

| 参数/机制 | 本次证据 | 实现处理 |
| --- | --- | --- |
| 队列档位 1 / 2 / 4 钻石 | [官方 v1.4 BETA](https://hypixel.net/threads/bed-wars-v1-4-beta-capture-mode-new-maps-more.1527824/) 明列三档费用及队列 | 放入历史参考档案，容量取三个价格档位，不声明现服全模式核实 |
| 致盲陷阱 8 秒 | [官方 v1.6](https://hypixel.net/threads/bed-wars-v1-6-pop-up-tower-4v4-mode-voidless-new-maps-and-more.2034329/) 延长旧名陷阱至 8 秒 | 作为持续时间参考，不误作触发冷却 |
| 疲劳陷阱 8 秒与新名称 | [官方 v1.9.3](https://hypixel.net/threads/bed-wars-v1-9-3-new-settings-menu-other-changes.5828709/) 首帖明确 | 使用 `miner_fatigue` 等稳定 ID，时长存为 160 仿真 tick |
| 反击陷阱 15 秒、速度 II/跳跃 II | [官方 2021 更新](https://hypixel.net/threads/bed-wars-update-challenges-bug-fixes-more.4585683/) 将旧时长改为 15 秒 | 持续时间目录记录 300 tick，不实现尚未定义的范围/效果应用 |
| 牛奶 30 秒 | [官方 v1.6](https://hypixel.net/threads/bed-wars-v1-6-pop-up-tower-4v4-mode-voidless-new-maps-and-more.2034329/) 修正旧描述 | 记录 600 tick；是否阻止触发/报警/消耗仍待核验 |
| 完整升级价格 | 本地既有规则表及[社区资料](https://hypixel.fandom.com/wiki/Bed_Wars)，本轮官方补丁未给出完整现价矩阵 | 标为候选，仅显式 opt-in 后用于研究参考 |
| 共享触发冷却及重置 | 对官方补丁与定向搜索，未获得足够可靠说明；不能用效果时长推出冷却 | 保持 Q15，运行触发前要求显式覆盖并记录来源 |
| 持续停留/多人目标顺序 | 旧官方说明描述进入基地时触发，但未给出现服所有边界 | 保留用户已采用的平台语义，继续标为待 Hypixel 对照 |
| 主动移除 | v1.9.3 实际提供购买者移除权限，Castle 另有禁用规则 | 保留用户明确的“不能移除”项目取舍，不静默覆盖 |
| 内部类型/同 tick 排序 | 未获得官方内部接口或完整事件流水线 | 使用版本化的平台类型与排序约定，明确不声称原生一致 |

数值到 tick 的转换按平台 20 Hz 名义时钟精确计算。以上官方来源是历史补丁证据，不能单凭重新访问就称为 2026 年现服校准完成。详细实现与剩余边界见 [0012](../docs/decisions/0012-team-core-types-and-ordering.md)，原 Q01–Q15 清单继续保留。
