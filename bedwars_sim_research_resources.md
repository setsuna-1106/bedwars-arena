# BedWars Arena — 2D 多智能体仿真平台资料索引

更新：2026-10-25（补充关键源码核查）  
目标：建立可无头运行的 2D BedWars 环境；外部 Agent 读取局部观测并提交行动；支持重复实验、批量对战、数据分析、事件回放。

现实参照已确定为 Hypixel Minecraft Bed Wars；日常查阅[规则参考](docs/rules/hypixel-bedwars.md)，证据见[规则调研与待核对参数](reports/2026-10-25-hypixel-bedwars-rules.md)。下列第三方项目用于工程借鉴，不能替代 Hypixel 规则核对。

> **检索结论（有限范围）**：已有 BedWars 风格独立 AI 仿真项目、BedWars 游戏规则代码、成熟的 2D 多智能体仿真框架与 Agent 通信框架；但尚未确认一个能够开箱即用地同时满足完整 2D BedWars、外部 Agent API、批量实验和网页回放的成熟项目。这里的“适合复用”是根据仓库文档与公开代码结构判断，**不是实测兼容性保证**。

**进一步核查**：[项目调研与适配性评估](reports/2026-10-25-project-survey.md)覆盖本索引的 16 个仓库和 3 个补充仓库；[来源清单](reports/2026-10-25-source-manifest.json)保存固定提交、许可证标识和已获取文件。此次核查发现 C# 项目的前向模拟函数未实现、MicroRTS 系列已宣布停更，以及多个框架的多人/回放能力边界。以下条目已据此修正；本次未安装、试运行或测试性能。

**运行补充**：[轻量验证与参考优先级](reports/2026-10-25-reference-validation.md)记录了随后完成的 5 组隔离探针。优先参考 PettingZoo 的接口、Blockyard 的规则状态机、Lux/bots 的策略接入；Lab2D 已跑通双玩家网格例子，是否作为底座仍取决于二维模型。

## A. 最值得查看：BedWars 与 AI 仿真本身

### A1. Minecraft-Bedwars-AI ★（规则抽象参考）
- 仓库：https://github.com/tilakpatell/Minecraft-Bedwars-AI
- 类型：C#；BedWars 风格独立 AI 仿真；代码体量小。
- README 说明：岛屿、资源、生成器、桥、武器、战斗、床、死亡/复活；四种策略；可运行多个 simulation 并输出结果统计。项目文件实际以 .NET 9 为目标。
- 最该看：`GameEngine.cs`、`GameState.cs`、`Connection.cs`、`BedwarsAIAgent.cs`、`Program.cs`。
- **谨慎**：其桥梁以岛屿连接关系描述，不等于完整格子级 2D 搭桥物理；未证实具备外部网络 API。仓库根目录未见明确 LICENSE 文件，复制源码前应获得适当授权；参考思路和自行实现则另当别论。
- **源码修正**：`SimulateAction` 与 `SimulateEnemyAction` 均直接返回原状态，没有生成行动后的搜索状态，不能据 README 将其视为有效的 minimax 基线。终局判定、随机种子与外部接口也需要重做或核验。固定源码证据见调研报告 §4.1。
- 适用：阅读规则抽象；当前不建议直接作为本项目引擎的移植起点。

### A2. Blockyard ★★★
- 仓库：https://github.com/Potrock/blockyard
- 类型：TypeScript + Rust/WASM；3D voxel 平台，内含 Bed Wars。
- 文档称可由 Bot 完成 Bed Wars 全局，`npm run test:headless` 无浏览器运行；模拟 `Sim` 与 Three.js 渲染分离，输入 `PlayerInput`，输出 `SimFrame`。
- 最该看：`src/games/bedwars`、`src/platform/sim`、`src/platform/net`、`tests/headless`、`docs/PLATFORM.md`。
- 局限：**3D 模型，不是纯 2D**；移植其整套 Rust/TypeScript 引擎可能超出项目需求。
- 许可证：仓库标记 MIT；具体使用时仍需阅读 LICENSE。
- **源码边界**：有种子 RNG，但爆炸拆块路径仍使用 `Math.random`；现有回放主要保留短时间历史，世界方块不会恢复到历史状态，不能直接当作完整可复现实验存档。证据见调研报告 §4.2。

### A3. BedWars1058 / Screaming BedWars（规则参考）
- BedWars1058：https://github.com/andrei1058/BedWars1058
- Screaming BedWars：https://github.com/ScreamingSandals/BedWars
- 类型：Minecraft 服务端 BedWars 插件。
- 可参考：床与胜负判定、商店/资源、事件触发、队伍/复活系统。
- 不推荐直接作为无头二维模拟核心：依赖实际 Minecraft 服务端体系。注意各自许可证。

## B. 已有 2D 多智能体引擎 / 比赛平台

### B1. Lux AI Season 2 ★★★
- 仓库：https://github.com/Lux-AI-Challenge/Lux-Design-S2
- 角色：**外部 Agent 运行协议、比赛调度、统计与回放的完整参考样板**。
- 已提供：1v1 自动对抗、Agent starter kits、CLI 本地运行、`replay.json`、网页回放、tournament 工具。
- 示例（原项目特定运行命令；并非 BedWars）：
  ```bash
  luxai-s2 path/to/bot/main.py path/to/bot/main.py -v 2 -o replay.json
  ```
- 浏览器回放：https://s2vis.lux-ai.org/
- 先读 `README.md` → `kits/` → `luxai_s2/` → CLI 和 tournament 文档。
- 限制：游戏是资源型策略对抗；BedWars 规则需重新实现。README 指定的旧版 Python 环境可能需隔离安装。
- **源码边界**：运行器限制两位参赛者，且依赖 Lux 专用状态与观测差分，替换游戏规则层需要抽离这些耦合。
- License：根 LICENSE 为 Apache-2.0；`luxai_s2/setup.py` 的 license 字段却写 MIT，存在元数据冲突，不能只依据包标签判断。

### B2. DeepMind Lab2D ★★★
- 仓库：https://github.com/google-deepmind/lab2d
- 角色：**基础二维世界引擎**。C++ + Lua、文本格子地图、支持多智能体；Python `dm_env` / C API。
- 文档：https://github.com/google-deepmind/lab2d/blob/main/README.md
- 适用：自定义世界逻辑、格子移动、局部感知；不需要自己写底层网格环境。
- 限制：需要掌握 Lua 规则系统；不是现成远程 Agent API。
- License：Apache-2.0。

### B3. MAgent2 ★★★
- 仓库：https://github.com/Farama-Foundation/MAgent2
- 文档：https://magent2.farama.org/
- 角色：大量二维网格 Agent 交互与战斗，兼容 PettingZoo。
- 先看：文档 `Battle`、`GridWorld`、`Config`、`Basic Usage`。
- 限制：偏多智能体战斗，不内置 BedWars 床/资源/商店/搭桥。
- 注意：**旧 PettingZoo 的 MAgent 已迁移至 MAgent2**。
- License：MIT（仓库所示）。
- 当前默认分支的 `pyproject.toml` 要求 Python >=3.11，与 README 的 3.8+ 描述不同；应按固定版本核对。

### B4. MicroRTS-Py / microRTS ★★
- **停更修正**：MicroRTS-Py 和其实际引用的 `Farama-Foundation/MicroRTS` 均在 README 宣布自 2025-08-11 起停止更新和支持；降低为历史设计参考，不建议作为新项目核心。
- 仓库（Python）：https://github.com/Farama-Foundation/MicroRTS-Py
- 仓库（RTS）：https://github.com/vwxyzjn/microrts
- 包装器当前配置的实际子模块：https://github.com/Farama-Foundation/MicroRTS （原索引中的 `vwxyzjn/microrts` 是另一分支）。
- 用处：参考网格 RTS 的行动系统、部分可观测、不同 AI 对抗，以及批量训练和评估结构。
- 局限：RTS 单位与基地，而非 BedWars 玩家与床；可能仅适合学习实验结构。
- 许可证分层：Python 包装器为 MIT；这里核查的 Java 引擎仓库为 GPL-3.0。

### B5. Grid Universe ★★
- 仓库：https://github.com/grid-universe/grid-universe
- 用处：可扩展确定性网格世界、实体组件系统 (ECS) 的结构设计。
- 限制：不是 BedWars 或完整对战协议，适合框架设计比较。
- **源码边界**：默认 Gymnasium 包装器控制单个 Agent；核心 `step(state, action, agent_id)` 一次处理一个动作并推进世界，不是已实现的多人同步动作接口。要求 Python >=3.13。

### B6. markusfisch/bots ★★
- 仓库：https://github.com/markusfisch/bots
- 用处：2D 地图、通过 TCP Socket/WebSocket 和外部 Bot 通信、旁观者及 WebGL 回放。
- 局限：回合制小型游戏，规则需换成 BedWars。尤其适合研究**如何让不在引擎进程内的 Bot 参赛**。
- 源码按接收命令执行动作并使用墙钟超时，不能直接视为同时结算协议；WebGL 回放器来自独立的 `ChristianNorbertBraun/bots_spectator` 仓库，本次未深审该前端。核心仓库采用 Unlicense。

## C. Agent API、远程运行和规范

### C1. PettingZoo Parallel API ★★★
- 文档：https://pettingzoo.farama.org/api/parallel/
- 适用：多个 Agent 同步提交动作：`reset(seed)`、`step(actions)`、逐 Agent observations/rewards/termination/truncation。
- 注意：这**是本地环境接口标准**，不是现成 HTTP API；网络层需要另外设计。

### C2. PettingZoo 自定义环境教程 ★★★
- 教程首页：https://pettingzoo.farama.org/tutorials/custom_environment/index.html
- 创建环境：https://pettingzoo.farama.org/content/environment_creation/
- 非法动作遮罩：https://pettingzoo.farama.org/tutorials/custom_environment/3-action-masking/
- 合规性测试：https://pettingzoo.farama.org/tutorials/custom_environment/4-testing-your-environment/
- 可直接帮助实现：`action_space`、`observation_space`、局部观测、不可用动作、自动测试。

### C3. OpenEnv ★★★
- 仓库：https://github.com/openenv/OpenEnv
- 官方概念：https://huggingface.co/docs/openenv/main/en/guides/concepts
- 用处：已有 client-server 环境概念和远程 Agent `reset`/`step`/`state`，通过 HTTP/WebSocket；可以参考协议、客户端 SDK、环境隔离。
- 注意：OpenEnv 默认侧重单 Agent 环境会话；**多 Agent 共用同一场对局**需要单独定义调度与同步语义，不要直接假设开箱即用。
- 当前源码进一步确认：并发会话各自创建环境实例；OpenSpiel 示例向外暴露单 Agent 对内置对手。许可证为 BSD-3-Clause。共享比赛需要额外的 match controller 或联合动作适配。

### C4. FastAPI WebSocket
- 官方教程：https://fastapi.tiangolo.com/advanced/websockets/
- 用途：实现自己的轻量传输层、连接管理、Agent 注册、接收动作、推送观测。
- 建议：本地决策直接调 Python 核心，外部才走 WebSocket，避免每一步 HTTP 往返开销。

### C5. Gymnasium：自定义环境及随机种子
- 创建环境：https://gymnasium.farama.org/main/tutorials/environment_creation/
- 规范：https://gymnasium.farama.org/main/api/env/
- 用途：实验复现、`reset(seed=...)` 和 `terminated`/`truncated` 的区分；对照环境测试。

## D. 2D 可视化与回放

### D1. PixiJS v8 ★★★
- 快速开始：https://pixijs.com/8.x/guides/getting-started/quick-start
- 适用：绘制网格、玩家、桥梁、床、资源点，显示战斗和时间轴。
- 边界：只画引擎导出的状态，不在前端重复计算规则。

### D2. Lux AI S2 的回放系统
- 仓库：https://github.com/Lux-AI-Challenge/Lux-Design-S2
- 现成可研究的模式：命令行输出 `replay.json`；网页回放导入同一文件；对局和显示解耦。

### D3. markusfisch/bots 的 WebGL 回放
- 仓库：https://github.com/markusfisch/bots
- 用处：2D bot 对战的旁观和回放设计，适合做最低成本原型。

### 推荐回放存储方案（设计建议）
- 每局保存 `manifest.json`（map_id、规则版本、策略版本、seed、参与 Agent）。
- 事件流 `events.jsonl`（tick、actor、event_type、payload）。
- 定期写状态快照（例如每 100 tick），使拖动时间轴不必从开局重算。
- 回放和模拟核心版本关联，防止规则更新后事件无法重现。

## E. BedWars 规则和公开数据

- Hypixel Bed Wars 官方版块/更新公告：https://hypixel.net/bed-wars/
- Hypixel Public API：https://api.hypixel.net/
- BedWars1058：https://github.com/andrei1058/BedWars1058
- Screaming BedWars：https://github.com/ScreamingSandals/BedWars

**提醒**：Hypixel Public API 提供玩家和近期比赛概要等公开数据，**不应假定能直接获得每一帧玩家位置、动作、隐身时机或完整录像**。要做精准行为统计，应优先在自己的仿真环境里收集，或在有权限的测试服务器记录事件。

## F. 如何决策：复用还是重写？

| 候选 | 能保留什么 | 预计需要自写什么 | 建议 |
|---|---|---|---|
| Minecraft-Bedwars-AI | 资源、岛屿、命令等抽象示例 | 空间模型、规则修订、有效前向模拟、API、复现 | 已审关键代码；降为参考，不建议直接移植 |
| Blockyard | BedWars 游戏机制、Bot、无头推进、网络机制 | 纯 2D 适配、实验 API、随机性统一、完整存档 | 接受 3D 核心时值得进一步验证；纯二维时改造较大 |
| Lux AI S2 | Agent 开发套件、runner、批量比赛、replay | BedWars 游戏规则和状态模型 | 如果目标是 Agent 竞赛平台，价值很高 |
| Lab2D | 2D 网格、底层高性能、定制规则 | BedWars 规则、WebSocket、回放 | 如果目标是严格纯 2D，值得做原型 |
| PettingZoo + 自建引擎 | 标准 Agent API 和测试 | 世界更新、所有游戏规则、通信 | 架构可控；BedWars 部分仍要开发 |

**不要同时引入 Lux AI、Lab2D、MAgent2 作为核心依赖**；它们有大量职责重叠。先选一条仿真技术路线，再在外层使用 PettingZoo 或自定义兼容层。

## G. 推荐 API 契约（项目自身设计，不是上述仓库的现有功能）

同步仿真：
```python
observations, infos = env.reset(seed=42)
while env.agents:
    actions = {a: policies[a](observations[a]) for a in env.agents}
    observations, rewards, terminations, truncations, infos = env.step(actions)
```

远程 Agent：
```json
{"type":"observation","match_id":"m42","tick":120,"agent_id":"red_1","observation":{"self":{"health":20,"position":[6,8]},"visible_enemies":[]},"legal_actions":["move","wait"]}
```
```json
{"type":"action","match_id":"m42","tick":120,"agent_id":"red_1","action":{"type":"move","direction":"east"}}
```

关键设计决定：
1. **每个 tick 只推进一次世界**：中央 match controller 收集所有动作后再推进，处理超时/default action。
2. **Observation != World State**：不可把隐身或视野外敌人精确坐标泄漏给 Agent。
3. **定义动作时延**：移动、攻击、搭桥、购物都需要时间和合法性校验。
4. **统一随机源**：每局单独随机种子，记录规则/地图/策略版本。
5. **无界面批量仿真为一等功能**：渲染必须可关闭、速度不得被帧率锁死。

## H. 下一轮验证建议（尚未执行）

关键源码核查已见调研报告；不再将 C# 项目列为首个移植候选。

1. 先明确二维地图的含义与首版规则集，再固定观测、动作、时间推进及复活契约。
2. 优先比较“自建规则核心 + PettingZoo”与“Lab2D 格子原型”；MAgent2 可另用于战斗子问题，Blockyard 在接受 3D 核心时重评。
3. 阅读 Lux 的进程运行器与 bots 的协议，分别参考进程隔离、远程接入、超时及对局记录。
4. 在相同规则、地图和动作记录下检查复现、信息边界与终局，再测无界面吞吐量和 100/1000 场批量成本。
5. 等核心契约稳定后，再决定网络层采用轻量 FastAPI 还是 OpenEnv 适配，以及是否需要 PixiJS 回放。

这些是待选择的工程验证项，不是已完成的测试、已采用的技术路线或固定排期。

## I. 代码复用与许可提醒

- `Minecraft-Bedwars-AI`：检索时未发现顶层开源许可证；默认**不要**把代码直接复制到自己的仓库。
- `Blockyard`：MIT。
- `Lux AI S2`：Apache-2.0。
- `Lab2D`：Apache-2.0。
- `MAgent2`：MIT。
- `MicroRTS-Py` 包装器：MIT；核查的 Java MicroRTS 引擎：GPL-3.0。
- `Grid Universe` / `PettingZoo` / `Gymnasium` / `FastAPI` / `PixiJS`：MIT。
- `bots`：Unlicense；`OpenEnv`：BSD-3-Clause。
- 其他仓库应在选用当日查看其实际 `LICENSE`，不要只依据本索引。

以上仓库和文档链接均基于本次公开网页检索；项目的 API、依赖和许可证可能随版本变动。建议固定 commit/tag 并保留对应文档链接。
